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
