"""
Normalization engine — Phase 3.

Turns a Document's extracted DocumentPages (Phase 2 output: raw_text +
tables, per page) into Transaction rows. Deterministic parsing/matching
only — no LLM calls in this module, per the project's core separation
principle (personal_finance_llm.md §17): normalization is "must be
correct" work, not "requires flexible language understanding" work.

Entry point: `normalize_document(db, document)`.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    Document,
    DocumentPage,
    NormalizationStatus,
    Transaction,
    TransactionType,
)
from app.pipeline.normalize.amounts import ParsedAmount, parse_amount
from app.pipeline.normalize.columns import (
    ColumnMapping,
    detect_columns_from_header,
    detect_columns_positional,
    reuse_mapping,
)
from app.pipeline.normalize.dates import ParsedDate, parse_transaction_date
from app.pipeline.normalize.merchants import MerchantCandidates, clean_merchant_text, resolve_merchant

# Currencies Phase 3 knows how to parse amounts for. See amounts.py
# module docstring for why (shared decimal-point/comma-grouping
# convention) — this is a real scope limit, not a placeholder.
SUPPORTED_CURRENCIES = frozenset({"INR", "USD"})

# Cap on how many per-row skip reasons get written into a page's
# `warnings` JSONB — a messy multi-hundred-row statement shouldn't blow
# up the column size with one entry per unparseable line. The count
# itself is still recorded in full.
_MAX_LOGGED_ROW_WARNINGS = 10

# Line pattern for the raw-text (no extracted tables) fallback path:
# <date token> <description ...> <amount, exactly 2 decimals, optional
# currency symbol/Cr/Dr>. Requires 2 decimal places specifically because
# that's what distinguishes a trailing money amount from an arbitrary
# trailing number (a reference ID, a page number).
_LINE_RE = re.compile(
    r"^\s*(?P<date>\S+(?:[/\-.]\S+){1,2})\s+(?P<desc>.+?)\s+"
    r"(?P<amount>[(\-+]?\s?[$₹]?\s?[\d,]+\.\d{2}\s?\)?\s?(?:cr|dr)?\.?)\s*$",
    re.IGNORECASE,
)


class UnsupportedCurrencyError(Exception):
    pass


def _to_confidence(components: list[float]) -> float:
    return round(sum(components) / len(components), 2) if components else 0.0


def _resolve_type_and_amount(
    row: list[str],
    mapping: ColumnMapping,
) -> tuple[ParsedAmount, TransactionType, float] | None:
    """
    Returns (parsed_amount, transaction_type, sign_confidence) or None if
    no usable amount is present on this row at all.
    """
    if mapping.debit_idx is not None or mapping.credit_idx is not None:
        debit_cell = row[mapping.debit_idx] if mapping.debit_idx is not None and mapping.debit_idx < len(row) else ""
        credit_cell = row[mapping.credit_idx] if mapping.credit_idx is not None and mapping.credit_idx < len(row) else ""
        debit_amount = parse_amount(debit_cell)
        credit_amount = parse_amount(credit_cell)
        # Separate debit/credit columns are the clearest possible signal
        # — whichever cell is populated says the type directly.
        if debit_amount is not None:
            return debit_amount, TransactionType.debit, 1.0
        if credit_amount is not None:
            return credit_amount, TransactionType.credit, 1.0
        return None

    if mapping.amount_idx is None or mapping.amount_idx >= len(row):
        return None
    parsed = parse_amount(row[mapping.amount_idx])
    if parsed is None:
        return None
    return _resolve_from_sign_hint(parsed)


def _resolve_from_sign_hint(parsed: ParsedAmount) -> tuple[ParsedAmount, TransactionType, float]:
    if parsed.sign_hint == "credit":
        return parsed, TransactionType.credit, 1.0
    if parsed.sign_hint == "debit":
        return parsed, TransactionType.debit, 1.0
    # No sign at all in a single-amount-column layout — genuinely
    # ambiguous. Documented default (see amounts.py / Known Gaps): debit,
    # since expenses are the more common unsigned case in practice, but
    # flagged with reduced confidence so it's visibly not a sure thing.
    return parsed, TransactionType.debit, 0.5


def _build_description(row: list[str], mapping: ColumnMapping, fallback_cell: str | None) -> str:
    if mapping.description_idx is not None and mapping.description_idx < len(row):
        text = row[mapping.description_idx].strip()
        if text:
            return text
    if fallback_cell:
        return fallback_cell.strip()
    used = {mapping.date_idx, mapping.amount_idx, mapping.debit_idx, mapping.credit_idx}
    remainder = " ".join(cell.strip() for i, cell in enumerate(row) if i not in used and cell and cell.strip())
    return remainder or "(no description)"


def _date_to_datetime(parsed: ParsedDate) -> datetime:
    return datetime(parsed.value.year, parsed.value.month, parsed.value.day, tzinfo=timezone.utc)


def _build_transaction(
    *,
    date_str: str,
    amount_result: tuple[ParsedAmount, TransactionType, float],
    description: str,
    account: Account,
    user_id,
    document: Document,
    page: DocumentPage,
    candidates: MerchantCandidates,
    column_confidence: float,
    date_method_confidence: float,
) -> Transaction | None:
    parsed_date = parse_transaction_date(date_str)
    if parsed_date is None:
        return None

    parsed_amount, txn_type, sign_confidence = amount_result

    cleaned_merchant = clean_merchant_text(description)
    canonical_merchant, match_type = resolve_merchant(cleaned_merchant, candidates)
    merchant_confidence = {"alias": 1.0, "fuzzy": 0.75, "unmatched": 0.5}[match_type]

    page_confidence = 1.0
    if page.extraction_method.value == "ocr":
        page_confidence = (page.ocr_confidence / 100.0) if page.ocr_confidence is not None else 0.5

    confidence = _to_confidence(
        [column_confidence, date_method_confidence, sign_confidence, merchant_confidence, page_confidence]
    )

    return Transaction(
        user_id=user_id,
        account_id=account.id,
        source_document_id=document.id,
        transaction_date=_date_to_datetime(parsed_date),
        description_raw=description[:2000],
        merchant_normalized=canonical_merchant or None,
        amount=parsed_amount.magnitude.quantize(Decimal("0.01")),
        currency=account.currency,
        transaction_type=txn_type,
        confidence_score=confidence,
        raw_data={
            "source_page": page.page_number,
            "merchant_match_type": match_type,
            "date_parse_method": parsed_date.method,
            "column_source": column_confidence,
        },
    )


def _normalize_table(
    table: list[list[str]],
    page: DocumentPage,
    account: Account,
    user_id,
    document: Document,
    candidates: MerchantCandidates,
    cached_mapping: ColumnMapping | None,
) -> tuple[list[Transaction], int, ColumnMapping | None]:
    if not table:
        return [], 0, cached_mapping

    num_columns = len(table[0])
    mapping = detect_columns_from_header(table[0])
    data_rows = table[1:] if mapping is not None else table

    if mapping is None:
        mapping = reuse_mapping(cached_mapping, num_columns)
        data_rows = table
    if mapping is None:
        mapping = detect_columns_positional(table)
        data_rows = table

    if mapping is None:
        return [], 0, cached_mapping

    column_confidence = {"header": 1.0, "reused": 0.85, "positional": 0.6}[mapping.source]

    transactions: list[Transaction] = []
    skipped = 0
    for row in data_rows:
        if mapping.date_idx >= len(row):
            skipped += 1
            continue
        amount_result = _resolve_type_and_amount(row, mapping)
        if amount_result is None:
            skipped += 1
            continue
        description = _build_description(row, mapping, None)
        parsed_date_probe = parse_transaction_date(row[mapping.date_idx])
        date_method_confidence = 1.0 if (parsed_date_probe and parsed_date_probe.method == "strict") else 0.8
        txn = _build_transaction(
            date_str=row[mapping.date_idx],
            amount_result=amount_result,
            description=description,
            account=account,
            user_id=user_id,
            document=document,
            page=page,
            candidates=candidates,
            column_confidence=column_confidence,
            date_method_confidence=date_method_confidence,
        )
        if txn is None:
            skipped += 1
            continue
        transactions.append(txn)

    return transactions, skipped, mapping


def _normalize_raw_text(
    raw_text: str,
    page: DocumentPage,
    account: Account,
    user_id,
    document: Document,
    candidates: MerchantCandidates,
) -> tuple[list[Transaction], int]:
    transactions: list[Transaction] = []
    skipped = 0
    for line in raw_text.splitlines():
        match = _LINE_RE.match(line)
        if not match:
            continue
        parsed_amount = parse_amount(match.group("amount"))
        if parsed_amount is None:
            skipped += 1
            continue
        amount_result = _resolve_from_sign_hint(parsed_amount)
        parsed_date_probe = parse_transaction_date(match.group("date"))
        date_method_confidence = 1.0 if (parsed_date_probe and parsed_date_probe.method == "strict") else 0.8
        txn = _build_transaction(
            date_str=match.group("date"),
            amount_result=amount_result,
            description=match.group("desc"),
            account=account,
            user_id=user_id,
            document=document,
            page=page,
            candidates=candidates,
            column_confidence=0.5,  # unstructured line-regex path — lowest-trust source
            date_method_confidence=date_method_confidence,
        )
        if txn is None:
            skipped += 1
            continue
        transactions.append(txn)
    return transactions, skipped


def normalize_document(db: Session, document: Document) -> int:
    """
    Runs normalization for one document and commits. Idempotent: any
    Transaction rows previously produced from this document are deleted
    first, so re-running (e.g. after fixing the account assignment)
    doesn't duplicate rows.

    Raises UnsupportedCurrencyError if the account's currency isn't
    INR/USD — caller is expected to catch this and set
    normalization_status=skipped, not treat it as a crash.
    """
    account = document.account
    if account is None:
        raise ValueError("document has no account assigned")
    if account.currency not in SUPPORTED_CURRENCIES:
        raise UnsupportedCurrencyError(account.currency)

    db.execute(delete(Transaction).where(Transaction.source_document_id == document.id))

    candidates = MerchantCandidates.load(db, document.user_id)

    total_created = 0
    cached_mapping: ColumnMapping | None = None

    for page in document.pages:
        page_warnings = list(page.warnings or [])
        row_skip_count = 0

        if page.tables:
            for table in page.tables:
                txns, skipped, mapping = _normalize_table(
                    table, page, account, document.user_id, document, candidates, cached_mapping
                )
                if mapping is not None:
                    cached_mapping = mapping
                else:
                    page_warnings.append("column_detection_failed")
                for txn in txns:
                    db.add(txn)
                total_created += len(txns)
                row_skip_count += skipped
        elif page.raw_text:
            txns, skipped = _normalize_raw_text(
                page.raw_text, page, account, document.user_id, document, candidates
            )
            for txn in txns:
                db.add(txn)
            total_created += len(txns)
            row_skip_count += skipped

        if row_skip_count:
            logged = min(row_skip_count, _MAX_LOGGED_ROW_WARNINGS)
            page_warnings.append(f"unparseable_rows: {row_skip_count} (showing up to {logged})")

        if page_warnings != (page.warnings or []):
            page.warnings = page_warnings

    document.transaction_count = total_created
    return total_created
