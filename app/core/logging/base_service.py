from abc import ABC, abstractmethod
from typing import Any


class LogServiceInterface(ABC):
    """
    Abstract base class for logging service implementations.

    Defines the interface that all logging services must implement.
    """

    # Synchronous methods
    @abstractmethod
    def debug(self, msg: str, *args: Any, **kwargs: Any) -> Any:
        """
        Log a debug level message synchronously.

        Args:
            msg: The log message
            *args: Additional arguments
            **kwargs: Additional context to include in the log

        """
        pass

    @abstractmethod
    def info(self, msg: str, *args: Any, **kwargs: Any) -> Any:
        """
        Log an info level message synchronously.

        Args:
            msg: The log message
            *args: Additional arguments
            **kwargs: Additional context to include in the log

        """
        pass

    @abstractmethod
    def warning(self, msg: str, *args: Any, **kwargs: Any) -> Any:
        """
        Log a warning level message synchronously.

        Args:
            msg: The log message
            *args: Additional arguments
            **kwargs: Additional context to include in the log

        """
        pass

    @abstractmethod
    def error(self, msg: str, *args: Any, **kwargs: Any) -> Any:
        """
        Log an error level message synchronously.

        Args:
            msg: The log message
            *args: Additional arguments
            **kwargs: Additional context to include in the log

        """
        pass

    @abstractmethod
    def critical(self, msg: str, *args: Any, **kwargs: Any) -> Any:
        """
        Log a critical level message synchronously.

        Args:
            msg: The log message
            *args: Additional arguments
            **kwargs: Additional context to include in the log

        """
        pass

    @abstractmethod
    def exception(self, msg: str, *args: Any, **kwargs: Any) -> Any:
        """
        Log an exception message synchronously.

        Args:
            msg: The log message
            *args: Additional arguments
            **kwargs: Additional context to include in the log

        """
        pass

    # Asynchronous methods
    @abstractmethod
    async def a_info(self, msg: str, *args: Any, **kwargs: Any) -> Any:
        """
        Log an info level message asynchronously.

        Args:
            msg: The log message
            *args: Additional arguments
            **kwargs: Additional context to include in the log

        """
        pass

    @abstractmethod
    async def a_error(self, msg: str, *args: Any, **kwargs: Any) -> Any:
        """
        Log an error level message asynchronously.

        Args:
            msg: The log message
            *args: Additional arguments
            **kwargs: Additional context to include in the log

        """
        pass

    @abstractmethod
    async def a_warning(self, msg: str, *args: Any, **kwargs: Any) -> Any:
        """
        Log a warning level message asynchronously.

        Args:
            msg: The log message
            *args: Additional arguments
            **kwargs: Additional context to include in the log

        """
        pass

    @abstractmethod
    async def a_debug(self, msg: str, *args: Any, **kwargs: Any) -> Any:
        """
        Log a debug level message asynchronously.

        Args:
            msg: The log message
            *args: Additional arguments
            **kwargs: Additional context to include in the log

        """
        pass
