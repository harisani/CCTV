from __future__ import annotations

import logging
from time import monotonic
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.request_context import (
    bind_correlation_id,
    choose_correlation_id,
    reset_correlation_id,
)

logger = logging.getLogger("app.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, *, max_length: int) -> None:
        super().__init__(app)
        self.max_length = max_length

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        correlation_id = choose_correlation_id(
            request.headers.get("X-Correlation-ID"),
            self.max_length,
        )
        token = bind_correlation_id(correlation_id)
        started = monotonic()
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id
            logger.info(
                "HTTP request completed",
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_status": response.status_code,
                    "duration_ms": round((monotonic() - started) * 1000, 3),
                },
            )
            return response
        finally:
            reset_correlation_id(token)
