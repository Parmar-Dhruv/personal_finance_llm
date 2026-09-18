import io

from PIL import Image

from app.pipeline.extractors.common import ExtractedPage
from app.pipeline.extractors.ocr import LOW_OCR_CONFIDENCE_THRESHOLD, ocr_image


def extract_image(file_bytes: bytes) -> list[ExtractedPage]:
    # Pillow raises on genuinely corrupt/unrecognized image bytes — that
    # propagates up and marks the document `failed`, same as a broken PDF.
    image = Image.open(io.BytesIO(file_bytes))
    image = image.convert("RGB")

    text, mean_confidence = ocr_image(image)

    warnings = []
    if mean_confidence is not None and mean_confidence < LOW_OCR_CONFIDENCE_THRESHOLD:
        warnings.append("low_ocr_confidence")
    if not text.strip():
        warnings.append("empty_page")

    return [
        ExtractedPage(
            page_number=1,
            method="ocr",
            text=text,
            ocr_confidence=mean_confidence,
            warnings=warnings,
        )
    ]
