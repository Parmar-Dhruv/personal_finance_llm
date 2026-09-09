from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_dummy_password, verify_password
from app.db.base import get_db
from app.db.models import User
from app.schemas.auth import Token, UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def signup(payload: UserCreate, db: Session = Depends(get_db)) -> User:
    user = User(
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Deliberately vague: confirming "email already exists" to an
        # unauthenticated caller lets an attacker enumerate registered
        # emails. Same message either way.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not create account")
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> Token:
    # OAuth2PasswordRequestForm uses `username` as the field name regardless
    # of what you're actually authenticating with — here that's the email.
    user = db.query(User).filter(User.email == form_data.username.lower()).first()

    # Verify against a fixed dummy hash when the user doesn't exist, so
    # login takes roughly the same time either way — otherwise response
    # timing leaks whether an email is registered.
    if user is None:
        verify_dummy_password(form_data.password)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    access_token = create_access_token(subject=str(user.id))
    return Token(access_token=access_token)


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user
