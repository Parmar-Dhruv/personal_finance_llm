"""
Read-only analytics endpoints. Thin: parse + authorize, then delegate to
app/analytics/ (which has no HTTP knowledge so Phase 8's agent can reuse it).
"""

import re
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.analytics import breakdowns, budgets, cashflow, recurring
from app.analytics.common import Scope, month_end, month_start
from app.api.deps import get_current_user, get_owned_account
from app.db.base import get_db
from app.db.models import TransactionType, User
from app.schemas.ml import RecurringTotalRead
from app.schemas.analytics import (
    AccountSummaryRead,
    BreakdownRead,
    MonthlyRead,
    SummaryRead,
    UtilizationResponse,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


def get_scope(
    date_from: date | None = Query(default=None, description="Inclusive start date"),
    date_to: date | None = Query(default=None, description="Inclusive end date"),
    account_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Scope:
    if account_id is not None:
        get_owned_account(db, current_user, account_id)  # 404 if not theirs
    try:
        return Scope(user_id=current_user.id, date_from=date_from, date_to=date_to, account_id=account_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get("/summary", response_model=list[SummaryRead])
def get_summary(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Income, expense and net per currency. Currencies are never combined."""
    return cashflow.summary(db, scope)


@router.get("/monthly", response_model=list[MonthlyRead])
def get_monthly(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Month-by-month series per currency, gaps zero-filled, with month-over-month change."""
    return cashflow.monthly(db, scope)


@router.get("/categories", response_model=list[BreakdownRead])
def get_category_breakdown(
    type: TransactionType = TransactionType.debit,
    limit: int | None = Query(default=None, ge=1, le=200),
    scope: Scope = Depends(get_scope),
    db: Session = Depends(get_db),
):
    return breakdowns.by_category(db, scope, type, limit)


@router.get("/merchants", response_model=list[BreakdownRead])
def get_merchant_breakdown(
    type: TransactionType = TransactionType.debit,
    limit: int = Query(default=10, ge=1, le=200),
    scope: Scope = Depends(get_scope),
    db: Session = Depends(get_db),
):
    return breakdowns.by_merchant(db, scope, type, limit)


@router.get("/accounts", response_model=list[AccountSummaryRead])
def get_account_summaries(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return breakdowns.by_account(db, scope)


_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@router.get("/budget-utilization", response_model=UtilizationResponse)
def get_budget_utilization(
    month: str | None = Query(default=None, description="YYYY-MM; defaults to the current UTC month"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if month is None:
        period = month_start(datetime.now(timezone.utc).date())
    elif _MONTH_RE.match(month):
        period = date(int(month[:4]), int(month[5:]), 1)
    else:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="month must be YYYY-MM")
    return UtilizationResponse(
        period_start=period,
        period_end=month_end(period),
        budgets=budgets.utilization(db, current_user.id, period),
    )


@router.get("/recurring", response_model=list[RecurringTotalRead])
def get_recurring_totals(
    active_only: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Monthly-equivalent recurring expense/income per currency, from detected
    recurring series (run POST /ml/run first). Not date-scoped: recurring
    streams are a property of the whole history.
    """
    return recurring.recurring_totals(db, current_user.id, active_only=active_only)
