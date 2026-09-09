"""Unit tests for token helpers — pure functions, no DB, no app wiring."""

import uuid

import pytest
from app.modules.auth import security


def test_access_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    token = security.create_access_token(subject=user_id)

    assert security.decode_access(token) == user_id


def test_decode_access_rejects_refresh_token() -> None:
    user_id = uuid.uuid4()
    refresh, _ = security.create_refresh_token(subject=user_id, jti=uuid.uuid4())

    with pytest.raises(security.TokenError):
        security.decode_access(refresh)


def test_valid_password_hash() -> None:
    password = "password123"
    hashed = security.hash_password(password)
    assert security.verify_password(password, hashed)


def test_invalid_password_hash() -> None:
    password = "password123"
    hashed = security.hash_password(password)
    assert not security.verify_password("wrongpassword", hashed)


def test_create_refresh_token() -> None:
    user_id = uuid.uuid4()
    jti = uuid.uuid4()
    refresh, _ = security.create_refresh_token(subject=user_id, jti=jti)
    assert security.decode_refresh(refresh) == (user_id, jti)


def test_decode_refresh_rejects_access_token() -> None:
    user_id = uuid.uuid4()
    token = security.create_access_token(subject=user_id)
    with pytest.raises(security.TokenError):
        security.decode_refresh(token)


def test_decode_access_rejects_garbage() -> None:
    with pytest.raises(security.TokenError):
        security.decode_access("not-a-jwt")


def test_decode_access_rejects_wrong_signature() -> None:
    import jwt

    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access"},
        "wrong-secret-key-that-is-at-least-32-bytes-long",
        algorithm="HS256",
    )
    with pytest.raises(security.TokenError):
        security.decode_access(forged)


def test_dummy_verify_does_not_raise() -> None:
    security.dummy_verify()
