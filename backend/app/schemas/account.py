import uuid

from pydantic import BaseModel, Field

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

    model_config = {"from_attributes": True}
