from typing import Literal
from urllib.parse import quote_plus

from app.core.config.base_config import BaseConfig
from pydantic import (
    PostgresDsn,
    computed_field,
    model_validator,
)


class AppConfig(BaseConfig):
    _default_secrets: list[str] = ["DATABASE_PASSWORD", "SECRET_KEY"]

    ENVIRONMENT: Literal["local", "staging", "production", "testing"] = "local"
    PROJECT_NAME: str = "Insight Backend"
    DOMAIN: str = "localhost"
    HOST: str = "0.0.0.0"
    PORT: int = 80

    SECRET_KEY: str = "changethis"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    REFRESH_COOKIE_NAME: str = "refresh_token"
    REFRESH_COOKIE_PATH: str = "/auth"
    REFRESH_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def refresh_cookie_secure(self) -> bool:
        return self.ENVIRONMENT not in ("local", "testing")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def refresh_cookie_max_age(self) -> int:
        return self.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60

    @computed_field  # type: ignore[prop-decorator]
    @property
    def app_url(self) -> str:
        if self.ENVIRONMENT in ["local", "testing"]:
            return f"http://{self.DOMAIN}"
        return f"https://{self.DOMAIN}"

    BACKEND_CORS_ORIGINS: str | list[str] = ""
    RATE_LIMITER_ENABLED: bool = True

    DATABASE_HOST: str = "localhost"
    DATABASE_PORT: int = 5432
    DATABASE_USER: str = "postgres"
    DATABASE_PASSWORD: str = "changethis"
    DATABASE_NAME: str = "app"
    SQL_ECHO: bool = False

    @computed_field  # type: ignore[misc]
    @property
    def postgres_url(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.DATABASE_USER,
            password=quote_plus(self.DATABASE_PASSWORD),
            host=self.DATABASE_HOST,
            port=self.DATABASE_PORT,
            path=self.DATABASE_NAME,
        )

    MINIO_USER: str = "minioadmin"
    MINIO_PASSWORD: str = "minioadmin"
    MINIO_API_PORT: int = 9000
    MINIO_CONSOLE_PORT: int = 9001

    LOG_LEVEL: str = "INFO"
    LOG_HANDLERS: str | list[str] = "stream"

    @model_validator(mode="after")
    def parse_string_lists(self) -> AppConfig:
        """
        Parse string fields that should be lists.

        Returns:
            AppConfig: Self with parsed list fields

        """
        if isinstance(self.BACKEND_CORS_ORIGINS, str):
            value = self.BACKEND_CORS_ORIGINS
            if not value or value == "":
                self.BACKEND_CORS_ORIGINS = []
            elif value == "*":
                self.BACKEND_CORS_ORIGINS = ["*"]
            else:
                self.BACKEND_CORS_ORIGINS = [
                    origin.strip() for origin in value.split(",") if origin.strip()
                ]

        # Parse LOG_HANDLERS
        if isinstance(self.LOG_HANDLERS, str):
            value = self.LOG_HANDLERS
            if not value or value == "":
                self.LOG_HANDLERS = ["stream"]
            else:
                self.LOG_HANDLERS = [
                    handler.strip() for handler in value.split(",") if handler.strip()
                ]

        return self


app_config = AppConfig()
