import logging
import uuid
from datetime import datetime, timezone

from app.core.celery_app import celery_app
from app.core.storage import download_file
from app.db.base import SessionLocal
from app.db.models import Document, DocumentPage, DocumentStatus, ExtractionMethod
from app.pipeline.extractors.image import extract_image
from app.pipeline.extractors.pdf import extract_pdf
from app.pipeline.extractors.spreadsheet import extract_csv, extract_xlsx

logger = logging.getLogger(__name__)

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Dispatch table keyed on the same mime types Phase 1 already validates
# against at upload time (settings.allowed_upload_mime_types) -- if that
# list ever grows, this table needs a matching entry or extraction will
# correctly fail loudly rather than silently no-op.
_EXTRACTORS = {
    "application/pdf": extract_pdf,
    "text/csv": extract_csv,
    _XLSX_MIME: extract_xlsx,
    "image/png": extract_image,
    "image/jpeg": extract_image,
}


@celery_app.task(name="process_document", bind=True, max_retries=3)
def process_document(self, document_id: str) -> None:
    """
    Phase 2: downloads the original file, runs the format-appropriate
    extractor, and persists one DocumentPage row per page/sheet with
    provenance (document_id, page_number) and confidence where
    applicable. Phase 3 (normalization) reads these rows to populate
    actual Transaction records -- this task deliberately does not attempt
    to interpret the extracted content.
    """
    db = SessionLocal()
    try:
        document = db.get(Document, uuid.UUID(document_id))
        if document is None:
            logger.error("process_document: document %s not found", document_id)
            return

        document.status = DocumentStatus.processing
        db.commit()

        extractor = _EXTRACTORS.get(document.mime_type)
        if extractor is None:
            raise ValueError(f"No extractor registered for mime type: {document.mime_type}")

        file_bytes = download_file(document.storage_path)
        extracted_pages = extractor(file_bytes)

        if not extracted_pages:
            raise ValueError("Extractor returned no pages")

        for page in extracted_pages:
            db.add(
                DocumentPage(
                    document_id=document.id,
                    page_number=page.page_number,
                    extraction_method=ExtractionMethod(page.method),
                    raw_text=page.text,
                    char_count=len(page.text),
                    ocr_confidence=page.ocr_confidence,
                    tables=page.tables or None,
                    warnings=page.warnings or None,
                )
            )

        document.page_count = len(extracted_pages)
        document.status = DocumentStatus.processed
        document.processed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:
        db.rollback()
        document = db.get(Document, uuid.UUID(document_id))
        if document is not None:
            document.status = DocumentStatus.failed
            # str(exc) can be genuinely empty for a real exception (e.g.
            # pdfplumber's PdfminerException wrapping PDFPasswordIncorrect
            # on an encrypted PDF has no message) -- repr() always carries
            # the exception type, so error_message is never silently "".
            document.error_message = (str(exc) or repr(exc))[:2000]
            db.commit()
        raise
    finally:
        db.close()
