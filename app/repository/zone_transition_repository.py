"""Read models for local tracks and immutable zone transition events."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tracking, ZoneEvent, ZoneEventType
from app.repository.base import BaseRepository


class ZoneTransitionRepository(BaseRepository[ZoneEvent]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ZoneEvent)

    async def list_events(
        self,
        *,
        camera_id: UUID | None,
        zone_id: UUID | None,
        tracking_id: UUID | None,
        event_type: ZoneEventType | None,
        start_at: datetime | None,
        end_at: datetime | None,
        offset: int,
        limit: int,
    ) -> tuple[list[ZoneEvent], int]:
        statement = select(ZoneEvent)
        if camera_id is not None:
            statement = statement.where(ZoneEvent.camera_id == camera_id)
        if zone_id is not None:
            statement = statement.where(ZoneEvent.zone_id == zone_id)
        if tracking_id is not None:
            statement = statement.where(
                ZoneEvent.tracking_id == tracking_id
            )
        if event_type is not None:
            statement = statement.where(ZoneEvent.event_type == event_type)
        if start_at is not None:
            statement = statement.where(ZoneEvent.occurred_at >= start_at)
        if end_at is not None:
            statement = statement.where(ZoneEvent.occurred_at <= end_at)
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        page = (
            statement.order_by(ZoneEvent.occurred_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(page)).all()), int(total or 0)

    async def list_tracks(
        self,
        *,
        camera_id: UUID | None,
        person_id: UUID | None,
        active: bool | None,
        start_at: datetime | None,
        end_at: datetime | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Tracking], int]:
        statement = select(Tracking)
        if camera_id is not None:
            statement = statement.where(Tracking.camera_id == camera_id)
        if person_id is not None:
            statement = statement.where(Tracking.person_id == person_id)
        if active is not None:
            statement = statement.where(Tracking.is_active.is_(active))
        if start_at is not None:
            statement = statement.where(Tracking.started_at >= start_at)
        if end_at is not None:
            statement = statement.where(Tracking.started_at <= end_at)
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        page = (
            statement.order_by(Tracking.started_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(page)).all()), int(total or 0)
