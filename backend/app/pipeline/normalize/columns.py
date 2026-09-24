"""
Column detection — Phase 3.

Bank/credit-card statement tables have no universal schema, so column
identification runs in three descending-confidence tiers:
  1. Header keyword match (this table's own row 0 says what each column is)
  2. Reuse the previous table/page's mapping in this same document
     (handles multi-page statements where only page 1 has a header)
  3. Positional inference (which column's values mostly parse as dates,
     which mostly parse as amounts)

A table that fails all three is skipped with a `column_detection_failed`
warning on its page, rather than guessed at further.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.pipeline.normalize.amounts import parse_amount
from app.pipeline.normalize.dates import parse_transaction_date

ColumnSource = Literal["header", "reused", "positional"]

# Checked in this order — DEBIT/CREDIT before the generic AMOUNT set, so
# a header like "Debit Amount" is classified as a debit column, not
# collapsed into a single ambiguous amount column.
_DATE_KEYWORDS = ("transaction date", "posting date", "value date", "txn date", "date")
_DEBIT_KEYWORDS = ("debit amount", "withdrawal amt", "withdrawal", "debit", "dr")
_CREDIT_KEYWORDS = ("credit amount", "deposit amt", "deposit", "credit", "cr")
_AMOUNT_KEYWORDS = ("amount", "amt")
_DESCRIPTION_KEYWORDS = ("description", "particulars", "narrative", "details", "remarks", "transaction details")

# Fraction of sampled rows that must parse for a positionally-inferred
# column to be trusted, and how many rows to sample.
_POSITIONAL_MIN_HIT_RATE = 0.5
_POSITIONAL_SAMPLE_SIZE = 20


@dataclass(frozen=True)
class ColumnMapping:
    date_idx: int
    description_idx: int | None
    amount_idx: int | None  # single combined amount column
    debit_idx: int | None  # separate debit column
    credit_idx: int | None  # separate credit column
    source: ColumnSource
    num_columns: int


def _match_keyword(cell: str, keywords: tuple[str, ...]) -> bool:
    """
    Word-boundary match, NOT naive substring containment. Naive `in`
    matching was tried first and broke on real data: the short
    abbreviation keywords "cr"/"dr" are legitimate header text on their
    own ("Cr", "Dr" columns) but also appear as bare substrings inside
    unrelated words — "description" contains "cr" (des-CR-iption),
    "withdrawal" contains "dr" — which silently misclassified a
    Description column as a Credit column. \\b anchors prevent a keyword
    from matching mid-word.
    """
    lowered = cell.strip().lower()
    return any(re.search(rf"\b{re.escape(keyword)}\b", lowered) for keyword in keywords)


def detect_columns_from_header(header_row: list[str]) -> ColumnMapping | None:
    date_idx = description_idx = amount_idx = debit_idx = credit_idx = None

    for i, cell in enumerate(header_row):
        if date_idx is None and _match_keyword(cell, _DATE_KEYWORDS):
            date_idx = i
        elif debit_idx is None and _match_keyword(cell, _DEBIT_KEYWORDS):
            debit_idx = i
        elif credit_idx is None and _match_keyword(cell, _CREDIT_KEYWORDS):
            credit_idx = i
        elif amount_idx is None and _match_keyword(cell, _AMOUNT_KEYWORDS):
            amount_idx = i
        elif description_idx is None and _match_keyword(cell, _DESCRIPTION_KEYWORDS):
            description_idx = i

    if date_idx is None:
        return None
    if amount_idx is None and debit_idx is None and credit_idx is None:
        return None

    return ColumnMapping(
        date_idx=date_idx,
        description_idx=description_idx,
        amount_idx=amount_idx,
        debit_idx=debit_idx,
        credit_idx=credit_idx,
        source="header",
        num_columns=len(header_row),
    )


def detect_columns_positional(rows: list[list[str]]) -> ColumnMapping | None:
    if not rows:
        return None
    num_columns = len(rows[0])
    sample = rows[:_POSITIONAL_SAMPLE_SIZE]

    date_hits = [0] * num_columns
    amount_hits = [0] * num_columns
    text_lengths = [0] * num_columns

    for row in sample:
        for i in range(min(num_columns, len(row))):
            cell = row[i]
            if parse_transaction_date(cell) is not None:
                date_hits[i] += 1
            if parse_amount(cell) is not None:
                amount_hits[i] += 1
            text_lengths[i] += len(cell or "")

    min_hits = max(1, int(len(sample) * _POSITIONAL_MIN_HIT_RATE))

    date_idx = max(range(num_columns), key=lambda i: date_hits[i], default=None)
    if date_idx is None or date_hits[date_idx] < min_hits:
        return None

    amount_candidates = [i for i in range(num_columns) if i != date_idx]
    if not amount_candidates:
        return None
    amount_idx = max(amount_candidates, key=lambda i: amount_hits[i])
    if amount_hits[amount_idx] < min_hits:
        return None

    remaining = [i for i in range(num_columns) if i not in (date_idx, amount_idx)]
    description_idx = max(remaining, key=lambda i: text_lengths[i]) if remaining else None

    return ColumnMapping(
        date_idx=date_idx,
        description_idx=description_idx,
        amount_idx=amount_idx,
        debit_idx=None,
        credit_idx=None,
        source="positional",
        num_columns=num_columns,
    )


def reuse_mapping(previous: ColumnMapping | None, num_columns: int) -> ColumnMapping | None:
    """Only reuse a prior page's mapping if the column count still lines up."""
    if previous is None or previous.num_columns != num_columns:
        return None
    return ColumnMapping(
        date_idx=previous.date_idx,
        description_idx=previous.description_idx,
        amount_idx=previous.amount_idx,
        debit_idx=previous.debit_idx,
        credit_idx=previous.credit_idx,
        source="reused",
        num_columns=num_columns,
    )
