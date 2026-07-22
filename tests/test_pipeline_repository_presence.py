import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.models import Event, PresenceStatus, Tracking
from app.repository.pipeline_repository import PipelineRepository
from app.services.crossing_service import CrossingEvent, CrossingType
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
    async def test_orphan_exit_is_suppressed(self) -> None:
        database_tracking_id = uuid4()
        session = FakeSession(
            SimpleNamespace(id=database_tracking_id, camera_id=uuid4()),
            [None, None],
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
            [None, open_presence],
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
