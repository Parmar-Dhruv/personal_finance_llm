"""
Phase 6: cash-flow forecasting.

Layering mirrors app/analytics and app/ml: nothing in this package imports
FastAPI, so Phase 8's agent can wrap `engine.forecast_cashflow` as a tool.

    methods.py   point-forecast methods for ONE short monthly series (pure)
    backtest.py  rolling-origin evaluation, model selection, intervals (pure)
    schedule.py  projects detected recurring payments onto dates (pure)
    history.py   loads transactions, builds the clean monthly series (DB edge)
    engine.py    puts it together per currency (pure core + thin DB wrapper)

Money is Decimal everywhere except inside methods.py/backtest.py, which
*estimate* and so use floats; values cross back to Decimal, rounded to cents,
only in engine.py.
"""
