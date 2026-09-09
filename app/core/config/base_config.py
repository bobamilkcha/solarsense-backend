from typing import Any, ClassVar, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        env_ignore_empty=True,
        extra="ignore",
        env_parse_none_str="null",
    )

    @staticmethod
    def _parse_list(v: Any) -> list[str]:  # pyright: ignore[reportExplicitAny, reportAny]
        if v is None or v == "":
            return []
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, list):
            return v  # pyright: ignore[reportUnknownVariableType]
        elif isinstance(v, str):
            return [i.strip() for i in v.split(",") if i.strip()]
        raise ValueError(v)  # pyright: ignore[reportAny]

    def _check_default_secret(self, name: str) -> None:
        if getattr(self, name) == "changethis":
            raise ValueError(
                f"The value of {name} is 'changethis', for security reasons, please change it."
            )

    _default_secrets: list[str] = []

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        # Skip secret validation in testing or local environment
        # This allows CI builds and local development without full configuration
        environment = getattr(self, "ENVIRONMENT", None)
        if environment in ("testing", "local"):
            return self

        for name in self._default_secrets:
            self._check_default_secret(name)

        return self
