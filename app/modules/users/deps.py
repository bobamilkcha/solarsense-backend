from typing import Annotated

from app.core.deps import DBSession
from app.modules.users.service import UsersService
from fastapi import Depends


def get_users_service(db: DBSession) -> UsersService:
    return UsersService(db)


UsersServiceDep = Annotated[UsersService, Depends(get_users_service)]
