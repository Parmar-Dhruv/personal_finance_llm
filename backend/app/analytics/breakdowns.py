"""Spending/income broken down by category, merchant and account."""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.common import ZERO, Scope, count_by_type, money, pct, scope_conditions, sum_by_type
from app.db.models import Account, Category, Transaction, TransactionType

UNCATEGORIZED = "Uncategorized"


@dataclass(frozen=True)
class BreakdownRow:
    # category_id / merchant is None for the "uncategorized" / "no merchant"
    # bucket. It's reported explicitly, never silently dropped, so the
    # rows always add up to `total`.
    key_id: uuid.UUID | None
    label: str
    total: Decimal
    transaction_count: int
    pct_of_total: Decimal | None


@dataclass(frozen=True)
class CurrencyBreakdown:
    currency: str
    transaction_type: TransactionType
    total: Decimal  # of ALL rows, before any `limit` is applied
    rows: list[BreakdownRow]
    other_total: Decimal  # sum of rows cut off by `limit` (0 when not truncated)
    other_count: int


def _assemble(
    raw: list[tuple[str, uuid.UUID | None, str, Decimal, int]],
    txn_type: TransactionType,
    limit: int | None,
) -> list[CurrencyBreakdown]:
    by_currency: dict[str, list[tuple[uuid.UUID | None, str, Decimal, int]]] = {}
    for currency, key_id, label, total, n in raw:
        by_currency.setdefault(currency, []).append((key_id, label, money(total), n))

    out = []
    for currency in sorted(by_currency):
        # Largest first; label as a tiebreaker so output is deterministic.
        items = sorted(by_currency[currency], key=lambda r: (-r[2], r[1]))
        grand_total = sum((r[2] for r in items), ZERO)
        shown = items if limit is None else items[:limit]
        cut = [] if limit is None else items[limit:]
        out.append(
            CurrencyBreakdown(
                currency=currency,
                transaction_type=txn_type,
                total=grand_total,
                rows=[BreakdownRow(k, l, t, n, pct(t, grand_total)) for k, l, t, n in shown],
                other_total=sum((r[2] for r in cut), ZERO),
                other_count=sum(r[3] for r in cut),
            )
        )
    return out


def by_category(
    db: Session, scope: Scope, txn_type: TransactionType = TransactionType.debit, limit: int | None = None
) -> list[CurrencyBreakdown]:
    """Totals per directly-assigned category (no parent roll-up)."""
    stmt = (
        select(
            Transaction.currency,
            Transaction.category_id,
            func.coalesce(Category.name, UNCATEGORIZED),
            func.sum(Transaction.amount),
            func.count(),
        )
        .outerjoin(Category, Category.id == Transaction.category_id)
        .where(*scope_conditions(scope), Transaction.transaction_type == txn_type)
        .group_by(Transaction.currency, Transaction.category_id, Category.name)
    )
    return _assemble([tuple(r) for r in db.execute(stmt).all()], txn_type, limit)


def by_merchant(
    db: Session, scope: Scope, txn_type: TransactionType = TransactionType.debit, limit: int | None = 10
) -> list[CurrencyBreakdown]:
    """Totals per canonical merchant (`merchant_normalized`); NULL merchants pooled."""
    stmt = (
        select(
            Transaction.currency,
            Transaction.merchant_normalized,
            func.sum(Transaction.amount),
            func.count(),
        )
        .where(*scope_conditions(scope), Transaction.transaction_type == txn_type)
        .group_by(Transaction.currency, Transaction.merchant_normalized)
    )
    raw = [(c, None, m if m is not None else "(unknown merchant)", total, n) for c, m, total, n in db.execute(stmt).all()]
    return _assemble(raw, txn_type, limit)


@dataclass(frozen=True)
class AccountSummary:
    account_id: uuid.UUID
    account_name: str
    currency: str
    income: Decimal
    expense: Decimal
    net: Decimal
    income_count: int
    expense_count: int


def by_account(db: Session, scope: Scope) -> list[AccountSummary]:
    """
    One row per (account, currency) with activity, plus a zero row for any
    of the user's accounts with none in the window, so an idle account
    shows up as idle rather than missing.
    """
    stmt = (
        select(
            Transaction.account_id,
            Transaction.currency,
            sum_by_type(TransactionType.credit),
            sum_by_type(TransactionType.debit),
            count_by_type(TransactionType.credit),
            count_by_type(TransactionType.debit),
        )
        .where(*scope_conditions(scope))
        .group_by(Transaction.account_id, Transaction.currency)
    )
    activity = {(a, c): (money(i), money(e), ic, ec) for a, c, i, e, ic, ec in db.execute(stmt).all()}

    accounts_stmt = select(Account).where(Account.user_id == scope.user_id)
    if scope.account_id is not None:
        accounts_stmt = accounts_stmt.where(Account.id == scope.account_id)
    accounts = db.execute(accounts_stmt.order_by(Account.created_at, Account.id)).scalars().all()

    rows: list[AccountSummary] = []
    for acct in accounts:
        keys = sorted(k for k in activity if k[0] == acct.id) or [(acct.id, acct.currency)]
        for key in keys:
            income, expense, ic, ec = activity.get(key, (ZERO, ZERO, 0, 0))
            rows.append(AccountSummary(acct.id, acct.name, key[1], income, expense, income - expense, ic, ec))
    return rows
