import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.models import EventType, PresenceStatus
from app.services.presence_reconciliation_scheduler import PresenceReconciliationScheduler


class FakeScalarResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class FakeSession:
    def __init__(self, presence: object, camera: object) -> None:
        self._results = [FakeScalarResult([presence]), FakeScalarResult([camera])]
        self.added: list[object] = []
        self.committed = False

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def scalars(self, _query: object) -> FakeScalarResult:
        return self._results.pop(0)

    def add(self, value: object) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.committed = True


class PresenceReconciliationSchedulerTest(unittest.IsolatedAsyncioTestCase):
    async def test_closes_previous_day_presence_with_system_exit(self) -> None:
        camera_id = uuid4()
        presence = SimpleNamespace(
            id=uuid4(),
            person_id=uuid4(),
            camera_id=camera_id,
            entry_tracking_id=uuid4(),
            status=PresenceStatus.ACTIVE,
            entered_at=datetime(2026, 7, 21, 14, 0, tzinfo=UTC),
            exit_event_id=None,
            exit_tracking_id=None,
            exited_at=None,
            uncertain_since=None,
            updated_at=None,
        )
        camera = SimpleNamespace(id=camera_id, name="Lobby", location="Pintu utama")
        session = FakeSession(presence, camera)
        settings = SimpleNamespace(
            presence_timezone="Asia/Jakarta",
            presence_reconcile_interval_seconds=30,
        )
        scheduler = PresenceReconciliationScheduler(settings, lambda: session, SimpleNamespace())

        payloads = await scheduler.reconcile(datetime(2026, 7, 22, 1, 0, tzinfo=UTC))

        self.assertTrue(session.committed)
        self.assertEqual(presence.status, PresenceStatus.CLOSED)
        self.assertEqual(presence.exited_at, datetime(2026, 7, 21, 17, 0, tzinfo=UTC))
        self.assertEqual(session.added[0].event_type, EventType.EXIT)
        self.assertEqual(session.added[0].event_metadata["reason"], "MIDNIGHT_NO_EXIT")
        self.assertEqual(payloads[0]["camera_name"], "Lobby")
        self.assertTrue(payloads[0]["system_generated"])


if __name__ == "__main__":
    unittest.main()
