from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

# Argon2id (pwdlib's default) — memory-hard, current OWASP recommendation.
# Deliberately not passlib/bcrypt: see requirements.txt comment for why.
password_hash = PasswordHash.recommended()

# Precomputed valid hash of an arbitrary password, used only to burn
# roughly the same CPU time as a real verify() when a login is attempted
# against an email that doesn't exist — this prevents response-time from
# leaking whether an email is registered. Must be a real hash (not a
# hand-written string) or verify() raises instead of returning False.
_DUMMY_HASH = password_hash.hash("not-a-real-password-timing-mitigation-only")


def hash_password(plain_password: str) -> str:
    return password_hash.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


def verify_dummy_password(plain_password: str) -> None:
    """Call this (and discard the result) when a login target doesn't exist,
    to burn comparable time to a real verify() — see _DUMMY_HASH comment."""
    password_hash.verify(plain_password, _DUMMY_HASH)


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    """
    `subject` is the user id (as a string — JWT `sub` claim must be a string,
    not a UUID object) baked into the token.
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes if expires_minutes is not None else settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expire, "iat": datetime.now(timezone.utc)}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """
    Raises jwt.PyJWTError (ExpiredSignatureError, InvalidTokenError, etc.)
    on any failure — caller is responsible for turning that into a 401.
    """
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
