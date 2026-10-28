"""
Anomaly detection: pure, no DB.

An anomaly here means "unusually LARGE for this merchant/category/user", not
fraud (spec §9: surface for investigation, never accuse). Method: robust
z-score on log(amount) -- median/MAD instead of mean/std so one huge outlier
can't hide itself by inflating the spread, log because spend is right-skewed.

Baseline hierarchy, most specific first, falling through only when there
isn't enough history:
    merchant (>= 8 txns)  ->  category (>= 15)  ->  user-wide (>= 30)
A transaction with no sufficient baseline is NOT flagged -- "can't tell" is
reported as such (score None), never as "normal".
Only upward deviations are flagged: an unusually small charge isn't a
finding a person needs to investigate.
Isolation Forest and IQR are implemented in app/ml/eval.py as benchmarks to
justify this choice; they are not served.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from decimal import Decimal

Z_THRESHOLD = 3.5  # Iglewicz & Hoaglin's conventional cutoff for modified z
MAD_FLOOR = 0.15  # in log space (~16%): a zero-spread baseline (fixed rent) must not turn $1 of drift into z=inf
MIN_N = {"merchant": 8, "category": 15, "user": 30}


@dataclass(frozen=True)
class ATxn:
    id: object
    currency: str
    type: str
    amount: Decimal
    merchant: str | None
    category: object | None


@dataclass(frozen=True)
class AnomalyResult:
    txn_id: object
    score: float | None  # modified z; None = no usable baseline
    flagged: bool
    level: str | None
    n: int
    median: float | None  # baseline median, back in currency units
    mad: float | None  # in log space


def _modified_z(x_log: float, logs: list[float]) -> tuple[float, float, float]:
    med = statistics.median(logs)
    mad = max(statistics.median(abs(v - med) for v in logs), MAD_FLOOR)
    return 0.6745 * (x_log - med) / mad, med, mad


def score_anomalies(txns: list[ATxn], threshold: float = Z_THRESHOLD) -> list[AnomalyResult]:
    logs = {t.id: math.log(max(float(t.amount), 0.01)) for t in txns}
    levels: dict[str, dict[tuple, list[ATxn]]] = {"merchant": {}, "category": {}, "user": {}}
    for t in txns:
        base = (t.currency, t.type)
        if t.merchant:
            levels["merchant"].setdefault(base + (t.merchant.lower(),), []).append(t)
        if t.category is not None:
            levels["category"].setdefault(base + (t.category,), []).append(t)
        levels["user"].setdefault(base, []).append(t)

    cache: dict[tuple, tuple[list[float], float]] = {}
    out: list[AnomalyResult] = []
    for t in txns:
        base = (t.currency, t.type)
        keys = {
            "merchant": base + (t.merchant.lower(),) if t.merchant else None,
            "category": base + (t.category,) if t.category is not None else None,
            "user": base,
        }
        result = AnomalyResult(t.id, None, False, None, 0, None, None)
        for level in ("merchant", "category", "user"):
            key = keys[level]
            group = levels[level].get(key) if key else None
            if not group or len(group) < MIN_N[level]:
                continue
            ck = (level, key)
            if ck not in cache:
                cache[ck] = ([logs[g.id] for g in group], 0.0)
            z, med, mad = _modified_z(logs[t.id], cache[ck][0])
            result = AnomalyResult(t.id, round(z, 3), z >= threshold, level, len(group), round(math.exp(med), 2), round(mad, 3))
            break
        out.append(result)
    return out
