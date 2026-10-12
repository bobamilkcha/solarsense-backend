import uuid
from datetime import datetime

from app.models import UserRole
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegisterRequest(BaseModel):
    """Registers a new company and its first user (company_admin) together.

    There is no public endpoint to join an *existing* company yet — that would
    need an invite flow, which is still TODO.
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
    created_at: datetime
    updated_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
