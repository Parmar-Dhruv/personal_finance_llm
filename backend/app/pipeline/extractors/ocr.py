import pytesseract
from PIL import Image

# Below this mean Tesseract word-confidence (0-100), the page gets a
# "low_ocr_confidence" warning rather than being silently trusted —
# Tesseract's known weak spot is noisy/skewed/handwritten scans, and a
# low score is the cheapest signal we have that a human should look at
# the source document rather than the extracted text.
LOW_OCR_CONFIDENCE_THRESHOLD = 60.0


def ocr_image(pil_image: Image.Image) -> tuple[str, float | None]:
    """
    Runs Tesseract via image_to_data (not image_to_string) specifically
    to get per-word confidence scores back, not just text — the
    confidence is what lets downstream consumers decide whether to trust
    an OCR'd page.
    """
    data = pytesseract.image_to_data(pil_image, output_type=pytesseract.Output.DICT)

    words: list[str] = []
    confidences: list[float] = []
    for text, conf in zip(data["text"], data["conf"]):
        if not text.strip():
            continue
        words.append(text)
        try:
            conf_value = float(conf)
        except (TypeError, ValueError):
            continue
        # Tesseract uses -1 for "no confidence available" (e.g. on
        # non-text regions) — exclude rather than let it drag the mean down.
        if conf_value >= 0:
            confidences.append(conf_value)

    full_text = " ".join(words)
    mean_confidence = sum(confidences) / len(confidences) if confidences else None
    return full_text, mean_confidence
