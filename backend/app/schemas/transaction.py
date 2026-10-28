import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.db.models import TransactionType


class TransactionRead(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    category_id: uuid.UUID | None
    source_document_id: uuid.UUID | None
    transaction_date: datetime
    description_raw: str
    merchant_normalized: str | None
    amount: Decimal
    currency: str
    transaction_type: TransactionType
    confidence_score: float | None
    is_anomaly: bool
    is_recurring: bool
    created_at: datetime
    # Phase 5 provenance. category_source says who set category_id: 'user'
    # (never touched by ML) or the machine path that auto-applied it.
    category_source: str | None = None
    category_confidence: float | None = None
    suggested_category_id: uuid.UUID | None = None
    suggested_category_confidence: float | None = None
    suggested_category_source: str | None = None
    # duplicate_of_id is what analytics honors; review says why/what a human decided.
    duplicate_of_id: uuid.UUID | None = None
    duplicate_candidate_of_id: uuid.UUID | None = None
    duplicate_score: float | None = None
    duplicate_review: str | None = None
    anomaly_score: float | None = None
    anomaly_detail: dict | None = None
    recurring_series_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class TransactionUpdate(BaseModel):
    # The only user-editable transaction field so far. Explicit null
    # un-categorizes; omitting the key is a no-op (checked via
    # model_fields_set in the endpoint, since both look like None here).
    category_id: uuid.UUID | None = None
