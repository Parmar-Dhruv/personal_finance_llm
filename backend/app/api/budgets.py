"""Budget CRUD. Utilization math lives in app/analytics/budgets.py and is served by /analytics/budget-utilization."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_visible_category
from app.db.base import get_db
from app.db.models import Budget, User
from app.schemas.budget import BudgetCreate, BudgetRead, BudgetUpdate

router = APIRouter(prefix="/budgets", tags=["budgets"])

_DUPLICATE = "A budget for that category and currency already exists"


def _get_owned_budget(db: Session, user: User, budget_id: uuid.UUID) -> Budget:
    budget = db.get(Budget, budget_id)
    if budget is None or budget.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
    return budget


@router.post("", response_model=BudgetRead, status_code=status.HTTP_201_CREATED)
def create_budget(
    payload: BudgetCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Budget:
    if payload.category_id is not None:
        get_visible_category(db, current_user, payload.category_id)

    budget = Budget(
        user_id=current_user.id,
        category_id=payload.category_id,
        currency=payload.currency.upper(),
        amount=payload.amount,
        alert_threshold_pct=payload.alert_threshold_pct,
    )
    db.add(budget)
    try:
        db.commit()
    except IntegrityError:
        # uq_budget_user_category_currency (NULLS NOT DISTINCT, so this also
        # covers "second overall budget in the same currency").
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_DUPLICATE)
    db.refresh(budget)
    return budget


@router.get("", response_model=list[BudgetRead])
def list_budgets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Budget]:
    stmt = select(Budget).where(Budget.user_id == current_user.id).order_by(Budget.created_at, Budget.id)
    return list(db.execute(stmt).scalars().all())


@router.patch("/{budget_id}", response_model=BudgetRead)
def update_budget(
    budget_id: uuid.UUID,
    payload: BudgetUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Budget:
    budget = _get_owned_budget(db, current_user, budget_id)
    changes = payload.model_dump(exclude_unset=True)
    if any(v is None for v in changes.values()):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Fields cannot be null")
    for field, value in changes.items():
        setattr(budget, field, value)
    db.commit()
    db.refresh(budget)
    return budget


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(
    budget_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    budget = _get_owned_budget(db, current_user, budget_id)
    db.delete(budget)
    db.commit()
