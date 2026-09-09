import uuid
from datetime import UTC, datetime

from app.models import RefreshToken, User
from app.modules.auth import security
from app.modules.auth.exceptions import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)
from app.modules.auth.schemas import UserRegisterRequest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def register(self, data: UserRegisterRequest) -> User:
        existing = await self.db.scalar(select(User).where(User.email == data.email))

        if existing:
            raise EmailAlreadyExistsError

        user = User(
            email=data.email,
            password_hash=security.hash_password(data.password),
            first_name=data.first_name,
            last_name=data.last_name,
        )

        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        return user

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.db.scalar(select(User).where(User.email == email))

        if user is None:
            # Equalize timing with the found-user path to avoid leaking existence.
            security.dummy_verify()
            raise InvalidCredentialsError

        if not security.verify_password(password, user.password_hash):
            raise InvalidCredentialsError

        # TODO: Ensure that the email is verified. Pending mailtrap integration.

        if security.needs_rehash(user.password_hash):
            user.password_hash = security.hash_password(password)
            await self.db.commit()

        return user

    async def issue_tokens(self, user: User, user_agent: str | None = None) -> tuple[str, str]:
        access = security.create_access_token(subject=user.id)
        jti = uuid.uuid4()
        refresh, expires_at = security.create_refresh_token(subject=user.id, jti=jti)

        self.db.add(
            RefreshToken(
                jti=jti,
                user_id=user.id,
                expires_at=expires_at,
                user_agent=user_agent,
            )
        )

        await self.db.commit()

        return access, refresh

    async def rotate_refresh_token(
        self, raw_token: str, user_agent: str | None = None
    ) -> tuple[str, str, User]:
        try:
            user_id, jti = security.decode_refresh(raw_token)
        except security.TokenError as err:
            raise InvalidRefreshTokenError from err

        row = await self.db.get(RefreshToken, jti)

        if row is None:
            raise InvalidRefreshTokenError

        if row.revoked_at is not None:
            # Reuse of an already-rotated token: revoke the whole family.
            await self._revoke_all_for_user(user_id)
            raise InvalidRefreshTokenError

        user = await self.db.get(User, user_id)

        if user is None:
            raise InvalidRefreshTokenError

        # Stage the revocation and let issue_tokens commit both in one transaction
        # so rotation is atomic.
        row.revoked_at = datetime.now(UTC)

        access, refresh = await self.issue_tokens(user, user_agent)
        return access, refresh, user

    async def revoke_refresh_token(self, raw_token: str) -> None:
        try:
            _, jti = security.decode_refresh(raw_token)
        except security.TokenError:
            return  # Logout is idempotent and lenient.

        row = await self.db.get(RefreshToken, jti)
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            await self.db.commit()

    async def _revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await self.db.commit()
