"""Integration tests for AuthService (business logic against a real DB)."""

import pytest
from app.models import RefreshToken
from app.modules.auth import security
from app.modules.auth.exceptions import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)
from app.modules.auth.schemas import UserRegisterRequest
from app.modules.auth.service import AuthService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _payload(**overrides) -> UserRegisterRequest:
    data = {"email": "svc@example.com", "password": "supersecret"}
    data.update(overrides)
    return UserRegisterRequest(**data)


async def test_register_stores_hashed_password(db: AsyncSession) -> None:
    svc = AuthService(db)
    user = await svc.register(_payload())

    assert user.id is not None
    assert user.password_hash != "supersecret"
    assert security.verify_password("supersecret", user.password_hash)


async def test_register_allows_optional_names(db: AsyncSession) -> None:
    svc = AuthService(db)
    user = await svc.register(_payload())
    assert user.first_name is None
    assert user.last_name is None


async def test_register_duplicate_email_raises(db: AsyncSession) -> None:
    svc = AuthService(db)
    await svc.register(_payload())
    with pytest.raises(EmailAlreadyExistsError):
        await svc.register(_payload())


async def test_authenticate_success(db: AsyncSession) -> None:
    svc = AuthService(db)
    await svc.register(_payload())
    user = await svc.authenticate("svc@example.com", "supersecret")
    assert user.email == "svc@example.com"


async def test_authenticate_unknown_email_raises(db: AsyncSession) -> None:
    svc = AuthService(db)
    with pytest.raises(InvalidCredentialsError):
        await svc.authenticate("nobody@example.com", "supersecret")


async def test_authenticate_wrong_password_raises(db: AsyncSession) -> None:
    svc = AuthService(db)
    await svc.register(_payload())
    with pytest.raises(InvalidCredentialsError):
        await svc.authenticate("svc@example.com", "wrong")


async def test_issue_tokens_persists_row_with_user_agent(db: AsyncSession) -> None:
    svc = AuthService(db)
    user = await svc.register(_payload())
    _, refresh = await svc.issue_tokens(user, user_agent="pytest-agent")

    _, jti = security.decode_refresh(refresh)
    row = await db.get(RefreshToken, jti)
    assert row is not None
    assert row.user_id == user.id
    assert row.user_agent == "pytest-agent"
    assert row.revoked_at is None


async def test_rotate_revokes_old_row(db: AsyncSession) -> None:
    svc = AuthService(db)
    user = await svc.register(_payload())
    _, refresh = await svc.issue_tokens(user)
    _, old_jti = security.decode_refresh(refresh)

    access, new_refresh, returned = await svc.rotate_refresh_token(refresh)
    assert returned.id == user.id
    assert new_refresh != refresh

    old_row = await db.get(RefreshToken, old_jti)
    assert old_row is not None
    assert old_row.revoked_at is not None


async def test_rotate_reuse_revokes_whole_family(db: AsyncSession) -> None:
    svc = AuthService(db)
    user = await svc.register(_payload())
    _, refresh = await svc.issue_tokens(user)

    # First rotation succeeds and revokes the original.
    _, new_refresh, _ = await svc.rotate_refresh_token(refresh)

    # Reusing the now-revoked original triggers family-wide revocation.
    with pytest.raises(InvalidRefreshTokenError):
        await svc.rotate_refresh_token(refresh)

    rows = (
        (await db.execute(select(RefreshToken).where(RefreshToken.user_id == user.id)))
        .scalars()
        .all()
    )
    assert rows
    assert all(r.revoked_at is not None for r in rows)


async def test_rotate_unknown_jti_raises(db: AsyncSession) -> None:
    svc = AuthService(db)
    user = await svc.register(_payload())
    # Valid signature, but the jti was never persisted.
    import uuid

    fake, _ = security.create_refresh_token(subject=user.id, jti=uuid.uuid4())
    with pytest.raises(InvalidRefreshTokenError):
        await svc.rotate_refresh_token(fake)


async def test_revoke_is_lenient_on_garbage(db: AsyncSession) -> None:
    svc = AuthService(db)
    # Must not raise.
    await svc.revoke_refresh_token("not-a-jwt")


async def test_revoke_marks_row_revoked(db: AsyncSession) -> None:
    svc = AuthService(db)
    user = await svc.register(_payload())
    _, refresh = await svc.issue_tokens(user)
    _, jti = security.decode_refresh(refresh)

    await svc.revoke_refresh_token(refresh)

    row = await db.get(RefreshToken, jti)
    assert row is not None
    assert row.revoked_at is not None
