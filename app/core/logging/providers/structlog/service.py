from typing import Any

from app.core.logging.base_service import LogServiceInterface


class StructLogService(LogServiceInterface):
    def __init__(self, logger: Any) -> None:  # pyright: ignore[reportExplicitAny, reportAny]
        self._logger = logger  # pyright: ignore[reportAny, reportUnannotatedClassAttribute]

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportExplicitAny, reportAny, reportImplicitOverride]
        return self._logger.log(level, msg, *args, **kwargs)  # pyright: ignore[reportAny]

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportExplicitAny, reportAny, reportImplicitOverride]
        return self._logger.debug(msg, *args, **kwargs)  # pyright: ignore[reportAny]

    def info(self, msg: str, *args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportExplicitAny, reportAny, reportImplicitOverride]
        return self._logger.info(msg, *args, **kwargs)  # pyright: ignore[reportAny]

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportExplicitAny, reportAny, reportImplicitOverride]
        return self._logger.warning(msg, *args, **kwargs)  # pyright: ignore[reportAny]

    def error(self, msg: str, *args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportExplicitAny, reportAny, reportImplicitOverride]
        return self._logger.error(msg, *args, **kwargs)  # pyright: ignore[reportAny]

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportExplicitAny, reportAny, reportImplicitOverride]
        return self._logger.critical(msg, *args, **kwargs)  # pyright: ignore[reportAny]

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportExplicitAny, reportAny, reportImplicitOverride]
        return self._logger.exception(msg, *args, **kwargs)  # pyright: ignore[reportAny]

    async def a_debug(self, msg: str, *args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportExplicitAny, reportAny, reportImplicitOverride]
        return await self._logger.adebug(msg, *args, **kwargs)  # pyright: ignore[reportAny]

    async def a_info(self, msg: str, *args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportExplicitAny, reportAny, reportImplicitOverride]
        return await self._logger.ainfo(msg, *args, **kwargs)  # pyright: ignore[reportAny]

    async def a_warning(self, msg: str, *args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportExplicitAny, reportAny, reportImplicitOverride]
        return await self._logger.awarning(msg, *args, **kwargs)  # pyright: ignore[reportAny]

    async def a_error(self, msg: str, *args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportExplicitAny, reportAny, reportImplicitOverride]
        return await self._logger.aerror(msg, *args, **kwargs)  # pyright: ignore[reportAny]

    async def a_critical(self, msg: str, *args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportExplicitAny, reportAny, reportImplicitOverride]
        return await self._logger.acritical(msg, *args, **kwargs)  # pyright: ignore[reportAny]

    async def a_exception(self, msg: str, *args: Any, **kwargs: Any) -> Any:  # pyright: ignore[reportExplicitAny, reportAny, reportImplicitOverride]
        return await self._logger.aexception(msg, *args, **kwargs)  # pyright: ignore[reportAny]
