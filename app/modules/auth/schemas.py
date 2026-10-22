import uuid
from datetime import datetime

from app.models import UserRole
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegisterRequest(BaseModel):
    """Registers a new company and its first user (company_admin) together.

    To join an *existing* company, a company_admin creates an invitation
    (`POST /users/invitations`) and the invitee accepts it
    (`POST /auth/invitations/accept`).
    """

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    company_name: str = Field(min_length=1, max_length=200)
    first_name: str | None = None
    last_name: str | None = None


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_id: uuid.UUID
    role: UserRole
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None
    email_verified: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class InvitationTokenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class InvitationPreviewResponse(BaseModel):
    """What an invitee sees before accepting: who invited them, as what."""

    email: EmailStr
    role: UserRole
    company_name: str
    expires_at: datetime


class AcceptInvitationRequest(InvitationTokenRequest):
    # Email and role come from the invitation, not the request.
    password: str = Field(min_length=8, max_length=128)
    first_name: str | None = None
    last_name: str | None = None
