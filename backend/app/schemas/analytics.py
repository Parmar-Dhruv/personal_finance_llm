import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from app.analytics.budgets import BudgetStatus
from app.db.models import TransactionType

# All money is Decimal and serializes as a JSON *string* (e.g. "1250.50"),
# same as TransactionRead — never a float, so clients can't lose cents.


class SummaryRead(BaseModel):
    currency: str
    income: Decimal
    expense: Decimal
    net: Decimal
    income_count: int
    expense_count: int
    savings_rate_pct: Decimal | None

    model_config = {"from_attributes": True}


class MonthPointRead(BaseModel):
    month: date
    income: Decimal
    expense: Decimal
    net: Decimal
    transaction_count: int
    partial: bool
    income_change: Decimal | None
    income_change_pct: Decimal | None
    expense_change: Decimal | None
    expense_change_pct: Decimal | None
    net_change: Decimal | None

    model_config = {"from_attributes": True}


class MonthlyRead(BaseModel):
    currency: str
    months: list[MonthPointRead]

    model_config = {"from_attributes": True}


class BreakdownRowRead(BaseModel):
    key_id: uuid.UUID | None
    label: str
    total: Decimal
    transaction_count: int
    pct_of_total: Decimal | None

    model_config = {"from_attributes": True}


class BreakdownRead(BaseModel):
    currency: str
    transaction_type: TransactionType
    total: Decimal
    rows: list[BreakdownRowRead]
    other_total: Decimal
    other_count: int

    model_config = {"from_attributes": True}


class AccountSummaryRead(BaseModel):
    account_id: uuid.UUID
    account_name: str
    currency: str
    income: Decimal
    expense: Decimal
    net: Decimal
    income_count: int
    expense_count: int

    model_config = {"from_attributes": True}


class BudgetUtilizationRead(BaseModel):
    budget_id: uuid.UUID
    category_id: uuid.UUID | None
    category_name: str | None
    currency: str
    limit: Decimal
    spent: Decimal
    remaining: Decimal
    pct_used: Decimal
    alert_threshold_pct: Decimal
    status: BudgetStatus
    transaction_count: int

    model_config = {"from_attributes": True}


class UtilizationResponse(BaseModel):
    period_start: date
    period_end: date
    budgets: list[BudgetUtilizationRead]
