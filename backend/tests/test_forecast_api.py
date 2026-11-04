"""
Phase 6 against real Postgres + real HTTP (no mocks): the balance endpoints and
GET /forecast/cashflow, including auth, isolation, validation and end-to-end
numbers that are derived by hand in the comments.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

BALANCE = "/accounts/{}/balance"
FORECAST = "/forecast/cashflow"


def _seed(add_txn, user, account, *, ccy="INR", salary="60000", rent="20000", months=18, start=(2025, 1)):
    """Salary on the 1st, rent on the 5th, two one-off shops a month (3500..4500 each)."""
    y, m = start
    for i in range(months):
        add_txn(user, account, f"{y}-{m:02d}-01", salary, "credit", currency=ccy, merchant="Acme Payroll")
        add_txn(user, account, f"{y}-{m:02d}-05", rent, "debit", currency=ccy, merchant="Landlord")
        # second shop on the LAST day of the month, like a statement that runs to month-end: the engine
        # takes the last transaction date as the forecast origin, so otherwise the final month is "partial"
        last_day = calendar.monthrange(y, m)[1]
        for j, d in enumerate((10, last_day)):
            add_txn(user, account, f"{y}-{m:02d}-{d:02d}", str(3500 + 500 * ((i + j) % 3)), "debit",
                    currency=ccy, merchant=f"Shop {i}-{j}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


# ---------------------------------------------------------------------------
# balance endpoints
# ---------------------------------------------------------------------------
def test_endpoints_require_auth(client):
    aid = "00000000-0000-0000-0000-000000000001"
    assert client.get(FORECAST).status_code == 401
    assert client.put(BALANCE.format(aid), json={"opening_balance": "1", "balance_as_of": "2026-01-01"}).status_code == 401
    assert client.delete(BALANCE.format(aid)).status_code == 401


def test_set_read_overwrite_and_clear_balance(alice):
    aid = alice.account()
    assert alice.get("/accounts").json()[0]["opening_balance"] is None

    r = alice.put(BALANCE.format(aid), json={"opening_balance": "12345.67", "balance_as_of": "2026-06-30"})
    assert r.status_code == 200, r.text
    assert r.json()["opening_balance"] == "12345.67" and r.json()["balance_as_of"] == "2026-06-30"
    assert alice.get("/accounts").json()[0]["opening_balance"] == "12345.67"  # persisted, not just echoed

    # negative = money owed (credit card); overwrite replaces both fields together
    r = alice.put(BALANCE.format(aid), json={"opening_balance": "-5000", "balance_as_of": "2026-07-01"})
    assert r.json()["opening_balance"] == "-5000.00" and r.json()["balance_as_of"] == "2026-07-01"

    for _ in range(2):  # clearing is idempotent
        r = alice.delete(BALANCE.format(aid))
        assert r.status_code == 200 and r.json()["opening_balance"] is None and r.json()["balance_as_of"] is None


@pytest.mark.parametrize("body", [
    {"opening_balance": "NaN", "balance_as_of": "2026-06-30"},
    {"opening_balance": "Infinity", "balance_as_of": "2026-06-30"},
    {"opening_balance": "10.001", "balance_as_of": "2026-06-30"},          # 3 decimal places
    {"opening_balance": "1000000000000.00", "balance_as_of": "2026-06-30"},  # 13 integer digits overflows Numeric(14,2)
    {"opening_balance": "abc", "balance_as_of": "2026-06-30"},
    {"opening_balance": "100", "balance_as_of": "2999-01-01"},              # far future
    {"opening_balance": "100", "balance_as_of": "not-a-date"},
    {"opening_balance": "100"},                                              # as_of is mandatory
    {"balance_as_of": "2026-06-30"},                                         # so is the balance
])
def test_balance_validation_rejects_bad_input(alice, body):
    aid = alice.account()
    r = alice.put(BALANCE.format(aid), json=body)
    assert r.status_code == 422, (body, r.text)
    assert alice.get("/accounts").json()[0]["opening_balance"] is None  # nothing was half-written


def test_balance_accepts_the_largest_value_numeric_14_2_can_hold(alice):
    aid = alice.account()
    for v in ("999999999999.99", "-999999999999.99"):  # 12 integer digits + 2 decimals = 14 digits
        r = alice.put(BALANCE.format(aid), json={"opening_balance": v, "balance_as_of": "2026-06-30"})
        assert r.status_code == 200 and r.json()["opening_balance"] == v


def test_balance_date_allows_today_in_any_timezone_but_not_far_future(alice):
    aid = alice.account()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()  # an IST user is a day ahead of UTC
    assert alice.put(BALANCE.format(aid), json={"opening_balance": "1", "balance_as_of": tomorrow}).status_code == 200
    in_a_week = (date.today() + timedelta(days=8)).isoformat()
    assert alice.put(BALANCE.format(aid), json={"opening_balance": "1", "balance_as_of": in_a_week}).status_code == 422


def test_balance_is_isolated_between_users(alice, bob):
    aid = alice.account()
    body = {"opening_balance": "1", "balance_as_of": "2026-01-01"}
    assert bob.put(BALANCE.format(aid), json=body).status_code == 404
    assert bob.delete(BALANCE.format(aid)).status_code == 404
    assert alice.put(BALANCE.format("00000000-0000-0000-0000-000000000000"), json=body).status_code == 404
    assert alice.get("/accounts").json()[0]["opening_balance"] is None


def test_db_refuses_half_a_balance(alice, db):
    aid = alice.account()
    for sql in ("UPDATE accounts SET opening_balance = 5 WHERE id = :a", "UPDATE accounts SET balance_as_of = '2026-01-01' WHERE id = :a"):
        with pytest.raises(IntegrityError):
            db.execute(text(sql), {"a": aid})
            db.commit()
        db.rollback()


# ---------------------------------------------------------------------------
# forecast endpoint
# ---------------------------------------------------------------------------
def test_forecast_for_a_user_with_no_data_is_empty_not_an_error(alice):
    r = alice.get(FORECAST)
    assert r.status_code == 200
    body = r.json()
    assert body["currencies"] == [] and "not financial advice" in body["notice"]


@pytest.mark.parametrize("qs", ["horizon_months=0", "horizon_months=13", "interval_level=0.4", "interval_level=0.99", "as_of=2026-13-45"])
def test_forecast_parameter_validation(alice, qs):
    assert alice.get(f"{FORECAST}?{qs}").status_code == 422


def test_forecast_rejects_someone_elses_account(alice, bob):
    assert bob.get(f"{FORECAST}?account_id={alice.account()}").status_code == 404


def test_forecast_end_to_end_numbers(alice, add_txn):
    acct = alice.account()
    _seed(add_txn, alice, acct)
    assert alice.put(BALANCE.format(acct),
                     json={"opening_balance": "100000.00", "balance_as_of": "2026-06-30"}).status_code == 200

    r = alice.get(f"{FORECAST}?horizon_months=3")
    assert r.status_code == 200, r.text
    (cur,) = r.json()["currencies"]
    assert cur["currency"] == "INR" and cur["status"] == "ok" and cur["as_of"] == "2026-06-30"
    assert [p["start"] for p in cur["periods"]] == ["2026-07-01", "2026-08-01", "2026-09-01"]

    july = cur["periods"][0]
    # Recurring figures are exact, serialized as strings (never floats).
    assert july["recurring_expense"] == "20000.00" and july["recurring_income"] == "60000.00"
    assert {(l["merchant"], l["on"], l["cadence"]) for l in july["recurring"]} == {
        ("Landlord", "2026-07-05", "monthly"), ("Acme Payroll", "2026-07-01", "monthly")}
    # one-off shops 3500..4500 each, two a month -> variable expense is in 7,000..9,000 (+ model error)
    assert Decimal("6000") < Decimal(july["variable_expense"]) < Decimal("10000")
    assert Decimal(july["net"]) == Decimal(july["income"]) - Decimal(july["expense"])

    # Balance chain: 100,000 + each month's net, to the cent.
    bal = Decimal("100000.00")
    for p in cur["periods"]:
        bal += Decimal(p["net"])
        assert Decimal(p["end_balance"]) == bal
        assert Decimal(p["end_balance_low"]) < Decimal(p["end_balance"]) < Decimal(p["end_balance_high"])
    assert cur["balance"]["complete"] is True and cur["balance"]["start_balance"] == "100000.00"
    assert cur["verdict"] == "covered" and cur["verdict_basis"] == "interval"
    assert cur["expense_model"]["mode"] == "backtested" and cur["expense_model"]["leaderboard"]
    assert any("independent" in a for a in cur["assumptions"])  # the weak assumption is stated, not hidden


def test_forecast_without_balance_is_flow_only(alice, add_txn):
    acct = alice.account()
    _seed(add_txn, alice, acct)
    (cur,) = alice.get(FORECAST).json()["currencies"]
    assert cur["balance"]["start_balance"] is None and cur["verdict"] == "unknown"
    assert all(p["end_balance"] is None and p["net"] is not None for p in cur["periods"])


def test_currencies_are_forecast_separately_and_never_combined(alice, add_txn):
    inr = alice.account("Indian", "INR")
    usd = alice.account("Dollar", "USD")
    _seed(add_txn, alice, inr, ccy="INR", salary="60000", rent="20000")
    _seed(add_txn, alice, usd, ccy="USD", salary="3000", rent="1000")
    body = alice.get(FORECAST).json()["currencies"]
    assert [c["currency"] for c in body] == ["INR", "USD"]
    assert body[0]["periods"][0]["recurring_income"] == "60000.00"
    assert body[1]["periods"][0]["recurring_income"] == "3000.00"


def test_other_users_data_never_leaks_into_a_forecast(alice, bob, add_txn):
    _seed(add_txn, alice, alice.account())
    assert bob.get(FORECAST).json()["currencies"] == []
    b_acct = bob.account()
    _seed(add_txn, bob, b_acct, salary="99000", rent="1000")
    a = alice.get(FORECAST).json()["currencies"][0]["periods"][0]
    assert a["recurring_income"] == "60000.00"  # not 99,000: bob's rows are invisible


def test_duplicate_flagged_rows_do_not_feed_the_forecast(alice, add_txn):
    acct = alice.account()
    _seed(add_txn, alice, acct)
    base = alice.get(FORECAST).json()["currencies"][0]["periods"][0]["variable_expense"]
    # Re-upload every shop transaction as a flagged duplicate: forecast must not change.
    from app.db.base import SessionLocal
    from app.db.models import Transaction
    with SessionLocal() as s:
        shops = s.query(Transaction).filter(Transaction.user_id == alice.id, Transaction.merchant_normalized.like("Shop %")).all()
        originals = [(t.id, t.transaction_date, t.amount) for t in shops]
    for tid, when, amount in originals:
        add_txn(alice, acct, when.date().isoformat(), str(amount), "debit", merchant="Shop dup", duplicate_of=tid)
    assert alice.get(FORECAST).json()["currencies"][0]["periods"][0]["variable_expense"] == base


def test_as_of_ignores_later_transactions_what_if(alice, add_txn):
    acct = alice.account()
    _seed(add_txn, alice, acct)
    full = alice.get(FORECAST).json()["currencies"][0]
    assert full["as_of"] == "2026-06-30"
    earlier = alice.get(f"{FORECAST}?as_of=2025-12-31").json()["currencies"][0]
    assert earlier["as_of"] == "2025-12-31" and earlier["periods"][0]["start"] == "2026-01-01"
    # Only 12 months of data then: fewer origins than the full-history run.
    assert earlier["expense_model"]["history_months"] == 12 and full["expense_model"]["history_months"] == 18
    assert alice.get(f"{FORECAST}?as_of=2020-01-01").json()["currencies"] == []  # before any data


def test_account_filter_and_balance_completeness(alice, add_txn):
    main, side = alice.account("Main"), alice.account("Side")
    _seed(add_txn, alice, main)
    add_txn(alice, side, "2026-06-15", "900", "debit", merchant="Cafe")
    alice.put(BALANCE.format(main), json={"opening_balance": "100000", "balance_as_of": "2026-06-30"})

    both = alice.get(FORECAST).json()["currencies"][0]
    assert both["balance"]["accounts_without_balance"] == ["Side"] and both["balance"]["complete"] is False
    assert both["verdict"] == "unknown" and all(p["end_balance"] is None for p in both["periods"])

    only_main = alice.get(f"{FORECAST}?account_id={main}").json()["currencies"][0]
    assert only_main["balance"]["complete"] is True and only_main["verdict"] in ("covered", "at_risk")


def test_short_history_degrades_honestly(alice, add_txn):
    acct = alice.account()
    _seed(add_txn, alice, acct, months=5, start=(2026, 2))  # Feb..Jun
    (cur,) = alice.get(FORECAST).json()["currencies"]
    assert cur["status"] == "limited" and cur["expense_model"]["mode"] == "limited"
    assert cur["expense_model"]["method"] == "moving_average_3"
    assert all(p["variable_expense_low"] is None and p["end_balance_low"] is None for p in cur["periods"])  # no invented interval
    assert any("too few to backtest" in w for w in cur["warnings"])


def test_stale_data_is_flagged_in_the_response(alice, add_txn):
    _seed(add_txn, alice, alice.account())  # data ends 2026-06-30; the real clock is later
    (cur,) = alice.get(FORECAST).json()["currencies"]
    assert any("days old" in w for w in cur["warnings"])


# ---------------------------------------------------------------------------
# Phase 3 -> Phase 5 -> Phase 6 seam: nothing hand-inserted. The statement goes
# through the REAL normalization engine and the REAL enrichment pipeline, and the
# forecast must find the recurring payments in what those produced.
# ---------------------------------------------------------------------------
def test_real_pipeline_output_feeds_the_forecast(alice, db):
    from app.ml.service import enrich_user
    from app.pipeline.normalize.engine import normalize_document
    from tests.test_pipeline_to_analytics import _statement

    acct = alice.account("HDFC", "INR")
    table = [["Date", "Description", "Debit", "Credit"]]
    shop_days = [(3, 17), (9, 26), (12, 21), (2, 14), (6, 24), (11, 19), (4, 28)]  # irregular on purpose
    y, m = 2025, 1
    for i in range(14):  # Jan 2025 .. Feb 2026
        last = calendar.monthrange(y, m)[1]
        table.append([f"01/{m:02d}/{y}", "SALARY ACME CORP", "", "75,000.00"])
        table.append([f"05/{m:02d}/{y}", "HOUSE RENT LANDLORD", "22,000.00", ""])
        for k, d in enumerate(shop_days[i % len(shop_days)]):
            table.append([f"{d:02d}/{m:02d}/{y}", "SWIGGY ORDER 123", f"{400 + 55 * ((i * 2 + k) % 5)}.00", ""])
        table.append([f"{last:02d}/{m:02d}/{y}", "UPI BOOKSTORE", f"{900 + 70 * (i % 4)}.00", ""])
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    doc = _statement(db, alice, acct, table)
    assert normalize_document(db, doc) == 14 * 5
    db.commit()
    enrich_user(db, alice.id)
    db.commit()

    (cur,) = alice.get(f"{FORECAST}?horizon_months=2").json()["currencies"]
    assert cur["as_of"] == "2026-02-28" and cur["status"] == "ok"
    march = cur["periods"][0]
    assert march["start"] == "2026-03-01"
    # Hand-derived: salary credit 75,000 on the 1st and rent debit 22,000 on the 5th, projected exactly.
    lines = {(l["type"], l["amount"], l["on"]) for l in march["recurring"]}
    assert ("credit", "75000.00", "2026-03-01") in lines
    assert ("debit", "22000.00", "2026-03-05") in lines
    # The month-end bookstore purchase (one a month, 900..1110) is correctly detected as a variable-amount
    # monthly bill: its projected amount is the median of the last three (1110, 900, 970) = 970. The day shown
    # drifts to the 28th (clamping), so only the amount and the month are asserted.
    book = [l for l in march["recurring"] if l["amount"] == "970.00"]
    assert len(book) == 1 and book[0]["amount_variable"] is True and book[0]["on"].startswith("2026-03-")
    assert march["recurring_income"] == "75000.00" and march["recurring_expense"] == "22970.00"
    # Recurring items are removed from the variable history (else rent would be counted twice). What is left
    # is Swiggy only: two orders of 400..620, so 800..1240 a month. Bounds are loose on purpose: the chosen
    # model may legitimately extrapolate a little.
    assert Decimal("600") < Decimal(march["variable_expense"]) < Decimal("1600")
    assert march["variable_income"] == "0.00"
    # A salaried user's all-zero variable income is normal, not something to warn about on every request.
    assert not any("every usable month is 0" in w for w in cur["warnings"])
    assert cur["income_model"]["mode"] == "all_zero"


def test_longest_horizon_works_and_far_intervals_are_borrowed_not_invented(alice, add_txn):
    acct = alice.account()
    _seed(add_txn, alice, acct)
    alice.put(BALANCE.format(acct), json={"opening_balance": "100000", "balance_as_of": "2026-06-30"})
    r = alice.get(f"{FORECAST}?horizon_months=12")
    assert r.status_code == 200, r.text
    (cur,) = r.json()["currencies"]
    assert len(cur["periods"]) == 12 and cur["periods"][-1]["end"] == "2027-06-30"
    # every period carries a complete, finite balance chain and an interval; far ones are no narrower than near ones
    widths = [Decimal(p["end_balance_high"]) - Decimal(p["end_balance"]) for p in cur["periods"]]
    assert all(w > 0 for w in widths) and widths == sorted(widths)
