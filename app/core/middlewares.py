import time
import uuid

from app.core.logging.service import get_log_service
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for structured logging with request tracking.

    Adds request_id and trace_id to all requests and logs request details
    including method, URL, status code, and processing time.
    """

    def __init__(self, app: ASGIApp):
        """
        Initialize logging middleware.

        Args:
            app: ASGI application instance

        """
        super().__init__(app)
        self.logger = get_log_service()

    async def dispatch(self, request: Request, call_next):
        """
        Process request and add logging context.

        Args:
            request: FastAPI request object
            call_next: Next middleware or route handler

        Returns:
            Response object with added headers

        """
        # Generate or extract request_id and trace_id
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))

        # Store in request state for access in routes
        request.state.request_id = request_id
        request.state.trace_id = trace_id

        start_time = time.time()

        response = await call_next(request)

        duration = time.time() - start_time

        # Add request tracking headers to response
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-ID"] = trace_id

        await self.logger.a_info(
            "request",
            method=request.method,
            url=str(request.url),
            path=request.url.path,
            status_code=response.status_code,
            duration_seconds=duration,
            request_id=request_id,
            trace_id=trace_id,
        )

        return response
