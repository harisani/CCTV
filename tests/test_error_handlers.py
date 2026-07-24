import logging

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.error_handlers import register_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.utils.logging import JsonFormatter


class ValidationPayload(BaseModel):
    password: str


def make_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware, max_length=128)
    register_exception_handlers(app)

    @app.get("/limited")
    async def limited() -> None:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": "30"},
        )

    @app.post("/validate")
    async def validate(_: ValidationPayload) -> None:
        return None

    @app.get("/explode")
    async def explode() -> None:
        raise RuntimeError("postgresql://user:secret@db/private")

    @app.get("/integrity")
    async def integrity() -> None:
        raise IntegrityError(
            "INSERT INTO users (password) VALUES (:password)",
            {"password": "sensitive-submitted-value"},
            RuntimeError("postgresql://user:secret@db/private"),
        )

    @app.get("/database")
    async def database() -> None:
        raise SQLAlchemyError("postgresql://user:secret@db/private SELECT password FROM users")

    return TestClient(app, raise_server_exceptions=False)


client = make_client()


def test_http_error_preserves_status_headers_and_adds_correlation() -> None:
    response = client.get(
        "/limited",
        headers={"X-Correlation-ID": "error-test-1"},
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"
    assert response.json() == {
        "detail": "Too many requests",
        "correlation_id": "error-test-1",
    }


def test_validation_error_does_not_echo_sensitive_input() -> None:
    response = client.post(
        "/validate",
        headers={"X-Correlation-ID": "validation-test-1"},
        json={"password": ["sensitive-submitted-value"]},
    )

    assert response.status_code == 422
    assert response.json()["correlation_id"] == "validation-test-1"
    assert "sensitive-submitted-value" not in response.text


def test_unexpected_error_hides_internal_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.handler.setFormatter(JsonFormatter())
    with caplog.at_level(logging.ERROR, logger="app.api.error_handlers"):
        response = client.get(
            "/explode",
            headers={"X-Correlation-ID": "unexpected-test-1"},
        )

    assert response.status_code == 500
    assert response.headers["X-Correlation-ID"] == "unexpected-test-1"
    assert "postgresql://" not in response.text
    assert response.json() == {
        "detail": "An unexpected server error occurred.",
        "correlation_id": "unexpected-test-1",
    }
    error_record = next(
        record for record in caplog.records if record.name == "app.api.error_handlers"
    )
    assert error_record.correlation_id == "unexpected-test-1"
    assert "postgresql://" not in caplog.text


@pytest.mark.parametrize(
    ("path", "status_code", "detail", "exception_type"),
    [
        ("/integrity", 409, "Data conflict.", "IntegrityError"),
        (
            "/database",
            503,
            "Database service is temporarily unavailable.",
            "SQLAlchemyError",
        ),
    ],
)
def test_database_errors_log_safe_metadata(
    path: str,
    status_code: int,
    detail: str,
    exception_type: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="app.api.error_handlers"):
        response = client.get(
            path,
            headers={"X-Correlation-ID": "database-test-1"},
        )

    assert response.status_code == status_code
    assert response.json() == {
        "detail": detail,
        "correlation_id": "database-test-1",
    }
    error_record = next(
        record for record in caplog.records if record.name == "app.api.error_handlers"
    )
    assert error_record.correlation_id == "database-test-1"
    assert error_record.exception_type == exception_type
    assert "postgresql://" not in caplog.text
    assert "sensitive-submitted-value" not in caplog.text
    assert "SELECT password" not in caplog.text
