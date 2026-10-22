import uuid
from typing import Annotated

from app.core.deps import DBSession
from app.models import User, UserRole
from app.modules.auth import security
from app.modules.auth.exceptions import ForbiddenError
from app.modules.auth.service import AuthService
from fastapi import Depends, status
from fastapi.exceptions import HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: DBSession,
) -> User:
    cred_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        user_id = security.decode_access(credentials.credentials)
    except security.TokenError as err:
        raise cred_exception from err

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise cred_exception

    return user


def get_auth_service(db: DBSession) -> AuthService:
    return AuthService(db)


CurrentUser = Annotated[User, Depends(get_current_user)]

AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def require_roles(*roles: UserRole):
    """Dependency factory: 403s unless the current user has one of `roles`.

    super_admin always passes, regardless of the roles listed, since it's the
    platform-wide role that supersedes company-scoped ones.
    """

    async def _check(current_user: CurrentUser) -> User:
        if current_user.role == UserRole.SUPER_ADMIN or current_user.role in roles:
            return current_user
        raise ForbiddenError

    return Depends(_check)


def company_scope(current_user: User) -> uuid.UUID | None:
    """Company filter to apply for a read: None means "no filter" and is only
    valid for super_admin, who can see every company's data.
    """
    return None if current_user.role == UserRole.SUPER_ADMIN else current_user.company_id
