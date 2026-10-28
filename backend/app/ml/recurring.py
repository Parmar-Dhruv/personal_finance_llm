"""
Recurring-payment detection: pure algorithm, no DB.

A "recurring payment" here means a bill/subscription/salary-style stream: the
same merchant, on a fixed cadence (weekly, biweekly, monthly, quarterly,
yearly), at a fixed or slowly drifting amount. Habitual spending (Swiggy three
times a week) is deliberately NOT recurring -- its intervals are irregular.
Daily cadence isn't modeled.

Method (all deterministic, no learned parameters):
 1. Group by (account, currency, type, merchant).
 2. Take the distinct purchase dates; compute day intervals.
 3. Snap the median interval to the nearest standard cadence; score each
    interval as on-cadence (1.0), a skipped period (0.5: ~2-3x the cadence)
    or off (0). Accept when the mean score >= MIN_REGULARITY.
 4. Characterize the amount: tight band -> fixed price; wider but bounded ->
    variable bill (utilities); wild -> reject.
 5. If the whole merchant fails step 3 (two interleaved subscriptions at one
    merchant, say), retry each amount cluster (+-5%) on its own.
Statistical, not learned: there is no labeled real data to learn from.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

# name -> (nominal days, tolerance days, min occurrences)
CADENCES: dict[str, tuple[float, float, int]] = {
    "weekly": (7.0, 1.5, 4),
    "biweekly": (14.0, 2.5, 4),
    "monthly": (30.44, 4.5, 3),
    "quarterly": (91.31, 9.0, 3),
    "yearly": (365.25, 16.0, 2),
}
MIN_REGULARITY = 0.75
FIXED_AMOUNT_BAND = 0.05  # MAD/median at or below this = fixed price
MAX_VARIABLE_SPREAD = 0.50  # above this = not a bill, just a merchant
YEARLY_TENTATIVE_CAP = 0.55  # two yearly occurrences prove very little


@dataclass(frozen=True)
class RTxn:
    id: object
    date: datetime
    merchant: str | None
    amount: Decimal
    type: str
    account: object
    currency: str


@dataclass
class Series:
    account: object
    currency: str
    type: str
    merchant: str
    cadence: str
    interval_days: float
    typical_amount: Decimal
    amount_variable: bool
    confidence: float
    first_date: datetime
    last_date: datetime
    next_expected_date: datetime
    is_active: bool
    member_ids: list = field(default_factory=list)

    @property
    def occurrence_count(self) -> int:
        return len(self.member_ids)


def _snap(median_interval: float) -> str | None:
    best, best_ratio = None, 1.0
    for name, (nominal, tol, _) in CADENCES.items():
        ratio = abs(median_interval - nominal) / tol
        if ratio <= best_ratio:
            best, best_ratio = name, ratio
    return best


def _regularity(intervals: list[float], cadence: str) -> float:
    nominal, tol, _ = CADENCES[cadence]
    score = 0.0
    for iv in intervals:
        if abs(iv - nominal) <= tol:
            score += 1.0
        elif any(abs(iv - k * nominal) <= tol * k * 0.6 for k in (2, 3)):
            score += 0.5  # a skipped period, not a broken stream
    return score / len(intervals)


def _robust_spread(values: list[float]) -> float:
    med = statistics.median(values)
    if med == 0:
        return 0.0
    return statistics.median(abs(v - med) for v in values) / abs(med)


def _evaluate(txns: list[RTxn], as_of: datetime, extra_occ: int = 0) -> Series | None:
    # One occurrence per calendar date: extra same-day rows would give
    # zero-day intervals and mean "two payments", not "a stream".
    by_day: dict = {}
    for t in sorted(txns, key=lambda x: x.date):
        by_day.setdefault(t.date.date(), t)
    members = list(by_day.values())
    if len(members) < 2:
        return None
    dates = [m.date for m in members]
    intervals = [(b - a).total_seconds() / 86400 for a, b in zip(dates, dates[1:])]
    cadence = _snap(statistics.median(intervals))
    if cadence is None or len(members) < CADENCES[cadence][2] + extra_occ:
        return None
    reg = _regularity(intervals, cadence)
    if reg < MIN_REGULARITY:
        return None

    amounts = [float(m.amount) for m in members]
    spread = _robust_spread(amounts)
    if spread > MAX_VARIABLE_SPREAD:
        return None
    variable = spread > FIXED_AMOUNT_BAND

    n, min_occ = len(members), CADENCES[cadence][2]
    depth = 0.6 + 0.4 * min(1.0, (n - min_occ + 1) / 4)  # more occurrences, more trust
    conf = reg * depth * (0.9 if variable else 1.0)
    if cadence == "yearly" and n < 3:
        conf = min(conf, YEARLY_TENTATIVE_CAP)

    nominal = CADENCES[cadence][0]
    # Typical amount = median of the most recent occurrences, so a price
    # rise shows the *current* price rather than the all-time median.
    typical = Decimal(str(statistics.median(amounts[-3:]))).quantize(Decimal("0.01"))
    last = dates[-1]
    return Series(
        account=members[0].account, currency=members[0].currency, type=members[0].type,
        merchant=members[0].merchant or "", cadence=cadence, interval_days=round(statistics.median(intervals), 2),
        typical_amount=typical, amount_variable=variable, confidence=round(conf, 3),
        first_date=dates[0], last_date=last, next_expected_date=last + timedelta(days=nominal),
        is_active=(as_of - last).total_seconds() / 86400 <= 1.5 * nominal,
        member_ids=[m.id for m in members],
    )


def _amount_clusters(txns: list[RTxn]) -> list[list[RTxn]]:
    clusters: list[list[RTxn]] = []
    for t in sorted(txns, key=lambda x: x.amount):
        if clusters and float(t.amount) <= float(clusters[-1][0].amount) * (1 + FIXED_AMOUNT_BAND):
            clusters[-1].append(t)
        else:
            clusters.append([t])
    return clusters


def detect_recurring(txns: list[RTxn], as_of: datetime | None = None) -> list[Series]:
    """
    `as_of` defaults to the latest transaction date in `txns` (not the wall
    clock), so results are reproducible and an old upload isn't instantly
    "inactive".
    """
    usable = [t for t in txns if t.merchant and t.merchant.strip()]
    if not usable:
        return []
    as_of = as_of or max(t.date for t in txns)

    groups: dict[tuple, list[RTxn]] = {}
    for t in usable:
        groups.setdefault((t.account, t.currency, t.type, t.merchant.strip().lower()), []).append(t)

    out: list[Series] = []
    for group in groups.values():
        series = _evaluate(group, as_of)
        if series is not None:
            out.append(series)
            continue
        for cluster in _amount_clusters(group):
            if len(cluster) >= 3:
                # One more occurrence than the whole-merchant path demands: a
                # busy merchant has many amount clusters, and with enough
                # clusters some 3-point run lines up with a cadence by pure
                # chance (found in eval: Uber "quarterly" in 5/20 users).
                s = _evaluate(cluster, as_of, extra_occ=1)
                if s is not None:
                    out.append(s)
    return out
