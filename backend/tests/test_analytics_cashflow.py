from decimal import Decimal


def test_summary_basic_and_exact_decimals(alice, add_txn):
    acct = alice.account()
    add_txn(alice, acct, "2026-08-01", "50000.00", "credit", merchant="Employer")
    add_txn(alice, acct, "2026-08-02", "1200.50", "debit")
    add_txn(alice, acct, "2026-08-03", "799.50", "debit")
    r = alice.get("/analytics/summary")
    assert r.status_code == 200
    (row,) = r.json()
    assert row == {
        "currency": "INR", "income": "50000.00", "expense": "2000.00", "net": "48000.00",
        "income_count": 1, "expense_count": 2, "savings_rate_pct": "96.00",
    }


def test_thousand_dime_sums_are_exact(alice, add_txn, db):
    """0.10 * 1000 must be exactly 100.00. Float summation famously isn't."""
    from datetime import datetime, timezone
    from app.db.models import Transaction, TransactionType
    acct = alice.account()
    db.add_all([
        Transaction(user_id=alice.id, account_id=acct, transaction_date=datetime(2026, 8, 1, tzinfo=timezone.utc),
                    description_raw="dime", amount=Decimal("0.10"), currency="INR",
                    transaction_type=TransactionType.debit)
        for _ in range(1000)
    ])
    db.commit()
    # Sanity check on the premise: naive float accumulation really does drift.
    # (Not builtin sum() — since Python 3.12 it uses compensated summation and
    # would hide the drift, which is a trap worth remembering.)
    acc = 0.0
    for _ in range(1000):
        acc += 0.1
    assert acc != 100.0
    assert alice.get("/analytics/summary").json()[0]["expense"] == "100.00"


def test_currencies_never_combined(alice, add_txn):
    inr, usd = alice.account("INR acct", "INR"), alice.account("USD acct", "USD")
    add_txn(alice, inr, "2026-08-01", "1000.00", "debit", currency="INR")
    add_txn(alice, usd, "2026-08-01", "10.00", "debit", currency="USD")
    rows = {r["currency"]: r for r in alice.get("/analytics/summary").json()}
    assert set(rows) == {"INR", "USD"}
    assert rows["INR"]["expense"] == "1000.00" and rows["USD"]["expense"] == "10.00"


def test_savings_rate_undefined_without_income(alice, add_txn):
    acct = alice.account()
    add_txn(alice, acct, "2026-08-01", "10.00", "debit")
    row = alice.get("/analytics/summary").json()[0]
    assert row["income"] == "0.00" and row["net"] == "-10.00"
    assert row["savings_rate_pct"] is None


def test_negative_savings_rate(alice, add_txn):
    acct = alice.account()
    add_txn(alice, acct, "2026-08-01", "100.00", "credit")
    add_txn(alice, acct, "2026-08-02", "150.00", "debit")
    assert alice.get("/analytics/summary").json()[0]["savings_rate_pct"] == "-50.00"


def test_date_range_inclusive_both_ends(alice, add_txn):
    acct = alice.account()
    for d in ("2026-07-31", "2026-08-01", "2026-08-31", "2026-09-01"):
        add_txn(alice, acct, d, "10.00", "debit")
    r = alice.get("/analytics/summary", params={"date_from": "2026-08-01", "date_to": "2026-08-31"}).json()
    assert r[0]["expense"] == "20.00" and r[0]["expense_count"] == 2


def test_single_day_range(alice, add_txn):
    acct = alice.account()
    add_txn(alice, acct, "2026-08-15", "10.00", "debit")
    add_txn(alice, acct, "2026-08-16", "99.00", "debit")
    r = alice.get("/analytics/summary", params={"date_from": "2026-08-15", "date_to": "2026-08-15"}).json()
    assert r[0]["expense"] == "10.00"


def test_inverted_range_is_422(alice):
    r = alice.get("/analytics/summary", params={"date_from": "2026-09-01", "date_to": "2026-08-01"})
    assert r.status_code == 422


def test_garbage_params_are_422(alice):
    assert alice.get("/analytics/summary", params={"date_from": "not-a-date"}).status_code == 422
    assert alice.get("/analytics/summary", params={"account_id": "nope"}).status_code == 422


def test_duplicates_excluded(alice, add_txn):
    acct = alice.account()
    original = add_txn(alice, acct, "2026-08-01", "500.00", "debit")
    add_txn(alice, acct, "2026-08-01", "500.00", "debit", duplicate_of=original)
    r = alice.get("/analytics/summary").json()[0]
    assert r["expense"] == "500.00" and r["expense_count"] == 1


def test_account_filter_and_foreign_account_404(alice, bob, add_txn):
    a1, a2 = alice.account("A1"), alice.account("A2")
    add_txn(alice, a1, "2026-08-01", "10.00", "debit")
    add_txn(alice, a2, "2026-08-01", "30.00", "debit")
    assert alice.get("/analytics/summary", params={"account_id": a2}).json()[0]["expense"] == "30.00"
    bobs = bob.account("B1")
    assert alice.get("/analytics/summary", params={"account_id": bobs}).status_code == 404
    assert alice.get("/analytics/summary", params={"account_id": "00000000-0000-0000-0000-000000000000"}).status_code == 404


def test_empty_user_gets_empty_lists_not_errors(alice):
    for path in ("/analytics/summary", "/analytics/monthly", "/analytics/categories",
                 "/analytics/merchants", "/analytics/accounts"):
        r = alice.get(path)
        assert r.status_code == 200 and r.json() == [], path


def test_cross_user_isolation(alice, bob, add_txn):
    acct = alice.account()
    add_txn(alice, acct, "2026-08-01", "999.00", "debit", merchant="Secret Shop")
    for path in ("/analytics/summary", "/analytics/monthly", "/analytics/categories", "/analytics/merchants"):
        assert bob.get(path).json() == [], path


def test_requires_auth(client):
    for path in ("/analytics/summary", "/analytics/monthly", "/analytics/categories", "/analytics/merchants",
                 "/analytics/accounts", "/analytics/budget-utilization", "/budgets", "/categories"):
        assert client.get(path).status_code == 401, path


# ---------------- monthly -----------------

def _months(resp):
    return {m["month"]: m for m in resp[0]["months"]}


def test_monthly_gap_fill_and_mom(alice, add_txn):
    acct = alice.account()
    add_txn(alice, acct, "2026-06-10", "1000.00", "debit")
    add_txn(alice, acct, "2026-08-10", "1500.00", "debit")  # July has nothing
    add_txn(alice, acct, "2026-08-11", "4000.00", "credit")
    series = alice.get("/analytics/monthly").json()
    assert [m["month"] for m in series[0]["months"]] == ["2026-06-01", "2026-07-01", "2026-08-01"]
    m = _months(series)
    assert m["2026-06-01"]["expense_change"] is None  # first point has no predecessor
    assert m["2026-07-01"]["expense"] == "0.00" and m["2026-07-01"]["expense_change"] == "-1000.00"
    assert m["2026-07-01"]["expense_change_pct"] == "-100.00"
    # previous (July) expense is 0 -> % change undefined, absolute change still given
    assert m["2026-08-01"]["expense_change"] == "1500.00" and m["2026-08-01"]["expense_change_pct"] is None
    assert m["2026-08-01"]["net"] == "2500.00" and m["2026-08-01"]["transaction_count"] == 2


def test_monthly_percent_change_rounding(alice, add_txn):
    acct = alice.account()
    add_txn(alice, acct, "2026-05-05", "300.00", "debit")
    add_txn(alice, acct, "2026-06-05", "400.00", "debit")
    m = _months(alice.get("/analytics/monthly").json())
    assert m["2026-06-01"]["expense_change_pct"] == "33.33"


def test_month_boundaries_and_year_rollover(alice, add_txn):
    acct = alice.account()
    add_txn(alice, acct, "2026-12-31", "10.00", "debit")
    add_txn(alice, acct, "2027-01-01", "20.00", "debit")
    add_txn(alice, acct, "2028-02-29", "5.00", "debit")  # leap day
    m = _months(alice.get("/analytics/monthly", params={"date_from": "2026-12-01", "date_to": "2028-02-29"}).json())
    assert m["2026-12-01"]["expense"] == "10.00" and m["2027-01-01"]["expense"] == "20.00"
    assert m["2028-02-01"]["expense"] == "5.00"
    assert len(m) == 15  # Dec 2026 .. Feb 2028 inclusive, gaps filled


def test_monthly_partial_flags(alice, add_txn):
    acct = alice.account()
    add_txn(alice, acct, "2026-08-20", "10.00", "debit")
    add_txn(alice, acct, "2026-09-05", "10.00", "debit")
    add_txn(alice, acct, "2026-10-05", "10.00", "debit")
    m = _months(alice.get("/analytics/monthly", params={"date_from": "2026-08-15", "date_to": "2026-10-15"}).json())
    assert m["2026-08-01"]["partial"] is True    # starts mid-month
    assert m["2026-09-01"]["partial"] is False   # whole month inside the range
    assert m["2026-10-01"]["partial"] is True    # ends mid-month
    full = _months(alice.get("/analytics/monthly", params={"date_from": "2026-08-01", "date_to": "2026-10-31"}).json())
    assert not any(p["partial"] for p in full.values())


def test_monthly_range_extends_beyond_data(alice, add_txn):
    acct = alice.account()
    add_txn(alice, acct, "2026-08-10", "10.00", "debit")
    series = alice.get("/analytics/monthly", params={"date_from": "2026-07-01", "date_to": "2026-09-30"}).json()
    assert [m["month"] for m in series[0]["months"]] == ["2026-07-01", "2026-08-01", "2026-09-01"]


def test_monthly_per_currency_series(alice, add_txn):
    inr, usd = alice.account("i", "INR"), alice.account("u", "USD")
    add_txn(alice, inr, "2026-08-01", "100.00", "debit", currency="INR")
    add_txn(alice, usd, "2026-10-01", "5.00", "debit", currency="USD")
    series = {s["currency"]: s for s in alice.get("/analytics/monthly").json()}
    assert len(series["INR"]["months"]) == 1 and len(series["USD"]["months"]) == 1  # each spans only its own data
