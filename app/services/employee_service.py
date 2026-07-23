"""Employee lifecycle and RFID credential registration rules."""

from __future__ import annotations

import csv
import io
import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.models import Employee, RFIDCard, RFIDCardStatus, User
from app.repository import AuditRepository, EmployeeRepository, RFIDCardRepository


class EmployeeService:
    """Coordinate employee and RFID persistence inside one transaction boundary."""

    def __init__(
        self,
        employees: EmployeeRepository,
        cards: RFIDCardRepository,
        audit: AuditRepository | None = None,
    ) -> None:
        if employees.session is not cards.session:
            raise ValueError("Employee and RFID repositories must share one session")
        self.employees = employees
        self.cards = cards
        self.audit = audit or AuditRepository(employees.session)

    async def create_employee(self, payload: Any, actor: User) -> Employee:
        employee_number = payload.employee_number.strip().upper()
        if await self.employees.get_by_employee_number(employee_number):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Nomor pegawai sudah digunakan.",
            )
        employee = Employee(
            employee_number=employee_number,
            full_name=payload.full_name.strip(),
            department=self._optional_text(payload.department),
            is_active=payload.is_active,
        )
        await self.employees.add(employee)
        await self.audit.record(
            actor_user_id=actor.id,
            action="EMPLOYEE_CREATED",
            resource_type="employee",
            resource_id=str(employee.id),
            details={
                "employee_number": employee.employee_number,
                "department": employee.department,
            },
        )
        await self._commit("Pegawai tidak dapat dibuat karena terjadi konflik data.")
        return employee

    async def update_employee(
        self,
        employee: Employee,
        payload: Any,
        actor: User,
    ) -> Employee:
        changes = payload.model_dump(exclude_unset=True)
        if "employee_number" in changes:
            candidate = changes["employee_number"].strip().upper()
            existing = await self.employees.get_by_employee_number(candidate)
            if existing is not None and existing.id != employee.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Nomor pegawai sudah digunakan.",
                )
            changes["employee_number"] = candidate
        if "full_name" in changes:
            changes["full_name"] = changes["full_name"].strip()
        if "department" in changes:
            changes["department"] = self._optional_text(changes["department"])
        for field, value in changes.items():
            setattr(employee, field, value)
        await self.audit.record(
            actor_user_id=actor.id,
            action="EMPLOYEE_UPDATED",
            resource_type="employee",
            resource_id=str(employee.id),
            details={"fields": sorted(changes)},
        )
        await self._commit("Pegawai tidak dapat diperbarui karena terjadi konflik data.")
        await self.employees.session.refresh(employee)
        return employee

    async def import_employees_csv(
        self,
        content: bytes,
        actor: User,
    ) -> tuple[int, int]:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="File CSV harus menggunakan encoding UTF-8.",
            ) from error
        reader = csv.DictReader(io.StringIO(text))
        headers = {header.strip() for header in (reader.fieldnames or []) if header}
        missing = {"employee_number", "full_name"} - headers
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Header CSV wajib memuat employee_number dan full_name. "
                    f"Kolom yang belum ada: {', '.join(sorted(missing))}."
                ),
            )
        reader.fieldnames = [
            header.strip() if header else header for header in (reader.fieldnames or [])
        ]

        prepared: list[dict[str, Any]] = []
        problems: list[str] = []
        seen_numbers: set[str] = set()
        for row_number, row in enumerate(reader, start=2):
            if row_number > 5001:
                problems.append("File melebihi batas 5.000 pegawai.")
                break
            employee_number = (row.get("employee_number") or "").strip().upper()
            full_name = (row.get("full_name") or "").strip()
            department = self._optional_text(row.get("department"))
            try:
                is_active = self._parse_boolean(row.get("is_active"))
            except ValueError:
                problems.append(
                    f"Baris {row_number}: is_active harus true/false, 1/0, aktif/nonaktif."
                )
                continue
            if not employee_number or not re.fullmatch(r"[A-Z0-9._/-]+", employee_number):
                problems.append(f"Baris {row_number}: employee_number tidak valid.")
                continue
            if len(employee_number) > 80:
                problems.append(f"Baris {row_number}: employee_number melebihi 80 karakter.")
                continue
            if len(full_name) < 2 or len(full_name) > 150:
                problems.append(f"Baris {row_number}: full_name harus 2–150 karakter.")
                continue
            if department is not None and len(department) > 120:
                problems.append(f"Baris {row_number}: department melebihi 120 karakter.")
                continue
            if employee_number in seen_numbers:
                problems.append(
                    f"Baris {row_number}: employee_number {employee_number} duplikat di file."
                )
                continue
            seen_numbers.add(employee_number)
            prepared.append(
                {
                    "employee_number": employee_number,
                    "full_name": full_name,
                    "department": department,
                    "is_active": is_active,
                }
            )

        if not prepared and not problems:
            problems.append("File CSV tidak memiliki baris pegawai.")
        existing = await self.employees.get_by_employee_numbers(
            [item["employee_number"] for item in prepared]
        )
        if existing:
            existing_numbers = ", ".join(
                sorted(item.employee_number for item in existing)[:10]
            )
            problems.append(f"Nomor pegawai sudah tersedia: {existing_numbers}.")
        if problems:
            summary = " ".join(problems[:10])
            if len(problems) > 10:
                summary += f" Terdapat {len(problems) - 10} masalah lainnya."
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=summary,
            )

        employees = [Employee(**item) for item in prepared]
        self.employees.session.add_all(employees)
        await self.employees.session.flush()
        await self.audit.record(
            actor_user_id=actor.id,
            action="EMPLOYEES_IMPORTED",
            resource_type="employee",
            resource_id=None,
            details={"imported_count": len(employees)},
        )
        await self._commit("Import pegawai gagal karena terjadi konflik data.")
        return len(employees), len(prepared)

    async def register_card(
        self,
        employee: Employee,
        payload: Any,
        actor: User,
    ) -> RFIDCard:
        if not employee.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Aktifkan pegawai sebelum mendaftarkan kartu.",
            )
        card_number = payload.card_number.strip().upper()
        if await self.cards.get_by_card_number(card_number):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Nomor kartu RFID sudah terdaftar.",
            )
        self._validate_validity_window(payload.valid_from, payload.valid_until)
        card = RFIDCard(
            employee_id=employee.id,
            card_number=card_number,
            label=self._optional_text(payload.label),
            status=payload.status,
            valid_from=payload.valid_from,
            valid_until=payload.valid_until,
        )
        await self.cards.add(card)
        await self.audit.record(
            actor_user_id=actor.id,
            action="RFID_CARD_REGISTERED",
            resource_type="rfid_card",
            resource_id=str(card.id),
            details={
                "employee_id": str(employee.id),
                "employee_number": employee.employee_number,
                "card_number_suffix": card.card_number[-4:],
                "status": card.status.value,
            },
        )
        await self._commit("Kartu RFID tidak dapat didaftarkan karena terjadi konflik data.")
        return card

    async def update_card(
        self,
        card: RFIDCard,
        payload: Any,
        actor: User,
    ) -> RFIDCard:
        changes = payload.model_dump(exclude_unset=True)
        if "label" in changes:
            changes["label"] = self._optional_text(changes["label"])
        valid_from = changes.get("valid_from", card.valid_from)
        valid_until = changes.get("valid_until", card.valid_until)
        self._validate_validity_window(valid_from, valid_until)
        for field, value in changes.items():
            setattr(card, field, value)
        await self.audit.record(
            actor_user_id=actor.id,
            action="RFID_CARD_UPDATED",
            resource_type="rfid_card",
            resource_id=str(card.id),
            details={
                "employee_id": str(card.employee_id),
                "fields": sorted(changes),
                "status": card.status.value,
            },
        )
        await self._commit("Kartu RFID tidak dapat diperbarui karena terjadi konflik data.")
        await self.cards.session.refresh(card)
        return card

    async def _commit(self, conflict_detail: str) -> None:
        try:
            await self.employees.session.commit()
        except IntegrityError as error:
            await self.employees.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=conflict_detail,
            ) from error

    @staticmethod
    def _validate_validity_window(valid_from: Any, valid_until: Any) -> None:
        if (
            valid_from is not None
            and valid_until is not None
            and valid_until < valid_from
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Masa berlaku akhir tidak boleh sebelum tanggal mulai.",
            )

    @staticmethod
    def _optional_text(value: str | None) -> str | None:
        normalized = value.strip() if value else None
        return normalized or None

    @staticmethod
    def _parse_boolean(value: str | None) -> bool:
        if value is None or not value.strip():
            return True
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes", "ya", "aktif"}:
            return True
        if normalized in {"false", "0", "no", "tidak", "nonaktif"}:
            return False
        raise ValueError("Invalid boolean value")
