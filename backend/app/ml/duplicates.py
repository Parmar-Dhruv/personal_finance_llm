"""
Duplicate-transaction scoring: pure, no DB.

What a "duplicate" is here: the same real-world payment recorded twice --
overwhelmingly an overlapping statement uploaded twice, or a posting-date
shift between two exports. NOT two legitimate identical purchases (two
chais at Rs 20 the same morning), which is why the score is a probability-ish
number routed to review rather than a delete.

Score (hand-weighted, uncalibrated -- there's no real labeled data):
    base = 0.45*date + 0.35*description + 0.20*cross_document
      date:  same day 1.0, 1 day 0.7, 2 days 0.45, 3 days 0.30, more: never a candidate
      description: rapidfuzz token_set_ratio on cleaned narrations
      cross_document: 1 if the rows came from different uploaded documents
    x0.25 if both narrations carry reference numbers and they DIFFER (bank
         ref ids are unique per payment: different refs = different payments)
    x0.5  for same-document pairs in a habit pattern (>=4 identical
         amount/merchant rows within a week, e.g. a daily metro fare)
Thresholds: >= AUTO_THRESHOLD is applied (duplicate_of_id set, analytics
exclude the later row); >= PENDING_THRESHOLD waits for a human.
Only same account + currency + direction + EXACT amount are ever compared.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from rapidfuzz import fuzz

from app.pipeline.normalize.merchants import clean_merchant_text

AUTO_THRESHOLD = 0.95
PENDING_THRESHOLD = 0.70
MAX_DAY_GAP = 3
_REF_RE = re.compile(r"\d{6,}")


@dataclass(frozen=True)
class DTxn:
    id: object
    account: object
    currency: str
    type: str
    amount: Decimal
    date: datetime
    description: str
    document: object | None
    # Lower sorts first = treated as the original. Callers pass something
    # like (document upload time, date, id) -- server-side created_at is
    # useless for this because a bulk insert gives every row the same now().
    order: tuple


@dataclass(frozen=True)
class DupResult:
    txn_id: object
    candidate_id: object
    score: float
    status: str  # auto | pending


_DATE_SCORE = {0: 1.0, 1: 0.7, 2: 0.45, 3: 0.30}


def _refs(text: str) -> set[str]:
    return set(_REF_RE.findall(text))


def pair_score(a: DTxn, b: DTxn, habitual: bool = False) -> float:
    days = abs((a.date.date() - b.date.date()).days)
    if days > MAX_DAY_GAP:
        return 0.0
    ca, cb = clean_merchant_text(a.description).lower(), clean_merchant_text(b.description).lower()
    desc = fuzz.token_set_ratio(ca, cb) / 100.0
    cross = 1.0 if (a.document is not None and b.document is not None and a.document != b.document) else 0.0
    score = 0.45 * _DATE_SCORE[days] + 0.35 * desc + 0.20 * cross
    ra, rb = _refs(a.description), _refs(b.description)
    if ra and rb and not (ra & rb):
        score *= 0.25
    if habitual and cross == 0.0:
        score *= 0.5
    return round(score, 4)


def detect_duplicates(txns: list[DTxn], skip_later: frozenset = frozenset()) -> list[DupResult]:
    """`skip_later`: ids that may serve as an original but are never re-judged as a duplicate
    (a human already confirmed or dismissed them)."""
    blocks: dict[tuple, list[DTxn]] = {}
    for t in txns:
        blocks.setdefault((t.account, t.currency, t.type, t.amount), []).append(t)

    results: list[DupResult] = []
    for block in blocks.values():
        if len(block) < 2:
            continue
        block.sort(key=lambda t: t.order)
        root: dict = {}  # txn id -> root original id, for auto-applied rows
        for j, later in enumerate(block):
            if later.id in skip_later:
                continue
            best: tuple[float, DTxn] | None = None
            for earlier in block[:j]:
                if abs((later.date.date() - earlier.date.date()).days) > MAX_DAY_GAP:
                    continue
                habitual = (
                    sum(
                        1 for x in block
                        if x.document == later.document and abs((x.date.date() - later.date.date()).days) <= 7
                    ) >= 4
                )
                s = pair_score(later, earlier, habitual)
                if best is None or s > best[0]:
                    best = (s, earlier)
            if best is None or best[0] < PENDING_THRESHOLD:
                continue
            score, cand = best
            status = "auto" if score >= AUTO_THRESHOLD else "pending"
            target = root.get(cand.id, cand.id) if status == "auto" else cand.id
            if status == "auto":
                root[later.id] = target
            results.append(DupResult(later.id, target, score, status))
    return results
