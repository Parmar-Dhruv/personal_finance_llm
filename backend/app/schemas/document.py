import uuid
from datetime import datetime

from pydantic import BaseModel

from app.db.models import DocumentStatus, ExtractionMethod, NormalizationStatus


class DocumentRead(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID | None
    filename: str
    mime_type: str
    status: DocumentStatus
    error_message: str | None
    page_count: int | None
    created_at: datetime
    processed_at: datetime | None
    normalization_status: NormalizationStatus
    normalization_error: str | None
    transaction_count: int | None
    normalized_at: datetime | None

    model_config = {"from_attributes": True}


class DocumentAccountUpdate(BaseModel):
    account_id: uuid.UUID


class DocumentDownloadURL(BaseModel):
    url: str
    expires_in_seconds: int


class DocumentPageRead(BaseModel):
    id: uuid.UUID
    page_number: int
    extraction_method: ExtractionMethod
    raw_text: str | None
    char_count: int
    ocr_confidence: float | None
    tables: list | None
    warnings: list[str] | None

    model_config = {"from_attributes": True}
