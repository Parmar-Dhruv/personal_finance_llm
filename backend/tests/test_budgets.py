from decimal import Decimal


def util(user, month="2026-08"):
    r = user.get("/analytics/budget-utilization", params={"month": month})
    assert r.status_code == 200, r.text
    return r.json()


def by_name(body):
    return {(b["category_name"], b["currency"]): b for b in body["budgets"]}


def test_budget_crud(alice):
    food = alice.category("Groceries")
    r = alice.post("/budgets", json={"category_id": food, "currency": "inr", "amount": "10000"})
    assert r.status_code == 201
    b = r.json()
    assert b["currency"] == "INR" and b["amount"] == "10000.00" and b["alert_threshold_pct"] == "80.00"
    assert alice.patch(f"/budgets/{b['id']}", json={"amount": "12000.50", "alert_threshold_pct": "90"}).json()["amount"] == "12000.50"
    assert len(alice.get("/budgets").json()) == 1
    assert alice.delete(f"/budgets/{b['id']}").status_code == 204
    assert alice.get("/budgets").json() == []
    assert alice.delete(f"/budgets/{b['id']}").status_code == 404


def test_budget_validation(alice):
    base = {"currency": "INR"}
    for bad in ("0", "-5", "abc", "100.123", "99999999999999.00", "NaN", "Infinity"):
        assert alice.post("/budgets", json={**base, "amount": bad}).status_code == 422, bad
    assert alice.post("/budgets", json={"currency": "RUPEES", "amount": "10"}).status_code == 422
    assert alice.post("/budgets", json={"currency": "IN1", "amount": "10"}).status_code == 422
    for bad in ("0", "101", "-1"):
        assert alice.post("/budgets", json={**base, "amount": "10", "alert_threshold_pct": bad}).status_code == 422, bad
    assert alice.post("/budgets", json={**base, "amount": "10", "alert_threshold_pct": "100"}).status_code == 201


def test_budget_uniqueness_including_overall(alice):
    food = alice.category("Groceries")
    assert alice.post("/budgets", json={"category_id": food, "currency": "INR", "amount": "1"}).status_code == 201
    assert alice.post("/budgets", json={"category_id": food, "currency": "INR", "amount": "2"}).status_code == 409
    assert alice.post("/budgets", json={"category_id": food, "currency": "USD", "amount": "2"}).status_code == 201
    # NULL category = overall: only one per currency (the NULLS NOT DISTINCT case)
    assert alice.post("/budgets", json={"currency": "INR", "amount": "5"}).status_code == 201
    assert alice.post("/budgets", json={"currency": "INR", "amount": "6"}).status_code == 409
    assert alice.post("/budgets", json={"currency": "USD", "amount": "6"}).status_code == 201
    assert len(alice.get("/budgets").json()) == 4


def test_budget_isolation(alice, bob):
    bobs_cat = bob.category("Mine")
    assert alice.post("/budgets", json={"category_id": bobs_cat, "currency": "INR", "amount": "10"}).status_code == 404
    mine = alice.post("/budgets", json={"currency": "INR", "amount": "10"}).json()["id"]
    assert bob.patch(f"/budgets/{mine}", json={"amount": "1"}).status_code == 404
    assert bob.delete(f"/budgets/{mine}").status_code == 404
    assert bob.get("/budgets").json() == []
    assert util(bob)["budgets"] == []


def test_patch_rejects_nulls_and_bad_values(alice):
    b = alice.post("/budgets", json={"currency": "INR", "amount": "10"}).json()["id"]
    assert alice.patch(f"/budgets/{b}", json={"amount": None}).status_code == 422
    assert alice.patch(f"/budgets/{b}", json={"amount": "0"}).status_code == 422
    assert alice.patch(f"/budgets/{b}", json={}).status_code == 200  # no-op


def test_utilization_math_and_status_boundaries(alice, add_txn):
    acct = alice.account()
    food = alice.category("Groceries")
    alice.post("/budgets", json={"category_id": food, "currency": "INR", "amount": "1000", "alert_threshold_pct": "80"})
    cases = [
        ("799.99", "ok", "80.00"),    # 79.999% rounds to 80.00 for display but is still BELOW the threshold
        ("800.00", "near", "80.00"),  # exactly at threshold
        ("1000.00", "near", "100.00"),  # exactly at the limit is not "over"
        ("1000.01", "over", "100.00"),
        ("1500.00", "over", "150.00"),
    ]
    for spent, status, pct in cases:
        # fresh month per case so each is isolated
        month_no = cases.index((spent, status, pct)) + 1
        add_txn(alice, acct, f"2026-0{month_no}-10", spent, category_id=food)
        row = by_name(util(alice, f"2026-0{month_no}"))[("Groceries", "INR")]
        assert row["status"] == status, (spent, row)
        assert row["pct_used"] == pct, (spent, row)
        assert Decimal(row["remaining"]) == Decimal("1000.00") - Decimal(spent)
    row = by_name(util(alice, "2026-05"))[("Groceries", "INR")]
    assert row["spent"] == "1500.00"  # sanity check below


def test_no_spend_is_ok_zero(alice):
    alice.post("/budgets", json={"currency": "INR", "amount": "500"})
    (row,) = util(alice)["budgets"]
    assert row["spent"] == "0.00" and row["pct_used"] == "0.00" and row["status"] == "ok"
    assert row["remaining"] == "500.00" and row["category_name"] is None


def test_category_subtree_rollup(alice, add_txn):
    acct = alice.account()
    food = alice.category("Food2")
    takeaway = alice.category("Takeaway", food)
    pizza = alice.category("Pizza", takeaway)
    other = alice.category("Other")
    alice.post("/budgets", json={"category_id": food, "currency": "INR", "amount": "1000"})
    add_txn(alice, acct, "2026-08-01", "100.00", category_id=food)
    add_txn(alice, acct, "2026-08-02", "200.00", category_id=takeaway)
    add_txn(alice, acct, "2026-08-03", "300.00", category_id=pizza)
    add_txn(alice, acct, "2026-08-04", "999.00", category_id=other)   # outside the subtree
    row = by_name(util(alice))[("Food2", "INR")]
    assert row["spent"] == "600.00" and row["transaction_count"] == 3


def test_budget_on_leaf_does_not_include_parent_spend(alice, add_txn):
    acct = alice.account()
    parent = alice.category("Par")
    child = alice.category("Kid", parent)
    alice.post("/budgets", json={"category_id": child, "currency": "INR", "amount": "100"})
    add_txn(alice, acct, "2026-08-01", "50.00", category_id=parent)
    assert by_name(util(alice))[("Kid", "INR")]["spent"] == "0.00"


def test_overall_budget_includes_uncategorized_and_everything(alice, add_txn):
    acct = alice.account()
    c = alice.category("Cat")
    alice.post("/budgets", json={"currency": "INR", "amount": "1000"})
    alice.post("/budgets", json={"category_id": c, "currency": "INR", "amount": "1000"})
    add_txn(alice, acct, "2026-08-01", "100.00", category_id=c)
    add_txn(alice, acct, "2026-08-02", "50.00")
    res = by_name(util(alice))
    assert res[(None, "INR")]["spent"] == "150.00"
    assert res[("Cat", "INR")]["spent"] == "100.00"


def test_budget_is_currency_scoped(alice, add_txn):
    inr, usd = alice.account("i", "INR"), alice.account("u", "USD")
    alice.post("/budgets", json={"currency": "INR", "amount": "1000"})
    alice.post("/budgets", json={"currency": "USD", "amount": "100"})
    add_txn(alice, inr, "2026-08-01", "400.00", currency="INR")
    add_txn(alice, usd, "2026-08-01", "30.00", currency="USD")
    res = by_name(util(alice))
    assert res[(None, "INR")]["spent"] == "400.00" and res[(None, "USD")]["spent"] == "30.00"


def test_only_debits_in_month_and_no_duplicates(alice, add_txn):
    acct = alice.account()
    alice.post("/budgets", json={"currency": "INR", "amount": "1000"})
    first = add_txn(alice, acct, "2026-08-01", "100.00")
    add_txn(alice, acct, "2026-08-01", "100.00", duplicate_of=first)   # flagged duplicate: ignored
    add_txn(alice, acct, "2026-08-02", "500.00", "credit")            # income: ignored
    add_txn(alice, acct, "2026-07-31", "700.00")                      # previous month
    add_txn(alice, acct, "2026-09-01", "800.00")                      # next month
    add_txn(alice, acct, "2026-08-31", "10.00")                       # last day counts
    (row,) = util(alice)["budgets"]
    assert row["spent"] == "110.00" and row["transaction_count"] == 2


def test_inactive_budget_excluded(alice):
    b = alice.post("/budgets", json={"currency": "INR", "amount": "10"}).json()["id"]
    alice.patch(f"/budgets/{b}", json={"is_active": False})
    assert util(alice)["budgets"] == []
    assert len(alice.get("/budgets").json()) == 1  # still listed, just not evaluated


def test_utilization_period_and_validation(alice):
    body = util(alice, "2028-02")
    assert body["period_start"] == "2028-02-01" and body["period_end"] == "2028-02-29"
    assert util(alice, "2026-12")["period_end"] == "2026-12-31"
    for bad in ("2026-13", "2026-00", "26-08", "2026-8", "garbage", "2026-08-01"):
        assert alice.get("/analytics/budget-utilization", params={"month": bad}).status_code == 422, bad
    assert alice.get("/analytics/budget-utilization").status_code == 200  # defaults to current month


def test_deleting_category_via_db_cascades_budget_not_overall(alice, db):
    """A category budget must disappear with its category, never silently become an overall budget."""
    from sqlalchemy import text
    c = alice.category("Temp")
    alice.post("/budgets", json={"category_id": c, "currency": "INR", "amount": "10"})
    db.execute(text("DELETE FROM categories WHERE id = :i"), {"i": c})
    db.commit()
    assert alice.get("/budgets").json() == []
