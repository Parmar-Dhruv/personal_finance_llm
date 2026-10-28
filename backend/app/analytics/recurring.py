"""
Recurring expense/income totals (spec §8, deferred from Phase 4 until Phase 5
could detect recurring streams). Deterministic arithmetic over the detector's
output; the *detection* is statistical (see app/ml/recurring.py), the totals
are not.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RecurringSeries, TransactionType

# Per-month multiplier for each cadence (52 weeks / 12 months, etc.).
_MONTHLY_FACTOR = {
    "weekly": Decimal(52) / 12,
    "biweekly": Decimal(26) / 12,
    "monthly": Decimal(1),
    "quarterly": Decimal(1) / 3,
    "yearly": Decimal(1) / 12,
}
_CENT = Decimal("0.01")


@dataclass
class RecurringTotals:
    currency: str
    expense_monthly_equivalent: Decimal
    income_monthly_equivalent: Decimal
    expense_series_count: int
    income_series_count: int
    series: list


def recurring_totals(db: Session, user_id: uuid.UUID, *, active_only: bool = True) -> list[RecurringTotals]:
    """
    Monthly-equivalent totals per currency (never combined across
    currencies, same rule as the rest of analytics). A variable-amount bill
    contributes its recent typical amount, so the figure is an estimate.
    """
    stmt = select(RecurringSeries).where(RecurringSeries.user_id == user_id)
    if active_only:
        stmt = stmt.where(RecurringSeries.is_active.is_(True))
    rows = db.execute(stmt.order_by(RecurringSeries.currency, RecurringSeries.typical_amount.desc())).scalars().all()

    by_ccy: dict[str, RecurringTotals] = {}
    for s in rows:
        t = by_ccy.setdefault(
            s.currency, RecurringTotals(s.currency, Decimal("0.00"), Decimal("0.00"), 0, 0, [])
        )
        monthly = (s.typical_amount * _MONTHLY_FACTOR[s.cadence]).quantize(_CENT, rounding=ROUND_HALF_UP)
        if s.transaction_type == TransactionType.debit:
            t.expense_monthly_equivalent += monthly
            t.expense_series_count += 1
        else:
            t.income_monthly_equivalent += monthly
            t.income_series_count += 1
        t.series.append(s)
    return list(by_ccy.values())
