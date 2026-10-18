import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func

from app.db.models import Transaction, TransactionType

ZERO = Decimal("0.00")
_PCT_QUANT = Decimal("0.01")


@dataclass(frozen=True)
class Scope:
    """What slice of one user's transactions an analytics call covers."""

    user_id: uuid.UUID
    date_from: date | None = None  # inclusive
    date_to: date | None = None  # inclusive
    account_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")


def _utc_midnight(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def scope_conditions(scope: Scope) -> list:
    """
    WHERE conditions shared by every analytics query. Half-open on the
    upper bound (`< date_to + 1 day`) so the whole of date_to is included
    no matter what time-of-day a row carries.
    """
    conds = [
        Transaction.user_id == scope.user_id,
        Transaction.duplicate_of_id.is_(None),
    ]
    if scope.account_id is not None:
        conds.append(Transaction.account_id == scope.account_id)
    if scope.date_from is not None:
        conds.append(Transaction.transaction_date >= _utc_midnight(scope.date_from))
    if scope.date_to is not None:
        conds.append(Transaction.transaction_date < _utc_midnight(scope.date_to + timedelta(days=1)))
    return conds


def pct(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """numerator/denominator as a percentage, 2dp; None when undefined (denominator 0)."""
    if denominator == 0:
        return None
    return (numerator / denominator * 100).quantize(_PCT_QUANT, rounding=ROUND_HALF_UP)


def month_start(d: date) -> date:
    return d.replace(day=1)


def next_month(d: date) -> date:
    """First day of the month after `d`'s month."""
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def month_end(d: date) -> date:
    """Last calendar day of `d`'s month."""
    return next_month(d) - timedelta(days=1)


_CENT = Decimal("0.01")


def money(value: Decimal | None) -> Decimal:
    """Normalize a SUM() result (None when no rows) to a 2dp Decimal."""
    return ZERO if value is None else Decimal(value).quantize(_CENT)


def sum_by_type(txn_type: TransactionType):
    return func.coalesce(func.sum(Transaction.amount).filter(Transaction.transaction_type == txn_type), 0)


def count_by_type(txn_type: TransactionType):
    return func.count().filter(Transaction.transaction_type == txn_type)
