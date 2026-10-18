import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class BudgetCreate(BaseModel):
    # category_id omitted/null = overall budget for the currency.
    category_id: uuid.UUID | None = None
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    # Numeric(14,2): reject extra decimal places and absurd magnitudes
    # instead of letting the DB round or overflow.
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    alert_threshold_pct: Decimal = Field(default=Decimal("80"), gt=0, le=100, max_digits=5, decimal_places=2)


class BudgetUpdate(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    alert_threshold_pct: Decimal | None = Field(default=None, gt=0, le=100, max_digits=5, decimal_places=2)
    is_active: bool | None = None


class BudgetRead(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID | None
    currency: str
    amount: Decimal
    alert_threshold_pct: Decimal
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
