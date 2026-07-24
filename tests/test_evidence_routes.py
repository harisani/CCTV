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
from app.models import EvidenceAsset, EvidenceAssetType, Snapshot, User

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
    def __init__(
        self,
        snapshot: object,
        user: object,
        asset: object | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.user = user
        self.asset = asset
        self.added: list[object] = []
        self.commits = 0

    async def get(self, model: type, identifier: object) -> object | None:
        if model is Snapshot and identifier == self.snapshot.id:
            return self.snapshot
        if model is User and identifier == self.user.id:
            return self.user
        if (
            model is EvidenceAsset
            and self.asset is not None
            and identifier == self.asset.id
        ):
            return self.asset
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
    user = SimpleNamespace(id=uuid4(), is_active=True, token_version=1)
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
    assert grant.headers["cache-control"] == "no-store"
    assert grant.json()["content_url"] == (
        f"/api/v1/evidence/snapshots/{snapshot.id}/content"
    )
    assert "?" not in grant.json()["content_url"]

    content = client.get(
        grant.json()["content_url"],
        headers={"Authorization": f"Bearer {grant.json()['access_token']}"},
    )
    assert content.status_code == 200
    assert content.content == b"snapshot-bytes"
    assert content.headers["cache-control"] == "private, no-store"
    assert content.headers["referrer-policy"] == "no-referrer"
    assert [item.action for item in session.added] == [
        "EVIDENCE_ACCESS_GRANTED",
        "EVIDENCE_SNAPSHOT_VIEWED",
    ]
    assert session.commits == 2
    grant_id = session.added[0].details["grant_id"]
    assert grant_id
    assert session.added[1].details["grant_id"] == grant_id


def test_asset_grant_and_content_are_path_safe_and_audited(
    tmp_path: Path,
) -> None:
    image = tmp_path / "body.jpg"
    image.write_bytes(b"full-body-evidence")
    snapshot = SimpleNamespace(id=uuid4(), image_path=str(image))
    user = SimpleNamespace(id=uuid4(), is_active=True, token_version=2)
    asset = SimpleNamespace(
        id=uuid4(),
        capture_event_id=uuid4(),
        asset_type=EvidenceAssetType.FULL_BODY,
        storage_key="body.jpg",
        mime_type="image/jpeg",
        deleted_at=None,
    )
    session = FakeSession(snapshot, user, asset)
    settings = SimpleNamespace(
        storage_path=tmp_path,
        evidence_signing_secret=(
            "evidence-signing-secret-with-at-least-32-characters"
        ),
        evidence_access_token_expire_seconds=60,
    )

    async def database_override():
        yield session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_database_session] = database_override
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[require_authenticated_user] = lambda: user
    client = TestClient(app)

    grant = client.post(f"/api/v1/evidence/assets/{asset.id}/access")
    assert grant.status_code == 200
    assert "?" not in grant.json()["content_url"]

    content = client.get(
        grant.json()["content_url"],
        headers={"Authorization": f"Bearer {grant.json()['access_token']}"},
    )

    assert content.status_code == 200
    assert content.content == b"full-body-evidence"
    assert content.headers["x-content-type-options"] == "nosniff"
    assert [item.action for item in session.added] == [
        "EVIDENCE_ASSET_ACCESS_GRANTED",
        "EVIDENCE_ASSET_VIEWED",
    ]


def test_anonymous_evidence_grant_is_rejected(tmp_path: Path) -> None:
    client, _, snapshot = make_client(tmp_path)
    client.app.dependency_overrides.pop(require_authenticated_user)

    response = client.post(f"/api/v1/evidence/snapshots/{snapshot.id}/access")

    assert response.status_code == 401


def test_content_rejects_missing_evidence_bearer_credential(tmp_path: Path) -> None:
    client, _, snapshot = make_client(tmp_path)

    response = client.get(f"/api/v1/evidence/snapshots/{snapshot.id}/content")

    assert response.status_code == 401


def test_content_rejects_malformed_evidence_bearer_credential(
    tmp_path: Path,
) -> None:
    client, _, snapshot = make_client(tmp_path)

    response = client.get(
        f"/api/v1/evidence/snapshots/{snapshot.id}/content",
        headers={"Authorization": "Basic not-a-bearer-credential"},
    )

    assert response.status_code == 401


def test_content_does_not_accept_evidence_token_in_query_string(
    tmp_path: Path,
) -> None:
    client, _, snapshot = make_client(tmp_path)
    grant = client.post(f"/api/v1/evidence/snapshots/{snapshot.id}/access")

    response = client.get(
        f"{grant.json()['content_url']}?access_token={grant.json()['access_token']}"
    )

    assert response.status_code == 401


def test_content_rejects_invalid_signed_token(tmp_path: Path) -> None:
    client, _, snapshot = make_client(tmp_path)

    response = client.get(
        f"/api/v1/evidence/snapshots/{snapshot.id}/content",
        headers={"Authorization": "Bearer invalid"},
    )

    assert response.status_code == 401


def test_content_rejects_revoked_user_token_version(tmp_path: Path) -> None:
    client, session, snapshot = make_client(tmp_path)
    grant = client.post(f"/api/v1/evidence/snapshots/{snapshot.id}/access")
    session.user.token_version += 1

    response = client.get(
        grant.json()["content_url"],
        headers={"Authorization": f"Bearer {grant.json()['access_token']}"},
    )

    assert response.status_code == 401
    assert response.content != b"snapshot-bytes"
    assert [item.action for item in session.added] == ["EVIDENCE_ACCESS_GRANTED"]
    assert session.commits == 1


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
