"""Development-only RFID reader simulator using production persistence boundaries."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.config.settings import Settings
from app.models import (
    AccessDirection,
    AccessEvent,
    AccessEventStatus,
    Employee,
    RFIDCard,
    RFIDCardStatus,
    RFIDReader,
    RFIDReaderDirection,
    User,
)
from app.repository import (
    AccessEventRepository,
    AuditRepository,
    EmployeeRepository,
    RFIDCardRepository,
    RFIDReaderRepository,
)

logger = logging.getLogger(__name__)


class RFIDSimulatorService:
    """Create deterministic virtual reader taps without bypassing application rules."""

    def __init__(
        self,
        settings: Settings,
        readers: RFIDReaderRepository,
        cards: RFIDCardRepository,
        employees: EmployeeRepository,
        events: AccessEventRepository,
        audit: AuditRepository | None = None,
    ) -> None:
        sessions = {
            id(readers.session),
            id(cards.session),
            id(employees.session),
            id(events.session),
        }
        if len(sessions) != 1:
            raise ValueError("RFID simulator repositories must share one session")
        self.settings = settings
        self.readers = readers
        self.cards = cards
        self.employees = employees
        self.events = events
        self.audit = audit or AuditRepository(events.session)

    def ensure_enabled(self) -> None:
        if not self.settings.enable_rfid_simulator:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "RFID simulator tidak aktif. Set ENABLE_RFID_SIMULATOR=true "
                    "hanya pada environment testing."
                ),
            )

    async def list_card_options(self, *, at: datetime | None = None) -> list[RFIDCard]:
        self.ensure_enabled()
        return await self.cards.list_active_with_employees(at=at, limit=500)

    async def simulate_tap(
        self,
        payload: Any,
        actor: User,
    ) -> tuple[AccessEvent, bool]:
        self.ensure_enabled()
        occurred_at = payload.occurred_at or datetime.now(UTC)
        reader = await self._get_or_create_reader()
        self._validate_reader_direction(reader, payload.direction)

        external_event_id = (
            f"sim:{payload.idempotency_key}"
            if payload.idempotency_key
            else f"sim:{uuid4()}"
        )
        existing = await self.events.get_by_external_id_with_relations(
            reader_id=reader.id,
            external_event_id=external_event_id,
        )
        if existing is not None:
            return existing, False

        card_number = payload.card_number.strip().upper()
        active_card = await self.cards.get_active_by_card_number(
            card_number,
            at=occurred_at,
        )
        known_card = active_card or await self.cards.get_by_card_number(card_number)
        employee = (
            await self.employees.get(known_card.employee_id)
            if known_card is not None
            else None
        )
        event_status, reason = self._resolve_event_status(
            active_card=active_card,
            known_card=known_card,
            employee=employee,
            occurred_at=occurred_at,
        )
        event = AccessEvent(
            reader_id=reader.id,
            card_id=known_card.id if known_card is not None else None,
            employee_id=employee.id if employee is not None else None,
            external_event_id=external_event_id,
            credential_identifier=card_number,
            direction=payload.direction,
            status=event_status,
            occurred_at=occurred_at,
            expires_at=occurred_at
            + timedelta(seconds=self.settings.rfid_simulator_event_ttl_seconds),
            status_reason=reason,
            raw_payload={
                "source": "rfid_simulator",
                "actor_user_id": str(actor.id),
                "actor_username": actor.username,
                "reader_code": reader.code,
            },
            reader=reader,
            card=known_card,
            employee=employee,
        )
        await self.events.add(event)
        await self.audit.record(
            actor_user_id=actor.id,
            action="RFID_SIMULATED_TAP",
            resource_type="access_event",
            resource_id=str(event.id),
            details={
                "reader_code": reader.code,
                "direction": payload.direction.value,
                "status": event_status.value,
                "card_number_suffix": card_number[-4:],
            },
        )
        reader_id = reader.id
        try:
            await self.events.session.commit()
        except IntegrityError as error:
            await self.events.session.rollback()
            duplicate = await self.events.get_by_external_id_with_relations(
                reader_id=reader.id,
                external_event_id=external_event_id,
            )
            if duplicate is not None:
                return duplicate, False
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tap virtual tidak dapat disimpan karena konflik data.",
            ) from error

        logger.info(
            "RFID simulator tap reader=%s direction=%s status=%s card_suffix=%s",
            reader.code,
            payload.direction.value,
            event_status.value,
            card_number[-4:],
        )
        persisted_event = await self.events.get_by_external_id_with_relations(
            reader_id=reader_id,
            external_event_id=external_event_id,
        )
        if persisted_event is None:
            raise RuntimeError(
                "RFID simulator event was committed but could not be reloaded"
            )
        return persisted_event, True

    async def list_events(
        self,
        *,
        direction: AccessDirection | None = None,
        event_status: AccessEventStatus | None = None,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[AccessEvent], int]:
        self.ensure_enabled()
        reader = await self.readers.get_by_code(
            self.settings.rfid_simulator_reader_code.upper()
        )
        if reader is None:
            return [], 0
        return await self.events.list_filtered(
            reader_id=reader.id,
            direction=direction,
            event_status=event_status,
            offset=offset,
            limit=limit,
        )

    async def _get_or_create_reader(self) -> RFIDReader:
        code = self.settings.rfid_simulator_reader_code.strip().upper()
        reader = await self.readers.get_by_code(code)
        if reader is not None:
            if not reader.enabled:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Reader simulator terdaftar tetapi sedang nonaktif.",
                )
            return reader

        reader = RFIDReader(
            code=code,
            name=self.settings.rfid_simulator_reader_name.strip(),
            location=self.settings.rfid_simulator_reader_location.strip() or None,
            direction=RFIDReaderDirection.BIDIRECTIONAL,
            enabled=True,
        )
        await self.readers.add(reader)
        logger.info("Created virtual RFID reader code=%s", code)
        return reader

    @staticmethod
    def _validate_reader_direction(
        reader: RFIDReader,
        direction: AccessDirection,
    ) -> None:
        if reader.direction == RFIDReaderDirection.BIDIRECTIONAL:
            return
        if reader.direction.value != direction.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Reader {reader.code} hanya menerima arah "
                    f"{reader.direction.value}."
                ),
            )

    @staticmethod
    def _resolve_event_status(
        *,
        active_card: RFIDCard | None,
        known_card: RFIDCard | None,
        employee: Employee | None,
        occurred_at: datetime,
    ) -> tuple[AccessEventStatus, str]:
        if active_card is not None:
            return (
                AccessEventStatus.PENDING,
                "Tap diterima dan menunggu korelasi dengan event kamera.",
            )
        if known_card is None:
            return AccessEventStatus.REJECTED, "Kartu RFID belum terdaftar."
        if employee is None or not employee.is_active:
            return AccessEventStatus.REJECTED, "Pegawai pemilik kartu sedang nonaktif."
        if known_card.status != RFIDCardStatus.ACTIVE:
            return (
                AccessEventStatus.REJECTED,
                f"Status kartu {known_card.status.value}.",
            )
        if known_card.valid_from is not None and known_card.valid_from > occurred_at:
            return AccessEventStatus.REJECTED, "Masa berlaku kartu belum dimulai."
        if known_card.valid_until is not None and known_card.valid_until < occurred_at:
            return AccessEventStatus.REJECTED, "Masa berlaku kartu sudah berakhir."
        return AccessEventStatus.REJECTED, "Kartu RFID tidak dapat digunakan."
