"""
ML-layer endpoints. Thin: authorize, delegate to app/ml/service.py.

POST /ml/run executes in the request thread (like POST /documents/{id}/normalize)
-- fine at single-user scale; after an upload the Celery chain runs the same
steps in the background.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.base import get_db
from app.db.models import RecurringSeries, Transaction, User
from app.ml import service
from app.schemas.ml import (
    DuplicateCandidateRead,
    MLStatusRead,
    RecurringSeriesRead,
    RunRequest,
)
from app.schemas.transaction import TransactionRead

router = APIRouter(prefix="/ml", tags=["ml"])


@router.get("/status", response_model=MLStatusRead)
def ml_status(current_user: User = Depends(get_current_user)):
    b = service.get_classifier()
    meta = b.meta or {}
    return MLStatusRead(
        ml_model_available=b.ml_available,
        reason_unavailable=b.reason,
        mode="rules+ml" if b.ml_available else "rules-only",
        trained_at=meta.get("trained_at"),
        training_data=meta.get("training_data"),
        ml_only_auto_apply_threshold=b.ml_auto_threshold,
        suggestion_min_confidence=service.SUGGEST_MIN_CONFIDENCE,
        eval_unseen_merchants=meta.get("eval_unseen_merchants"),
        llm_classifier_enabled=settings.llm_classifier_enabled,
    )


@router.post("/run")
def run_ml(
    payload: RunRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Run duplicates -> classification -> recurring -> anomalies for the current user."""
    payload = payload or RunRequest()
    result = service.enrich_user(db, current_user.id, force_reclassify=payload.force_reclassify)
    db.commit()
    return result


@router.get("/suggestions", response_model=list[TransactionRead])
def list_suggestions(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pending category suggestions, most confident first."""
    stmt = (
        select(Transaction)
        .where(Transaction.user_id == current_user.id, Transaction.suggested_category_id.is_not(None))
        .order_by(Transaction.suggested_category_confidence.desc(), Transaction.id)
        .limit(limit).offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


@router.get("/duplicates", response_model=list[DuplicateCandidateRead])
def list_duplicates(
    review: str = Query(default="pending", pattern="^(auto|pending|confirmed|dismissed)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Duplicate candidates by review state, each paired with the row it supposedly duplicates."""
    cand = aliased(Transaction)
    stmt = (
        select(Transaction, cand)
        .join(cand, cand.id == Transaction.duplicate_candidate_of_id)
        .where(Transaction.user_id == current_user.id, Transaction.duplicate_review == review)
        .order_by(Transaction.duplicate_score.desc(), Transaction.id)
        .limit(limit).offset(offset)
    )
    return [
        DuplicateCandidateRead(
            transaction=TransactionRead.model_validate(t), candidate=TransactionRead.model_validate(c),
            score=t.duplicate_score or 0.0, review=t.duplicate_review,
        )
        for t, c in db.execute(stmt).all()
    ]


@router.get("/recurring", response_model=list[RecurringSeriesRead])
def list_recurring(
    active_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(RecurringSeries).where(RecurringSeries.user_id == current_user.id)
    if active_only:
        stmt = stmt.where(RecurringSeries.is_active.is_(True))
    return list(db.execute(stmt.order_by(RecurringSeries.confidence.desc(), RecurringSeries.merchant)).scalars().all())


@router.get("/anomalies", response_model=list[TransactionRead])
def list_anomalies(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Flagged transactions, most extreme first. Unusual is not fraud."""
    stmt = (
        select(Transaction)
        .where(Transaction.user_id == current_user.id, Transaction.is_anomaly.is_(True))
        .order_by(Transaction.anomaly_score.desc(), Transaction.id)
        .limit(limit).offset(offset)
    )
    return list(db.execute(stmt).scalars().all())
