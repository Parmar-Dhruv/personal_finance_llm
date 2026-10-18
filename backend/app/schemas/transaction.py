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

    model_config = {"from_attributes": True}


class TransactionUpdate(BaseModel):
    # The only user-editable transaction field so far. Explicit null
    # un-categorizes; omitting the key is a no-op (checked via
    # model_fields_set in the endpoint, since both look like None here).
    category_id: uuid.UUID | None = None
