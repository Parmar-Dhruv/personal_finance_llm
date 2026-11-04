"""
Rolling-origin backtest, model selection and prediction intervals for one
short monthly series. Pure (numpy only); the methods themselves are in
methods.py.

Why rolling origin and not one train/test split: personal series are 3-36
points, and a single split leaves a test set of 2-6 points. Rolling the
forecast origin through the history reuses every point as a test point
(Hyndman, "Time series cross-validation"). Each origin trains on everything
before it and records the 1..h step-ahead errors.

Selection rule, stated plainly because it is the part most likely to be wrong:
 * every contestant is scored on the SAME origins (otherwise a model that
   needs 10 months of history is compared on easier, later origins than the
   one that needs 3);
 * a model may only enter if it can be scored on at least
   min(PREFERRED_ORIGINS, n - 3) origins, floor MIN_ORIGINS. That is why ETS
   only appears from about 14 months of history;
 * the lowest MAE wins, but anything within SELECTION_TOLERANCE of the best
   MAE ties and the SIMPLEST tied model is taken. The 2% band is a tie-break
   convention, not a tuned value.
Picking the best of several models on a handful of errors is optimistic in
principle (the winner's backtest MAE understates its future error, which would
make the intervals too narrow). eval.py measures this on synthetic series and
finds observed coverage close to nominal (about 77-84% against 80%); that is
evidence about those synthetic archetypes, not about real spending, and it
covers single-series intervals only (the combined net/balance intervals built
in engine.py are not validated by it).

Intervals are split-conformal style: the half-width at step k is an empirical
quantile of the selected model's own absolute backtest errors at that step.
No distribution is assumed. With few errors the quantile is capped at the
largest observed error and labelled as such.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.forecast.methods import BY_NAME, LIMITED_METHOD, METHODS, Method

MIN_HISTORY = 3  # below this no variable forecast is made at all
MIN_BACKTEST_OBS = 7  # below this: limited mode (no selection, no intervals)
MIN_ORIGINS = 4
PREFERRED_ORIGINS = 8
MIN_INTERVAL_ERRORS = 5
SELECTION_TOLERANCE = 0.02
FEW_ORIGINS_WARNING = 8


@dataclass
class ModelScore:
    name: str
    label: str
    status: str  # scored | ineligible | failed
    mae: float | None = None
    rmse: float | None = None
    # MAE divided by the series' own one-step naive MAE; < 1 beats "repeat last month".
    mase: float | None = None
    n_errors: int = 0
    detail: str | None = None


@dataclass
class Backtest:
    horizon: int
    n_obs: int
    first_origin: int | None
    n_origins: int
    scale: float | None
    scores: list[ModelScore]
    selected: str | None
    # step -> signed errors (actual - forecast) of the SELECTED model only
    selected_errors: dict[int, list[float]]


def _target_origins(n: int) -> int:
    return max(MIN_ORIGINS, min(PREFERRED_ORIGINS, n - 3))


def run_backtest(y, horizon: int, methods: tuple[Method, ...] = METHODS) -> Backtest:
    y = np.asarray(y, dtype=float)
    n = len(y)
    scale = float(np.mean(np.abs(np.diff(y)))) if n >= 2 else None
    target = _target_origins(n)

    scores: dict[str, ModelScore] = {}
    contestants: list[Method] = []
    for m in methods:
        if n - m.min_train >= target:
            contestants.append(m)
        else:
            scores[m.name] = ModelScore(
                m.name, m.label, "ineligible",
                detail=f"needs {m.min_train + target} months of history to be scored on {target} origins; have {n}",
            )
    if not contestants:
        return Backtest(horizon, n, None, 0, scale, list(scores.values()), None, {})

    t0 = max(m.min_train for m in contestants)  # common first origin for everyone
    errors: dict[str, dict[int, list[float]]] = {m.name: {} for m in contestants}
    alive = {m.name: m for m in contestants}
    for t in range(t0, n):
        steps = min(horizon, n - t)
        for name, m in list(alive.items()):
            try:
                fc = m.forecast(y[:t], steps)
            except Exception as exc:  # noqa: BLE001 - third-party fits fail in many ways; recorded, not hidden
                scores[name] = ModelScore(name, m.label, "failed", detail=f"{type(exc).__name__}: {exc}")
                del alive[name]
                continue
            for k in range(1, steps + 1):
                errors[name].setdefault(k, []).append(float(y[t + k - 1] - fc[k - 1]))

    for name, m in alive.items():
        flat = np.array([e for errs in errors[name].values() for e in errs])
        mae = float(np.mean(np.abs(flat)))
        scores[name] = ModelScore(
            name, m.label, "scored", mae=mae, rmse=float(np.sqrt(np.mean(flat**2))),
            mase=(mae / scale) if scale else None, n_errors=len(flat),
        )

    ranked = rank_models([s for s in scores.values() if s.status == "scored"])
    selected = ranked[0] if ranked else None
    ordered = [scores[m.name] for m in methods if m.name in scores]
    return Backtest(
        horizon, n, t0, n - t0, scale, ordered, selected,
        errors[selected] if selected else {},
    )


def rank_models(scored: list[ModelScore]) -> list[str]:
    """Preference order: the simplest model within SELECTION_TOLERANCE of the best MAE first."""
    if not scored:
        return []
    best = min(s.mae for s in scored)
    band = [s for s in scored if s.mae <= best * (1 + SELECTION_TOLERANCE) + 1e-9]
    rest = [s for s in scored if s not in band]
    key = lambda s: (BY_NAME[s.name].complexity, s.mae, s.name)  # noqa: E731
    return [s.name for s in sorted(band, key=key)] + [s.name for s in sorted(rest, key=lambda s: (s.mae, s.name))]


def conformal_halfwidth(abs_errors: list[float], level: float) -> tuple[float, bool]:
    """Empirical (m+1)-adjusted quantile; second value True when capped at the max error."""
    s = sorted(abs_errors)
    rank = math.ceil((len(s) + 1) * level)
    if rank > len(s):
        return s[-1], True
    return s[rank - 1], False


def interval_halfwidths(
    errors: dict[int, list[float]], max_step: int, level: float
) -> list[tuple[float | None, str | None]]:
    """
    One (half_width, basis) per step 1..max_step. A step with fewer than
    MIN_INTERVAL_ERRORS backtest errors borrows the nearest shorter step's width
    (labelled; real error usually grows with horizon, so a borrowed interval is
    too narrow, not too wide). Before any step qualifies, no interval at all.
    """
    out: list[tuple[float | None, str | None]] = []
    last: tuple[int, float] | None = None
    for k in range(1, max_step + 1):
        errs = [abs(e) for e in errors.get(k, [])]
        if len(errs) >= MIN_INTERVAL_ERRORS:
            hw, capped = conformal_halfwidth(errs, level)
            out.append((hw, f"backtest_step_{k}" + ("_capped_at_max_error" if capped else "")))
            last = (k, hw)
        elif last is not None:
            out.append((last[1], f"borrowed_from_step_{last[0]}"))
        else:
            out.append((None, None))
    return out


@dataclass
class SeriesForecast:
    mode: str  # backtested | limited | all_zero | unavailable
    method: str | None
    point: list[float] | None
    half_width: list[float | None]
    interval_basis: list[str | None]
    level: float
    backtest: Backtest | None
    notes: list[str]


def forecast_series(y, steps: int, level: float = 0.8) -> SeriesForecast:
    y = np.asarray(y, dtype=float)
    n = len(y)
    none_hw: list[float | None] = [None] * steps
    none_basis: list[str | None] = [None] * steps

    if n < MIN_HISTORY:
        return SeriesForecast(
            "unavailable", None, None, none_hw, none_basis, level, None,
            [f"only {n} usable month(s) of history; at least {MIN_HISTORY} are needed"],
        )
    if not np.any(y):
        return SeriesForecast(
            "all_zero", "all_zero", [0.0] * steps, [0.0] * steps, ["history_is_all_zero"] * steps, level, None,
            ["every usable month is 0, so 0 is forecast"],
        )

    def limited(note: str) -> SeriesForecast:
        pt = BY_NAME[LIMITED_METHOD].forecast(y, steps)
        return SeriesForecast("limited", LIMITED_METHOD, [float(v) for v in pt], none_hw, none_basis, level, None, [note])

    if n < MIN_BACKTEST_OBS:
        return limited(
            f"{n} months is too few to backtest (need {MIN_BACKTEST_OBS}); using the last-3-month average, no interval"
        )

    bt = run_backtest(y, steps)
    if bt.selected is None:
        return limited("no model could be scored; using the last-3-month average, no interval")
    try:
        pt = BY_NAME[bt.selected].forecast(y, steps)  # refit on ALL history
    except Exception as exc:  # noqa: BLE001
        return limited(f"{bt.selected} scored well but failed on the full history ({type(exc).__name__}); fell back")

    notes: list[str] = []
    if bt.n_origins < FEW_ORIGINS_WARNING:
        notes.append(f"only {bt.n_origins} backtest origins; model choice and intervals are weakly supported")
    hws = interval_halfwidths(bt.selected_errors, steps, level)
    if hws[0][0] is None:
        notes.append("too few backtest errors for an interval; point forecast only")
    return SeriesForecast(
        "backtested", bt.selected, [float(v) for v in pt],
        [h for h, _ in hws], [b for _, b in hws], level, bt, notes,
    )
