import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

class LoggingMiddleware(BaseHTTPMiddleware):
    """Logs every request with method, path, status code, and duration."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = str(uuid.uuid4())[:8]
        start = time.perf_counter()

        logger.info(
            "Request started  | id=%s method=%s path=%s",
            request_id,
            request.method,
            request.url.path,
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            duration = (time.perf_counter() - start) * 1000
            logger.error(
                "Request failed   | id=%s method=%s path=%s duration=%.1fms error=%s",
                request_id,
                request.method,
                request.url.path,
                duration,
                exc,
            )
            raise

        duration = (time.perf_counter() - start) * 1000
        logger.info(
            "Request complete | id=%s method=%s path=%s status=%s duration=%.1fms",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )
        return response
