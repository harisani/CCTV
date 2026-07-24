from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.middleware import RequestContextMiddleware
from app.api.request_context import (
    bind_correlation_id,
    choose_correlation_id,
    get_correlation_id,
    reset_correlation_id,
)
from app.config.settings import Settings


def settings_values() -> dict[str, object]:
    return {
        "_env_file": None,
        "postgres_password": "test-postgres-password",
        "jwt_secret": "test-jwt-secret",
        "api_admin_password": "test-admin-password",
    }


def test_phase1_settings_have_safe_bounds() -> None:
    settings = Settings(**settings_values())
    assert settings.log_format == "auto"
    assert settings.correlation_id_max_length == 128
    assert settings.health_database_timeout_seconds == 2.0
    assert settings.login_rate_limit_attempts == 5
    assert settings.login_rate_limit_window_seconds == 60
    assert settings.login_rate_limit_max_entries == 10_000


def test_choose_correlation_id_preserves_only_safe_values() -> None:
    assert choose_correlation_id("client-42:request.7", 128) == "client-42:request.7"
    assert choose_correlation_id("has spaces", 128) != "has spaces"
    assert choose_correlation_id("x" * 129, 128) != "x" * 129


def test_context_binding_is_reset() -> None:
    token = bind_correlation_id("request-one")
    assert get_correlation_id() == "request-one"
    reset_correlation_id(token)
    assert get_correlation_id() is None


def test_context_is_isolated_between_concurrent_tasks() -> None:
    async def worker(value: str) -> str | None:
        token = bind_correlation_id(value)
        try:
            await asyncio.sleep(0)
            return get_correlation_id()
        finally:
            reset_correlation_id(token)

    async def scenario() -> list[str | None]:
        return list(await asyncio.gather(worker("one"), worker("two")))

    assert asyncio.run(scenario()) == ["one", "two"]


def test_middleware_returns_effective_correlation_id() -> None:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware, max_length=128)

    @app.get("/probe")
    async def probe() -> dict[str, str | None]:
        return {"correlation_id": get_correlation_id()}

    client = TestClient(app)
    response = client.get("/probe", headers={"X-Correlation-ID": "factory-test-1"})

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "factory-test-1"
    assert response.json() == {"correlation_id": "factory-test-1"}
    assert get_correlation_id() is None


def test_application_allows_client_correlation_header(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-postgres-password")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("API_ADMIN_PASSWORD", "test-admin-password")

    from app.app import create_app
    from app.config.settings import get_settings

    get_settings.cache_clear()
    application = create_app()

    @application.get("/cors-probe")
    async def cors_probe() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(application)
    preflight = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Correlation-ID",
        },
    )

    assert preflight.status_code == 200
    assert "x-correlation-id" in preflight.headers["access-control-allow-headers"].lower()

    response = client.get(
        "/cors-probe",
        headers={
            "Origin": "http://localhost:5173",
            "X-Correlation-ID": "browser-client-1",
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "browser-client-1"
    assert "x-correlation-id" in response.headers.get("access-control-expose-headers", "").lower()
