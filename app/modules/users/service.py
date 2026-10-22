import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from app.core.config.app_config import app_config
from app.models import Invitation, RefreshToken, User, UserRole
from app.modules.auth import security
from app.modules.users.exceptions import (
    CannotModifySelfError,
    CannotModifySuperAdminError,
    EmailAlreadyRegisteredError,
    InvitationNotFoundError,
    UserNotFoundError,
)
from app.modules.users.schemas import InvitationCreateRequest, UserUpdateRequest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


def _is_super(user: User) -> bool:
    return user.role == UserRole.SUPER_ADMIN


class UsersService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_users(self, company_id: uuid.UUID | None) -> Sequence[User]:
        """`company_id=None` lists every user (super_admin only)."""
        stmt = select(User).order_by(User.created_at)
        if company_id is not None:
            stmt = stmt.where(User.company_id == company_id)
        return (await self.db.scalars(stmt)).all()

    async def update_user(self, actor: User, user_id: uuid.UUID, data: UserUpdateRequest) -> User:
        target = await self.db.get(User, user_id)
        if target is None or (not _is_super(actor) and target.company_id != actor.company_id):
            # Another company's user: 404, not 403, so we don't leak their existence.
            raise UserNotFoundError
        if target.id == actor.id:
            raise CannotModifySelfError
        if _is_super(target) and not _is_super(actor):
            raise CannotModifySuperAdminError

        if data.role is not None:
            target.role = data.role
        if data.is_active is not None:
            target.is_active = data.is_active
            if not data.is_active:
                # Sign them out everywhere; access tokens are rejected by
                # get_current_user's is_active check.
                await self.db.execute(
                    update(RefreshToken)
                    .where(RefreshToken.user_id == target.id, RefreshToken.revoked_at.is_(None))
                    .values(revoked_at=datetime.now(UTC))
                )

        await self.db.commit()
        await self.db.refresh(target)
        return target

    async def create_invitation(
        self, actor: User, data: InvitationCreateRequest
    ) -> tuple[Invitation, str]:
        """Returns the invitation and its raw token (not stored anywhere)."""
        if await self.db.scalar(select(User).where(User.email == data.email)):
            raise EmailAlreadyRegisteredError

        now = datetime.now(UTC)
        # Re-inviting the same email replaces the old invite, so only the
        # newest link works.
        await self.db.execute(
            update(Invitation)
            .where(
                Invitation.company_id == actor.company_id,
                Invitation.email == data.email,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

        raw_token, token_hash = security.generate_invite_token()
        invitation = Invitation(
            company_id=actor.company_id,
            email=data.email,
            role=data.role,
            token_hash=token_hash,
            invited_by_id=actor.id,
            expires_at=now + timedelta(days=app_config.INVITATION_EXPIRE_DAYS),
        )
        self.db.add(invitation)
        await self.db.commit()
        await self.db.refresh(invitation)
        return invitation, raw_token

    async def list_pending_invitations(self, company_id: uuid.UUID | None) -> Sequence[Invitation]:
        stmt = (
            select(Invitation)
            .where(
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > datetime.now(UTC),
            )
            .order_by(Invitation.created_at.desc())
        )
        if company_id is not None:
            stmt = stmt.where(Invitation.company_id == company_id)
        return (await self.db.scalars(stmt)).all()

    async def revoke_invitation(
        self, company_id: uuid.UUID | None, invitation_id: uuid.UUID
    ) -> None:
        invitation = await self.db.get(Invitation, invitation_id)
        if (
            invitation is None
            or (company_id is not None and invitation.company_id != company_id)
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
        ):
            raise InvitationNotFoundError

        invitation.revoked_at = datetime.now(UTC)
        await self.db.commit()
