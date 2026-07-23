from __future__ import annotations

import warnings
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from starlette.exceptions import StarletteDeprecationWarning

from app.api.dependencies import get_app_settings, get_database_session
from app.api.routes.evidence import router
from app.api.security import require_authenticated_user
from app.models import Snapshot, User

warnings.filterwarnings(
    "ignore",
    message=(
        r"Using `httpx` with `starlette\.testclient` is deprecated; "
        r"install `httpx2` instead\."
    ),
    category=StarletteDeprecationWarning,
)

from fastapi.testclient import TestClient  # noqa: E402


class FakeSession:
    def __init__(self, snapshot: object, user: object) -> None:
        self.snapshot = snapshot
        self.user = user
        self.added: list[object] = []
        self.commits = 0

    async def get(self, model: type, identifier: object) -> object | None:
        if model is Snapshot and identifier == self.snapshot.id:
            return self.snapshot
        if model is User and identifier == self.user.id:
            return self.user
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None

    async def refresh(self, value: object) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


def make_client(tmp_path: Path) -> tuple[TestClient, FakeSession, object]:
    image = tmp_path / "snapshot.jpg"
    image.write_bytes(b"snapshot-bytes")
    snapshot = SimpleNamespace(id=uuid4(), image_path=str(image))
    user = SimpleNamespace(id=uuid4(), is_active=True)
    session = FakeSession(snapshot, user)
    settings = SimpleNamespace(
        storage_path=tmp_path,
        evidence_signing_secret="evidence-signing-secret-with-at-least-32-characters",
        evidence_access_token_expire_seconds=60,
    )

    async def database_override():
        yield session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_database_session] = database_override
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[require_authenticated_user] = lambda: user
    return TestClient(app), session, snapshot


def test_grant_and_content_are_audited(tmp_path: Path) -> None:
    client, session, snapshot = make_client(tmp_path)

    grant = client.post(f"/api/v1/evidence/snapshots/{snapshot.id}/access")
    assert grant.status_code == 200

    content = client.get(grant.json()["content_url"])
    assert content.status_code == 200
    assert content.content == b"snapshot-bytes"
    assert content.headers["cache-control"] == "private, no-store"
    assert [item.action for item in session.added] == [
        "EVIDENCE_ACCESS_GRANTED",
        "EVIDENCE_SNAPSHOT_VIEWED",
    ]


def test_content_rejects_invalid_signed_token(tmp_path: Path) -> None:
    client, _, snapshot = make_client(tmp_path)

    response = client.get(
        f"/api/v1/evidence/snapshots/{snapshot.id}/content?access_token=invalid"
    )

    assert response.status_code == 401


def test_application_has_no_public_storage_mount(monkeypatch, tmp_path: Path) -> None:
    from app.config.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-postgres-password")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("API_ADMIN_PASSWORD", "test-admin-password")
    from app.app import create_app

    application = create_app()

    assert all(getattr(route, "path", None) != "/storage" for route in application.routes)
    get_settings.cache_clear()
