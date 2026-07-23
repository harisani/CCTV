import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.api.dependencies import get_employee_repository
from app.database.base import Base
from app.models import (
    AccessCameraMatch,
    AccessDirection,
    AccessEvent,
    AccessEventStatus,
    AccessMatchStatus,
    Employee,
    RFIDCard,
    RFIDCardStatus,
    RFIDReader,
    RFIDReaderDirection,
)
from app.repository import (
    AccessCameraMatchRepository,
    AccessEventRepository,
    EmployeeRepository,
    RFIDCardRepository,
    RFIDReaderRepository,
)


class FakeScalarResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def all(self) -> list[object]:
        return self.values


class FakeSession:
    def __init__(
        self,
        *,
        scalar_results: list[object | None] | None = None,
        rows: list[object] | None = None,
    ) -> None:
        self.scalar_results = list(scalar_results or [])
        self.rows = list(rows or [])
        self.statements: list[object] = []

    async def scalar(self, statement: object) -> object | None:
        self.statements.append(statement)
        return self.scalar_results.pop(0) if self.scalar_results else None

    async def scalars(self, statement: object) -> FakeScalarResult:
        self.statements.append(statement)
        return FakeScalarResult(self.rows)


def postgres_sql(statement: object) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class RFIDModelTest(unittest.TestCase):
    def test_all_rfid_tables_are_registered(self) -> None:
        self.assertTrue(
            {
                "employees",
                "rfid_cards",
                "rfid_readers",
                "access_events",
                "access_camera_matches",
            }.issubset(Base.metadata.tables)
        )

    def test_employee_is_not_an_application_user(self) -> None:
        employee = Employee(
            employee_number="EMP-001",
            full_name="Budi Santoso",
            department="Produksi",
        )
        card = RFIDCard(
            employee=employee,
            card_number="04AABBCC",
            status=RFIDCardStatus.ACTIVE,
        )

        self.assertEqual(card.employee.employee_number, "EMP-001")
        self.assertNotIn("password_hash", Employee.__table__.columns)

    def test_access_event_supports_unknown_card_and_pending_verification(self) -> None:
        now = datetime.now(UTC)
        access_event = AccessEvent(
            reader_id=uuid4(),
            card_id=None,
            employee_id=None,
            external_event_id="device-event-1",
            credential_identifier="UNKNOWN-CARD",
            direction=AccessDirection.ENTER,
            status=AccessEventStatus.PENDING,
            occurred_at=now,
            expires_at=now + timedelta(seconds=15),
        )

        self.assertIsNone(access_event.employee_id)
        self.assertEqual(access_event.status, AccessEventStatus.PENDING)

    def test_database_has_unique_selected_match_guards(self) -> None:
        index_names = {index.name for index in AccessCameraMatch.__table__.indexes}

        self.assertIn(
            "uq_access_camera_matches_selected_access_event",
            index_names,
        )
        self.assertIn(
            "uq_access_camera_matches_selected_crossing_event",
            index_names,
        )
        self.assertEqual(AccessMatchStatus.SELECTED.value, "SELECTED")

    def test_reader_supports_fixed_and_bidirectional_modes(self) -> None:
        reader = RFIDReader(
            code="READER-01",
            name="Pintu Utama",
            direction=RFIDReaderDirection.BIDIRECTIONAL,
        )

        self.assertEqual(reader.direction, RFIDReaderDirection.BIDIRECTIONAL)


class RFIDRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_repository_types_are_bound_to_their_models(self) -> None:
        session = FakeSession()

        self.assertIs(EmployeeRepository(session).model_type, Employee)
        self.assertIs(RFIDCardRepository(session).model_type, RFIDCard)
        self.assertIs(RFIDReaderRepository(session).model_type, RFIDReader)
        self.assertIs(AccessEventRepository(session).model_type, AccessEvent)
        self.assertIs(
            AccessCameraMatchRepository(session).model_type,
            AccessCameraMatch,
        )

    async def test_pending_events_can_be_claimed_safely_by_parallel_workers(self) -> None:
        session = FakeSession(rows=[])
        repository = AccessEventRepository(session)

        await repository.list_pending(
            at=datetime(2026, 7, 23, tzinfo=UTC),
            limit=20,
            lock=True,
        )

        query = postgres_sql(session.statements[0])
        self.assertIn("access_events.status = 'PENDING'", query)
        self.assertIn("FOR UPDATE SKIP LOCKED", query)
        self.assertIn("LIMIT 20", query)

    async def test_external_event_lookup_is_scoped_to_reader(self) -> None:
        expected = object()
        session = FakeSession(scalar_results=[expected])
        repository = AccessEventRepository(session)
        reader_id = uuid4()

        result = await repository.get_by_external_id(
            reader_id=reader_id,
            external_event_id=" event-123 ",
        )

        query = postgres_sql(session.statements[0])
        self.assertIs(result, expected)
        self.assertIn(str(reader_id), query)
        self.assertIn("event-123", query)

    async def test_employee_filter_returns_page_and_total(self) -> None:
        employee = Employee(employee_number="EMP-001", full_name="Budi")
        session = FakeSession(scalar_results=[1], rows=[employee])
        repository = EmployeeRepository(session)

        items, total = await repository.list_filtered(
            search="Budi",
            department="Produksi",
            is_active=True,
            offset=0,
            limit=10,
        )

        self.assertEqual(items, [employee])
        self.assertEqual(total, 1)
        page_query = postgres_sql(session.statements[1])
        self.assertIn("lower(employees.department) = 'produksi'", page_query)
        self.assertIn("employees.is_active IS true", page_query)

    async def test_dependency_provider_injects_request_session(self) -> None:
        session = FakeSession()

        async def fake_get_session():
            yield session

        with patch("app.api.dependencies.get_session", fake_get_session):
            provider = get_employee_repository()
            repository = await anext(provider)
            await provider.aclose()

        self.assertIsInstance(repository, EmployeeRepository)
        self.assertIs(repository.session, session)


if __name__ == "__main__":
    unittest.main()
