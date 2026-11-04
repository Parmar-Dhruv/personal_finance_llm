"""
Cash-flow forecast, per currency (currencies are never converted or combined).

    forecast = recurring payments on their dates          (deterministic)
             + variable spending / income, statistically  (backtested, with intervals)
    balance  = user-supplied opening balance + realised flows + forecast flows

`forecast_currency` is pure; `forecast_cashflow` is the thin DB wrapper.

Recurring payments are RE-DETECTED here from the transactions on or before
`as_of` (the same pure detector Phase 5 uses) instead of read from the stored
recurring_series rows. Stored rows reflect the user's whole history, so a
what-if `as_of` would leak the future into the schedule, and they go stale
between uploads and enrichment. The cost is one extra detector pass per request.

What "variable" means: every transaction that is NOT a member of a trusted
(confidence >= MIN_SERIES_CONFIDENCE) recurring series. Members of ended
(inactive) trusted series are removed from the history too, so a cancelled
subscription does not keep inflating the forecast, but only ACTIVE trusted
series are projected forward.

Accounting vs estimation: everything that is money (sums, balances, outputs)
is Decimal; floats exist only inside the statistical models, and cross back
here rounded to cents.
"""

from __future__ import annotations

import calendar
import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.common import Scope, month_end, month_start, next_month
from app.db.models import Account
from app.forecast import history, schedule
from app.forecast.backtest import ModelScore, SeriesForecast, forecast_series
from app.ml import recurring as rec

MIN_SERIES_CONFIDENCE = 0.5
STALE_AFTER_DAYS = 35
MAX_HORIZON_MONTHS = 12
_CENT = Decimal("0.01")
ZERO = Decimal("0.00")

NOTICE = (
    "Projection for decision support, not financial advice. Every figure rests on the assumptions "
    "listed with it; the model's own error on past months is the only uncertainty measured."
)


def _d(x: float) -> Decimal:
    return Decimal(repr(float(x))).quantize(_CENT, rounding=ROUND_HALF_UP)


# ----------------------------------------------------------------------------
# Result types
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class AccountInfo:
    id: object
    name: str
    currency: str
    opening_balance: Decimal | None
    balance_as_of: date | None


@dataclass
class RecurringLine:
    merchant: str
    type: str
    cadence: str
    amount: Decimal
    on: date
    assumed_pending: bool
    amount_variable: bool
    confidence: float


@dataclass
class PeriodForecast:
    start: date
    end: date
    is_stub: bool  # the rest of the current month, shorter than a full month
    recurring_expense: Decimal
    recurring_income: Decimal
    variable_expense: Decimal | None
    variable_income: Decimal | None
    expense: Decimal | None  # recurring + variable
    income: Decimal | None
    net: Decimal | None
    variable_expense_low: Decimal | None
    variable_expense_high: Decimal | None
    net_low: Decimal | None
    net_high: Decimal | None
    end_balance: Decimal | None
    end_balance_low: Decimal | None
    end_balance_high: Decimal | None
    recurring: list[RecurringLine] = field(default_factory=list)


@dataclass
class SeriesSummary:
    mode: str  # backtested | limited | all_zero | unavailable
    method: str | None
    interval_level: float
    history_months: int
    first_month: date | None
    last_month: date | None
    n_origins: int | None
    leaderboard: list[ModelScore]
    notes: list[str]


@dataclass
class BalanceInfo:
    start_balance: Decimal | None  # the balance at `as_of`, before any forecast flow
    accounts_with_balance: list[str]
    accounts_without_balance: list[str]  # accounts that have transactions but no balance set
    complete: bool
    notes: list[str]


@dataclass
class CurrencyForecast:
    currency: str
    status: str  # ok | limited | recurring_only
    as_of: date
    horizon_months: int
    periods: list[PeriodForecast]
    expense_model: SeriesSummary
    income_model: SeriesSummary
    balance: BalanceInfo
    verdict: str  # covered | at_risk | shortfall | unknown
    verdict_basis: str  # interval | point_only | why it is unknown
    verdict_period_end: date | None
    assumptions: list[str]
    warnings: list[str]


# ----------------------------------------------------------------------------
# Periods
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class _Period:
    start: date
    end: date
    is_stub: bool
    days_total: int  # days in the calendar month


def build_periods(as_of: date, horizon_months: int) -> list[_Period]:
    """The rest of the current month (if any) followed by `horizon_months` full months."""
    start = as_of + timedelta(days=1)
    periods: list[_Period] = []
    cursor = start
    if start.day != 1:
        periods.append(_Period(start, month_end(start), True, calendar.monthrange(start.year, start.month)[1]))
        cursor = next_month(start)
    for _ in range(horizon_months):
        periods.append(_Period(cursor, month_end(cursor), False, calendar.monthrange(cursor.year, cursor.month)[1]))
        cursor = next_month(cursor)
    return periods


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


# ----------------------------------------------------------------------------
# Pure core
# ----------------------------------------------------------------------------
def _summary(fc: SeriesForecast, clean: history.CleanSeries) -> SeriesSummary:
    bt = fc.backtest
    return SeriesSummary(
        mode=fc.mode, method=fc.method, interval_level=fc.level,
        history_months=len(clean.months),
        first_month=clean.months[0] if clean.months else None,
        last_month=clean.months[-1] if clean.months else None,
        n_origins=bt.n_origins if bt else None,
        leaderboard=bt.scores if bt else [],
        notes=fc.notes,
    )


def _balances(rows: list[history.TxnRow], accounts: list[AccountInfo], as_of: date) -> BalanceInfo:
    by_id = {a.id: a for a in accounts}
    delta: dict[object, Decimal] = {a.id: Decimal(0) for a in accounts if a.opening_balance is not None}
    has_txns: set = set()
    for r in rows:
        has_txns.add(r.account_id)
        a = by_id.get(r.account_id)
        # balance_as_of is the END of that day: later transactions are on top of it,
        # earlier-or-equal ones are already inside it.
        if a is not None and a.balance_as_of is not None and r.on > a.balance_as_of:
            delta[a.id] += r.amount if r.type == "credit" else -r.amount

    with_bal = [a for a in accounts if a.opening_balance is not None]
    without = [a for a in accounts if a.opening_balance is None and a.id in has_txns]
    notes: list[str] = []
    for a in with_bal:
        if a.balance_as_of > as_of:
            notes.append(
                f"{a.name}: balance is dated {a.balance_as_of}, after the last transaction ({as_of}); "
                "flows between the two dates are not in the data, so the projection may be off"
            )
    start = sum((a.opening_balance + delta[a.id] for a in with_bal), Decimal(0)).quantize(_CENT) if with_bal else None
    return BalanceInfo(
        start_balance=start,
        accounts_with_balance=[a.name for a in with_bal],
        accounts_without_balance=[a.name for a in without],
        complete=bool(with_bal) and not without,
        notes=notes,
    )


def forecast_currency(
    currency: str,
    rows: list[history.TxnRow],
    accounts: list[AccountInfo],
    *,
    as_of: date,
    horizon_months: int,
    level: float,
    today: date,
) -> CurrencyForecast:
    warnings: list[str] = []

    # --- recurring: detect on data <= as_of, split history, project forward ----
    as_of_dt = datetime.combine(as_of, time.min, tzinfo=timezone.utc)
    detected = rec.detect_recurring(
        [rec.RTxn(r.id, datetime.combine(r.on, time.min, tzinfo=timezone.utc), r.merchant, r.amount, r.type,
                  r.account_id, r.currency) for r in rows],
        as_of=as_of_dt,
    )
    trusted = [s for s in detected if s.confidence >= MIN_SERIES_CONFIDENCE]
    excluded_ids = {i for s in trusted for i in s.member_ids}
    items = [
        schedule.Item(s.account, s.merchant, s.type, s.cadence, s.typical_amount, s.amount_variable,
                      s.confidence, s.last_date.date())
        for s in trusted if s.is_active
    ]
    if not detected:
        warnings.append("no recurring payments were detected, so every flow is forecast statistically")

    # --- variable history ------------------------------------------------------
    clean = history.monthly_variable(rows, excluded_ids, as_of)

    periods = build_periods(as_of, horizon_months)
    steps_by_period: list[int] = []
    max_step = 1
    if clean.months:
        last = clean.months[-1]
        steps_by_period = [_months_between(last, month_start(p.start)) for p in periods]
        max_step = max(steps_by_period)
    fc_exp = forecast_series(clean.expense, max_step, level)
    fc_inc = forecast_series(clean.income, max_step, level)

    occurrences = schedule.project(items, as_of, periods[-1].end)

    # --- period by period -------------------------------------------------------
    balance = _balances(rows, accounts, as_of)
    variable_ok = fc_exp.point is not None and fc_inc.point is not None
    can_project_balance = variable_ok and balance.start_balance is not None and balance.complete

    out: list[PeriodForecast] = []
    running = balance.start_balance
    cum_var_sq = 0.0  # running sum of squared net half-widths (independent months)
    cum_ok = True
    for idx, p in enumerate(periods):
        occ = [o for o in occurrences if p.start <= o.on <= p.end]
        lines = [
            RecurringLine(o.item.merchant, o.item.type, o.item.cadence, o.item.amount, o.on, o.assumed_pending,
                          o.item.amount_variable, o.item.confidence)
            for o in occ
        ]
        rec_exp = sum((o.item.amount for o in occ if o.item.type == "debit"), Decimal(0)).quantize(_CENT)
        rec_inc = sum((o.item.amount for o in occ if o.item.type == "credit"), Decimal(0)).quantize(_CENT)

        var_exp = var_inc = None
        exp_lo = exp_hi = net_lo = net_hi = None
        net = expense = income = None
        end_bal = end_lo = end_hi = None
        if variable_ok:
            k = steps_by_period[idx] - 1
            # Stub month: prorate the monthly forecast by days remaining (uniform spending assumed).
            factor = ((p.end - p.start).days + 1) / p.days_total if p.is_stub else 1.0
            e_pt, i_pt = fc_exp.point[k] * factor, fc_inc.point[k] * factor
            var_exp, var_inc = _d(e_pt), _d(i_pt)
            expense, income = rec_exp + var_exp, rec_inc + var_inc
            net = income - expense
            e_hw, i_hw = fc_exp.half_width[k], fc_inc.half_width[k]
            if e_hw is not None:
                exp_lo, exp_hi = _d(max(0.0, e_pt - e_hw * factor)), _d(e_pt + e_hw * factor)
            if e_hw is not None and i_hw is not None:
                net_hw = math.hypot(e_hw * factor, i_hw * factor)  # independent series assumed
                net_lo, net_hi = net - _d(net_hw), net + _d(net_hw)
                cum_var_sq += net_hw**2
            else:
                cum_ok = False
            if can_project_balance:
                running = running + net
                end_bal = running
                if cum_ok:
                    cum_hw = math.sqrt(cum_var_sq)  # independent across months assumed
                    end_lo, end_hi = end_bal - _d(cum_hw), end_bal + _d(cum_hw)
        out.append(PeriodForecast(
            p.start, p.end, p.is_stub, rec_exp, rec_inc, var_exp, var_inc, expense, income, net,
            exp_lo, exp_hi, net_lo, net_hi, end_bal, end_lo, end_hi, lines,
        ))

    # --- verdict on the first FULL month ---------------------------------------
    first_full = next(p for p in out if not p.is_stub)
    if not variable_ok:
        verdict, basis = "unknown", "too little history to forecast variable spending"
    elif balance.start_balance is None:
        verdict, basis = "unknown", "no account balance set; the forecast shows flows only"
    elif not balance.complete:
        verdict, basis = "unknown", "some accounts in this currency have no balance set: " + ", ".join(balance.accounts_without_balance)
    elif first_full.end_balance < 0:
        verdict, basis = "shortfall", "point_only" if first_full.end_balance_low is None else "interval"
    elif first_full.end_balance_low is None:
        verdict, basis = "covered", "point_only"
    else:
        verdict, basis = ("at_risk" if first_full.end_balance_low < 0 else "covered"), "interval"

    # --- warnings and assumptions ---------------------------------------------
    warnings.extend(clean.notes)
    # An all-zero variable series is the NORMAL state for the income side of a salaried
    # user (everything arrives as a recurring payment), so it is reported in the model
    # summary only, not as a warning on every forecast they ever request.
    if fc_exp.mode != "all_zero":
        warnings.extend(f"expenses: {n}" for n in fc_exp.notes)
    if fc_inc.mode != "all_zero":
        warnings.extend(f"income: {n}" for n in fc_inc.notes)
    warnings.extend(balance.notes)
    if variable_ok and balance.start_balance is not None and not balance.complete:
        warnings.append("projected balances are withheld: forecasting one account's flows against another's balance would be wrong")
    if (today - as_of).days > STALE_AFTER_DAYS:
        warnings.append(f"the last transaction is {(today - as_of).days} days old; upload newer statements for a current forecast")
    if any(o.assumed_pending for o in occurrences):
        warnings.append("some recurring payments were overdue as of the last transaction and are assumed still pending")
    if any(o.item.amount_variable for o in occurrences):
        warnings.append("variable-amount bills (utilities) use their recent typical amount with no uncertainty band")

    stub = next((p for p in periods if p.is_stub), None)
    assumptions = [
        "Variable flows are everything outside detected recurring series; each is forecast per month by its own backtested model.",
        f"Recurring payments ({len(items)} active) are projected at their recent typical amount on calendar-stepped dates.",
        f"Intervals are the {level:.0%} quantile of the chosen model's own past errors; series and months are combined "
        "assuming independent errors, so real coverage is probably lower than nominal.",
        "Own-account transfers and card-bill payments are counted as income and expense (known gap).",
        "Only period-end balances are projected: a bill early in a month can overdraw an account that ends it positive.",
        "Amounts are never converted between currencies.",
    ]
    if stub:
        left = (stub.end - stub.start).days + 1
        assumptions.append(f"The rest of the current month ({left} days) gets the monthly variable forecast prorated by days, assuming even spending.")

    if fc_exp.mode == "unavailable" or fc_inc.mode == "unavailable":
        status = "recurring_only"
    elif fc_exp.mode == "limited" or fc_inc.mode == "limited":
        status = "limited"
    else:
        status = "ok"

    return CurrencyForecast(
        currency=currency, status=status, as_of=as_of, horizon_months=horizon_months, periods=out,
        expense_model=_summary(fc_exp, clean), income_model=_summary(fc_inc, clean), balance=balance,
        verdict=verdict, verdict_basis=basis, verdict_period_end=first_full.end,
        assumptions=assumptions, warnings=warnings,
    )


# ----------------------------------------------------------------------------
# DB wrapper
# ----------------------------------------------------------------------------
def forecast_cashflow(
    db: Session,
    user_id: uuid.UUID,
    *,
    horizon_months: int = 3,
    account_id: uuid.UUID | None = None,
    as_of: date | None = None,
    interval_level: float = 0.8,
    today: date | None = None,
) -> list[CurrencyForecast]:
    """
    One forecast per currency the user has data in. `as_of` means "ignore
    anything after this date"; the forecast origin is the last transaction on or
    before it, per currency (a currency whose statements stopped earlier is
    forecast from where its data stops, not from a date it has no data for).
    """
    if not 1 <= horizon_months <= MAX_HORIZON_MONTHS:
        raise ValueError(f"horizon_months must be between 1 and {MAX_HORIZON_MONTHS}")
    if not 0.5 <= interval_level <= 0.95:
        raise ValueError("interval_level must be between 0.5 and 0.95")
    today = today or datetime.now(timezone.utc).date()

    rows = history.load_rows(db, Scope(user_id=user_id, date_to=as_of, account_id=account_id))
    if not rows:
        return []
    # ALL accounts, active or not: any account that has transactions in scope needs
    # a balance, otherwise its flows would be projected against someone else's.
    acct_stmt = select(Account).where(Account.user_id == user_id)
    if account_id is not None:
        acct_stmt = acct_stmt.where(Account.id == account_id)
    accounts = [
        AccountInfo(a.id, a.name, a.currency, a.opening_balance, a.balance_as_of)
        for a in db.execute(acct_stmt).scalars().all()
    ]

    out = []
    for currency in sorted({r.currency for r in rows}):
        rows_c = [r for r in rows if r.currency == currency]
        out.append(forecast_currency(
            currency, rows_c, [a for a in accounts if a.currency == currency],
            as_of=max(r.on for r in rows_c), horizon_months=horizon_months, level=interval_level, today=today,
        ))
    return out
