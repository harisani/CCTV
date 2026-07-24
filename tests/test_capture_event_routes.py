from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_capture_evidence_service
from app.api.routes.capture_events import router
from app.api.security import require_authenticated_user
from app.models import CaptureEventStatus


class FakeCaptureEvidenceService:
    def __init__(self) -> None:
        self.event_id = uuid4()
        self.event = SimpleNamespace(
            id=self.event_id,
            source_event_id=uuid4(),
            camera_id=uuid4(),
            zone_id=uuid4(),
            virtual_line_id=uuid4(),
            tracking_id=uuid4(),
            status=CaptureEventStatus.CAPTURED,
            direction="down",
            bbox={"x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0},
            centroid={"x": 2.0, "y": 3.0},
            capture_quality={"detector_confidence": 0.9},
            capture_metadata={"event_type": "ENTER"},
            captured_at=datetime.now(UTC),
            processing_started_at=None,
            processed_at=None,
            dashboard_updated_at=None,
            processing_latency_ms=None,
            failed_at=None,
            attempt_count=0,
            retry_count=0,
            evidence_assets=[],
        )

    async def list_events(self, **_filters):
        return [self.event], 1

    async def get_event(self, capture_event_id):
        return self.event if capture_event_id == self.event_id else None

    async def list_assets(self, capture_event_id):
        return [] if capture_event_id == self.event_id else None


def make_client():
    service = FakeCaptureEvidenceService()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_authenticated_user] = lambda: (
        SimpleNamespace(id=uuid4())
    )
    app.dependency_overrides[get_capture_evidence_service] = lambda: service
    return TestClient(app), service


def test_capture_event_list_exposes_metadata_without_storage_paths():
    client, service = make_client()

    response = client.get("/api/v1/capture-events")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == str(service.event_id)
    assert payload["items"][0]["status"] == "CAPTURED"
    assert "storage_key" not in payload["items"][0]
    assert "idempotency_key" not in payload["items"][0]


def test_capture_event_detail_and_missing_event():
    client, service = make_client()

    detail = client.get(f"/api/v1/capture-events/{service.event_id}")
    missing = client.get(f"/api/v1/capture-events/{uuid4()}")

    assert detail.status_code == 200
    assert detail.json()["capture_metadata"]["event_type"] == "ENTER"
    assert detail.json()["evidence_assets"] == []
    assert missing.status_code == 404
