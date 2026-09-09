import uuid

from pydantic import BaseModel, EmailStr, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        # Deliberately minimal — length is the single strongest predictor of
        # crack resistance. Composition rules (must-have-symbol, etc.) push
        # users toward predictable patterns and are no longer recommended
        # (NIST SP 800-63B). Argon2id handles the rest.
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserRead(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    is_active: bool

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
