import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.db.models import TransactionType
from app.schemas.transaction import TransactionRead


class RunRequest(BaseModel):
    # Re-evaluate earlier machine decisions too (e.g. after retraining).
    # Never touches user-set categories or dismissed suggestions.
    force_reclassify: bool = False


class MLStatusRead(BaseModel):
    ml_model_available: bool
    reason_unavailable: str | None
    mode: str  # "rules+ml" | "rules-only"
    trained_at: str | None
    training_data: str | None
    ml_only_auto_apply_threshold: float | None
    suggestion_min_confidence: float
    eval_unseen_merchants: dict | None
    llm_classifier_enabled: bool


class DuplicateCandidateRead(BaseModel):
    transaction: TransactionRead
    candidate: TransactionRead
    score: float
    review: str


class RecurringSeriesRead(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    merchant: str
    currency: str
    transaction_type: TransactionType
    cadence: str
    interval_days: float
    typical_amount: Decimal
    amount_variable: bool
    occurrence_count: int
    first_date: datetime
    last_date: datetime
    next_expected_date: datetime | None
    confidence: float
    is_active: bool

    model_config = {"from_attributes": True}


class RecurringTotalRead(BaseModel):
    currency: str
    expense_monthly_equivalent: Decimal
    income_monthly_equivalent: Decimal
    expense_series_count: int
    income_series_count: int
    series: list[RecurringSeriesRead]
