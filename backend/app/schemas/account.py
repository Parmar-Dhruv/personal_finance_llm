import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.db.models import AccountType


class AccountCreate(BaseModel):
    name: str
    institution: str | None = None
    account_type: AccountType
    currency: str = Field(default="USD", min_length=3, max_length=3)


class AccountRead(BaseModel):
    id: uuid.UUID
    name: str
    institution: str | None
    account_type: AccountType
    currency: str
    is_active: bool
    # Phase 6. Both null until the user sets a balance.
    opening_balance: Decimal | None = None
    balance_as_of: date | None = None

    model_config = {"from_attributes": True}


class AccountBalanceSet(BaseModel):
    """
    Signed: positive = money held, negative = money owed (a credit card with
    5,000 outstanding is -5000). `balance_as_of` is the day the balance was
    true at the END of; later transactions are added on top by the forecast.
    """

    # Numeric(14,2): reject extra decimal places, NaN/Infinity and absurd
    # magnitudes up front instead of letting the DB round or overflow.
    opening_balance: Decimal = Field(allow_inf_nan=False, max_digits=14, decimal_places=2)
    balance_as_of: date

    @field_validator("balance_as_of")
    @classmethod
    def _not_in_the_future(cls, v: date) -> date:
        # One day of slack: a user ahead of UTC (IST) entering "today" in the
        # early morning is on a date UTC hasn't reached yet. Anything further
        # out is a typo, and would silently shift every projected balance.
        if v > datetime.now(timezone.utc).date() + timedelta(days=1):
            raise ValueError("balance_as_of cannot be in the future")
        return v
