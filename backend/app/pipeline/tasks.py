import logging
import uuid
from datetime import datetime, timezone

from app.core.celery_app import celery_app
from app.db.base import SessionLocal
from app.db.models import Document, DocumentStatus

logger = logging.getLogger(__name__)


@celery_app.task(name="process_document", bind=True, max_retries=3)
def process_document(self, document_id: str) -> None:
    """
    Phase 1 stub: proves Celery can pick up a task, load the row by id,
    and transition its status end-to-end. No actual extraction happens
    here yet — that's Phase 2 (OCR/table extraction).
    """
    db = SessionLocal()
    try:
        document = db.get(Document, uuid.UUID(document_id))
        if document is None:
            logger.error("process_document: document %s not found", document_id)
            return

        document.status = DocumentStatus.processing
        db.commit()

        # --- Phase 2 will replace this block with real extraction ---
        document.status = DocumentStatus.processed
        document.processed_at = datetime.now(timezone.utc)
        db.commit()
        # ---------------------------------------------------------------

    except Exception as exc:
        db.rollback()
        document = db.get(Document, uuid.UUID(document_id))
        if document is not None:
            document.status = DocumentStatus.failed
            document.error_message = str(exc)[:2000]
            db.commit()
        raise
    finally:
        db.close()
