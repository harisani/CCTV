from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_zone_transition_service
from app.api.routes.zone_transitions import router
from app.api.security import require_authenticated_user
from app.models import ZoneEventType


class FakeZoneTransitionService:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.event = SimpleNamespace(
            id=uuid4(),
            transition_id=uuid4(),
            crossing_event_id=uuid4(),
            tracking_id=uuid4(),
            camera_id=uuid4(),
            virtual_line_id=uuid4(),
            zone_id=uuid4(),
            origin_zone_id=uuid4(),
            destination_zone_id=uuid4(),
            event_type=ZoneEventType.ZONE_ENTER,
            local_track_id=17,
            direction="right",
            centroid={"x": 120.0, "y": 80.0},
            confidence=0.94,
            occurred_at=now,
            event_metadata={"line_id": "mixing"},
            created_at=now,
        )
        self.track = SimpleNamespace(
            id=self.event.tracking_id,
            camera_id=self.event.camera_id,
            person_id=None,
            byte_track_id=17,
            started_at=now,
            last_seen_at=now,
            ended_at=None,
            last_centroid={"x": 120.0, "y": 80.0},
            last_bbox={"x1": 90.0, "y1": 20.0, "x2": 150.0, "y2": 170.0},
            detector_confidence=0.94,
            direction="right",
            detector_model="yolo11n.pt",
            is_active=True,
        )

    async def list_events(self, **_filters):
        return [self.event], 1

    async def get_event(self, event_id):
        return self.event if event_id == self.event.id else None

    async def list_tracks(self, **_filters):
        return [self.track], 1


def make_client() -> tuple[TestClient, FakeZoneTransitionService]:
    service = FakeZoneTransitionService()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_authenticated_user] = lambda: (
        SimpleNamespace(id=uuid4())
    )
    app.dependency_overrides[get_zone_transition_service] = lambda: service
    return TestClient(app), service


def test_zone_event_list_detail_and_local_tracks():
    client, service = make_client()

    listing = client.get("/api/v1/zone-events")
    detail = client.get(f"/api/v1/zone-events/{service.event.id}")
    tracks = client.get("/api/v1/local-tracks?active=true")

    assert listing.status_code == 200
    assert listing.json()["items"][0]["event_type"] == "ZONE_ENTER"
    assert detail.status_code == 200
    assert detail.json()["transition_id"] == str(service.event.transition_id)
    assert tracks.status_code == 200
    assert tracks.json()["items"][0]["byte_track_id"] == 17
    assert tracks.json()["items"][0]["detector_model"] == "yolo11n.pt"
