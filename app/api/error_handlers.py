"""Centralized, safe HTTP error responses."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException

from app.api.request_context import get_correlation_id

logger = logging.getLogger(__name__)


def error_content(detail: object) -> dict[str, object]:
    """Build an error response carrying the active request correlation ID."""
    return {
        "detail": detail,
        "correlation_id": get_correlation_id(),
    }


def safe_validation_errors(error: RequestValidationError) -> list[dict[str, object]]:
    """Return useful validation metadata without submitted input values."""
    return [
        {
            "type": item["type"],
            "loc": list(item["loc"]),
            "msg": item["msg"],
        }
        for item in error.errors()
    ]


def register_exception_handlers(app: FastAPI) -> None:
    """Log infrastructure failures without exposing internal details to clients."""

    @app.exception_handler(HTTPException)
    async def handle_http_error(_: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content=error_content(error.detail),
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_content(safe_validation_errors(error)),
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(_: Request, error: IntegrityError) -> JSONResponse:
        logger.warning(
            "Database integrity violation",
            extra={
                "correlation_id": get_correlation_id(),
                "exception_type": type(error).__name__,
            },
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=error_content("Data conflict."),
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(_: Request, error: SQLAlchemyError) -> JSONResponse:
        logger.error(
            "Database operation failed",
            extra={
                "correlation_id": get_correlation_id(),
                "exception_type": type(error).__name__,
            },
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error_content("Database service is temporarily unavailable."),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, error: Exception) -> JSONResponse:
        logger.exception("Unhandled application error", exc_info=error)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_content("An unexpected server error occurred."),
        )
