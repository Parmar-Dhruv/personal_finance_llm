import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.models import Transaction, User
from app.schemas.transaction import TransactionRead

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=list[TransactionRead])
def list_transactions(
    account_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 100,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Transaction]:
    stmt = select(Transaction).where(Transaction.user_id == current_user.id)
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    if date_from is not None:
        stmt = stmt.where(Transaction.transaction_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Transaction.transaction_date <= date_to)
    stmt = stmt.order_by(Transaction.transaction_date.desc()).limit(min(limit, 500)).offset(offset)
    return list(db.execute(stmt).scalars().all())


@router.get("/{transaction_id}", response_model=TransactionRead)
def get_transaction(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Transaction:
    txn = db.get(Transaction, transaction_id)
    if txn is None or txn.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return txn
