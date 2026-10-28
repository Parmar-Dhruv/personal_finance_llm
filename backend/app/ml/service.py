"""
DB glue for the ML layer: loads a user's rows, calls the pure algorithms,
writes results back. Nothing here commits -- the caller (Celery task or API
handler) owns the transaction, same convention as normalize_document.

Every step is idempotent and user-scoped (never touches another user's rows).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Category, Document, RecurringSeries, Transaction, TransactionType
from app.ml import anomalies as anom
from app.ml import duplicates as dup
from app.ml import recurring as rec
from app.ml.classifier import HybridClassifier, ModelUnavailable, load_model

logger = logging.getLogger(__name__)

# Predictions whose label came from a rule (alone or confirmed by the model)
# are auto-applied. Measured precision on unseen synthetic merchants: ~0.99
# (see docs/ml_eval) -- expect lower on real statements.
AUTO_SOURCES = ("rule", "hybrid")
SUGGEST_MIN_CONFIDENCE = 0.5
_BATCH = 1000


def _lock_user(db: Session, user_id: uuid.UUID) -> None:
    """
    Serialize ML jobs per user for the rest of this transaction. Without it
    two concurrent runs (API call + Celery chain, say) both delete a user's
    recurring series and both re-insert -> duplicate series. Advisory lock,
    released automatically at commit/rollback; re-entrant within one session.
    """
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(str(user_id), 0))))


def model_dir() -> Path:
    return Path(settings.ml_model_dir) if settings.ml_model_dir else Path(__file__).resolve().parents[2] / "models"


@dataclass
class ClassifierBundle:
    classifier: HybridClassifier
    meta: dict | None
    ml_available: bool
    reason: str | None = None  # why ML is unavailable, if it is
    ml_auto_threshold: float | None = None


_cache: dict[tuple, ClassifierBundle] = {}


def get_classifier(directory: Path | None = None) -> ClassifierBundle:
    """
    Hybrid classifier backed by the saved model; if there isn't a usable one,
    degrade to rules-only and say why (never crash the pipeline over it).
    Cached per (directory, model-file mtime) so a retrain is picked up
    without a restart.
    """
    directory = directory or model_dir()
    model_file = directory / "classifier.joblib"
    stamp = (str(directory), model_file.stat().st_mtime_ns if model_file.exists() else None)
    if stamp in _cache:
        return _cache[stamp]
    try:
        ml, meta = load_model(directory)
        bundle = ClassifierBundle(
            HybridClassifier(ml, min_confidence=SUGGEST_MIN_CONFIDENCE), meta, True,
            ml_auto_threshold=meta.get("ml_only_auto_apply_threshold"),
        )
    except ModelUnavailable as exc:
        logger.warning("ML model unavailable, using rules only: %s", exc)
        bundle = ClassifierBundle(HybridClassifier(None, min_confidence=SUGGEST_MIN_CONFIDENCE), None, False, str(exc))
    _cache.clear()
    _cache[stamp] = bundle
    return bundle


# ----------------------------------------------------------------------------
# Classification
# ----------------------------------------------------------------------------
@dataclass
class ClassifyStats:
    examined: int = 0
    auto_applied: int = 0
    suggested: int = 0
    no_prediction: int = 0
    skipped_user_set: int = 0
    cleared: int = 0
    by_source: dict = field(default_factory=dict)


def _system_category_ids(db: Session) -> dict[str, uuid.UUID]:
    rows = db.execute(
        select(Category.name, Category.id).where(Category.user_id.is_(None), Category.parent_id.is_(None))
    ).all()
    return {name: cid for name, cid in rows}


def classify_user(
    db: Session,
    user_id: uuid.UUID,
    *,
    force: bool = False,
    bundle: ClassifierBundle | None = None,
    document_id: uuid.UUID | None = None,
) -> ClassifyStats:
    """
    Never overwrites a user-set category and never revisits a dismissed
    suggestion. By default only rows with no category and no pending
    suggestion are examined; `force` re-evaluates earlier machine
    decisions too (e.g. after retraining) and clears ones the model no
    longer stands behind.
    """
    _lock_user(db, user_id)
    bundle = bundle or get_classifier()
    cat_ids = _system_category_ids(db)
    stats = ClassifyStats()

    stats.skipped_user_set = db.scalar(
        select(func.count()).select_from(Transaction).where(
            Transaction.user_id == user_id,
            (Transaction.category_source == "user")
            | (Transaction.category_id.is_not(None) & Transaction.category_source.is_(None)),
        )
    ) or 0

    stmt = select(Transaction).where(
        Transaction.user_id == user_id,
        Transaction.duplicate_of_id.is_(None),
        Transaction.suggestion_dismissed.is_(False),
        (Transaction.category_source.is_(None)) | (Transaction.category_source != "user"),
        # A category with no recorded source predates provenance tracking
        # (or was written by a path that didn't set one): treat as human-set.
        ~(Transaction.category_id.is_not(None) & Transaction.category_source.is_(None)),
    )
    if document_id is not None:
        stmt = stmt.where(Transaction.source_document_id == document_id)
    if not force:
        stmt = stmt.where(Transaction.category_id.is_(None), Transaction.suggested_category_id.is_(None))
    stmt = stmt.order_by(Transaction.transaction_date, Transaction.id)

    rows = list(db.execute(stmt).scalars().all())
    for start in range(0, len(rows), _BATCH):
        chunk = rows[start : start + _BATCH]
        preds = bundle.classifier.predict(
            [(t.description_raw, t.merchant_normalized, t.transaction_type.value, float(t.amount)) for t in chunk]
        )
        for t, pred in zip(chunk, preds):
            stats.examined += 1
            had_machine_state = t.category_source is not None or t.suggested_category_id is not None
            cat_id = cat_ids.get(pred.label) if pred else None
            if pred is None or cat_id is None:
                stats.no_prediction += 1
                if had_machine_state:  # force run: model no longer backs the old call
                    t.category_id = t.category_source = t.category_confidence = None
                    t.suggested_category_id = t.suggested_category_confidence = t.suggested_category_source = None
                    stats.cleared += 1
                continue
            stats.by_source[pred.source] = stats.by_source.get(pred.source, 0) + 1
            auto = pred.source in AUTO_SOURCES or (
                pred.source == "ml" and bundle.ml_auto_threshold is not None and pred.confidence >= bundle.ml_auto_threshold
            )
            if auto:
                t.category_id, t.category_source, t.category_confidence = cat_id, pred.source, pred.confidence
                t.suggested_category_id = t.suggested_category_confidence = t.suggested_category_source = None
                stats.auto_applied += 1
            else:
                t.category_id = t.category_source = t.category_confidence = None
                t.suggested_category_id = cat_id
                t.suggested_category_confidence = pred.confidence
                t.suggested_category_source = pred.source
                stats.suggested += 1
    db.flush()
    return stats


# ----------------------------------------------------------------------------
# Duplicates
# ----------------------------------------------------------------------------
@dataclass
class DuplicateStats:
    auto_applied: int = 0
    pending: int = 0
    reset: int = 0


def detect_duplicates_user(db: Session, user_id: uuid.UUID) -> DuplicateStats:
    _lock_user(db, user_id)
    stats = DuplicateStats()
    # Forget this detector's previous opinions; keep every human decision.
    res = db.execute(
        update(Transaction)
        .where(Transaction.user_id == user_id, Transaction.duplicate_review.in_(("auto", "pending")))
        .values(duplicate_of_id=None, duplicate_candidate_of_id=None, duplicate_score=None, duplicate_review=None)
    )
    stats.reset = res.rowcount or 0

    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    doc_ts = {
        did: ts for did, ts in db.execute(
            select(Document.id, Document.created_at).where(Document.user_id == user_id)
        ).all()
    }
    rows = db.execute(
        select(
            Transaction.id, Transaction.account_id, Transaction.currency, Transaction.transaction_type,
            Transaction.amount, Transaction.transaction_date, Transaction.description_raw,
            Transaction.source_document_id, Transaction.duplicate_of_id, Transaction.duplicate_review,
        ).where(Transaction.user_id == user_id)
    ).all()

    items, decided = [], set()
    for r in rows:
        if r.duplicate_of_id is not None:  # a human-confirmed duplicate is not an "original"
            decided.add(r.id)
            continue
        if r.duplicate_review in ("confirmed", "dismissed"):
            decided.add(r.id)
        items.append(
            dup.DTxn(
                id=r.id, account=r.account_id, currency=r.currency, type=r.transaction_type.value,
                amount=r.amount, date=r.transaction_date, description=r.description_raw,
                document=r.source_document_id,
                order=(doc_ts.get(r.source_document_id, epoch), r.transaction_date, str(r.id)),
            )
        )

    results = dup.detect_duplicates(items, skip_later=frozenset(decided))
    for res_ in results:
        values = dict(duplicate_candidate_of_id=res_.candidate_id, duplicate_score=res_.score, duplicate_review=res_.status)
        if res_.status == "auto":
            values["duplicate_of_id"] = res_.candidate_id
            stats.auto_applied += 1
        else:
            stats.pending += 1
        db.execute(update(Transaction).where(Transaction.id == res_.txn_id).values(**values))
    db.flush()
    return stats


# ----------------------------------------------------------------------------
# Recurring
# ----------------------------------------------------------------------------
@dataclass
class RecurringStats:
    series: int = 0
    active: int = 0
    transactions_marked: int = 0


def detect_recurring_user(db: Session, user_id: uuid.UUID) -> RecurringStats:
    _lock_user(db, user_id)
    stats = RecurringStats()
    db.execute(delete(RecurringSeries).where(RecurringSeries.user_id == user_id))
    db.execute(
        update(Transaction)
        .where(Transaction.user_id == user_id, (Transaction.is_recurring.is_(True)) | (Transaction.recurring_series_id.is_not(None)))
        .values(is_recurring=False, recurring_series_id=None)
    )
    rows = db.execute(
        select(
            Transaction.id, Transaction.transaction_date, Transaction.merchant_normalized, Transaction.amount,
            Transaction.transaction_type, Transaction.account_id, Transaction.currency,
        ).where(Transaction.user_id == user_id, Transaction.duplicate_of_id.is_(None))
    ).all()
    txns = [rec.RTxn(r.id, r.transaction_date, r.merchant_normalized, r.amount, r.transaction_type.value, r.account_id, r.currency) for r in rows]
    for s in rec.detect_recurring(txns):
        row = RecurringSeries(
            user_id=user_id, account_id=s.account, merchant=s.merchant, currency=s.currency,
            transaction_type=TransactionType(s.type), cadence=s.cadence, interval_days=s.interval_days,
            typical_amount=s.typical_amount, amount_variable=s.amount_variable, occurrence_count=s.occurrence_count,
            first_date=s.first_date, last_date=s.last_date, next_expected_date=s.next_expected_date,
            confidence=s.confidence, is_active=s.is_active,
        )
        db.add(row)
        db.flush()
        db.execute(
            update(Transaction).where(Transaction.id.in_(s.member_ids)).values(is_recurring=True, recurring_series_id=row.id)
        )
        stats.series += 1
        stats.active += s.is_active
        stats.transactions_marked += len(s.member_ids)
    db.flush()
    return stats


# ----------------------------------------------------------------------------
# Anomalies
# ----------------------------------------------------------------------------
@dataclass
class AnomalyStats:
    scored: int = 0
    flagged: int = 0
    no_baseline: int = 0


def detect_anomalies_user(db: Session, user_id: uuid.UUID) -> AnomalyStats:
    _lock_user(db, user_id)
    stats = AnomalyStats()
    # Duplicate-flagged rows are neither scored nor allowed to shape baselines.
    db.execute(
        update(Transaction)
        .where(Transaction.user_id == user_id, Transaction.duplicate_of_id.is_not(None))
        .values(is_anomaly=False, anomaly_score=None, anomaly_detail=None)
    )
    rows = db.execute(
        select(
            Transaction.id, Transaction.currency, Transaction.transaction_type, Transaction.amount,
            Transaction.merchant_normalized, Transaction.category_id,
        ).where(Transaction.user_id == user_id, Transaction.duplicate_of_id.is_(None))
    ).all()
    results = anom.score_anomalies(
        [anom.ATxn(r.id, r.currency, r.transaction_type.value, Decimal(r.amount), r.merchant_normalized, r.category_id) for r in rows]
    )
    mappings = []
    for r in results:
        stats.scored += r.score is not None
        stats.no_baseline += r.score is None
        stats.flagged += r.flagged
        mappings.append({
            "id": r.txn_id, "is_anomaly": r.flagged, "anomaly_score": r.score,
            "anomaly_detail": None if r.score is None else {"level": r.level, "n": r.n, "baseline_median": r.median, "mad_log": r.mad},
        })
    if mappings:
        db.execute(update(Transaction), mappings)  # bulk UPDATE by primary key
    db.flush()
    return stats


# ----------------------------------------------------------------------------
def enrich_user(db: Session, user_id: uuid.UUID, *, force_reclassify: bool = False, bundle: ClassifierBundle | None = None) -> dict:
    """All four steps in dependency order: duplicates first (they remove rows
    from everything else), then categories (anomaly baselines use them), then
    recurring, then anomalies."""
    return {
        "duplicates": detect_duplicates_user(db, user_id).__dict__,
        "classification": classify_user(db, user_id, force=force_reclassify, bundle=bundle).__dict__,
        "recurring": detect_recurring_user(db, user_id).__dict__,
        "anomalies": detect_anomalies_user(db, user_id).__dict__,
    }
