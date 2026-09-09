import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from app.core.config.app_config import app_config
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# Pre-computed hash used to equalize response time when a user is not found,
# preventing a timing oracle that would otherwise leak email existence.
_DUMMY_HASH = _hasher.hash("dummy-password-for-constant-time-verify")


class TokenError(Exception):
    """Raised when a token is malformed, expired, or of the wrong type."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
        return True
    except VerifyMismatchError, InvalidHashError, VerificationError:
        return False


def dummy_verify() -> None:
    """Run a throwaway verification to keep auth timing constant."""
    verify_password("dummy", _DUMMY_HASH)


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def create_access_token(subject: uuid.UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "iat": now,
        "exp": now + timedelta(minutes=app_config.ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }

    return jwt.encode(payload, app_config.SECRET_KEY, algorithm=app_config.JWT_ALGORITHM)


def create_refresh_token(subject: uuid.UUID, jti: uuid.UUID) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=app_config.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(subject),
        "iat": now,
        "exp": expires_at,
        "jti": str(jti),
        "type": "refresh",
    }
    token = jwt.encode(payload, app_config.SECRET_KEY, algorithm=app_config.JWT_ALGORITHM)
    return token, expires_at


def _decode(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, app_config.SECRET_KEY, algorithms=[app_config.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError("Could not decode token") from exc

    if payload.get("type") != expected_type:
        raise TokenError(f"Expected {expected_type} token")

    return payload


def decode_access(token: str) -> uuid.UUID:
    """Validate an access token and return its subject (user id)."""
    payload = _decode(token, "access")
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise TokenError("Invalid access token subject") from exc


def decode_refresh(token: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Validate a refresh token and return (user_id, jti)."""
    payload = _decode(token, "refresh")
    try:
        return uuid.UUID(payload["sub"]), uuid.UUID(payload["jti"])
    except (KeyError, ValueError) as exc:
        raise TokenError("Invalid refresh token claims") from exc
