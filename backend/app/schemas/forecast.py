from datetime import date
from decimal import Decimal

from pydantic import BaseModel

# Money fields are Decimal (serialized as strings, same as the analytics API);
# statistical fields (MAE, confidence, interval level) are floats.


class ModelScoreRead(BaseModel):
    name: str
    label: str
    status: str  # scored | ineligible | failed
    mae: float | None
    rmse: float | None
    mase: float | None
    n_errors: int
    detail: str | None

    model_config = {"from_attributes": True}


class SeriesSummaryRead(BaseModel):
    mode: str  # backtested | limited | all_zero | unavailable
    method: str | None
    interval_level: float
    history_months: int
    first_month: date | None
    last_month: date | None
    n_origins: int | None
    leaderboard: list[ModelScoreRead]
    notes: list[str]

    model_config = {"from_attributes": True}


class RecurringLineRead(BaseModel):
    merchant: str
    type: str
    cadence: str
    amount: Decimal
    on: date
    assumed_pending: bool
    amount_variable: bool
    confidence: float

    model_config = {"from_attributes": True}


class PeriodForecastRead(BaseModel):
    start: date
    end: date
    is_stub: bool
    recurring_expense: Decimal
    recurring_income: Decimal
    variable_expense: Decimal | None
    variable_income: Decimal | None
    expense: Decimal | None
    income: Decimal | None
    net: Decimal | None
    variable_expense_low: Decimal | None
    variable_expense_high: Decimal | None
    net_low: Decimal | None
    net_high: Decimal | None
    end_balance: Decimal | None
    end_balance_low: Decimal | None
    end_balance_high: Decimal | None
    recurring: list[RecurringLineRead]

    model_config = {"from_attributes": True}


class BalanceInfoRead(BaseModel):
    start_balance: Decimal | None
    accounts_with_balance: list[str]
    accounts_without_balance: list[str]
    complete: bool
    notes: list[str]

    model_config = {"from_attributes": True}


class CurrencyForecastRead(BaseModel):
    currency: str
    status: str  # ok | limited | recurring_only
    as_of: date
    horizon_months: int
    periods: list[PeriodForecastRead]
    expense_model: SeriesSummaryRead
    income_model: SeriesSummaryRead
    balance: BalanceInfoRead
    verdict: str  # covered | at_risk | shortfall | unknown
    verdict_basis: str
    verdict_period_end: date | None
    assumptions: list[str]
    warnings: list[str]

    model_config = {"from_attributes": True}


class ForecastResponse(BaseModel):
    notice: str
    currencies: list[CurrencyForecastRead]
