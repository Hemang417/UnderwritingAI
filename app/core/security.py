from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings

settings = get_settings()
_hasher = PasswordHasher()


def hash_password(raw_password: str) -> str:
    return _hasher.hash(raw_password)


def verify_password(raw_password: str, hashed_password: str) -> bool:
    try:
        return _hasher.verify(hashed_password, raw_password)
    except VerifyMismatchError:
        return False


def _create_token(subject: UUID, expires_delta: timedelta, token_type: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: UUID) -> str:
    return _create_token(
        user_id, timedelta(minutes=settings.jwt_access_token_minutes), "access"
    )


def create_refresh_token(user_id: UUID) -> str:
    return _create_token(
        user_id, timedelta(days=settings.jwt_refresh_token_days), "refresh"
    )


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
