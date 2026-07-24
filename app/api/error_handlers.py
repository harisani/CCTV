"""Centralized, safe HTTP error responses."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException

from app.api.request_context import (
    bind_correlation_id,
    choose_correlation_id,
    get_correlation_id,
    reset_correlation_id,
)
from app.config.settings import get_settings
from app.services.topology_service import (
    TopologyConflictError,
    TopologyNotFoundError,
    TopologyValidationError,
)

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

    @app.exception_handler(TopologyNotFoundError)
    async def handle_topology_not_found(
        _: Request, error: TopologyNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=error_content(str(error)),
        )

    @app.exception_handler(TopologyConflictError)
    async def handle_topology_conflict(
        _: Request, error: TopologyConflictError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=error_content(str(error)),
        )

    @app.exception_handler(TopologyValidationError)
    async def handle_topology_validation(
        _: Request, error: TopologyValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_content(str(error)),
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
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        correlation_id = get_correlation_id()
        context_token = None
        if correlation_id is None:
            correlation_id = choose_correlation_id(
                request.headers.get("X-Correlation-ID"),
                get_settings().correlation_id_max_length,
            )
            context_token = bind_correlation_id(correlation_id)
        try:
            logger.exception(
                "Unhandled application error",
                exc_info=error,
                extra={
                    "correlation_id": correlation_id,
                    "exception_type": type(error).__name__,
                },
            )
            response = JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content=error_content("An unexpected server error occurred."),
            )
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            if context_token is not None:
                reset_correlation_id(context_token)
