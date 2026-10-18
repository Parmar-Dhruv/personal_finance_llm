"""Budget utilization math (the CRUD for budgets lives in api/budgets.py)."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.common import ZERO, Scope, money, month_end, month_start, pct, scope_conditions
from app.db.models import Budget, Category, Transaction, TransactionType


class BudgetStatus(str, Enum):
    ok = "ok"  # below the alert threshold
    near = "near"  # at/over the alert threshold, still within the limit (spent == limit counts here)
    over = "over"  # spent strictly more than the limit


@dataclass(frozen=True)
class BudgetUtilization:
    budget_id: uuid.UUID
    category_id: uuid.UUID | None
    category_name: str | None  # None = overall budget
    currency: str
    limit: Decimal
    spent: Decimal
    remaining: Decimal  # negative once over budget
    pct_used: Decimal  # spent / limit * 100, 2dp (limit is CHECKed > 0 so never undefined)
    alert_threshold_pct: Decimal
    status: BudgetStatus
    transaction_count: int


def category_subtree_ids(db: Session, root_id: uuid.UUID) -> list[uuid.UUID]:
    """
    `root_id` plus every descendant category, via recursive CTE. UNION (not
    UNION ALL) de-duplicates rows, so a cycle in the hierarchy couldn't
    loop forever even though the API can't currently create one.
    """
    tree = select(Category.id).where(Category.id == root_id).cte("tree", recursive=True)
    tree = tree.union(select(Category.id).join(tree, Category.parent_id == tree.c.id))
    return list(db.execute(select(tree.c.id)).scalars().all())


def _status(spent: Decimal, limit: Decimal, threshold: Decimal) -> BudgetStatus:
    # Compared on exact values (spent/limit >= threshold/100, cross-multiplied
    # to stay in Decimal with no division), NOT on the rounded pct_used shown
    # to the user: 79.996% rounds to "80.00" but is still below an 80% threshold.
    if spent > limit:
        return BudgetStatus.over
    if spent * 100 >= threshold * limit:
        return BudgetStatus.near
    return BudgetStatus.ok


def utilization(db: Session, user_id: uuid.UUID, month: date) -> list[BudgetUtilization]:
    """
    Spent-vs-limit for every ACTIVE budget of the user over one calendar
    month (`month` may be any date inside it).

    "Spent" = debits only, in the budget's currency, within the month,
    excluding flagged duplicates. Credits/refunds are NOT netted off (see
    Known Gaps). A category budget counts its whole category subtree; an
    overall budget counts everything including uncategorized spend, so an
    overall budget is NOT the sum of the category budgets next to it.
    """
    window = Scope(user_id=user_id, date_from=month_start(month), date_to=month_end(month))
    budgets = db.execute(
        select(Budget, Category.name)
        .outerjoin(Category, Category.id == Budget.category_id)
        .where(Budget.user_id == user_id, Budget.is_active.is_(True))
        .order_by(Category.name.nulls_first(), Budget.currency)
    ).all()

    out = []
    for budget, category_name in budgets:
        stmt = select(func.sum(Transaction.amount), func.count()).where(
            *scope_conditions(window),
            Transaction.transaction_type == TransactionType.debit,
            Transaction.currency == budget.currency,
        )
        if budget.category_id is not None:
            stmt = stmt.where(Transaction.category_id.in_(category_subtree_ids(db, budget.category_id)))
        spent_raw, n = db.execute(stmt).one()

        spent = money(spent_raw)
        limit = money(budget.amount)
        used = pct(spent, limit) or ZERO
        out.append(
            BudgetUtilization(
                budget_id=budget.id,
                category_id=budget.category_id,
                category_name=category_name,
                currency=budget.currency,
                limit=limit,
                spent=spent,
                remaining=limit - spent,
                pct_used=used,
                alert_threshold_pct=Decimal(budget.alert_threshold_pct).quantize(Decimal("0.01")),
                status=_status(spent, limit, Decimal(budget.alert_threshold_pct)),
                transaction_count=n,
            )
        )
    return out
