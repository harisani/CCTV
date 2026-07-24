from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_app_settings,
    get_login_rate_limiter,
    get_user_repository,
)
from app.api.routes.auth import router
from app.models import UserRole
from app.services.login_rate_limiter import LoginRateLimiter
from app.services.user_service import UserService


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, LoginRateLimiter]:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    settings = SimpleNamespace(
        jwt_access_token_expire_minutes=60,
        jwt_secret="test-secret-that-is-at-least-32-bytes-long",
        jwt_algorithm="HS256",
    )
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=60, max_entries=100)
    user = SimpleNamespace(
        id=uuid4(),
        username="admin",
        role=UserRole.SUPER_ADMIN,
        token_version=1,
    )

    async def authenticate(
        _self: UserService,
        _username: str,
        password: str,
        _settings: object,
    ) -> object:
        if password == "valid-password":
            return user
        if password == "locked-account":
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Account is temporarily locked",
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    monkeypatch.setattr(UserService, "authenticate", authenticate)
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_user_repository] = lambda: SimpleNamespace(session=object())
    app.dependency_overrides[get_login_rate_limiter] = lambda: limiter
    return TestClient(app), limiter


def test_failed_login_is_limited_at_configured_boundary(
    auth_client: tuple[TestClient, LoginRateLimiter],
) -> None:
    client, _limiter = auth_client
    invalid_credentials = {"username": "admin", "password": "invalid-password"}

    first = client.post(
        "/api/v1/auth/token",
        data=invalid_credentials,
        headers={"X-Forwarded-For": "198.51.100.1"},
    )
    second = client.post(
        "/api/v1/auth/token",
        data=invalid_credentials,
        headers={"X-Forwarded-For": "203.0.113.2"},
    )

    assert first.status_code == 401
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "60"
    assert second.json()["detail"] == "Too many login attempts"


def test_successful_login_resets_limiter_and_keeps_token_contract(
    auth_client: tuple[TestClient, LoginRateLimiter],
) -> None:
    client, limiter = auth_client
    expected_key = limiter.build_key("admin", "testclient")
    assert limiter.record_failure(expected_key) is None

    response = client.post(
        "/api/v1/auth/token",
        data={"username": " Admin ", "password": "valid-password"},
    )

    assert response.status_code == 200
    assert set(response.json()) == {"access_token", "token_type"}
    assert limiter.retry_after(expected_key) is None


def test_persistent_account_lock_status_is_unchanged(
    auth_client: tuple[TestClient, LoginRateLimiter],
) -> None:
    client, limiter = auth_client

    response = client.post(
        "/api/v1/auth/token",
        data={"username": "admin", "password": "locked-account"},
    )

    assert response.status_code == 423
    assert response.json()["detail"] == "Account is temporarily locked"
    assert limiter.retry_after(limiter.build_key("admin", "testclient")) is None
