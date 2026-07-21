"""Centralized, safe HTTP error responses."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """Log infrastructure failures without exposing internal details to clients."""

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(_: Request, error: IntegrityError) -> JSONResponse:
        logger.warning("Database integrity violation: %s", error.orig)
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": "Data conflict."})

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(_: Request, error: SQLAlchemyError) -> JSONResponse:
        logger.exception("Database operation failed", exc_info=error)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Database service is temporarily unavailable."},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, error: Exception) -> JSONResponse:
        logger.exception("Unhandled application error", exc_info=error)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An unexpected server error occurred."},
        )
