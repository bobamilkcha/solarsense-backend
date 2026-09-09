from app.core.config.app_config import app_config
from fastapi import Response


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=app_config.REFRESH_COOKIE_NAME,
        value=token,
        max_age=app_config.refresh_cookie_max_age,
        path=app_config.REFRESH_COOKIE_PATH,
        httponly=True,
        secure=app_config.refresh_cookie_secure,
        samesite=app_config.REFRESH_COOKIE_SAMESITE,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=app_config.REFRESH_COOKIE_NAME,
        path=app_config.REFRESH_COOKIE_PATH,
        httponly=True,
        secure=app_config.refresh_cookie_secure,
        samesite=app_config.REFRESH_COOKIE_SAMESITE,
    )
