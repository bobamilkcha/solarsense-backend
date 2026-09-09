from typing import Annotated

from app.core.config.app_config import app_config
from app.modules.auth import schemas
from app.modules.auth.cookies import clear_refresh_cookie, set_refresh_cookie
from app.modules.auth.deps import AuthServiceDep, CurrentUser
from app.modules.auth.exceptions import InvalidRefreshTokenError
from fastapi import APIRouter, Cookie, Response, status
from fastapi.requests import Request

router = APIRouter(prefix="/auth", tags=["auth"])

RefreshCookie = Annotated[str | None, Cookie(alias=app_config.REFRESH_COOKIE_NAME)]


@router.post(
    "/register",
    response_model=schemas.AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    data: schemas.UserRegisterRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
):
    user = await service.register(data)
    access, refresh = await service.issue_tokens(user, user_agent=request.headers.get("user-agent"))
    set_refresh_cookie(response, refresh)
    return schemas.AuthResponse(access_token=access, user=schemas.UserResponse.model_validate(user))


@router.post("/login", response_model=schemas.AuthResponse, status_code=status.HTTP_200_OK)
async def login(
    data: schemas.UserLoginRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
):
    user = await service.authenticate(data.email, data.password)
    access, refresh = await service.issue_tokens(user, user_agent=request.headers.get("user-agent"))
    set_refresh_cookie(response, refresh)
    return schemas.AuthResponse(access_token=access, user=schemas.UserResponse.model_validate(user))


@router.post("/refresh", response_model=schemas.AuthResponse)
async def refresh(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    refresh_token: RefreshCookie = None,
):
    if refresh_token is None:
        raise InvalidRefreshTokenError

    access, new_refresh, user = await service.rotate_refresh_token(
        refresh_token, user_agent=request.headers.get("user-agent")
    )
    set_refresh_cookie(response, new_refresh)
    return schemas.AuthResponse(access_token=access, user=schemas.UserResponse.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    service: AuthServiceDep,
    refresh_token: RefreshCookie = None,
):
    if refresh_token is not None:
        await service.revoke_refresh_token(refresh_token)
    clear_refresh_cookie(response)


@router.get("/me", response_model=schemas.UserResponse)
async def me(current_user: CurrentUser):
    return current_user
