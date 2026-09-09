"""Unit tests for auth exception metadata (drives the global handler)."""

from app.modules.auth.exceptions import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)
from fastapi import status


def test_status_codes() -> None:
    assert EmailAlreadyExistsError().status_code == status.HTTP_409_CONFLICT
    assert InvalidCredentialsError().status_code == status.HTTP_401_UNAUTHORIZED
    assert InvalidRefreshTokenError().status_code == status.HTTP_401_UNAUTHORIZED


def test_default_detail() -> None:
    assert EmailAlreadyExistsError().detail == "Email already exists"
    assert InvalidCredentialsError().detail == "Invalid credentials"


def test_custom_detail_overrides_default() -> None:
    err = EmailAlreadyExistsError("custom message")
    assert err.detail == "custom message"
    assert str(err) == "custom message"
