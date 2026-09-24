"""
Date normalization — Phase 3.

Policy decided 2026-09-22: FinSight assumes day-first (DD/MM/YYYY) dates,
full stop. No per-account/per-document locale detection, no MM/DD
fallback. This is a deliberate scope cut, not an oversight — see
PROGRESS_TRACKER.md Known Gaps. A statement using MM/DD (e.g. most raw
US bank exports) will be silently misparsed unless its dates happen to
be unambiguous (day > 12, or a month name). Revisit if/when non-DD/MM
sources are actually needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from dateutil import parser as dateutil_parser

# Tried in order, via strptime, before falling back to dateutil. Explicit
# formats are unambiguous and cheap; keeping them first means the common
# case never touches dateutil's fuzzier (and slower) guessing logic.
# ISO (%Y-%m-%d) is included even though it isn't day-first, because it
# is *inherently* unambiguous and appears in some export formats
# regardless of statement locale.
_STRICT_FORMATS = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%d-%m-%y",
    "%d %b %Y",
    "%d %B %Y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%Y-%m-%d",
)

_MIN_YEAR = 1990


@dataclass(frozen=True)
class ParsedDate:
    value: date
    # "strict" = matched one of _STRICT_FORMATS exactly (high confidence).
    # "dateutil" = fell back to dateutil.parser with dayfirst=True forced
    # (still DD/MM policy, just more permissive about separators/padding).
    method: str


def parse_transaction_date(raw: str) -> ParsedDate | None:
    """
    Returns None (never raises) on anything unparseable, so callers can
    treat it as "skip this row" rather than special-casing exceptions —
    header rows, footer/total lines, and empty cells all fail here by
    design, which is the mechanism that filters them out upstream.
    """
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None

    for fmt in _STRICT_FORMATS:
        try:
            return ParsedDate(value=datetime.strptime(text, fmt).date(), method="strict")
        except ValueError:
            continue

    try:
        # fuzzy=False: a description line like "Payment to Amazon on the
        # 3rd" should not be treated as a date just because it contains
        # date-like tokens. dayfirst=True is the whole point of this
        # module — never let dateutil guess month-first.
        parsed = dateutil_parser.parse(text, dayfirst=True, fuzzy=False)
    except (ValueError, OverflowError, TypeError):
        return None

    # dateutil silently fills in "today" for missing components (e.g. a
    # bare "14:30" parses as today's date at 14:30) — a genuine
    # transaction date should never round-trip through that default, so
    # sanity-bound the year rather than trust it blindly.
    current_year = datetime.now().year
    if parsed.year < _MIN_YEAR or parsed.year > current_year + 1:
        return None

    return ParsedDate(value=parsed.date(), method="dateutil")
