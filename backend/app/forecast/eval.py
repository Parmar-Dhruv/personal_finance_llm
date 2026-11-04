"""
Phase 6 evaluation on SYNTHETIC monthly series. Run:

    python -m app.forecast.eval --series-per-length 60 --seed 7 --out-dir docs/forecast_eval

What this can and cannot tell you
 * The series come from six archetypes the author chose (stationary, trend,
   seasonal, level shift, random walk, spiky). Conclusions hold FOR THOSE
   ARCHETYPES. Real spending is not guaranteed to look like any of them, and
   the author who wrote the models also wrote the generator: expect worse on
   real data, same caveat as the Phase 5 classifier evaluation.
 * Each series is cut into train (everything but the last 3 months) and a
   3-month holdout. The shipped pipeline (`forecast_series`: rolling-origin
   selection, then refit) only ever sees the train part.
 * MASE = MAE / mean|one-step naive error on the train part| (Hyndman &
   Koehler 2006). Below 1 beats "repeat last month" measured in-sample.
 * The GBM is an EVAL-ONLY benchmark (decided with the user: it is never used
   for real users). It is pooled over OTHER synthetic series drawn from the same
   archetypes, which is in-distribution and so FLATTERS it; a pooled model on
   real users would also mean training on other people's financial data.
 * Interval coverage is measured on the holdout for series that got an interval.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.forecast import backtest as _bt
from app.forecast.backtest import forecast_series
from app.forecast.methods import METHODS, MethodFailed

HORIZON = 3
LENGTHS = (12, 18, 24, 36, 48)  # training months
ARCHETYPES = ("stationary", "trend", "seasonal", "level_shift", "random_walk", "spiky")


# ----------------------------------------------------------------------------
# synthetic series
# ----------------------------------------------------------------------------
@dataclass
class Series:
    kind: str
    y: np.ndarray  # n_train + HORIZON monthly values, >= 0
    start_month: int  # calendar month (0-11) of y[0]


def make_series(rng: np.random.Generator, kind: str, n: int) -> np.ndarray:
    level = float(np.exp(rng.normal(np.log(15000), 0.6)))
    t = np.arange(n)
    noise_cv = rng.uniform(0.08, 0.30)
    if kind == "stationary":
        y = level * (1 + rng.normal(0, noise_cv, n))
    elif kind == "trend":
        g = rng.choice([-1, 1]) * rng.uniform(0.005, 0.015)
        y = level * (1 + g * t) * (1 + rng.normal(0, noise_cv * 0.7, n))
    elif kind == "seasonal":
        amp, phase = rng.uniform(0.10, 0.35), rng.uniform(0, 2 * np.pi)
        y = level * (1 + amp * np.sin(2 * np.pi * t / 12 + phase)) * (1 + rng.normal(0, noise_cv * 0.6, n))
    elif kind == "level_shift":
        at = int(rng.integers(max(4, n // 3), n - 2))
        y = level * np.where(t >= at, 1 + rng.choice([-1, 1]) * rng.uniform(0.2, 0.5), 1.0) * (1 + rng.normal(0, noise_cv * 0.6, n))
    elif kind == "random_walk":
        y = level * np.exp(np.cumsum(rng.normal(0, rng.uniform(0.04, 0.10), n)))
    elif kind == "spiky":
        y = level * (1 + rng.normal(0, noise_cv * 0.6, n))
        spikes = rng.random(n) < 0.10
        y = np.where(spikes, y * rng.uniform(2, 4, n), y)
    else:
        raise ValueError(kind)
    return np.maximum(y, 0.0)


def make_corpus(rng: np.random.Generator, per_length: int) -> list[Series]:
    out = []
    for n_train in LENGTHS:
        for i in range(per_length):
            kind = ARCHETYPES[i % len(ARCHETYPES)]
            out.append(Series(kind, make_series(rng, kind, n_train + HORIZON), int(rng.integers(0, 12))))
    return out


# ----------------------------------------------------------------------------
# eval-only pooled GBM (NOT shipped, never used for real users)
# ----------------------------------------------------------------------------
LAGS = 6


def _gbm_rows(y: np.ndarray, start_month: int, origins) -> tuple[list, list]:
    X, T = [], []
    for t in origins:  # forecast origin: y[:t] known
        hist = y[:t]
        scale = float(np.mean(hist[-LAGS:])) or 1.0
        lags = list(hist[-LAGS:] / scale)
        for k in range(1, HORIZON + 1):
            if t + k - 1 >= len(y):
                continue
            m = (start_month + t + k - 1) % 12
            X.append(lags + [k, np.sin(2 * np.pi * m / 12), np.cos(2 * np.pi * m / 12), float(np.std(hist[-12:]) / scale)])
            T.append(y[t + k - 1] / scale)
    return X, T


def train_gbm(rng: np.random.Generator, n_series: int):
    from sklearn.ensemble import HistGradientBoostingRegressor

    X, T = [], []
    for i in range(n_series):
        kind = ARCHETYPES[i % len(ARCHETYPES)]
        n = int(rng.choice([18, 24, 36, 48])) + HORIZON
        y = make_series(rng, kind, n)
        sm = int(rng.integers(0, 12))
        x, tt = _gbm_rows(y, sm, range(LAGS, n))
        X += x
        T += tt
    model = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, max_depth=4, random_state=0)
    model.fit(np.array(X), np.array(T))
    return model, len(T)


def gbm_forecast(model, train: np.ndarray, start_month: int) -> np.ndarray:
    scale = float(np.mean(train[-LAGS:])) or 1.0
    t = len(train)
    rows = []
    for k in range(1, HORIZON + 1):
        m = (start_month + t + k - 1) % 12
        rows.append(list(train[-LAGS:] / scale) + [k, np.sin(2 * np.pi * m / 12), np.cos(2 * np.pi * m / 12), float(np.std(train[-12:]) / scale)])
    return np.maximum(model.predict(np.array(rows)) * scale, 0.0)


# ----------------------------------------------------------------------------
# evaluation
# ----------------------------------------------------------------------------
def _boot_ci(diff: np.ndarray, rng: np.random.Generator, b: int = 4000) -> tuple[float, float, float]:
    idx = rng.integers(0, len(diff), (b, len(diff)))
    means = diff[idx].mean(axis=1)
    return float(diff.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def evaluate(per_length: int, seed: int, gbm_series: int, level: float = 0.8, tolerance: float | None = None) -> dict:
    if tolerance is not None:  # sensitivity analysis only; the shipped default is backtest.SELECTION_TOLERANCE
        _bt.SELECTION_TOLERANCE = tolerance
    rng = np.random.default_rng(seed)
    corpus = make_corpus(rng, per_length)
    gbm, gbm_rows = train_gbm(np.random.default_rng(seed + 1), gbm_series)  # different seed: disjoint series

    names = [m.name for m in METHODS] + ["auto", "gbm_eval_only"]
    mase: dict[str, list[float | None]] = {n: [] for n in names}
    meta = []  # per series
    cover: dict[int, list[int]] = defaultdict(list)  # step -> hit flags
    cover_by_len: dict[int, list[int]] = defaultdict(list)
    modes: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    chosen: dict[str, int] = defaultdict(int)
    latencies = []
    skipped_flat = 0

    for s in corpus:
        train, actual = s.y[:-HORIZON], s.y[-HORIZON:]
        n_train = len(train)
        scale = float(np.mean(np.abs(np.diff(train))))
        if scale <= 0:
            skipped_flat += 1
            continue

        def score(fc) -> float:
            return float(np.mean(np.abs(actual - fc)) / scale)

        row: dict[str, float | None] = {}
        for m in METHODS:
            if n_train < m.min_train:
                row[m.name] = None
                continue
            try:
                row[m.name] = score(m.forecast(train, HORIZON))
            except MethodFailed:
                row[m.name] = None
        t0 = time.perf_counter()
        fs = forecast_series(train, HORIZON, level)
        latencies.append((n_train, time.perf_counter() - t0))
        row["auto"] = score(np.array(fs.point)) if fs.point is not None else None
        row["gbm_eval_only"] = score(gbm_forecast(gbm, train, s.start_month))
        for n in names:
            mase[n].append(row[n])
        meta.append((s.kind, n_train))
        modes[n_train][fs.mode] += 1
        if fs.method:
            chosen[fs.method] += 1
        if fs.mode == "backtested":
            for k in range(HORIZON):
                if fs.half_width[k] is not None:
                    hit = int(abs(actual[k] - fs.point[k]) <= fs.half_width[k])
                    cover[k + 1].append(hit)
                    cover_by_len[n_train].append(hit)

    def stats(vals: list[float | None]) -> dict:
        v = np.array([x for x in vals if x is not None])
        return {"n": int(len(v)), "mean_mase": round(float(v.mean()), 4), "median_mase": round(float(np.median(v)), 4)} if len(v) else {"n": 0}

    overall = {n: stats(mase[n]) for n in names}
    by_len = {L: {n: stats([v for v, (_, nt) in zip(mase[n], meta) if nt == L]) for n in names} for L in LENGTHS}
    by_kind = {k: {n: stats([v for v, (kk, _) in zip(mase[n], meta) if kk == k]) for n in ("naive", "moving_average_3", "median_12", "auto", "gbm_eval_only")} for k in ARCHETYPES}

    # Paired differences on series where both methods produced a forecast.
    def paired(a: str, b: str) -> dict:
        d = np.array([x - y for x, y in zip(mase[a], mase[b]) if x is not None and y is not None])
        mean, lo, hi = _boot_ci(d, np.random.default_rng(seed + 2))
        return {"a": a, "b": b, "n": int(len(d)), "mean_diff_mase_a_minus_b": round(mean, 4), "ci95": [round(lo, 4), round(hi, 4)],
                "a_better_share": round(float(np.mean(d < 0)), 3)}

    comparisons = [paired("auto", "naive"), paired("auto", "moving_average_3"), paired("auto", "median_12"),
                   paired("auto", "ets_ann"), paired("auto", "ets_seasonal"),
                   paired("gbm_eval_only", "auto"), paired("gbm_eval_only", "naive")]

    # Hindsight oracle over the methods that were eligible: headroom a perfect selector would have.
    oracle = []
    for i in range(len(meta)):
        vals = [mase[m.name][i] for m in METHODS if mase[m.name][i] is not None]
        if vals:
            oracle.append(min(vals))

    cov = {k: {"n": len(v), "coverage": round(float(np.mean(v)), 3)} for k, v in sorted(cover.items())}
    cov_len = {L: {"n": len(v), "coverage": round(float(np.mean(v)), 3)} for L, v in sorted(cover_by_len.items())}
    lat = {L: round(float(np.mean([t for n, t in latencies if n == L])) * 1000) for L in LENGTHS}
    return {
        "setup": {"series_per_length": per_length, "train_lengths": list(LENGTHS), "holdout_months": HORIZON, "seed": seed,
                  "archetypes": list(ARCHETYPES), "interval_level": level, "gbm_training_series": gbm_series,
                  "gbm_training_rows": gbm_rows, "selection_tolerance": _bt.SELECTION_TOLERANCE, "series_evaluated": len(meta), "skipped_flat_series": skipped_flat,
                  "data": "SYNTHETIC; see module docstring for what this cannot tell you"},
        "overall_mase": overall, "mase_by_train_length": by_len, "mase_by_archetype": by_kind,
        "paired_comparisons": comparisons, "oracle_best_fixed_mean_mase": round(float(np.mean(oracle)), 4),
        "pipeline_modes_by_train_length": {L: dict(v) for L, v in sorted(modes.items())},
        "pipeline_selected_method_counts": dict(sorted(chosen.items(), key=lambda kv: -kv[1])),
        "interval_coverage_by_step": cov, "interval_coverage_by_train_length": cov_len, "nominal_coverage": level,
        "mean_pipeline_latency_ms_by_train_length": lat,
    }


def render_markdown(r: dict) -> str:
    s = r["setup"]
    o = r["overall_mase"]
    order = sorted(o, key=lambda n: o[n].get("mean_mase", 9e9))
    lines = [
        "# Phase 6 forecast evaluation (synthetic data)", "",
        f"{s['series_evaluated']} series (train lengths {s['train_lengths']}), 3-month holdout, seed {s['seed']}. "
        "**Synthetic, same-author archetypes: a check of behaviour under assumptions, not a measure of real-world accuracy.** "
        "`gbm_eval_only` is pooled over other synthetic series from the same archetypes (in-distribution, so it is flattered) and is never used for real users.", "",
        "## Mean MASE over the holdout (lower is better; 1.0 = in-sample 'repeat last month')", "",
        "| method | series | mean MASE | median MASE |", "|---|---:|---:|---:|",
    ]
    for n in order:
        lines.append(f"| {n} | {o[n]['n']} | {o[n].get('mean_mase', '-')} | {o[n].get('median_mase', '-')} |")
    lines += ["", "*Series counts differ because a method only runs when the history is long enough (e.g. `ets_seasonal` needs 36 training months). "
              "Compare methods with different counts through the by-length table or the paired comparisons, not this column alone.*", "",
              f"Hindsight oracle (best eligible fixed method per series, unattainable): **{r['oracle_best_fixed_mean_mase']}**", "",
              "## Paired differences (negative = first method better)", "",
              "| a | b | n | mean diff | 95% bootstrap CI | a better on |", "|---|---|---:|---:|---|---:|"]
    for c in r["paired_comparisons"]:
        lines.append(f"| {c['a']} | {c['b']} | {c['n']} | {c['mean_diff_mase_a_minus_b']} | [{c['ci95'][0]}, {c['ci95'][1]}] | {c['a_better_share']:.0%} |")
    lines += ["", "## Mean MASE by archetype", "", "| archetype | naive | moving_average_3 | median_12 | auto | gbm_eval_only |", "|---|---:|---:|---:|---:|---:|"]
    for k, v in r["mase_by_archetype"].items():
        lines.append(f"| {k} | " + " | ".join(str(v[m].get("mean_mase", "-")) for m in ("naive", "moving_average_3", "median_12", "auto", "gbm_eval_only")) + " |")
    lines += ["", "## Mean MASE by training length", "", "| train months | naive | median_12 | auto | gbm_eval_only |", "|---:|---:|---:|---:|---:|"]
    for L, v in r["mase_by_train_length"].items():
        lines.append(f"| {L} | " + " | ".join(str(v[m].get("mean_mase", "-")) for m in ("naive", "median_12", "auto", "gbm_eval_only")) + " |")
    lines += ["", f"## Interval coverage (nominal {r['nominal_coverage']:.0%})", "", "| step | intervals | observed coverage |", "|---:|---:|---:|"]
    for k, v in r["interval_coverage_by_step"].items():
        lines.append(f"| {k} | {v['n']} | {v['coverage']:.1%} |")
    lines += ["", "| train months | intervals | observed coverage |", "|---:|---:|---:|"]
    for L, v in r["interval_coverage_by_train_length"].items():
        lines.append(f"| {L} | {v['n']} | {v['coverage']:.1%} |")
    lines += ["", "## Methods the pipeline selected", "", ", ".join(f"{k}: {v}" for k, v in r["pipeline_selected_method_counts"].items()),
              "", "## Mean pipeline latency (ms, this machine, one series)", "", ", ".join(f"{L} months: {v}" for L, v in r["mean_pipeline_latency_ms_by_train_length"].items()), ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series-per-length", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--gbm-series", type=int, default=600)
    ap.add_argument("--out-dir", default="docs/forecast_eval")
    ap.add_argument("--tolerance", type=float, default=None, help="override the selection tie-break band (sensitivity analysis)")
    a = ap.parse_args()
    t0 = time.time()
    r = evaluate(a.series_per_length, a.seed, a.gbm_series, tolerance=a.tolerance)
    r["setup"]["wall_seconds"] = round(time.time() - t0, 1)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(r, indent=2, default=str))
    (out / "report.md").write_text(render_markdown(r))
    print(render_markdown(r))


if __name__ == "__main__":
    main()
