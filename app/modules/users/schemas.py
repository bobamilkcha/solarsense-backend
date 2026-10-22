import uuid
from datetime import datetime
from typing import Literal

from app.models import UserRole
from pydantic import BaseModel, ConfigDict, EmailStr

# Roles a company admin can hand out; super_admin is platform-level only.
AssignableRole = Literal[UserRole.INSTALLER, UserRole.COMPANY_ADMIN]


class InvitationCreateRequest(BaseModel):
    email: EmailStr
    role: AssignableRole = UserRole.INSTALLER


class InvitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_id: uuid.UUID
    email: EmailStr
    role: UserRole
    invited_by_id: uuid.UUID | None
    expires_at: datetime
    created_at: datetime


class InvitationCreatedResponse(InvitationResponse):
    # Shown only once. The frontend builds the invite link from it, e.g.
    # https://<frontend>/accept-invite?token=<token>
    token: str


class UserUpdateRequest(BaseModel):
    role: AssignableRole | None = None
    is_active: bool | None = None
