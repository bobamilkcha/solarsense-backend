from fastapi import status


class AuthError(Exception):
    """Base class for auth domain errors.

    Subclasses carry the HTTP status code and client-facing detail used by the
    global exception handler, so routers stay free of try/except mapping.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    detail: str = "Authentication error"

    def __init__(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class EmailAlreadyExistsError(AuthError):
    status_code = status.HTTP_409_CONFLICT
    detail = "Email already exists"


class InvalidCredentialsError(AuthError):
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Invalid credentials"


class InvalidRefreshTokenError(AuthError):
    status_code = status.HTTP_401_UNAUTHORIZED
    detail = "Invalid or expired refresh token"
