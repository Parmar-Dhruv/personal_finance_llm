"""The evaluation harness is shipped code: keep it runnable and deterministic (tiny corpus, a few seconds)."""

import numpy as np

from app.forecast import backtest as bt
from app.forecast import eval as fe


def test_synthetic_series_are_nonnegative_finite_and_deterministic():
    for kind in fe.ARCHETYPES:
        a = fe.make_series(np.random.default_rng(1), kind, 30)
        b = fe.make_series(np.random.default_rng(1), kind, 30)
        assert np.array_equal(a, b) and a.shape == (30,)
        assert np.all(np.isfinite(a)) and np.all(a >= 0)


def test_evaluate_runs_end_to_end_and_is_reproducible():
    before = bt.SELECTION_TOLERANCE
    r1 = fe.evaluate(per_length=2, seed=3, gbm_series=30)
    r2 = fe.evaluate(per_length=2, seed=3, gbm_series=30)
    assert r1["overall_mase"] == r2["overall_mase"]  # same seed, same numbers
    assert r1["setup"]["series_evaluated"] == 10 and r1["setup"]["selection_tolerance"] == before
    assert {"auto", "naive", "ets_ann", "gbm_eval_only"} <= set(r1["overall_mase"])
    assert r1["overall_mase"]["auto"]["n"] == 10
    assert "SYNTHETIC" in r1["setup"]["data"]
    md = fe.render_markdown(r1)
    assert "Interval coverage" in md and "synthetic" in md.lower()


def test_tolerance_override_is_a_sensitivity_switch_only():
    original = bt.SELECTION_TOLERANCE
    try:
        r = fe.evaluate(per_length=1, seed=3, gbm_series=30, tolerance=0.0)
        assert r["setup"]["selection_tolerance"] == 0.0
    finally:
        bt.SELECTION_TOLERANCE = original  # the override is a module-level patch: never leak it into other tests
    assert bt.SELECTION_TOLERANCE == 0.02
