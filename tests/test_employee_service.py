import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.schemas import (
    EmployeeCreate,
    EmployeeUpdate,
    RFIDCardCreate,
    RFIDCardUpdate,
)
from app.app import create_app
from app.models import Employee, RFIDCard, RFIDCardStatus
from app.services.employee_service import EmployeeService


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.added_many: list[object] = []

    def add_all(self, values: list[object]) -> None:
        for value in values:
            if getattr(value, "id", None) is None:
                value.id = uuid4()
        self.added_many.extend(values)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def refresh(self, _value: object) -> None:
        return None


class FakeEmployeeRepository:
    def __init__(self, session: FakeSession, existing: list[Employee] | None = None) -> None:
        self.session = session
        self.existing = list(existing or [])
        self.added: list[Employee] = []

    async def get_by_employee_number(self, number: str) -> Employee | None:
        normalized = number.casefold()
        return next(
            (
                employee
                for employee in self.existing
                if employee.employee_number.casefold() == normalized
            ),
            None,
        )

    async def get_by_employee_numbers(self, numbers: list[str]) -> list[Employee]:
        normalized = {number.casefold() for number in numbers}
        return [
            employee
            for employee in self.existing
            if employee.employee_number.casefold() in normalized
        ]

    async def add(self, employee: Employee) -> Employee:
        if employee.id is None:
            employee.id = uuid4()
        self.added.append(employee)
        self.existing.append(employee)
        return employee


class FakeCardRepository:
    def __init__(self, session: FakeSession, existing: list[RFIDCard] | None = None) -> None:
        self.session = session
        self.existing = list(existing or [])
        self.added: list[RFIDCard] = []

    async def get_by_card_number(self, card_number: str) -> RFIDCard | None:
        return next(
            (card for card in self.existing if card.card_number == card_number),
            None,
        )

    async def add(self, card: RFIDCard) -> RFIDCard:
        if card.id is None:
            card.id = uuid4()
        self.added.append(card)
        self.existing.append(card)
        return card


class FakeAuditRepository:
    def __init__(self) -> None:
        self.records: list[dict] = []

    async def record(self, **values):
        self.records.append(values)
        return SimpleNamespace(**values)


def service(
    *,
    employees: list[Employee] | None = None,
    cards: list[RFIDCard] | None = None,
) -> tuple[EmployeeService, FakeSession, FakeEmployeeRepository, FakeCardRepository, FakeAuditRepository]:
    session = FakeSession()
    employee_repository = FakeEmployeeRepository(session, employees)
    card_repository = FakeCardRepository(session, cards)
    audit = FakeAuditRepository()
    return (
        EmployeeService(employee_repository, card_repository, audit),
        session,
        employee_repository,
        card_repository,
        audit,
    )


class EmployeeSchemaTest(unittest.TestCase):
    def test_card_number_is_normalized_and_timestamp_requires_timezone(self) -> None:
        payload = RFIDCardCreate(card_number=" 04aa-bb ")
        self.assertEqual(payload.card_number, "04AA-BB")

        with self.assertRaises(ValidationError):
            RFIDCardCreate(
                card_number="04AABB",
                valid_until=datetime(2026, 8, 1),
            )

    def test_employee_number_rejects_spaces(self) -> None:
        with self.assertRaises(ValidationError):
            EmployeeCreate(employee_number="EMP 001", full_name="Budi Santoso")

    def test_empty_or_null_patch_is_rejected(self) -> None:
        invalid_payloads = (
            (EmployeeUpdate, {}),
            (EmployeeUpdate, {"employee_number": None}),
            (EmployeeUpdate, {"full_name": None}),
            (EmployeeUpdate, {"is_active": None}),
            (RFIDCardUpdate, {}),
            (RFIDCardUpdate, {"status": None}),
        )
        for schema, payload in invalid_payloads:
            with self.subTest(schema=schema.__name__, payload=payload):
                with self.assertRaises(ValidationError):
                    schema.model_validate(payload)

    def test_openapi_exposes_employee_and_card_operations(self) -> None:
        paths = create_app().openapi()["paths"]
        self.assertIn("/api/v1/employees", paths)
        self.assertIn("/api/v1/employees/import", paths)
        self.assertIn("/api/v1/employees/{employee_id}/cards", paths)
        self.assertIn("/api/v1/employees/{employee_id}/cards/{card_id}", paths)


class EmployeeServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_employee_normalizes_and_audits(self) -> None:
        subject, session, employees, _, audit = service()
        actor = SimpleNamespace(id=uuid4())

        created = await subject.create_employee(
            EmployeeCreate(
                employee_number="emp-001",
                full_name=" Budi Santoso ",
                department=" Produksi ",
            ),
            actor,
        )

        self.assertEqual(created.employee_number, "EMP-001")
        self.assertEqual(created.full_name, "Budi Santoso")
        self.assertEqual(created.department, "Produksi")
        self.assertEqual(employees.added, [created])
        self.assertEqual(audit.records[0]["action"], "EMPLOYEE_CREATED")
        self.assertTrue(session.committed)

    async def test_duplicate_employee_number_is_rejected(self) -> None:
        existing = Employee(
            id=uuid4(),
            employee_number="EMP-001",
            full_name="Budi Santoso",
        )
        subject, session, _, _, audit = service(employees=[existing])

        with self.assertRaises(HTTPException) as raised:
            await subject.create_employee(
                EmployeeCreate(employee_number="emp-001", full_name="Andi Saputra"),
                SimpleNamespace(id=uuid4()),
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertFalse(session.committed)
        self.assertEqual(audit.records, [])

    async def test_inactive_employee_cannot_receive_new_card(self) -> None:
        employee = Employee(
            id=uuid4(),
            employee_number="EMP-002",
            full_name="Sari Wulandari",
            is_active=False,
        )
        subject, session, _, cards, _ = service(employees=[employee])

        with self.assertRaises(HTTPException) as raised:
            await subject.register_card(
                employee,
                RFIDCardCreate(card_number="04AABBCC"),
                SimpleNamespace(id=uuid4()),
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(cards.added, [])
        self.assertFalse(session.committed)

    async def test_register_card_normalizes_and_audits(self) -> None:
        employee = Employee(
            id=uuid4(),
            employee_number="EMP-003",
            full_name="Andi Saputra",
            is_active=True,
        )
        subject, session, _, cards, audit = service(employees=[employee])

        created = await subject.register_card(
            employee,
            RFIDCardCreate(card_number="04aa:bbcc", label=" Kartu utama "),
            SimpleNamespace(id=uuid4()),
        )

        self.assertEqual(created.card_number, "04AA:BBCC")
        self.assertEqual(created.label, "Kartu utama")
        self.assertEqual(cards.added, [created])
        self.assertEqual(audit.records[0]["action"], "RFID_CARD_REGISTERED")
        self.assertTrue(session.committed)

    async def test_update_card_rejects_invalid_combined_window(self) -> None:
        now = datetime.now(UTC)
        card = RFIDCard(
            id=uuid4(),
            employee_id=uuid4(),
            card_number="CARD-1",
            status=RFIDCardStatus.ACTIVE,
            valid_from=now,
            valid_until=now + timedelta(days=10),
        )
        subject, session, _, _, _ = service(cards=[card])

        with self.assertRaises(HTTPException) as raised:
            await subject.update_card(
                card,
                RFIDCardUpdate(valid_until=now - timedelta(days=1)),
                SimpleNamespace(id=uuid4()),
            )

        self.assertEqual(raised.exception.status_code, 422)
        self.assertFalse(session.committed)

    async def test_csv_import_is_atomic_and_audited(self) -> None:
        subject, session, _, _, audit = service()
        content = (
            "employee_number,full_name,department,is_active\n"
            "EMP-010,Maya Pratama,Produksi,true\n"
            "EMP-011,Dimas Ardi,Maintenance,aktif\n"
        ).encode()

        imported, total = await subject.import_employees_csv(
            content,
            SimpleNamespace(id=uuid4()),
        )

        self.assertEqual((imported, total), (2, 2))
        self.assertEqual(len(session.added_many), 2)
        self.assertEqual(audit.records[0]["action"], "EMPLOYEES_IMPORTED")
        self.assertTrue(session.committed)

    async def test_csv_import_rejects_duplicate_before_writing(self) -> None:
        subject, session, _, _, audit = service()
        content = (
            "employee_number,full_name\n"
            "EMP-020,Maya Pratama\n"
            "EMP-020,Dimas Ardi\n"
        ).encode()

        with self.assertRaises(HTTPException) as raised:
            await subject.import_employees_csv(
                content,
                SimpleNamespace(id=uuid4()),
            )

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(session.added_many, [])
        self.assertEqual(audit.records, [])

    async def test_update_employee_can_clear_department(self) -> None:
        employee = Employee(
            id=uuid4(),
            employee_number="EMP-030",
            full_name="Maya Pratama",
            department="Produksi",
            is_active=True,
        )
        subject, session, _, _, audit = service(employees=[employee])

        updated = await subject.update_employee(
            employee,
            EmployeeUpdate(department=None),
            SimpleNamespace(id=uuid4()),
        )

        self.assertIsNone(updated.department)
        self.assertTrue(session.committed)
        self.assertEqual(audit.records[0]["action"], "EMPLOYEE_UPDATED")


if __name__ == "__main__":
    unittest.main()
