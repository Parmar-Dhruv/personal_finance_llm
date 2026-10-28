import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_visible_category
from app.db.base import get_db
from app.db.models import Transaction, User
from app.schemas.transaction import TransactionRead, TransactionUpdate

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=list[TransactionRead])
def list_transactions(
    account_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    is_anomaly: bool | None = None,
    is_recurring: bool | None = None,
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
        # Half-open upper bound so the whole of date_to is included even for
        # rows that carry a time-of-day (same convention as app/analytics).
        stmt = stmt.where(
            Transaction.transaction_date
            < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        )
    if is_anomaly is not None:
        stmt = stmt.where(Transaction.is_anomaly.is_(is_anomaly))
    if is_recurring is not None:
        stmt = stmt.where(Transaction.is_recurring.is_(is_recurring))
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


@router.patch("/{transaction_id}", response_model=TransactionRead)
def update_transaction(
    transaction_id: uuid.UUID,
    payload: TransactionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Transaction:
    """
    Assign (or, with category_id: null, clear) a transaction's category.

    A human assignment is final: category_source becomes 'user' and no ML job
    will ever overwrite it. Explicitly clearing counts as "stop guessing for
    this one" (suggestion_dismissed), otherwise the next classifier run would
    just put a category back.
    """
    txn = _owned(db, current_user, transaction_id)
    if "category_id" in payload.model_fields_set:
        if payload.category_id is not None:
            get_visible_category(db, current_user, payload.category_id)
            txn.category_source, txn.category_confidence = "user", None
        else:
            txn.category_source = txn.category_confidence = None
            txn.suggestion_dismissed = True
        txn.category_id = payload.category_id
        txn.suggested_category_id = txn.suggested_category_confidence = txn.suggested_category_source = None
        db.commit()
        db.refresh(txn)
    return txn


def _owned(db: Session, user: User, transaction_id: uuid.UUID) -> Transaction:
    txn = db.get(Transaction, transaction_id)
    if txn is None or txn.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    return txn


@router.post("/{transaction_id}/suggestion/accept", response_model=TransactionRead)
def accept_suggestion(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Transaction:
    """Turn a pending category suggestion into the (user-confirmed) category."""
    txn = _owned(db, current_user, transaction_id)
    if txn.suggested_category_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No pending suggestion")
    txn.category_id, txn.category_source, txn.category_confidence = txn.suggested_category_id, "user", None
    txn.suggested_category_id = txn.suggested_category_confidence = txn.suggested_category_source = None
    db.commit()
    db.refresh(txn)
    return txn


@router.post("/{transaction_id}/suggestion/reject", response_model=TransactionRead)
def reject_suggestion(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Transaction:
    """Discard a suggestion and stop the classifier from re-suggesting for this row."""
    txn = _owned(db, current_user, transaction_id)
    if txn.suggested_category_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No pending suggestion")
    txn.suggested_category_id = txn.suggested_category_confidence = txn.suggested_category_source = None
    txn.suggestion_dismissed = True
    db.commit()
    db.refresh(txn)
    return txn


@router.post("/{transaction_id}/suggestion/undismiss", response_model=TransactionRead)
def undismiss_suggestion(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Transaction:
    """
    Undo an explicit rejection/clear so the classifier may suggest again.

    Only the dismissal flag is cleared. A user-assigned category is still
    final, and any already-applied machine category is left untouched.
    """
    txn = _owned(db, current_user, transaction_id)
    if not txn.suggestion_dismissed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Suggestion is not dismissed")
    txn.suggestion_dismissed = False
    db.commit()
    db.refresh(txn)
    return txn


@router.post("/{transaction_id}/duplicate/confirm", response_model=TransactionRead)
def confirm_duplicate(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Transaction:
    """Human confirms the detector's candidate: this row is a duplicate (analytics will exclude it)."""
    txn = _owned(db, current_user, transaction_id)
    if txn.duplicate_candidate_of_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No duplicate candidate for this transaction")
    target = db.get(Transaction, txn.duplicate_candidate_of_id)
    if target is None or target.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate candidate no longer exists")
    # Point at the root original, never at another duplicate (no chains).
    if target.duplicate_of_id is not None:
        target = db.get(Transaction, target.duplicate_of_id) or target
    if target.id == txn.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Candidate resolves to the transaction itself")
    txn.duplicate_of_id, txn.duplicate_review = target.id, "confirmed"
    db.commit()
    db.refresh(txn)
    return txn


@router.post("/{transaction_id}/duplicate/dismiss", response_model=TransactionRead)
def dismiss_duplicate(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Transaction:
    """Human says "not a duplicate": un-flags the row and stops the detector re-judging it."""
    txn = _owned(db, current_user, transaction_id)
    if txn.duplicate_review not in ("auto", "pending", "confirmed"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Transaction is not flagged as a duplicate candidate")
    txn.duplicate_of_id, txn.duplicate_review = None, "dismissed"
    db.commit()
    db.refresh(txn)
    return txn
