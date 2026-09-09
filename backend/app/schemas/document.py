import uuid
from datetime import datetime

from pydantic import BaseModel

from app.db.models import DocumentStatus


class DocumentRead(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID | None
    filename: str
    mime_type: str
    status: DocumentStatus
    error_message: str | None
    created_at: datetime
    processed_at: datetime | None

    model_config = {"from_attributes": True}


class DocumentDownloadURL(BaseModel):
    url: str
    expires_in_seconds: int
