from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import get_app_settings, get_database_session, get_health_service
from app.api.routes.health import router
from app.services.health_service import HealthService


class FakeSession:
    def __init__(self) -> None:
        self.execute_calls = 0
        self.error: BaseException | None = None

    async def execute(self, _statement: object) -> None:
        self.execute_calls += 1
        if self.error is not None:
            raise self.error


class TestSettings:
    app_env = "test"
    health_database_timeout_seconds = 0.1


def test_liveness_does_not_touch_database() -> None:
    client, session = make_client()

    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert session.execute_calls == 0


def test_readiness_returns_503_before_startup_is_ready() -> None:
    client, session = make_client()
    client.app.state.ready = False

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == "Application is not ready"
    assert session.execute_calls == 0


def test_readiness_returns_503_without_exposing_database_error() -> None:
    client, session = make_client()
    client.app.state.ready = True
    session.error = SQLAlchemyError("postgresql://user:secret@db/private")

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert "secret" not in response.text


def test_database_readiness_treats_name_resolution_failure_as_unavailable() -> None:
    session = FakeSession()
    session.error = socket.gaierror("database host lookup failed")

    is_ready = asyncio.run(HealthService().database_ready(session, timeout_seconds=0.1))

    assert is_ready is False


def test_readiness_returns_generic_503_for_connection_os_error() -> None:
    client, session = make_client()
    client.app.state.ready = True
    session.error = OSError("postgresql://user:secret@db/private")

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
    assert "secret" not in response.text


def test_database_readiness_does_not_swallow_cancellation() -> None:
    session = FakeSession()
    session.error = asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(HealthService().database_ready(session, timeout_seconds=0.1))


def test_database_readiness_does_not_swallow_programming_errors() -> None:
    session = FakeSession()
    session.error = ValueError("bug")

    with pytest.raises(ValueError, match="bug"):
        asyncio.run(HealthService().database_ready(session, timeout_seconds=0.1))


def test_legacy_health_success_contract_is_unchanged() -> None:
    client, session = make_client()
    client.app.state.ready = True

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "environment": "test",
        "database": "connected",
    }
    assert session.execute_calls == 1


def make_client() -> tuple[TestClient, FakeSession]:
    app = FastAPI()
    app.state.ready = True
    app.include_router(router, prefix="/api/v1")
    session = FakeSession()

    async def database_override() -> AsyncGenerator[FakeSession, None]:
        yield session

    app.dependency_overrides[get_database_session] = database_override
    app.dependency_overrides[get_app_settings] = lambda: TestSettings()
    app.dependency_overrides[get_health_service] = lambda: HealthService()
    return TestClient(app), session
