from typing import Annotated

from app.core.deps import DBSession
from app.models import User
from app.modules.auth import security
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
    if user is None:
        raise cred_exception

    return user


def get_auth_service(db: DBSession) -> AuthService:
    return AuthService(db)


CurrentUser = Annotated[User, Depends(get_current_user)]

AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
