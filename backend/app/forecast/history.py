"""
Loads a user's transactions and turns them into the clean monthly series the
statistical models need. The only module in the package that touches the DB.

Cleaning policy (each rule exists because the naive alternative biases a
"can I afford it" answer):

 * The month containing `as_of` is dropped unless `as_of` is its last day. A
   half-month of spending looks like a sudden saving.
 * The first month is dropped if the first transaction is after day
   LEADING_PARTIAL_AFTER_DAY, as long as MIN_USABLE months remain. The data
   cannot say whether a statement started on the 12th or the user simply
   spent nothing on the 1st-11th; the threshold is a heuristic, and when too
   little history remains the month is kept and the series says so.
 * A month with ZERO transactions inside the data span is a missing statement,
   not a month of zero spending. Zero-filling it (as Phase 4's monthly view
   does, harmlessly, for display) would teach a model that spending collapses.
   Only the most recent run of months with no such hole is used.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.common import Scope, month_end, month_start, next_month, scope_conditions
from app.db.models import Transaction

LEADING_PARTIAL_AFTER_DAY = 7
MIN_USABLE = 3


@dataclass(frozen=True)
class TxnRow:
    id: object
    on: date  # UTC calendar date (Phase 3 stores midnight-UTC calendar dates)
    account_id: object
    currency: str
    type: str  # "debit" | "credit"
    amount: Decimal
    merchant: str | None


def load_rows(db: Session, scope: Scope) -> list[TxnRow]:
    """One user's non-duplicate transactions in scope, oldest first. One query."""
    stmt = (
        select(
            Transaction.id,
            Transaction.transaction_date,
            Transaction.account_id,
            Transaction.currency,
            Transaction.transaction_type,
            Transaction.amount,
            Transaction.merchant_normalized,
        )
        .where(*scope_conditions(scope))
        .order_by(Transaction.transaction_date, Transaction.id)
    )
    return [
        TxnRow(r.id, r.transaction_date.astimezone(timezone.utc).date(), r.account_id, r.currency,
               r.transaction_type.value, Decimal(r.amount), r.merchant_normalized)
        for r in db.execute(stmt).all()
    ]


@dataclass
class CleanSeries:
    months: list[date] = field(default_factory=list)  # first day of each month
    expense: list[float] = field(default_factory=list)  # variable (non-recurring) debits
    income: list[float] = field(default_factory=list)  # variable (non-recurring) credits
    notes: list[str] = field(default_factory=list)


def _prev_month_start(d: date) -> date:
    return month_start(month_start(d) - timedelta(days=1))


def monthly_variable(rows: list[TxnRow], excluded_ids: set, as_of: date) -> CleanSeries:
    """
    `rows` are one currency's transactions on or before `as_of`. Rows whose id
    is in `excluded_ids` (members of trusted recurring series) are left out of
    the variable amounts, but still count toward "was there any statement
    data this month" -- a month containing only a rent payment is not missing.
    """
    out = CleanSeries()
    if not rows:
        return out

    count: dict[date, int] = defaultdict(int)
    expense: dict[date, Decimal] = defaultdict(Decimal)
    income: dict[date, Decimal] = defaultdict(Decimal)
    for r in rows:
        m = month_start(r.on)
        count[m] += 1
        if r.id in excluded_ids:
            continue
        (expense if r.type == "debit" else income)[m] += r.amount

    first_date = min(r.on for r in rows)
    first_month = month_start(first_date)
    last_month = month_start(as_of) if as_of >= month_end(as_of) else _prev_month_start(as_of)
    if last_month < first_month:
        out.notes.append("all data falls in a single partial month; no complete month to learn from")
        return out

    months: list[date] = []
    cursor = first_month
    while cursor <= last_month:
        months.append(cursor)
        cursor = next_month(cursor)

    if as_of < month_end(as_of):
        out.notes.append(f"the partial month {month_start(as_of):%Y-%m} is excluded from the history")

    if first_date.day > LEADING_PARTIAL_AFTER_DAY:
        if len(months) - 1 >= MIN_USABLE:
            out.notes.append(
                f"{first_month:%Y-%m} excluded: the first transaction is on day {first_date.day}, so it may be a partial month"
            )
            months = months[1:]
        else:
            out.notes.append(
                f"{first_month:%Y-%m} may be a partial month (first transaction on day {first_date.day}) "
                "but is kept because too little history would remain"
            )

    holes = [m for m in months if count.get(m, 0) == 0]
    if holes:
        newest_hole = holes[-1]
        out.notes.append(
            "months with no transactions at all are treated as missing statements, not zero spending: "
            + ", ".join(f"{m:%Y-%m}" for m in holes)
            + f"; only the history after {newest_hole:%Y-%m} is used"
        )
        months = [m for m in months if m > newest_hole]

    out.months = months
    out.expense = [float(expense.get(m, Decimal(0))) for m in months]
    out.income = [float(income.get(m, Decimal(0))) for m in months]
    return out
