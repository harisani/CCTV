from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    AccessCameraMatch,
    AccessDirection,
    AccessEvent,
    AccessEventStatus,
    AccessMatchStatus,
)
from app.repository.base import BaseRepository


class AccessEventRepository(BaseRepository[AccessEvent]):
    """Async queries for RFID observations and their verification state."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AccessEvent)

    async def get_by_external_id(
        self,
        *,
        reader_id: UUID,
        external_event_id: str,
    ) -> AccessEvent | None:
        statement = select(AccessEvent).where(
            AccessEvent.reader_id == reader_id,
            AccessEvent.external_event_id == external_event_id.strip(),
        )
        return await self.session.scalar(statement)

    async def get_by_external_id_with_relations(
        self,
        *,
        reader_id: UUID,
        external_event_id: str,
    ) -> AccessEvent | None:
        statement = (
            select(AccessEvent)
            .options(
                selectinload(AccessEvent.reader),
                selectinload(AccessEvent.card),
                selectinload(AccessEvent.employee),
            )
            .where(
                AccessEvent.reader_id == reader_id,
                AccessEvent.external_event_id == external_event_id.strip(),
            )
        )
        return await self.session.scalar(statement)

    async def list_pending(
        self,
        *,
        at: datetime | None = None,
        limit: int = 100,
        lock: bool = False,
    ) -> list[AccessEvent]:
        checked_at = at or datetime.now(UTC)
        statement = (
            select(AccessEvent)
            .where(
                AccessEvent.status == AccessEventStatus.PENDING,
                AccessEvent.expires_at > checked_at,
            )
            .order_by(AccessEvent.occurred_at, AccessEvent.id)
            .limit(limit)
        )
        if lock:
            statement = statement.with_for_update(skip_locked=True)
        return list((await self.session.scalars(statement)).all())

    async def list_filtered(
        self,
        *,
        employee_id: UUID | None = None,
        reader_id: UUID | None = None,
        direction: AccessDirection | None = None,
        event_status: AccessEventStatus | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[AccessEvent], int]:
        statement = select(AccessEvent).options(
            selectinload(AccessEvent.reader),
            selectinload(AccessEvent.card),
            selectinload(AccessEvent.employee),
        )
        if employee_id is not None:
            statement = statement.where(AccessEvent.employee_id == employee_id)
        if reader_id is not None:
            statement = statement.where(AccessEvent.reader_id == reader_id)
        if direction is not None:
            statement = statement.where(AccessEvent.direction == direction)
        if event_status is not None:
            statement = statement.where(AccessEvent.status == event_status)
        if start_at is not None:
            statement = statement.where(AccessEvent.occurred_at >= start_at)
        if end_at is not None:
            statement = statement.where(AccessEvent.occurred_at <= end_at)

        total = int(
            await self.session.scalar(select(func.count()).select_from(statement.subquery()))
            or 0
        )
        page = (
            statement.order_by(AccessEvent.occurred_at.desc(), AccessEvent.id)
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(page)).all()), total


class AccessCameraMatchRepository(BaseRepository[AccessCameraMatch]):
    """Persistence boundary for camera candidates considered for an RFID tap."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AccessCameraMatch)

    async def list_for_access_event(
        self,
        access_event_id: UUID,
    ) -> list[AccessCameraMatch]:
        statement = (
            select(AccessCameraMatch)
            .where(AccessCameraMatch.access_event_id == access_event_id)
            .order_by(
                AccessCameraMatch.match_score.desc(),
                AccessCameraMatch.created_at,
            )
        )
        return list((await self.session.scalars(statement)).all())

    async def get_selected(
        self,
        access_event_id: UUID,
    ) -> AccessCameraMatch | None:
        statement = select(AccessCameraMatch).where(
            AccessCameraMatch.access_event_id == access_event_id,
            AccessCameraMatch.status == AccessMatchStatus.SELECTED,
        )
        return await self.session.scalar(statement)
