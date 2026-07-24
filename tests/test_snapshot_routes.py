from __future__ import annotations

import warnings
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from starlette.exceptions import StarletteDeprecationWarning

from app.api.dependencies import get_snapshot_repository
from app.api.routes.snapshots import router
from app.api.security import require_authenticated_user

warnings.filterwarnings(
    "ignore",
    message=(
        r"Using `httpx` with `starlette\.testclient` is deprecated; "
        r"install `httpx2` instead\."
    ),
    category=StarletteDeprecationWarning,
)

from fastapi.testclient import TestClient  # noqa: E402


class FakeSnapshotRepository:
    def __init__(self, snapshot: object) -> None:
        self.snapshot = snapshot

    async def list_filtered(
        self,
        *,
        camera_id: object,
        offset: int,
        limit: int,
    ) -> tuple[list[object], int]:
        return [self.snapshot], 1


def test_snapshot_list_never_serializes_storage_paths() -> None:
    snapshot_id = uuid4()
    event_id = uuid4()
    saved_at = datetime(2026, 7, 24, 12, 30, tzinfo=UTC)
    snapshot = SimpleNamespace(
        id=snapshot_id,
        event_id=event_id,
        image_path="/service/storage/2026/07/private.jpg",
        metadata_path="/service/storage/2026/07/private.json",
        bbox={"x1": 10.0, "y1": 20.0, "x2": 30.0, "y2": 40.0},
        saved_at=saved_at,
    )
    repository = FakeSnapshotRepository(snapshot)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_snapshot_repository] = lambda: repository
    app.dependency_overrides[require_authenticated_user] = lambda: SimpleNamespace(
        id=uuid4()
    )
    client = TestClient(app)

    response = client.get("/api/v1/snapshots")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item == {
        "id": str(snapshot_id),
        "event_id": str(event_id),
        "bbox": {"x1": 10.0, "y1": 20.0, "x2": 30.0, "y2": 40.0},
        "saved_at": saved_at.isoformat().replace("+00:00", "Z"),
    }
    assert "image_path" not in item
    assert "metadata_path" not in item
