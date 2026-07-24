import asyncio
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.detector import Detection
from app.services.crossing_service import CrossingEvent, CrossingType
from app.services.realtime_pipeline import CameraRealtimePipeline
from app.storage import SnapshotResult
from app.tracker import TrackedDetection


class PipelineSettings:
    ai_pipeline_fps = 60.0
    ai_person_class_id = 0
    ai_tracking_persist_interval_seconds = 0.001
    ai_track_inactive_frames = 3
    ai_event_retry_queue_size = 10
    reid_min_crop_width = 10
    reid_min_crop_height = 10
    reid_min_quality_score = 0.45
    storage_path = "storage"


class FakeDetector:
    def predict(self, _frame: object) -> list[Detection]:
        return [Detection((10, 10, 70, 150), 0.95, 0, "person", (40, 80))]


class FakeTracker:
    def __init__(self) -> None:
        self.calls = 0
        self.reset_called = False

    def update(self, _detections: object) -> list[TrackedDetection]:
        self.calls += 1
        centroid = (40.0, 80.0 + self.calls * 30)
        return [
            TrackedDetection(
                7,
                (10, 10, 70, 150),
                0.95,
                0,
                "person",
                centroid,
                "down",
                (centroid,),
            )
        ]

    def reset(self) -> None:
        self.reset_called = True


class FakeReIdentification:
    def crop_person(self, _frame: object, _bbox: object) -> object:
        return object()

    def extract_embedding(self, _crop: object) -> tuple[float, ...]:
        return (1.0,) + (0.0,) * 511

    def quality_score(self, _crop: object, *, detector_confidence: float) -> float:
        return detector_confidence


class FakeCrossing:
    def __init__(self) -> None:
        self.calls = 0

    def process(
        self, tracks: list[TrackedDetection], **_fields: object
    ) -> list[CrossingEvent]:
        self.calls += 1
        if self.calls != 2:
            return []
        return [
            CrossingEvent(
                uuid4(),
                CrossingType.ENTER,
                "door",
                tracks[0].tracking_id,
                tracks[0].centroid,
                datetime.now(UTC),
            )
        ]

    def reset(self) -> None:
        pass


class FakeSnapshots:
    def __init__(self, root: Path) -> None:
        self.root = root

    async def save_async(self, _frame: object, _event: object, _track: object, **_kwargs: object) -> SnapshotResult:
        image = self.root / "event.jpg"
        metadata = self.root / "event.json"
        image.write_bytes(b"jpeg")
        metadata.write_text("{}", encoding="utf-8")
        return SnapshotResult(uuid4(), image, metadata)


class FakePersistence:
    def __init__(
        self,
        person_id: UUID,
        *,
        fail_event_once: bool = False,
        reject_event: bool = False,
    ) -> None:
        self.person_id = person_id
        self.database_tracking_id = uuid4()
        self.started = 0
        self.persisted = 0
        self.closed = 0
        self.fail_event_once = fail_event_once
        self.reject_event = reject_event

    async def close_camera_trackings(self, _camera_id: UUID) -> None:
        pass

    async def identify_person(self, _service: object, _embedding: object, **_fields: object) -> object:
        return SimpleNamespace(person_id=self.person_id, embedding_id=uuid4())

    async def link_embedding(self, _embedding_id: UUID, _tracking_id: UUID) -> None:
        pass

    async def start_tracking(self, **_fields: object) -> UUID:
        self.started += 1
        return self.database_tracking_id

    async def confirm_person_presence(self, *_args: object, **_fields: object) -> None:
        pass

    async def mark_camera_presence_uncertain(self, *_args: object, **_fields: object) -> dict[str, int]:
        return {"confirmed": 0, "uncertain": 1, "total": 0}

    async def update_trackings(
        self, _updates: object, **_fields: object
    ) -> None:
        pass

    async def persist_crossing(self, **fields: object) -> tuple[bool, dict]:
        if self.fail_event_once:
            self.fail_event_once = False
            raise RuntimeError("temporary database outage")
        if self.reject_event:
            return False, {"reason": "orphan_exit", "discard_snapshot": True}
        self.persisted += 1
        crossing = fields["crossing"]
        snapshot = fields["snapshot"]
        return True, {
            "id": str(crossing.event_id),
            "event_type": crossing.event_type.value,
            "snapshot_id": str(snapshot.snapshot_id) if snapshot else None,
        }

    async def current_occupancy(self) -> dict[str, int]:
        return {"confirmed": 1, "uncertain": 0, "total": 1}

    async def close_trackings(self, tracking_ids: list[UUID], **_fields: object) -> None:
        self.closed += len(tracking_ids)

    @staticmethod
    def remove_snapshot(snapshot: SnapshotResult | None) -> None:
        if snapshot is None:
            return
        snapshot.image_path.unlink(missing_ok=True)
        snapshot.metadata_path.unlink(missing_ok=True)


class RealtimePipelineTest(unittest.IsolatedAsyncioTestCase):
    async def _pipeline(
        self,
        root: Path,
        *,
        fail_event_once: bool = False,
        reject_event: bool = False,
    ) -> tuple[CameraRealtimePipeline, FakePersistence, FakeTracker]:
        settings = PipelineSettings()
        settings.storage_path = str(root)
        persistence = FakePersistence(
            uuid4(),
            fail_event_once=fail_event_once,
            reject_event=reject_event,
        )
        tracker = FakeTracker()
        pipeline = CameraRealtimePipeline(
            camera_id=uuid4(),
            settings=settings,
            detector=FakeDetector(),
            tracker=tracker,
            reidentification=FakeReIdentification(),
            crossing=FakeCrossing(),
            snapshots=FakeSnapshots(root),
            persistence=persistence,
            inference_semaphore=asyncio.Semaphore(1),
        )
        await pipeline.start()
        return pipeline, persistence, tracker

    async def test_runs_detection_tracking_reid_crossing_snapshot_and_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, persistence, tracker = await self._pipeline(Path(directory))
            first = await pipeline.process(SimpleNamespace())
            await asyncio.sleep(0.02)
            second = await pipeline.process(SimpleNamespace())

            self.assertTrue(first.processed)
            self.assertEqual(persistence.started, 1)
            self.assertEqual(second.tracks[0]["tracking_id"], 7)
            self.assertEqual(second.events[0]["event_type"], "ENTER")
            self.assertIsNotNone(second.events[0]["snapshot_id"])
            self.assertNotIn("snapshot_url", second.events[0])
            self.assertNotIn("snapshot_path", second.events[0])
            self.assertEqual(second.occupancy["total"], 1)
            self.assertEqual(persistence.persisted, 1)
            self.assertTrue((Path(directory) / "event.jpg").is_file())

            await pipeline.stop()
            self.assertTrue(tracker.reset_called)
            self.assertEqual(persistence.closed, 1)

    async def test_retries_event_after_temporary_database_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, persistence, _tracker = await self._pipeline(
                Path(directory), fail_event_once=True
            )
            await pipeline.process(SimpleNamespace())
            await asyncio.sleep(0.02)
            failed = await pipeline.process(SimpleNamespace())
            self.assertEqual(failed.events, [])

            await asyncio.sleep(0.02)
            retried = await pipeline.process(SimpleNamespace())
            self.assertEqual(retried.events[0]["event_type"], "ENTER")
            self.assertIsNotNone(retried.events[0]["snapshot_id"])
            self.assertNotIn("snapshot_url", retried.events[0])
            self.assertNotIn("snapshot_path", retried.events[0])
            self.assertEqual(persistence.persisted, 1)

    async def test_rejected_crossing_removes_unpersisted_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, persistence, _tracker = await self._pipeline(
                Path(directory), reject_event=True
            )
            await pipeline.process(SimpleNamespace())
            await asyncio.sleep(0.02)
            result = await pipeline.process(SimpleNamespace())

            self.assertEqual(result.events, [])
            self.assertEqual(persistence.persisted, 0)
            self.assertFalse((Path(directory) / "event.jpg").exists())
            self.assertFalse((Path(directory) / "event.json").exists())


if __name__ == "__main__":
    unittest.main()
