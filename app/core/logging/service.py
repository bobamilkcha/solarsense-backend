from app.core.logging.base_service import LogServiceInterface
from app.core.logging.providers.structlog.service import StructLogService
from app.core.logging.providers.structlog.setup import (
    logger,  # pyright: ignore[reportAny]
)


def get_log_service() -> LogServiceInterface:
    return StructLogService(logger)
