import uuid

from pydantic import BaseModel, Field


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_id: uuid.UUID | None = None


class CategoryRead(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    is_system: bool

    model_config = {"from_attributes": True}
