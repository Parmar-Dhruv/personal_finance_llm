"""
Phase 6 pure-logic tests (no DB): methods, backtest, schedule, history, engine.
Expected values are worked out by hand in the comments, not copied from output.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest

from app.forecast import backtest as bt
from app.forecast import history, schedule
from app.forecast.engine import AccountInfo, build_periods, forecast_currency
from app.forecast.methods import BY_NAME, METHODS, MethodFailed


# ----------------------------------------------------------------------------
# methods
# ----------------------------------------------------------------------------
def test_simple_methods_exact_values():
    y = np.array([10.0, 20.0, 30.0, 40.0])
    assert list(BY_NAME["naive"].forecast(y, 3)) == [40.0] * 3
    assert list(BY_NAME["moving_average_3"].forecast(y, 2)) == [30.0, 30.0]  # (20+30+40)/3
    # drift: slope (40-10)/3 = 10 -> 50, 60, 70
    assert list(BY_NAME["drift"].forecast(y, 3)) == [50.0, 60.0, 70.0]


def test_median_12_ignores_one_off_spike():
    y = np.array([100.0] * 11 + [5000.0])
    assert BY_NAME["median_12"].forecast(y, 1)[0] == 100.0
    assert BY_NAME["moving_average_6"].forecast(y, 1)[0] > 800  # the mean is dragged by it


def test_seasonal_naive_repeats_same_month_last_year():
    y = np.arange(1.0, 13.0)  # Jan..Dec = 1..12
    # next 14 months: Jan, Feb, ..., Dec, Jan, Feb  -> wraps after 12
    assert list(BY_NAME["seasonal_naive"].forecast(y, 14)) == list(range(1, 13)) + [1.0, 2.0]


def test_negative_extrapolation_is_clipped_to_zero():
    y = np.array([100.0, 60.0, 20.0, 0.0])  # drift slope -33.3 -> would go negative
    out = BY_NAME["drift"].forecast(y, 3)
    assert np.all(out >= 0) and out[-1] == 0.0


def test_ets_runs_on_realistic_series_and_is_finite():
    rng = np.random.default_rng(1)
    y = 20000 + rng.normal(0, 1000, 16)
    for name in ("ets_ann", "ets_damped_trend"):
        out = BY_NAME[name].forecast(y, 4)
        assert out.shape == (4,) and np.all(np.isfinite(out)) and np.all(out >= 0)


def test_ets_seasonal_needs_three_years_and_recovers_seasonality():
    assert BY_NAME["ets_seasonal"].min_train == 36
    t = np.arange(48)
    y = 20000 + 4000 * np.sin(2 * np.pi * t / 12)
    pred = BY_NAME["ets_seasonal"].forecast(y, 12)
    truth = 20000 + 4000 * np.sin(2 * np.pi * np.arange(48, 60) / 12)
    assert np.mean(np.abs(pred - truth)) < 400  # noise-free sine: it must find it


def test_method_menu_is_ordered_by_complexity_with_unique_names():
    assert len({m.name for m in METHODS}) == len(METHODS)
    assert BY_NAME["naive"].complexity < BY_NAME["ets_ann"].complexity < BY_NAME["ets_seasonal"].complexity


# ----------------------------------------------------------------------------
# backtest
# ----------------------------------------------------------------------------
def test_eligibility_depends_on_history_length():
    y = np.linspace(1000, 1100, 14) + np.tile([0, 30], 7)
    res = bt.run_backtest(y, 3)
    status = {s.name: s.status for s in res.scores}
    # n=14 -> target origins = max(4, min(8, 11)) = 8. ets_ann min_train 6: 14-6=8 -> eligible.
    assert status["ets_ann"] == "scored"
    # ets_damped_trend min_train 10: 14-10=4 < 8 -> ineligible; seasonal-naive 12: 2 < 8.
    assert status["ets_damped_trend"] == "ineligible"
    assert status["seasonal_naive"] == "ineligible"
    assert status["ets_seasonal"] == "ineligible"
    assert "needs" in next(s for s in res.scores if s.name == "ets_damped_trend").detail


def test_all_contestants_scored_on_identical_origins():
    y = np.linspace(1000, 1100, 20) + np.tile([0, 30, -20], 7)[:20]
    res = bt.run_backtest(y, 3)
    scored = [s for s in res.scores if s.status == "scored"]
    assert len(scored) >= 4
    # Same origins for everyone => same number of errors for everyone.
    assert len({s.n_errors for s in scored}) == 1
    # origins t0..n-1, errors per origin = min(h, n-t)
    expected = sum(min(3, 20 - t) for t in range(res.first_origin, 20))
    assert scored[0].n_errors == expected


def test_perfectly_linear_series_selects_drift_with_zero_error():
    y = 1000.0 + 50.0 * np.arange(20)
    res = bt.run_backtest(y, 3)
    assert res.selected == "drift"
    drift = next(s for s in res.scores if s.name == "drift")
    assert drift.mae == pytest.approx(0.0, abs=1e-9)
    naive = next(s for s in res.scores if s.name == "naive")
    assert naive.mae > 50  # repeating the last month is off by 50*k
    assert naive.mase is not None and naive.mase > 1  # worse than its own one-step benchmark here


def test_constant_series_ties_everywhere_and_simplest_wins():
    res = bt.run_backtest(np.full(16, 500.0), 3)
    assert res.selected == "naive"  # everything has MAE 0; simplest model breaks the tie


def test_rank_models_tolerance_band_prefers_simplicity():
    a = bt.ModelScore("ets_ann", "", "scored", mae=100.0)  # complexity 4
    b = bt.ModelScore("naive", "", "scored", mae=101.5)  # complexity 0, within 2% of best
    c = bt.ModelScore("drift", "", "scored", mae=105.0)  # outside the band
    assert bt.rank_models([a, b, c]) == ["naive", "ets_ann", "drift"]
    # Just outside the band: the best model wins outright.
    b2 = bt.ModelScore("naive", "", "scored", mae=102.5)
    assert bt.rank_models([a, b2])[0] == "ets_ann"


def test_conformal_halfwidth_values():
    errs = [float(i) for i in range(1, 10)]  # 1..9
    # level .8, m=9: rank = ceil(10*.8) = 8 -> the 8th smallest = 8
    assert bt.conformal_halfwidth(errs, 0.8) == (8.0, False)
    # 3 errors at .8: rank = ceil(4*.8)=4 > 3 -> capped at the max, flagged
    assert bt.conformal_halfwidth([1.0, 2.0, 5.0], 0.8) == (5.0, True)


def test_interval_halfwidths_borrow_and_none_before_first_qualifying_step():
    errors = {1: [1.0] * 6, 2: [2.0] * 3, 3: [3.0] * 6}  # step 2 has too few (<5)
    out = bt.interval_halfwidths(errors, 4, 0.8)
    assert out[0][0] == 1.0 and out[0][1].startswith("backtest_step_1")
    assert out[1] == (1.0, "borrowed_from_step_1")  # step 2 borrows step 1
    assert out[2][0] == 3.0
    assert out[3] == (3.0, "borrowed_from_step_3")  # step 4 has no errors at all
    none_first = bt.interval_halfwidths({1: [1.0] * 2}, 2, 0.8)
    assert none_first == [(None, None), (None, None)]


def test_forecast_series_modes():
    assert bt.forecast_series([100.0, 200.0], 3).mode == "unavailable"
    assert bt.forecast_series([100.0, 200.0], 3).point is None

    lim = bt.forecast_series([100.0, 120.0, 110.0, 130.0, 100.0], 2)
    assert lim.mode == "limited" and lim.method == "moving_average_3"
    assert lim.point == pytest.approx([(110.0 + 130.0 + 100.0) / 3] * 2)
    assert lim.half_width == [None, None]  # no interval fabricated from 5 points

    z = bt.forecast_series([0.0] * 9, 2)
    assert z.mode == "all_zero" and z.point == [0.0, 0.0]

    rng = np.random.default_rng(3)
    ok = bt.forecast_series(8000 + rng.normal(0, 400, 20), 3)
    assert ok.mode == "backtested" and len(ok.point) == 3
    assert all(h is not None and h > 0 for h in ok.half_width)


def test_few_origins_is_flagged():
    # n=8: target origins = max(4, min(8, 8-3)) = 5. Only naive/MA3/median fit that many
    # (min_train <= 3); their common first origin is t=3, so 8-3 = 5 origins.
    fs = bt.forecast_series([100, 120, 90, 110, 130, 95, 105, 115], 2)
    assert fs.mode == "backtested" and fs.backtest.n_origins == 5
    assert {s.name for s in fs.backtest.scores if s.status == "scored"} == {"naive", "moving_average_3", "median_12"}
    assert any("only 5 backtest origins" in n for n in fs.notes)


# ----------------------------------------------------------------------------
# schedule
# ----------------------------------------------------------------------------
def test_add_months_clamps_to_month_end_without_drifting():
    assert schedule.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert schedule.add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)  # leap year
    assert schedule.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert schedule.add_months(date(2026, 12, 15), 1) == date(2027, 1, 15)  # year rollover


def _item(cadence="monthly", last=date(2026, 6, 5), typ="debit", amount="20000.00", merchant="Rent"):
    return schedule.Item("acct", merchant, typ, cadence, Decimal(amount), False, 0.9, last)


def test_monthly_projection_keeps_the_day_of_month():
    occ = schedule.project([_item(last=date(2026, 6, 5))], as_of=date(2026, 6, 30), end=date(2026, 9, 30))
    assert [o.on for o in occ] == [date(2026, 7, 5), date(2026, 8, 5), date(2026, 9, 5)]
    assert not any(o.assumed_pending for o in occ)


def test_weekly_and_biweekly_and_quarterly_projection():
    wk = schedule.project([_item("weekly", date(2026, 6, 29))], date(2026, 6, 30), date(2026, 7, 31))
    assert [o.on for o in wk] == [date(2026, 7, 6), date(2026, 7, 13), date(2026, 7, 20), date(2026, 7, 27)]
    bw = schedule.project([_item("biweekly", date(2026, 6, 20))], date(2026, 6, 30), date(2026, 7, 31))
    assert [o.on for o in bw] == [date(2026, 7, 4), date(2026, 7, 18)]
    # Quarterly, last 31 Mar: the 30 Jun occurrence is due ON as_of with no transaction
    # on record, so it is 0 days late (within tolerance) -> pending, placed on 1 Jul.
    q = schedule.project([_item("quarterly", date(2026, 3, 31))], date(2026, 6, 30), date(2027, 1, 31))
    assert [(o.on, o.assumed_pending) for o in q] == [
        (date(2026, 7, 1), True), (date(2026, 9, 30), False), (date(2026, 12, 31), False)
    ]


def test_overdue_within_tolerance_is_assumed_pending_beyond_is_skipped():
    # Monthly, last paid 2026-05-27 -> due 2026-06-27; as_of 06-30 is 3 days late (tolerance 4.5).
    pend = schedule.project([_item(last=date(2026, 5, 27))], date(2026, 6, 30), date(2026, 8, 31))
    assert [(o.on, o.assumed_pending) for o in pend] == [
        (date(2026, 7, 1), True), (date(2026, 7, 27), False), (date(2026, 8, 27), False)
    ]
    # 10 days late (> 4.5): treated as skipped, nothing placed on the first forecast day.
    skipped = schedule.project([_item(last=date(2026, 5, 20))], date(2026, 6, 30), date(2026, 8, 31))
    assert not any(o.assumed_pending for o in skipped)
    assert skipped[0].on == date(2026, 7, 20)


# ----------------------------------------------------------------------------
# history
# ----------------------------------------------------------------------------
def _row(on, amount="100", typ="debit", merchant=None, rid=None, account="a1", ccy="INR"):
    return history.TxnRow(rid or uuid.uuid4(), on, account, ccy, typ, Decimal(amount), merchant)


# day=3 on purpose: a first transaction after day 7 triggers the leading-partial-month rule
def _months_data(start_year, start_month, n, day=3, amount="1000"):
    rows, y, m = [], start_year, start_month
    for _ in range(n):
        rows.append(_row(date(y, m, day), amount))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return rows


def test_current_partial_month_is_dropped_but_complete_month_is_kept():
    rows = _months_data(2026, 1, 6)  # Jan..Jun, row on the 3rd
    partial = history.monthly_variable(rows, set(), date(2026, 6, 20))
    assert [m.month for m in partial.months] == [1, 2, 3, 4, 5]
    assert any("partial month 2026-06" in n for n in partial.notes)
    full = history.monthly_variable(rows, set(), date(2026, 6, 30))
    assert [m.month for m in full.months] == [1, 2, 3, 4, 5, 6]


def test_leading_partial_month_dropped_only_when_enough_history_remains():
    late_start = [_row(date(2026, 1, 20))] + _months_data(2026, 2, 6)  # first txn on the 20th
    out = history.monthly_variable(late_start, set(), date(2026, 7, 31))  # data runs Jan 20 .. Jul 3
    assert out.months[0] == date(2026, 2, 1)
    assert any("2026-01 excluded" in n for n in out.notes)

    short = [_row(date(2026, 1, 20))] + _months_data(2026, 2, 2)  # only 3 months total
    kept = history.monthly_variable(short, set(), date(2026, 3, 31))
    assert kept.months[0] == date(2026, 1, 1)  # too little history to drop it
    assert any("kept because too little history" in n for n in kept.notes)


def test_month_with_no_transactions_is_a_hole_not_zero_spending():
    rows = _months_data(2026, 1, 8)
    rows = [r for r in rows if r.on.month != 4]  # missing April statement
    out = history.monthly_variable(rows, set(), date(2026, 8, 31))
    assert [m.month for m in out.months] == [5, 6, 7, 8]  # only data after the hole
    assert all(v == 1000.0 for v in out.expense)  # no phantom 0 month
    assert any("missing statements" in n and "2026-04" in n for n in out.notes)


def test_excluded_recurring_rows_leave_the_amounts_but_not_the_data_presence():
    keep = _row(date(2026, 1, 3), "300")
    rent = _row(date(2026, 1, 5), "20000")
    only_rent_month = _row(date(2026, 2, 5), "20000")
    out = history.monthly_variable([keep, rent, only_rent_month] + _months_data(2026, 3, 4), {rent.id, only_rent_month.id}, date(2026, 6, 30))
    assert out.expense[0] == 300.0  # January: rent removed, groceries kept
    assert out.expense[1] == 0.0  # February had only rent: a REAL zero-variable month, not a hole
    assert date(2026, 2, 1) in out.months


def test_income_and_expense_are_separated_and_single_partial_month_yields_nothing():
    rows = [_row(date(2026, 1, 3), "500", "credit"), _row(date(2026, 1, 12), "200", "debit")] + _months_data(2026, 2, 3)
    out = history.monthly_variable(rows, set(), date(2026, 4, 30))
    assert out.income[0] == 500.0 and out.expense[0] == 200.0
    lone = history.monthly_variable([_row(date(2026, 6, 3))], set(), date(2026, 6, 10))
    assert lone.months == [] and any("single partial month" in n for n in lone.notes)


# ----------------------------------------------------------------------------
# engine (pure core)
# ----------------------------------------------------------------------------
def _scenario(n_months=18, with_variable_income=False):
    """Jan 2025 .. Jun 2026: salary 60,000 on the 1st, rent 20,000 on the 5th, two one-off shops a month."""
    rows, y, m = [], 2025, 1
    for i in range(n_months):
        rows.append(_row(date(y, m, 1), "60000", "credit", "Acme Payroll"))
        rows.append(_row(date(y, m, 5), "20000", "debit", "Landlord"))
        for j, d in enumerate((10, 20)):
            rows.append(_row(date(y, m, d), str(3500 + 500 * ((i + j) % 3)), "debit", f"Shop {i}-{j}"))
        if with_variable_income:
            rows.append(_row(date(y, m, 15), str(2000 + 300 * (i % 4)), "credit", f"Client {i}"))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return rows


ACCT = lambda bal=None, as_of=None: AccountInfo("a1", "Main", "INR", bal, as_of)  # noqa: E731


def test_build_periods_stub_then_full_months():
    p = build_periods(date(2026, 6, 30), 3)  # as_of is month-end: no stub
    assert [(x.start, x.end, x.is_stub) for x in p] == [
        (date(2026, 7, 1), date(2026, 7, 31), False),
        (date(2026, 8, 1), date(2026, 8, 31), False),
        (date(2026, 9, 1), date(2026, 9, 30), False),
    ]
    q = build_periods(date(2026, 6, 20), 2)  # 21..30 June is a stub, then 2 full months
    assert [(x.start, x.end, x.is_stub) for x in q] == [
        (date(2026, 6, 21), date(2026, 6, 30), True),
        (date(2026, 7, 1), date(2026, 7, 31), False),
        (date(2026, 8, 1), date(2026, 8, 31), False),
    ]
    assert build_periods(date(2025, 12, 31), 1)[0].start == date(2026, 1, 1)  # year rollover


def _run(rows, accounts, **kw):
    kw.setdefault("as_of", date(2026, 6, 30))
    kw.setdefault("horizon_months", 3)
    kw.setdefault("level", 0.8)
    kw.setdefault("today", date(2026, 7, 2))
    return forecast_currency("INR", rows, accounts, **kw)


def test_engine_recurring_exact_and_variable_statistical():
    f = _run(_scenario(), [ACCT(Decimal("100000.00"), date(2026, 6, 30))])
    assert f.status == "ok"
    july = f.periods[0]
    # Recurring items are exact: rent debit on 5 July, salary credit on 1 July.
    assert july.recurring_expense == Decimal("20000.00") and july.recurring_income == Decimal("60000.00")
    assert {(l.merchant, l.on) for l in july.recurring} == {("Landlord", date(2026, 7, 5)), ("Acme Payroll", date(2026, 7, 1))}
    # Variable income history is all zeros -> all_zero mode, forecast exactly 0 with a zero-width interval.
    assert f.income_model.mode == "all_zero" and july.variable_income == Decimal("0.00")
    # Variable expense: one-off shops 3500..4500 per shop, two a month -> monthly total 7,000..9,000.
    assert Decimal("6500") < july.variable_expense < Decimal("9500")
    assert july.expense == july.recurring_expense + july.variable_expense
    assert july.net == july.income - july.expense


def test_engine_balance_chain_reconciles():
    f = _run(_scenario(), [ACCT(Decimal("100000.00"), date(2026, 6, 30))])
    assert f.balance.start_balance == Decimal("100000.00") and f.balance.complete
    running = Decimal("100000.00")
    for p in f.periods:
        running += p.net
        assert p.end_balance == running  # each period's balance = previous + that period's net
    # Intervals widen with horizon (independent months add in quadrature).
    widths = [p.end_balance_high - p.end_balance for p in f.periods]
    assert widths[0] <= widths[1] <= widths[2]
    assert f.verdict == "covered" and f.verdict_basis == "interval"


def test_balance_counts_only_transactions_after_the_balance_date():
    rows = _scenario()
    # Balance stated at END of 2026-06-01: the June 1 salary is already inside it; later June rows are not.
    f = _run(rows, [ACCT(Decimal("50000.00"), date(2026, 6, 1))])
    june_after = Decimal(0)
    for r in rows:
        if r.on > date(2026, 6, 1) and r.on <= date(2026, 6, 30):
            june_after += r.amount if r.type == "credit" else -r.amount
    assert f.balance.start_balance == Decimal("50000.00") + june_after


def test_no_balance_means_flow_only_and_unknown_verdict():
    f = _run(_scenario(), [ACCT()])
    assert f.balance.start_balance is None
    assert all(p.end_balance is None for p in f.periods)
    assert f.periods[0].net is not None  # flows are still forecast
    assert f.verdict == "unknown" and "no account balance" in f.verdict_basis


def test_partial_balance_coverage_withholds_projection():
    rows = _scenario()
    rows += [_row(date(2026, 6, 15), "900", "debit", None, account="a2")]
    accts = [ACCT(Decimal("100000.00"), date(2026, 6, 30)), AccountInfo("a2", "Wallet", "INR", None, None)]
    f = _run(rows, accts)
    assert f.balance.complete is False and f.balance.accounts_without_balance == ["Wallet"]
    assert all(p.end_balance is None for p in f.periods)
    assert f.verdict == "unknown" and "Wallet" in f.verdict_basis
    assert any("withheld" in w for w in f.warnings)


def test_shortfall_and_at_risk_verdicts():
    rows = _scenario()
    # No salary in the data: rent + ~8,000 of shopping leaves a ~28,000 monthly hole -> point forecast negative.
    broke = _run([r for r in rows if r.merchant != "Acme Payroll"], [ACCT(Decimal("1000.00"), date(2026, 6, 30))])
    assert broke.periods[0].end_balance < 0 and broke.verdict == "shortfall"

    # at_risk, built deterministically: from a zero start, month 1 ends at N with lower band N-hw.
    # Starting from s = -(N - hw/2) puts the point forecast at +hw/2 and the lower band at -hw/2.
    base = _run(rows, [ACCT(Decimal("0.00"), date(2026, 6, 30))]).periods[0]
    hw = base.end_balance_high - base.end_balance
    assert hw > 0
    s = -(base.end_balance - hw / 2)
    edge = _run(rows, [ACCT(s.quantize(Decimal("0.01")), date(2026, 6, 30))])
    p = edge.periods[0]
    assert p.end_balance > 0 > p.end_balance_low
    assert edge.verdict == "at_risk" and edge.verdict_basis == "interval"
    # ...and a comfortable start is plainly covered.
    assert _run(rows, [ACCT(Decimal("500000.00"), date(2026, 6, 30))]).verdict == "covered"


def test_stale_data_and_pending_recurring_are_warned():
    f = _run(_scenario(), [ACCT()], today=date(2026, 9, 1))
    assert any("days old" in w for w in f.warnings)


def test_too_little_history_gives_recurring_only_status():
    rows = [_row(date(2026, 5, 5), "20000", "debit", "Landlord"), _row(date(2026, 6, 5), "20000", "debit", "Landlord")]
    f = _run(rows, [ACCT(Decimal("50000.00"), date(2026, 6, 30))])
    assert f.status == "recurring_only"
    assert all(p.variable_expense is None and p.net is None for p in f.periods)
    assert f.verdict == "unknown"


def test_cancelled_subscription_is_removed_from_history_and_not_projected():
    rows = _scenario()
    # A Netflix-style monthly 649 that stopped in Dec 2025 (6 months before as_of).
    y, m = 2025, 1
    for _ in range(12):
        rows.append(_row(date(y, m, 8), "649", "debit", "Streamly"))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    f = _run(rows, [ACCT()])
    projected = {l.merchant for p in f.periods for l in p.recurring}
    assert "Streamly" not in projected
    assert f.periods[0].recurring_expense == Decimal("20000.00")


def test_stub_month_prorates_and_marks_itself():
    rows = [r for r in _scenario() if r.on <= date(2026, 6, 20)]
    f = _run(rows, [ACCT()], as_of=date(2026, 6, 20))
    assert f.periods[0].is_stub and f.periods[0].start == date(2026, 6, 21)
    stub, nxt = f.periods[0], f.periods[1]
    assert not nxt.is_stub
    # 10 days of 30 -> a third of a full month's variable forecast (same model, different step: allow slack)
    assert stub.variable_expense < nxt.variable_expense
    assert any("prorated" in a for a in f.assumptions)


# ----------------------------------------------------------------------------
# robustness: seeded random histories must never crash and must stay self-consistent
# ----------------------------------------------------------------------------
def _random_rows(rng, n_rows, span_days, currencies=("INR",)):
    rows = []
    merchants = [None, "Salary Co", "Landlord", "Cafe", "Metro", "Gym", "Shop A", "Shop B", "Utility"]
    start = date(2024, 1, 1)
    for _ in range(n_rows):
        on = start + timedelta(days=int(rng.integers(0, span_days)))
        rows.append(history.TxnRow(
            uuid.uuid4(), on, "a1", str(rng.choice(currencies)), "credit" if rng.random() < 0.25 else "debit",
            Decimal(str(round(float(np.exp(rng.normal(7, 1.5))), 2))), merchants[int(rng.integers(0, len(merchants)))],
        ))
    return rows


@pytest.mark.parametrize("seed", range(40))
def test_random_histories_never_crash_and_stay_consistent(seed):
    rng = np.random.default_rng(seed)
    n_rows = int(rng.choice([1, 2, 5, 12, 40, 150, 400]))
    rows = _random_rows(rng, n_rows, int(rng.choice([1, 20, 90, 400, 900])))
    as_of = max(r.on for r in rows)
    bal = Decimal(str(round(float(rng.normal(20000, 30000)), 2))) if rng.random() < 0.6 else None
    acct = AccountInfo("a1", "Main", "INR", bal, (as_of - timedelta(days=int(rng.integers(0, 60)))) if bal is not None else None)
    horizon = int(rng.choice([1, 3, 6, 12]))

    f = forecast_currency("INR", rows, [acct], as_of=as_of, horizon_months=horizon, level=0.8, today=as_of)

    assert f.status in ("ok", "limited", "recurring_only") and f.verdict in ("covered", "at_risk", "shortfall", "unknown")
    assert len(f.periods) >= horizon  # a stub month may come first
    running = f.balance.start_balance
    for p in f.periods:
        assert p.start <= p.end
        for v in (p.recurring_expense, p.recurring_income):
            assert v >= 0 and v == v.quantize(Decimal("0.01"))
        if p.net is not None:
            assert p.variable_expense >= 0 and p.variable_income >= 0
            assert p.expense == p.recurring_expense + p.variable_expense
            assert p.income == p.recurring_income + p.variable_income
            assert p.net == p.income - p.expense
            if p.variable_expense_low is not None:
                assert p.variable_expense_low <= p.variable_expense <= p.variable_expense_high
            if p.net_low is not None:
                assert p.net_low <= p.net <= p.net_high
        if p.end_balance is not None:
            running = running + p.net
            assert p.end_balance == running
            if p.end_balance_low is not None:
                assert p.end_balance_low <= p.end_balance <= p.end_balance_high
        else:
            assert f.verdict == "unknown" or p.is_stub
    if f.balance.start_balance is None:
        assert all(p.end_balance is None for p in f.periods)
