import io

import pandas as pd

from app.pipeline.extractors.common import ExtractedPage

# Sanity cap, not a real-world limit — a personal/small-business bank
# export shouldn't approach this; it exists to stop a malformed or
# adversarial file from loading millions of rows into worker memory.
MAX_ROWS_PER_SHEET = 50_000

# Client-supplied CSVs from real banks are frequently NOT UTF-8 (Windows
# exports are commonly cp1252/latin-1) — assuming UTF-8 and letting it
# raise would fail on real bank statements, not just edge cases.
CSV_ENCODING_FALLBACKS = ("utf-8", "utf-8-sig", "latin-1")


def _dataframe_to_table(df: pd.DataFrame) -> list[list[str]]:
    header = [str(column) for column in df.columns.tolist()]
    rows = df.astype(str).values.tolist()
    return [header] + rows


def extract_csv(file_bytes: bytes) -> list[ExtractedPage]:
    warnings: list[str] = []
    df: pd.DataFrame | None = None
    last_error: Exception | None = None

    for encoding in CSV_ENCODING_FALLBACKS:
        try:
            # dtype=str + keep_default_na=False: this is raw extraction,
            # not normalization. Coercing "01/08/26" or "$1,234.00" to
            # numbers/dates here would silently destroy information the
            # Phase 3 normalization layer is supposed to interpret.
            df = pd.read_csv(io.BytesIO(file_bytes), encoding=encoding, dtype=str, keep_default_na=False)
            if encoding != "utf-8":
                warnings.append(f"decoded_as_{encoding}")
            break
        except UnicodeDecodeError as exc:
            last_error = exc
            continue

    if df is None:
        raise ValueError(f"Could not decode CSV with any of {CSV_ENCODING_FALLBACKS}") from last_error

    if len(df) > MAX_ROWS_PER_SHEET:
        warnings.append("truncated_rows")
        df = df.head(MAX_ROWS_PER_SHEET)

    return [
        ExtractedPage(
            page_number=1,
            method="tabular",
            text=df.to_csv(index=False),
            tables=[_dataframe_to_table(df)],
            warnings=warnings,
        )
    ]


def extract_xlsx(file_bytes: bytes) -> list[ExtractedPage]:
    pages: list[ExtractedPage] = []
    excel_file = pd.ExcelFile(io.BytesIO(file_bytes), engine="openpyxl")

    for i, sheet_name in enumerate(excel_file.sheet_names, start=1):
        df = excel_file.parse(sheet_name, dtype=str, keep_default_na=False)

        warnings: list[str] = []
        if len(df) > MAX_ROWS_PER_SHEET:
            warnings.append("truncated_rows")
            df = df.head(MAX_ROWS_PER_SHEET)

        pages.append(
            ExtractedPage(
                page_number=i,
                method="tabular",
                text=df.to_csv(index=False),
                tables=[_dataframe_to_table(df)],
                warnings=warnings,
            )
        )

    if not pages:
        raise ValueError("Workbook contains no sheets")

    return pages
