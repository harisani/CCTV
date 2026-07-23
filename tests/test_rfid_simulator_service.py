import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes.rfid_simulator import serialize_access_event
from app.api.schemas import RFIDSimulatorTapRequest
from app.app import create_app
from app.models import (
    AccessDirection,
    AccessEvent,
    AccessEventStatus,
    Employee,
    RFIDCard,
    RFIDCardStatus,
    RFIDReader,
    RFIDReaderDirection,
)
from app.services.rfid_simulator_service import RFIDSimulatorService


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeReaderRepository:
    def __init__(self, session: FakeSession, reader: RFIDReader | None = None) -> None:
        self.session = session
        self.reader = reader

    async def get_by_code(self, code: str) -> RFIDReader | None:
        if self.reader and self.reader.code == code:
            return self.reader
        return None

    async def add(self, reader: RFIDReader) -> RFIDReader:
        reader.id = reader.id or uuid4()
        self.reader = reader
        return reader


class FakeCardRepository:
    def __init__(
        self,
        session: FakeSession,
        card: RFIDCard | None = None,
        active: bool = True,
    ) -> None:
        self.session = session
        self.card = card
        self.active = active

    async def get_active_by_card_number(self, number: str, *, at: datetime):
        if self.card and self.card.card_number == number and self.active:
            return self.card
        return None

    async def get_by_card_number(self, number: str):
        return self.card if self.card and self.card.card_number == number else None

    async def list_active_with_employees(self, *, at=None, limit=200):
        return [self.card] if self.card and self.active else []


class FakeEmployeeRepository:
    def __init__(self, session: FakeSession, employee: Employee | None = None) -> None:
        self.session = session
        self.employee = employee

    async def get(self, employee_id):
        if self.employee and self.employee.id == employee_id:
            return self.employee
        return None


class FakeEventRepository:
    def __init__(self, session: FakeSession, existing: AccessEvent | None = None) -> None:
        self.session = session
        self.existing = existing
        self.added: list[AccessEvent] = []

    async def get_by_external_id_with_relations(self, *, reader_id, external_event_id):
        if (
            self.existing
            and self.existing.reader_id == reader_id
            and self.existing.external_event_id == external_event_id
        ):
            return self.existing
        return None

    async def add(self, event: AccessEvent) -> AccessEvent:
        event.id = event.id or uuid4()
        self.added.append(event)
        self.existing = event
        return event

    async def list_filtered(self, **_kwargs):
        return self.added, len(self.added)


class FakeAuditRepository:
    def __init__(self) -> None:
        self.records: list[dict] = []

    async def record(self, **values):
        self.records.append(values)
        return SimpleNamespace(**values)


def make_settings(*, enabled: bool = True):
    return SimpleNamespace(
        enable_rfid_simulator=enabled,
        rfid_simulator_reader_code="SIM-READER-01",
        rfid_simulator_reader_name="Simulator Pintu Utama",
        rfid_simulator_reader_location="Pintu Utama",
        rfid_simulator_event_ttl_seconds=30,
    )


def make_service(
    *,
    enabled: bool = True,
    card_status: RFIDCardStatus = RFIDCardStatus.ACTIVE,
    employee_active: bool = True,
    card_active: bool = True,
    reader: RFIDReader | None = None,
    existing_event: AccessEvent | None = None,
):
    session = FakeSession()
    employee = Employee(
        id=uuid4(),
        employee_number="EMP-001",
        full_name="Budi Santoso",
        is_active=employee_active,
    )
    card = RFIDCard(
        id=uuid4(),
        employee_id=employee.id,
        card_number="04AABBCC",
        status=card_status,
        employee=employee,
    )
    readers = FakeReaderRepository(session, reader)
    cards = FakeCardRepository(session, card, card_active)
    employees = FakeEmployeeRepository(session, employee)
    events = FakeEventRepository(session, existing_event)
    audit = FakeAuditRepository()
    subject = RFIDSimulatorService(
        make_settings(enabled=enabled),
        readers,
        cards,
        employees,
        events,
        audit,
    )
    return subject, session, readers, events, audit


class RFIDSimulatorSchemaTest(unittest.TestCase):
    def test_simulator_schema_normalizes_uid_and_requires_timezone(self) -> None:
        payload = RFIDSimulatorTapRequest(
            card_number=" 04aa:bbcc ",
            direction=AccessDirection.ENTER,
        )
        self.assertEqual(payload.card_number, "04AA:BBCC")

        with self.assertRaises(ValidationError):
            RFIDSimulatorTapRequest(
                card_number="04AABBCC",
                direction=AccessDirection.ENTER,
                occurred_at=datetime(2026, 7, 23, 10, 0),
            )

    def test_openapi_exposes_simulator_operations(self) -> None:
        paths = create_app().openapi()["paths"]
        self.assertIn("/api/v1/rfid/simulator/options", paths)
        self.assertIn("/api/v1/rfid/simulator/tap", paths)
        self.assertIn("/api/v1/rfid/simulator/events", paths)


class RFIDSimulatorServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_simulator_is_rejected(self) -> None:
        subject, *_ = make_service(enabled=False)
        with self.assertRaises(HTTPException) as raised:
            await subject.list_card_options()
        self.assertEqual(raised.exception.status_code, 403)

    async def test_active_card_creates_pending_event_and_audit(self) -> None:
        subject, session, readers, events, audit = make_service()
        actor = SimpleNamespace(id=uuid4(), username="admin")

        event, created = await subject.simulate_tap(
            RFIDSimulatorTapRequest(
                card_number="04aabbcc",
                direction=AccessDirection.ENTER,
                idempotency_key="test-tap-0001",
            ),
            actor,
        )

        self.assertTrue(created)
        self.assertEqual(event.status, AccessEventStatus.PENDING)
        self.assertEqual(event.employee.employee_number, "EMP-001")
        self.assertEqual(event.raw_payload["source"], "rfid_simulator")
        self.assertEqual(readers.reader.code, "SIM-READER-01")
        self.assertEqual(events.added, [event])
        self.assertEqual(audit.records[0]["action"], "RFID_SIMULATED_TAP")
        self.assertEqual(session.commits, 1)

    async def test_unknown_card_is_recorded_as_rejected(self) -> None:
        subject, _, _, _, _ = make_service()
        subject.cards.card = None

        event, created = await subject.simulate_tap(
            RFIDSimulatorTapRequest(
                card_number="UNKNOWN01",
                direction=AccessDirection.EXIT,
            ),
            SimpleNamespace(id=uuid4(), username="admin"),
        )

        self.assertTrue(created)
        self.assertEqual(event.status, AccessEventStatus.REJECTED)
        self.assertIsNone(event.card_id)
        self.assertIn("belum terdaftar", event.status_reason)

    async def test_blocked_card_is_rejected_with_reason(self) -> None:
        subject, *_ = make_service(
            card_status=RFIDCardStatus.BLOCKED,
            card_active=False,
        )
        event, _ = await subject.simulate_tap(
            RFIDSimulatorTapRequest(
                card_number="04AABBCC",
                direction=AccessDirection.ENTER,
            ),
            SimpleNamespace(id=uuid4(), username="admin"),
        )
        self.assertEqual(event.status, AccessEventStatus.REJECTED)
        self.assertEqual(event.status_reason, "Status kartu BLOCKED.")

    async def test_same_idempotency_key_returns_existing_event(self) -> None:
        reader = RFIDReader(
            id=uuid4(),
            code="SIM-READER-01",
            name="Simulator",
            direction=RFIDReaderDirection.BIDIRECTIONAL,
            enabled=True,
        )
        employee = Employee(
            id=uuid4(),
            employee_number="EMP-009",
            full_name="Sari Wulandari",
        )
        existing = AccessEvent(
            id=uuid4(),
            reader_id=reader.id,
            external_event_id="sim:test-tap-0009",
            credential_identifier="04AABBCC",
            direction=AccessDirection.ENTER,
            status=AccessEventStatus.PENDING,
            occurred_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(seconds=30),
            reader=reader,
            employee=employee,
        )
        subject, session, _, events, audit = make_service(
            reader=reader,
            existing_event=existing,
        )

        event, created = await subject.simulate_tap(
            RFIDSimulatorTapRequest(
                card_number="04AABBCC",
                direction=AccessDirection.ENTER,
                idempotency_key="test-tap-0009",
            ),
            SimpleNamespace(id=uuid4(), username="admin"),
        )

        self.assertFalse(created)
        self.assertIs(event, existing)
        self.assertEqual(events.added, [])
        self.assertEqual(audit.records, [])
        self.assertEqual(session.commits, 0)

    async def test_reader_direction_mismatch_is_rejected(self) -> None:
        reader = RFIDReader(
            id=uuid4(),
            code="SIM-READER-01",
            name="Simulator Masuk",
            direction=RFIDReaderDirection.ENTER,
            enabled=True,
        )
        subject, *_ = make_service(reader=reader)
        with self.assertRaises(HTTPException) as raised:
            await subject.simulate_tap(
                RFIDSimulatorTapRequest(
                    card_number="04AABBCC",
                    direction=AccessDirection.EXIT,
                ),
                SimpleNamespace(id=uuid4(), username="admin"),
            )
        self.assertEqual(raised.exception.status_code, 409)

    async def test_serialized_event_marks_simulator_source(self) -> None:
        subject, *_ = make_service()
        event, _ = await subject.simulate_tap(
            RFIDSimulatorTapRequest(
                card_number="04AABBCC",
                direction=AccessDirection.ENTER,
            ),
            SimpleNamespace(id=uuid4(), username="admin"),
        )
        response = serialize_access_event(event)
        self.assertTrue(response.simulated)
        self.assertEqual(response.employee_number, "EMP-001")
