import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.base import get_db
from app.db.models import Account, Category, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise CREDENTIALS_EXCEPTION
    except jwt.PyJWTError:
        raise CREDENTIALS_EXCEPTION

    try:
        user_uuid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise CREDENTIALS_EXCEPTION

    user = db.get(User, user_uuid)
    if user is None:
        raise CREDENTIALS_EXCEPTION
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    return user


# --- ownership helpers -------------------------------------------------
# Not-found and not-yours both return 404 (never 403) so the API doesn't
# reveal which IDs exist — same policy as the documents/transactions APIs.


def get_owned_account(db: Session, user: User, account_id: uuid.UUID) -> Account:
    account = db.get(Account, account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


def get_visible_category(db: Session, user: User, category_id: uuid.UUID) -> Category:
    """A category the user may use: a system one (user_id NULL) or their own."""
    category = db.get(Category, category_id)
    if category is None or (category.user_id is not None and category.user_id != user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return category
