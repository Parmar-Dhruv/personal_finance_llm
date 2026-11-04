"""
Point-forecast methods for ONE short, regularly spaced monthly series.

Floats on purpose: this layer estimates. Money arithmetic (balances, recurring
sums, API output) stays Decimal everywhere else.

The menu is deliberately small. A personal monthly series is 3-36 points long,
and every extra candidate is another chance for a model to win a backtest by
luck. Each method states the shortest history it may be used on; seasonal ETS
needs three full years because a 12-period seasonal state spends m-1 degrees of
freedom (Hyndman, "Fitting models to short time series") -- on 24 points that
is more parameters than the data can support, so it is not offered there.

Every method returns h non-negative numbers: spending and income cannot be
negative, so negative extrapolations are clipped to 0 (and the backtest scores
the clipped values, so what is selected is what is shipped).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Callable

import numpy as np

SEASON = 12  # monthly data, yearly seasonality


class MethodFailed(Exception):
    """A fit that did not converge or produced non-finite numbers. Never silent:
    the backtest records it on the model's leaderboard row."""


def _naive(y: np.ndarray, h: int) -> np.ndarray:
    return np.full(h, y[-1])


def _moving_average(k: int) -> Callable[[np.ndarray, int], np.ndarray]:
    def fn(y: np.ndarray, h: int) -> np.ndarray:
        return np.full(h, float(np.mean(y[-k:])))

    return fn


def _median_12(y: np.ndarray, h: int) -> np.ndarray:
    # Robust to a one-off big month (an annual premium, a trip) that drags a mean.
    return np.full(h, float(np.median(y[-12:])))


def _drift(y: np.ndarray, h: int) -> np.ndarray:
    # Extrapolates the average slope of the WHOLE history; noisy on short series,
    # included because it is the standard trend benchmark, not because it is
    # expected to win often.
    slope = (y[-1] - y[0]) / (len(y) - 1)
    return y[-1] + slope * np.arange(1, h + 1)


def _seasonal_naive(y: np.ndarray, h: int) -> np.ndarray:
    # Same month last year; needs a full year of history.
    return y[len(y) - SEASON + (np.arange(h) % SEASON)]


def _ets(trend: str | None, damped: bool, seasonal: str | None) -> Callable[[np.ndarray, int], np.ndarray]:
    def fn(y: np.ndarray, h: int) -> np.ndarray:
        # Imported lazily: statsmodels is a heavy import and only ETS needs it.
        from statsmodels.tools.sm_exceptions import ConvergenceWarning
        from statsmodels.tsa.exponential_smoothing.ets import ETSModel

        # Additive errors only: multiplicative ETS needs strictly positive data,
        # and a month with no variable income is legitimate here.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model = ETSModel(
                np.asarray(y, dtype=float),
                error="add",
                trend=trend,
                damped_trend=damped,
                seasonal=seasonal,
                seasonal_periods=SEASON if seasonal else None,
            )
            res = model.fit(disp=False)
            fc = np.asarray(res.forecast(h), dtype=float)
        # Only convergence trouble disqualifies a fit. Treating *every* warning as
        # failure would let a library deprecation notice silently remove ETS.
        if any(issubclass(w.category, ConvergenceWarning) for w in caught):
            raise MethodFailed("optimizer did not converge")
        if not np.all(np.isfinite(fc)):
            raise MethodFailed("non-finite forecast")
        return fc

    return fn


@dataclass(frozen=True)
class Method:
    name: str
    label: str
    min_train: int  # fewest observations the method may be fit on
    complexity: int  # tie-break: simpler wins when scores are close
    _fn: Callable[[np.ndarray, int], np.ndarray]

    def forecast(self, y: np.ndarray, h: int) -> np.ndarray:
        out = np.maximum(np.asarray(self._fn(np.asarray(y, dtype=float), h), dtype=float), 0.0)
        if out.shape != (h,) or not np.all(np.isfinite(out)):
            raise MethodFailed("method returned an unusable forecast")
        return out


METHODS: tuple[Method, ...] = (
    Method("naive", "Last month repeated", 2, 0, _naive),
    Method("moving_average_3", "Average of last 3 months", 3, 1, _moving_average(3)),
    Method("median_12", "Median of last 12 months", 3, 1, _median_12),
    Method("moving_average_6", "Average of last 6 months", 6, 2, _moving_average(6)),
    Method("drift", "Linear drift from first to last month", 4, 3, _drift),
    Method("seasonal_naive", "Same month last year", SEASON, 3, _seasonal_naive),
    Method("ets_ann", "Exponential smoothing (level)", 6, 4, _ets(None, False, None)),
    Method("ets_damped_trend", "Exponential smoothing (damped trend)", 10, 5, _ets("add", True, None)),
    Method("ets_seasonal", "Exponential smoothing (seasonal)", 3 * SEASON, 6, _ets(None, False, "add")),
)

BY_NAME: dict[str, Method] = {m.name: m for m in METHODS}

# What is used when there is too little history to backtest anything.
LIMITED_METHOD = "moving_average_3"
