"""
ML layer through the real stack: real Postgres + real migrations + real HTTP.
The classifier model is real too (trained in a temp dir by app.ml.train).
"""

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.core.config import settings
from app.db.models import Document, RecurringSeries, Transaction, TransactionType
from app.ml import service
from app.ml.train import train

UTC = timezone.utc


@pytest.fixture(scope="session")
def trained_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("model")
    train(d, n=4000, seed=5, run_eval=False)
    return d


@pytest.fixture
def with_model(trained_dir, monkeypatch):
    monkeypatch.setattr(settings, "ml_model_dir", str(trained_dir))


@pytest.fixture
def rules_only(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ml_model_dir", str(tmp_path / "empty"))


@pytest.fixture
def put(db):
    """Insert a transaction with full control over description/doc/type."""
    def _put(user, account_id, on, amount, desc, *, merchant=None, kind="debit", doc=None, ccy="INR", category_id=None, source=None):
        y, m, d = (int(x) for x in on.split("-"))
        t = Transaction(
            user_id=user.id, account_id=account_id, category_id=category_id, category_source=source,
            source_document_id=doc, transaction_date=datetime.combine(date(y, m, d), time.min, tzinfo=UTC),
            description_raw=desc, merchant_normalized=merchant, amount=Decimal(amount), currency=ccy,
            transaction_type=TransactionType(kind),
        )
        db.add(t)
        db.commit()
        return str(t.id)
    return _put


@pytest.fixture
def make_doc(db):
    def _doc(user, n=1):
        d = Document(user_id=user.id, filename=f"s{n}.csv", storage_path=f"{user.id}/{n}", mime_type="text/csv")
        db.add(d)
        db.commit()
        return d.id
    return _doc


def txn(user, tid):
    r = user.get(f"/transactions/{tid}")
    assert r.status_code == 200, r.text
    return r.json()


def cat_id(user, name):
    return next(c["id"] for c in user.get("/categories").json() if c["name"] == name)


# ------------------------------------------------------------------ auth / status
@pytest.mark.parametrize("method,url", [
    ("get", "/ml/status"), ("post", "/ml/run"), ("get", "/ml/suggestions"), ("get", "/ml/duplicates"),
    ("get", "/ml/recurring"), ("get", "/ml/anomalies"), ("get", "/analytics/recurring"),
    ("post", f"/transactions/{uuid.uuid4()}/suggestion/accept"), ("post", f"/transactions/{uuid.uuid4()}/duplicate/confirm"),
])
def test_endpoints_require_auth(client, method, url):
    assert getattr(client, method)(url).status_code == 401



def test_status_rules_only_when_no_model(alice, rules_only):
    s = alice.get("/ml/status").json()
    assert s["mode"] == "rules-only" and not s["ml_model_available"] and "no trained model" in s["reason_unavailable"]
    assert s["llm_classifier_enabled"] is False


def test_status_with_model(alice, with_model):
    s = alice.get("/ml/status").json()
    assert s["mode"] == "rules+ml" and s["ml_only_auto_apply_threshold"] is None  # unmeasured => never auto


# ------------------------------------------------------------------ classification
def test_rule_hit_is_auto_applied_ml_only_is_suggested(alice, with_model, put):
    acct = alice.account()
    swiggy = put(alice, acct, "2026-03-01", "300.00", "UPI/123456789012/SWIGGY/x@ybl", merchant="Swiggy")
    ml_only = put(alice, acct, "2026-03-02", "5000.00", "Max Healthcare")       # no rule; model has seen it in training
    junk = put(alice, acct, "2026-03-03", "10.00", "QZXW QZXW")
    r = alice.post("/ml/run").json()["classification"]
    assert r["auto_applied"] >= 1 and r["suggested"] >= 1

    s = txn(alice, swiggy)
    assert s["category_id"] == cat_id(alice, "Food") and s["category_source"] in ("rule", "hybrid") and s["suggested_category_id"] is None

    m = txn(alice, ml_only)
    # Confident or not, an ML-only call is a suggestion: category_id stays empty so analytics ignore it.
    assert m["category_id"] is None and m["suggested_category_id"] == cat_id(alice, "Healthcare")
    assert m["suggested_category_source"] == "ml" and m["suggested_category_confidence"] >= 0.5
    assert [t["id"] for t in alice.get("/ml/suggestions").json()] == [ml_only]
    assert txn(alice, junk)["category_id"] is None


def test_rules_only_mode_still_works(alice, rules_only, put):
    acct = alice.account()
    t = put(alice, acct, "2026-03-01", "300.00", "ZOMATO ORDER")
    u = put(alice, acct, "2026-03-02", "5000.00", "Max Healthcare")
    alice.post("/ml/run")
    assert txn(alice, t)["category_source"] == "rule"
    assert txn(alice, u)["category_id"] is None and txn(alice, u)["suggested_category_id"] is None


def test_never_overwrites_user_category_even_with_force(alice, with_model, put):
    acct = alice.account()
    mine = cat_id(alice, "Shopping")
    t = put(alice, acct, "2026-03-01", "300.00", "SWIGGY ORDER")
    assert alice.patch(f"/transactions/{t}", json={"category_id": mine}).status_code == 200
    legacy = put(alice, acct, "2026-03-02", "300.00", "ZOMATO", category_id=mine, source=None)  # pre-provenance row
    for force in (False, True):
        alice.post("/ml/run", json={"force_reclassify": force})
        assert txn(alice, t)["category_id"] == mine and txn(alice, t)["category_source"] == "user"
        assert txn(alice, legacy)["category_id"] == mine


def test_accept_and_reject_suggestions(alice, with_model, put):
    acct = alice.account()
    a = put(alice, acct, "2026-03-02", "5000.00", "Max Healthcare")
    b = put(alice, acct, "2026-03-03", "5000.00", "HDFC Ergo Health")
    alice.post("/ml/run")
    assert txn(alice, a)["suggested_category_id"] and txn(alice, b)["suggested_category_id"]

    ok = alice.post(f"/transactions/{a}/suggestion/accept").json()
    assert ok["category_id"] == cat_id(alice, "Healthcare") and ok["category_source"] == "user" and ok["suggested_category_id"] is None
    assert alice.post(f"/transactions/{a}/suggestion/accept").status_code == 409  # nothing pending now

    rej = alice.post(f"/transactions/{b}/suggestion/reject").json()
    assert rej["category_id"] is None and rej["suggested_category_id"] is None
    alice.post("/ml/run", json={"force_reclassify": True})
    assert txn(alice, b)["suggested_category_id"] is None  # rejection sticks, even on force


def test_explicit_clear_stops_reclassification(alice, with_model, put):
    acct = alice.account()
    t = put(alice, acct, "2026-03-01", "300.00", "SWIGGY ORDER")
    alice.post("/ml/run")
    assert txn(alice, t)["category_id"]
    assert alice.patch(f"/transactions/{t}", json={"category_id": None}).json()["category_source"] is None
    alice.post("/ml/run", json={"force_reclassify": True})
    assert txn(alice, t)["category_id"] is None


def test_force_clears_machine_decisions_it_no_longer_makes(alice, with_model, put, db):
    acct = alice.account()
    t = put(alice, acct, "2026-03-01", "300.00", "QZXW QZXW")
    # Simulate an earlier, more confident model having auto-applied a category.
    db.execute(text("UPDATE transactions SET category_id=(SELECT id FROM categories WHERE name='Food'), category_source='ml', category_confidence=0.99 WHERE id=:i"), {"i": t})
    db.commit()
    alice.post("/ml/run")                                      # non-force leaves it alone
    assert txn(alice, t)["category_source"] == "ml"
    alice.post("/ml/run", json={"force_reclassify": True})     # force: model no longer backs it
    assert txn(alice, t)["category_id"] is None and txn(alice, t)["category_source"] is None


def test_salary_only_for_credits(alice, rules_only, put):
    acct = alice.account()
    cr = put(alice, acct, "2026-03-01", "90000.00", "NEFT-HDFC0001234-INFOSYS LTD-SALARY MAR", kind="credit")
    db_ = put(alice, acct, "2026-03-01", "90000.00", "NEFT-HDFC0001234-INFOSYS LTD-SALARY MAR", kind="debit")
    alice.post("/ml/run")
    assert txn(alice, cr)["category_id"] == cat_id(alice, "Salary")
    assert txn(alice, db_)["category_id"] != cat_id(alice, "Salary")


def test_classification_scoped_to_one_user(alice, bob, rules_only, put):
    a_t = put(alice, alice.account(), "2026-03-01", "300.00", "SWIGGY")
    b_t = put(bob, bob.account(), "2026-03-01", "300.00", "SWIGGY")
    alice.post("/ml/run")
    assert txn(alice, a_t)["category_id"] and txn(bob, b_t)["category_id"] is None
    assert alice.get(f"/transactions/{b_t}").status_code == 404
    assert alice.post(f"/transactions/{b_t}/suggestion/accept").status_code == 404
    assert alice.post(f"/transactions/{b_t}/duplicate/confirm").status_code == 404


# ------------------------------------------------------------------ duplicates
def test_reuploaded_statement_duplicates_are_excluded_from_analytics(alice, rules_only, put, make_doc):
    acct = alice.account()
    d1, d2 = make_doc(alice, 1), make_doc(alice, 2)
    o = put(alice, acct, "2026-03-01", "250.00", "UPI/111111111111/SWIGGY", doc=d1)
    c = put(alice, acct, "2026-03-01", "250.00", "UPI/111111111111/SWIGGY", doc=d2)
    before = alice.get("/analytics/summary").json()[0]["expense"]
    assert before == "500.00"
    res = alice.post("/ml/run").json()["duplicates"]
    assert res["auto_applied"] == 1
    t = txn(alice, c)
    assert t["duplicate_of_id"] == o and t["duplicate_review"] == "auto" and t["duplicate_score"] >= 0.95
    assert txn(alice, o)["duplicate_of_id"] is None
    assert alice.get("/analytics/summary").json()[0]["expense"] == "250.00"   # the duplicate no longer counts


def test_pending_duplicate_is_not_applied_until_a_human_confirms(alice, rules_only, put, make_doc):
    acct = alice.account()
    d1, d2 = make_doc(alice, 1), make_doc(alice, 2)
    o = put(alice, acct, "2026-03-01", "250.00", "SWIGGY ORDER", doc=d1)
    c = put(alice, acct, "2026-03-02", "250.00", "SWIGGY ORDER", doc=d2)   # posting-date shift
    alice.post("/ml/run")
    assert txn(alice, c)["duplicate_review"] == "pending" and txn(alice, c)["duplicate_of_id"] is None
    assert alice.get("/analytics/summary").json()[0]["expense"] == "500.00"
    q = alice.get("/ml/duplicates").json()
    assert [(x["transaction"]["id"], x["candidate"]["id"]) for x in q] == [(c, o)]

    conf = alice.post(f"/transactions/{c}/duplicate/confirm").json()
    assert conf["duplicate_of_id"] == o and conf["duplicate_review"] == "confirmed"
    assert alice.get("/analytics/summary").json()[0]["expense"] == "250.00"
    alice.post("/ml/run")                                                   # re-run keeps the human decision
    assert txn(alice, c)["duplicate_review"] == "confirmed" and txn(alice, c)["duplicate_of_id"] == o


def test_dismissal_survives_reruns(alice, rules_only, put, make_doc):
    acct = alice.account()
    d1, d2 = make_doc(alice, 1), make_doc(alice, 2)
    put(alice, acct, "2026-03-01", "250.00", "UPI/111111111111/SWIGGY", doc=d1)
    c = put(alice, acct, "2026-03-01", "250.00", "UPI/111111111111/SWIGGY", doc=d2)
    alice.post("/ml/run")
    assert txn(alice, c)["duplicate_of_id"]
    out = alice.post(f"/transactions/{c}/duplicate/dismiss").json()
    assert out["duplicate_of_id"] is None and out["duplicate_review"] == "dismissed"
    assert alice.get("/analytics/summary").json()[0]["expense"] == "500.00"
    alice.post("/ml/run")
    assert txn(alice, c)["duplicate_of_id"] is None and txn(alice, c)["duplicate_review"] == "dismissed"


def test_confirm_without_candidate_and_dismiss_unflagged_are_409(alice, rules_only, put):
    t = put(alice, alice.account(), "2026-03-01", "10.00", "X")
    assert alice.post(f"/transactions/{t}/duplicate/confirm").status_code == 409
    assert alice.post(f"/transactions/{t}/duplicate/dismiss").status_code == 409


def test_detector_changes_its_mind_when_data_changes(alice, rules_only, put, make_doc, db):
    acct = alice.account()
    d1, d2 = make_doc(alice, 1), make_doc(alice, 2)
    put(alice, acct, "2026-03-01", "250.00", "SWIGGY", doc=d1)
    c = put(alice, acct, "2026-03-01", "250.00", "SWIGGY", doc=d2)
    alice.post("/ml/run")
    assert txn(alice, c)["duplicate_of_id"]
    db.execute(text("DELETE FROM transactions WHERE id != :c"), {"c": c})   # the original is deleted
    db.commit()
    alice.post("/ml/run")
    t = txn(alice, c)
    assert t["duplicate_of_id"] is None and t["duplicate_review"] is None   # stale auto-flag was withdrawn


# ------------------------------------------------------------------ recurring
def seed_monthly(user, put, acct, merchant, amount, months=6, day=5, kind="debit", desc=None, start=(2026, 1)):
    ids, (y, m) = [], start
    for _ in range(months):
        ids.append(put(user, acct, f"{y}-{m:02d}-{day:02d}", amount, desc or merchant.upper(), merchant=merchant, kind=kind))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return ids


def test_recurring_end_to_end_with_exact_totals(alice, rules_only, put):
    acct = alice.account()
    nflx = seed_monthly(alice, put, acct, "Netflix", "649.00")
    seed_monthly(alice, put, acct, "Landlord", "22000.00", day=2)
    seed_monthly(alice, put, acct, "Employer", "85000.00", kind="credit", day=1)
    for i in range(22):   # weekly tiffin 700, running through June like everything else
        put(alice, acct, (date(2026, 1, 3) + timedelta(days=7 * i)).isoformat(), "700.00", "TIFFIN", merchant="Tiffin")
    put(alice, acct, "2026-02-14", "999.00", "ONE OFF", merchant="Gadget Shop")

    r = alice.post("/ml/run").json()["recurring"]
    assert r["series"] == 4
    series = {s["merchant"]: s for s in alice.get("/ml/recurring").json()}
    assert set(series) == {"Netflix", "Landlord", "Employer", "Tiffin"}
    assert series["Netflix"]["cadence"] == "monthly" and series["Tiffin"]["cadence"] == "weekly"
    assert all(txn(alice, i)["is_recurring"] for i in nflx)
    assert alice.get("/transactions", params={"is_recurring": "true", "limit": 500}).json().__len__() == 6 + 6 + 6 + 22

    tot = alice.get("/analytics/recurring").json()
    assert len(tot) == 1 and tot[0]["currency"] == "INR"
    # 649 + 22000 + 700 * 52/12 (= 3033.33...) quantized to cents
    assert tot[0]["expense_monthly_equivalent"] == str((Decimal("649") + Decimal("22000") + (Decimal("700") * 52 / 12).quantize(Decimal("0.01"))).quantize(Decimal("0.01")))
    assert tot[0]["income_monthly_equivalent"] == "85000.00"
    assert tot[0]["expense_series_count"] == 3 and tot[0]["income_series_count"] == 1


def test_recurring_rerun_is_idempotent_and_concurrent_runs_dont_duplicate(alice, rules_only, put):
    from concurrent.futures import ThreadPoolExecutor
    acct = alice.account()
    seed_monthly(alice, put, acct, "Netflix", "649.00")
    alice.post("/ml/run")
    alice.post("/ml/run")
    assert len(alice.get("/ml/recurring").json()) == 1
    with ThreadPoolExecutor(6) as ex:
        codes = list(ex.map(lambda _: alice.post("/ml/run").status_code, range(6)))
    assert codes == [200] * 6
    assert len(alice.get("/ml/recurring").json()) == 1       # advisory lock serialized the delete+insert


def test_recurring_ignores_confirmed_duplicates_and_other_users(alice, bob, rules_only, put):
    seed_monthly(bob, put, bob.account(), "Netflix", "649.00")
    acct = alice.account()
    seed_monthly(alice, put, acct, "Netflix", "649.00", months=2)     # too few for alice
    alice.post("/ml/run")
    assert alice.get("/ml/recurring").json() == []
    assert bob.get("/ml/recurring").json() == []                      # bob never ran it: alice's run didn't touch him
    bob.post("/ml/run")
    assert len(bob.get("/ml/recurring").json()) == 1
    assert alice.get("/analytics/recurring").json() == []


def test_deleted_series_leaves_no_dangling_flags(alice, rules_only, put, db):
    acct = alice.account()
    ids = seed_monthly(alice, put, acct, "Netflix", "649.00")
    alice.post("/ml/run")
    db.execute(text("DELETE FROM recurring_series"))
    db.commit()
    assert txn(alice, ids[0])["recurring_series_id"] is None          # FK SET NULL
    alice.post("/ml/run")
    assert txn(alice, ids[0])["is_recurring"] is True


# ------------------------------------------------------------------ anomalies
def test_anomaly_flag_score_and_explanation(alice, rules_only, put):
    acct = alice.account()
    for i in range(30):
        put(alice, acct, (date(2026, 1, 1) + timedelta(days=i * 3)).isoformat(), str(200 + (i % 7) * 15), "SWIGGY", merchant="Swiggy")
    spike = put(alice, acct, "2026-05-01", "9000.00", "SWIGGY", merchant="Swiggy")
    new_merchant = put(alice, acct, "2026-05-02", "50000.00", "BRAND NEW SHOP", merchant="Brand New Shop")
    usd = put(alice, acct, "2026-05-03", "99999.00", "LONE USD", merchant="Lone", ccy="USD")   # no USD history at all
    r = alice.post("/ml/run").json()["anomalies"]
    assert r["flagged"] == 2 and r["no_baseline"] == 1
    s = txn(alice, spike)
    assert s["is_anomaly"] and s["anomaly_score"] > 3.5
    assert s["anomaly_detail"]["level"] == "merchant" and s["anomaly_detail"]["n"] == 31
    # A never-seen merchant has no merchant baseline; the user-wide baseline (>=30 txns) catches 50000-vs-~250.
    assert txn(alice, new_merchant)["is_anomaly"] and txn(alice, new_merchant)["anomaly_detail"]["level"] == "user"
    lone = txn(alice, usd)
    assert not lone["is_anomaly"] and lone["anomaly_score"] is None   # "can't tell", not "normal"
    assert {t["id"] for t in alice.get("/ml/anomalies").json()} == {spike, new_merchant}
    assert {t["id"] for t in alice.get("/transactions", params={"is_anomaly": "true"}).json()} == {spike, new_merchant}


def test_anomaly_flag_clears_when_baseline_absorbs_the_value(alice, rules_only, put, db):
    acct = alice.account()
    for i in range(12):
        put(alice, acct, (date(2026, 1, 1) + timedelta(days=i * 5)).isoformat(), "300.00", "CAFE", merchant="Cafe")
    spike = put(alice, acct, "2026-04-01", "30000.00", "CAFE", merchant="Cafe")
    alice.post("/ml/run")
    assert txn(alice, spike)["is_anomaly"]
    for i in range(14):    # the user starts spending like this regularly
        put(alice, acct, (date(2026, 5, 1) + timedelta(days=i)).isoformat(), "30000.00", "CAFE", merchant="Cafe")
    alice.post("/ml/run")
    assert not txn(alice, spike)["is_anomaly"]


def test_duplicates_do_not_distort_anomaly_baselines(alice, rules_only, put, make_doc):
    acct = alice.account()
    d1, d2 = make_doc(alice, 1), make_doc(alice, 2)
    for i in range(10):
        put(alice, acct, (date(2026, 1, 1) + timedelta(days=i * 7)).isoformat(), "300.00", f"UPI/1{i:011d}/CAFE", merchant="Cafe", doc=d1)
    big = put(alice, acct, "2026-04-01", "60000.00", "UPI/999999999999/CAFE", merchant="Cafe", doc=d1)
    dup = put(alice, acct, "2026-04-01", "60000.00", "UPI/999999999999/CAFE", merchant="Cafe", doc=d2)
    alice.post("/ml/run")
    assert txn(alice, dup)["duplicate_of_id"] == big
    assert txn(alice, big)["is_anomaly"] and not txn(alice, dup)["is_anomaly"]


# ------------------------------------------------------------------ the Celery task itself
def test_enrich_task_runs_end_to_end(alice, rules_only, put):
    from app.pipeline.tasks import enrich_user_transactions
    acct = alice.account()
    t = put(alice, acct, "2026-03-01", "300.00", "SWIGGY")
    out = enrich_user_transactions.apply(args=[alice.id]).get()    # runs the real task body, in-process
    assert out["classification"]["auto_applied"] == 1
    assert txn(alice, t)["category_id"]
