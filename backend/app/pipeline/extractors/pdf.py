import io
import logging

import pdfplumber
import pypdfium2 as pdfium

from app.pipeline.extractors.common import ExtractedPage
from app.pipeline.extractors.ocr import LOW_OCR_CONFIDENCE_THRESHOLD, ocr_image

logger = logging.getLogger(__name__)

# A genuinely-native page carries far more than this even when it's
# mostly whitespace/numbers (e.g. a single-line statement footer still
# clears it) — below this, treat the page as image-only and OCR it.
NATIVE_TEXT_MIN_CHARS = 20

# Hard cap so one huge/adversarial upload can't tie up a Celery worker
# indefinitely. Revisit if real multi-hundred-page statements show up.
MAX_PDF_PAGES = 300

# Points-per-inch is 72; rendering at this DPI balances OCR accuracy
# against per-page render+OCR time.
OCR_DPI = 300


def extract_pdf(file_bytes: bytes) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []

    # pdfplumber raises on encrypted/corrupted PDFs — let that propagate
    # up to the task, which marks the document `failed` with the real
    # error rather than silently producing zero pages.
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        total_pages = len(pdf.pages)
        pages_to_process = pdf.pages[:MAX_PDF_PAGES]
        truncated = total_pages > MAX_PDF_PAGES

        # Opened lazily: most real bank/credit-card statements are
        # native-text, so paying pdfium's parse cost when no page ever
        # needs OCR would be wasted work.
        pdfium_doc: pdfium.PdfDocument | None = None

        try:
            for i, page in enumerate(pages_to_process, start=1):
                native_text = page.extract_text() or ""
                tables = page.extract_tables() or []

                if len(native_text.strip()) >= NATIVE_TEXT_MIN_CHARS:
                    warnings = ["truncated_document"] if truncated and i == len(pages_to_process) else []
                    pages.append(
                        ExtractedPage(
                            page_number=i,
                            method="native_text",
                            text=native_text,
                            tables=tables,
                            warnings=warnings,
                        )
                    )
                    continue

                # Native extraction came back empty/near-empty -> scanned
                # page. Rasterize with pypdfium2 and OCR with Tesseract.
                if pdfium_doc is None:
                    pdfium_doc = pdfium.PdfDocument(file_bytes)

                warnings = []
                try:
                    pdfium_page = pdfium_doc[i - 1]
                    bitmap = pdfium_page.render(scale=OCR_DPI / 72)
                    pil_image = bitmap.to_pil()
                    ocr_text, mean_confidence = ocr_image(pil_image)

                    if mean_confidence is not None and mean_confidence < LOW_OCR_CONFIDENCE_THRESHOLD:
                        warnings.append("low_ocr_confidence")
                    if not ocr_text.strip():
                        warnings.append("empty_page")
                    if truncated and i == len(pages_to_process):
                        warnings.append("truncated_document")

                    pages.append(
                        ExtractedPage(
                            page_number=i,
                            # pdfplumber's table detection sometimes still
                            # finds ruled tables even on an otherwise
                            # image-only page, so keep it rather than
                            # discard it.
                            method="ocr",
                            text=ocr_text,
                            tables=tables,
                            ocr_confidence=mean_confidence,
                            warnings=warnings,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 — per-page OCR failure shouldn't fail the whole document
                    logger.exception("OCR failed on page %d", i)
                    pages.append(
                        ExtractedPage(
                            page_number=i,
                            method="ocr",
                            text="",
                            warnings=["ocr_failed", str(exc)[:200]],
                        )
                    )
        finally:
            if pdfium_doc is not None:
                pdfium_doc.close()

    return pages
