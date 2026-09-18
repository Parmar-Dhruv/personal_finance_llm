from dataclasses import dataclass, field


@dataclass
class ExtractedPage:
    """
    Uniform result shape every extractor returns, regardless of source
    format. `page_number` is 1-indexed and means "PDF page" or "image"
    (always 1) or "spreadsheet sheet position" depending on the source —
    the caller (the Celery task) doesn't need to know which.
    """

    page_number: int
    method: str  # matches app.db.models.ExtractionMethod values
    text: str
    tables: list[list[list[str]]] = field(default_factory=list)
    ocr_confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
