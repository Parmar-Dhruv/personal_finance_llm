"""
Read-only forecast endpoint. Thin: parse + authorize, then delegate to
app/forecast/ (no HTTP knowledge there, so Phase 8's agent can reuse it).

Computed on demand, nothing is stored: a forecast is a pure function of the
transactions, the user's balances and the parameters, so persisting one would
only create something that goes stale on the next upload. The response carries
its own assumptions and model leaderboard instead.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_owned_account
from app.db.base import get_db
from app.db.models import User
from app.forecast.engine import MAX_HORIZON_MONTHS, NOTICE, forecast_cashflow
from app.schemas.forecast import ForecastResponse

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/cashflow", response_model=ForecastResponse)
def get_cashflow_forecast(
    horizon_months: int = Query(default=3, ge=1, le=MAX_HORIZON_MONTHS, description="Full months to forecast after the current one"),
    interval_level: float = Query(default=0.8, ge=0.5, le=0.95, description="Nominal coverage of the intervals"),
    as_of: date | None = Query(default=None, description="Ignore transactions after this date (what-if / backtesting)"),
    account_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Per-currency income/expense/net forecast and, where every account in the
    currency has a balance set (PUT /accounts/{id}/balance), the projected
    period-end balance with an interval and a covered/at_risk/shortfall verdict.
    Decision support, not advice: read `assumptions` and `warnings`.
    """
    if account_id is not None:
        get_owned_account(db, current_user, account_id)  # 404 if not theirs
    try:
        currencies = forecast_cashflow(
            db, current_user.id, horizon_months=horizon_months, account_id=account_id,
            as_of=as_of, interval_level=interval_level,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return {"notice": NOTICE, "currencies": currencies}
