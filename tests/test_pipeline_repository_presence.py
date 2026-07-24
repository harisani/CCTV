import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from pathlib import Path

from app.models import (
    CaptureEvent,
    AIProcessingJob,
    EvidenceAsset,
    EvidenceAssetType,
    Event,
    PresenceStatus,
    Tracking,
    ZoneEvent,
    ZoneEventType,
)
from app.repository.pipeline_repository import PipelineRepository
from app.services.crossing_service import CrossingEvent, CrossingType
from app.storage import EvidenceFile, SnapshotResult
from app.tracker import TrackedDetection


class FakeSession:
    def __init__(self, tracking: object, scalar_results: list[object | None]) -> None:
        self.tracking = tracking
        self.scalar_results = scalar_results
        self.added: list[object] = []
        self.committed = False

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get(self, model: object, _key: object) -> object | None:
        if model is Event:
            return None
        if model is Tracking:
            return self.tracking
        return None

    async def scalar(self, _query: object) -> object | None:
        return self.scalar_results.pop(0)

    def add(self, value: object) -> None:
        self.added.append(value)

    def add_all(self, values: list[object]) -> None:
        self.added.extend(values)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        return None


def tracked(track_id: int) -> TrackedDetection:
    return TrackedDetection(
        track_id,
        (10, 10, 60, 120),
        0.95,
        0,
        "person",
        (35, 65),
        "left",
        ((35, 65),),
    )


class PipelineRepositoryPresenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_zone_to_zone_crossing_persists_exit_and_enter_pair(
        self,
    ) -> None:
        database_tracking_id = uuid4()
        camera_id = uuid4()
        origin_zone_id = uuid4()
        destination_zone_id = uuid4()
        transition_id = uuid4()
        session = FakeSession(
            SimpleNamespace(id=database_tracking_id, camera_id=camera_id),
            [None],
        )
        repository = PipelineRepository(lambda: session)

        created, payload = await repository.persist_crossing(
            database_tracking_id=database_tracking_id,
            person_id=None,
            crossing=CrossingEvent(
                transition_id,
                CrossingType.ENTER,
                "mixing-boundary",
                41,
                (35, 65),
                datetime.now(UTC),
                origin_zone_id=origin_zone_id,
                destination_zone_id=destination_zone_id,
            ),
            track=tracked(41),
            snapshot=None,
            snapshot_error="capture unavailable",
        )

        self.assertTrue(created)
        zone_events = [
            item for item in session.added if isinstance(item, ZoneEvent)
        ]
        self.assertEqual(len(zone_events), 2)
        self.assertEqual(
            {item.event_type for item in zone_events},
            {ZoneEventType.ZONE_EXIT, ZoneEventType.ZONE_ENTER},
        )
        self.assertEqual(
            {item.transition_id for item in zone_events},
            {transition_id},
        )
        self.assertEqual(
            payload["zone_transition"]["origin_zone_id"],
            str(origin_zone_id),
        )
        self.assertEqual(
            payload["zone_transition"]["destination_zone_id"],
            str(destination_zone_id),
        )

    async def test_enter_persists_legacy_and_phase3_evidence_atomically(
        self,
    ) -> None:
        database_tracking_id = uuid4()
        camera_id = uuid4()
        event_id = uuid4()
        session = FakeSession(
            SimpleNamespace(id=database_tracking_id, camera_id=camera_id),
            [None, None, None, None],
        )
        repository = PipelineRepository(lambda: session)
        image = Path("/tmp/phase3-annotated.jpg")
        metadata = Path("/tmp/phase3-metadata.json")
        evidence_file = EvidenceFile(
            asset_id=uuid4(),
            asset_type=EvidenceAssetType.ANNOTATED_SNAPSHOT,
            sequence_index=0,
            storage_key="2026/07/24/annotated.jpg",
            path=image,
            checksum_sha256="a" * 64,
            mime_type="image/jpeg",
            size_bytes=123,
            is_primary=True,
        )
        snapshot = SnapshotResult(
            snapshot_id=uuid4(),
            image_path=image,
            metadata_path=metadata,
            capture_event_id=event_id,
            idempotency_key=f"crossing:{event_id}",
            assets=(evidence_file,),
        )

        created, payload = await repository.persist_crossing(
            database_tracking_id=database_tracking_id,
            person_id=uuid4(),
            crossing=CrossingEvent(
                event_id,
                CrossingType.ENTER,
                "door",
                7,
                (35, 65),
                datetime.now(UTC),
            ),
            track=tracked(7),
            snapshot=snapshot,
            snapshot_error=None,
        )

        self.assertTrue(created)
        self.assertEqual(payload["capture_event_id"], str(event_id))
        self.assertEqual(payload["capture_status"], "QUEUED")
        self.assertIsNotNone(payload["processing_job_id"])
        captures = [
            item for item in session.added if isinstance(item, CaptureEvent)
        ]
        assets = [
            item for item in session.added if isinstance(item, EvidenceAsset)
        ]
        self.assertEqual(len(captures), 1)
        self.assertEqual(captures[0].idempotency_key, f"crossing:{event_id}")
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0].checksum_sha256, "a" * 64)
        jobs = [
            item
            for item in session.added
            if isinstance(item, AIProcessingJob)
        ]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(
            jobs[0].idempotency_key, f"capture-ingestion:{event_id}"
        )

    async def test_orphan_exit_is_suppressed(self) -> None:
        database_tracking_id = uuid4()
        session = FakeSession(
            SimpleNamespace(id=database_tracking_id, camera_id=uuid4()),
            [None, None, None],
        )
        repository = PipelineRepository(lambda: session)

        created, payload = await repository.persist_crossing(
            database_tracking_id=database_tracking_id,
            person_id=uuid4(),
            crossing=CrossingEvent(
                uuid4(), CrossingType.EXIT, "door", 9, (35, 65), datetime.now(UTC)
            ),
            track=tracked(9),
            snapshot=None,
            snapshot_error=None,
        )

        self.assertFalse(created)
        self.assertEqual(payload["reason"], "orphan_exit")
        self.assertTrue(payload["discard_snapshot"])
        self.assertEqual(session.added, [])

    async def test_exit_with_changed_identity_closes_oldest_camera_presence(self) -> None:
        database_tracking_id = uuid4()
        camera_id = uuid4()
        open_presence = SimpleNamespace(
            id=uuid4(),
            person_id=uuid4(),
            camera_id=camera_id,
            status=PresenceStatus.ACTIVE,
            entered_at=datetime.now(UTC),
            exit_tracking_id=None,
            exit_event_id=None,
            exited_at=None,
            uncertain_since=None,
            last_confirmed_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session = FakeSession(
            SimpleNamespace(id=database_tracking_id, camera_id=camera_id),
            [None, None, open_presence, None, None],
        )
        repository = PipelineRepository(lambda: session)

        created, payload = await repository.persist_crossing(
            database_tracking_id=database_tracking_id,
            person_id=uuid4(),
            crossing=CrossingEvent(
                uuid4(), CrossingType.EXIT, "door", 12, (35, 65), datetime.now(UTC)
            ),
            track=tracked(12),
            snapshot=None,
            snapshot_error=None,
        )

        self.assertTrue(created)
        self.assertTrue(session.committed)
        self.assertEqual(payload["event_type"], "EXIT")
        self.assertEqual(open_presence.status, PresenceStatus.CLOSED)
        event = session.added[0]
        self.assertEqual(event.event_metadata["presence_match"], "CAMERA_FIFO")
        self.assertEqual(
            event.event_metadata["matched_presence_person_id"],
            str(open_presence.person_id),
        )


if __name__ == "__main__":
    unittest.main()
