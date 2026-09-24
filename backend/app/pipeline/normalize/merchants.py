"""
Merchant canonicalization — Phase 3.

Three-tier resolution, cheapest/most-confident first:
  1. MerchantAlias table (system-seeded + user-defined) — regex pattern
     match against the cleaned text. High confidence.
  2. Fuzzy match (rapidfuzz) against merchant names this same user has
     already resolved — catches "AMAZON.COM" / "AMZN MKTPLACE US" /
     "AMAZON MKTPLACE" converging to one canonical name even without a
     seeded alias for it. Medium confidence.
  3. No match — the cleaned text becomes its own canonical name. Low
     confidence, and the *next* similar transaction will fuzzy-match
     against it via tier 2.

rapidfuzz, not fuzzywuzzy/thefuzz: MIT vs GPL, same license-hygiene call
already made for PyMuPDF and Garage in earlier phases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz, process
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MerchantAlias, Transaction

MatchType = Literal["alias", "fuzzy", "unmatched"]

# Fraction (0-100, rapidfuzz's scale) above which a fuzzy match is
# trusted. Picked conservatively — false merges (two different real
# merchants collapsed into one) are worse than false splits (the same
# merchant appearing as two canonical names) for a system whose job is
# auditable evidence, not maximal dedup.
_FUZZY_MATCH_THRESHOLD = 88.0

# Noise prefixes seen on real US/Indian statement description text:
# payment-network processor tags, transaction-type tags, and Indian
# payment-rail prefixes (NEFT/IMPS/UPI/RTGS carry a bank reference
# number, not the merchant name, immediately after them).
_PREFIX_NOISE_RE = re.compile(
    r"(?i)^(?:pos|ach|debit|credit|purchase|payment|withdrawal|"
    r"neft[-*]?|imps[-*]?|upi[-*/]?|rtgs[-*]?|tst\*|sq\s?\*|paypal\s?\*)\s*[:\-*]?\s*"
)

# Long digit runs (reference/card/order numbers), masked-card patterns
# (XXXX1234 / ****1234), and trailing "REF <digits>" tails.
_TRAILING_NOISE_RE = re.compile(
    r"(?i)\s*(?:x{2,}\d{2,}|\*{2,}\d{2,}|#?\d{6,}|ref\s*[:#]?\s*\d+)\s*$"
)

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s&.'-]")


def clean_merchant_text(raw: str) -> str:
    """
    Heuristic cleanup only — there is no universal standard for how
    banks format the merchant field, so this will miss cases. Known gap,
    tracked rather than silently assumed complete.
    """
    text = raw.strip()
    text = _PREFIX_NOISE_RE.sub("", text)
    text = _TRAILING_NOISE_RE.sub("", text)
    text = _PUNCT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


@dataclass
class MerchantCandidates:
    """
    Per-normalization-run cache: aliases loaded once, and the set of
    canonical names this user has already resolved to (seeded from
    existing Transaction rows, and grown in-memory as new ones resolve
    within the same run so multiple occurrences of a new merchant in
    one statement converge with each other, not just with history).
    """

    aliases: list[MerchantAlias]
    known_canonical: list[str]

    @classmethod
    def load(cls, db: Session, user_id) -> "MerchantCandidates":
        alias_stmt = (
            select(MerchantAlias)
            .where((MerchantAlias.user_id == user_id) | (MerchantAlias.user_id.is_(None)))
        )
        aliases = sorted(
            db.execute(alias_stmt).scalars().all(),
            key=lambda a: len(a.pattern),
            reverse=True,
        )

        # Cap the candidate pool — this is a per-row fuzzy-match seed
        # list, not an audit query; a user with tens of thousands of
        # historical transactions doesn't need all of them considered.
        known_stmt = (
            select(Transaction.merchant_normalized)
            .where(Transaction.user_id == user_id, Transaction.merchant_normalized.is_not(None))
            .distinct()
            .limit(2000)
        )
        known = [row[0] for row in db.execute(known_stmt).all()]

        return cls(aliases=aliases, known_canonical=known)


def resolve_merchant(cleaned: str, candidates: MerchantCandidates) -> tuple[str, MatchType]:
    if not cleaned:
        return "", "unmatched"

    for alias in candidates.aliases:
        try:
            if re.match(alias.pattern, cleaned, re.IGNORECASE):
                return alias.canonical_name, "alias"
        except re.error:
            # A malformed user-supplied pattern shouldn't take down
            # normalization for every transaction — skip it, not crash.
            continue

    if candidates.known_canonical:
        best = process.extractOne(
            cleaned, candidates.known_canonical, scorer=fuzz.token_sort_ratio
        )
        if best is not None and best[1] >= _FUZZY_MATCH_THRESHOLD:
            return best[0], "fuzzy"

    canonical = cleaned.title()
    candidates.known_canonical.append(canonical)
    return canonical, "unmatched"
