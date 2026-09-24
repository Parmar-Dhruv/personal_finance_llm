"""
Amount normalization — Phase 3.

Scope decided 2026-09-22: only INR and USD are supported. Both use the
same decimal-point/comma-grouping convention (`1,234.56` / `1,23,456.78`
for INR's lakh grouping — the grouping *spacing* differs but the
decimal point and thousands-separator characters are identical), so a
single parser handles both without per-currency branching on separator
style. This would need real rework (a different decimal_symbol per
currency) before a European-style currency (comma-decimal) could be
added — see PROGRESS_TRACKER.md Known Gaps.

Money is never handled as float anywhere in this module — every
conversion goes straight from a cleaned string to Decimal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

SignHint = Literal["debit", "credit"] | None

# $ and ₹ as symbols; Rs./Rs/INR/USD as text tokens, prefix or suffix,
# case-insensitive. Matched and stripped before the numeric conversion —
# the currency itself is NOT inferred from this (currency is inherited
# from Account.currency, per the existing model contract), this is
# purely noise removal so `$1,234.56` and `1,234.56 USD` both reduce to
# the same numeric string.
_CURRENCY_TOKEN_RE = re.compile(r"(?i)\b(?:rs\.?|inr|usd)\b|[$₹]")

# Indian bank-statement convention: amount is followed by "Cr"/"Dr"
# instead of a sign. This is an explicit, high-confidence signal for
# transaction_type and takes priority over any other sign heuristic.
_CR_DR_SUFFIX_RE = re.compile(r"(?i)\s*\b(cr|dr)\b\.?\s*$")

# Accounting-style negative: "(1,234.56)".
_PAREN_NEGATIVE_RE = re.compile(r"^\((.*)\)$")


@dataclass(frozen=True)
class ParsedAmount:
    magnitude: Decimal  # always >= 0
    sign_hint: SignHint  # "debit"/"credit" if the text itself said so, else None


def parse_amount(raw: str) -> ParsedAmount | None:
    """
    Returns None (never raises) on anything that isn't a real amount —
    blank cells, header/label text ("Amount", "Balance c/f"), and
    garbage OCR fragments all fail here, which is what lets the caller
    skip those rows instead of crashing the whole document.
    """
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None

    sign_hint: SignHint = None

    cr_dr_match = _CR_DR_SUFFIX_RE.search(text)
    if cr_dr_match:
        sign_hint = "credit" if cr_dr_match.group(1).lower() == "cr" else "debit"
        text = text[: cr_dr_match.start()].strip()

    text = _CURRENCY_TOKEN_RE.sub("", text).strip()

    paren_match = _PAREN_NEGATIVE_RE.match(text)
    if paren_match:
        # Parens are unambiguous, but don't let them contradict an
        # explicit Cr/Dr suffix if a (malformed) statement somehow has
        # both — Cr/Dr was already set above and takes priority.
        if sign_hint is None:
            sign_hint = "debit"
        text = paren_match.group(1).strip()

    explicit_minus = text.startswith("-")
    if explicit_minus:
        if sign_hint is None:
            sign_hint = "debit"
        text = text[1:].strip()
    elif text.startswith("+"):
        text = text[1:].strip()

    # Thousands separators only — safe to strip unconditionally since
    # INR/USD share the same decimal-point convention (see module
    # docstring); what varies is only where the commas land.
    text = text.replace(",", "").replace(" ", "")

    if not text:
        return None

    try:
        magnitude = Decimal(text)
    except InvalidOperation:
        return None

    # A row that's just "0.00" or "-" is almost always a placeholder
    # (empty debit/credit cell in a combined-column layout), not a real
    # zero-value transaction — treat as unparseable so the caller skips
    # it rather than recording a phantom $0 transaction.
    if magnitude == 0:
        return None

    return ParsedAmount(magnitude=abs(magnitude), sign_hint=sign_hint)
