from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Camera,
    Event,
    EventType,
    Person,
    PresenceSession,
    PresenceStatus,
    Snapshot,
    Tracking,
)


class StatisticsRepository:
    """Aggregate dashboard counts with optional camera and date filters."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def summary(
        self, *, camera_id: UUID | None, start_at: datetime | None, end_at: datetime | None
    ) -> dict[str, int]:
        event_filters = []
        if camera_id is not None:
            event_filters.append(Tracking.camera_id == camera_id)
        if start_at is not None:
            event_filters.append(Event.occurred_at >= start_at)
        if end_at is not None:
            event_filters.append(Event.occurred_at <= end_at)
        event_query = select(Event).join(Tracking).where(*event_filters).subquery()
        enter_count = await self.session.scalar(
            select(func.count()).select_from(event_query).where(event_query.c.event_type == EventType.ENTER)
        )
        exit_count = await self.session.scalar(
            select(func.count()).select_from(event_query).where(event_query.c.event_type == EventType.EXIT)
        )
        total_events = await self.session.scalar(select(func.count()).select_from(event_query))
        total_persons = await self.session.scalar(
            select(func.count()).select_from(Person).where(Person.is_active.is_(True))
        )
        total_cameras = await self.session.scalar(select(func.count()).select_from(Camera).where(Camera.enabled.is_(True)))
        total_snapshots = await self.session.scalar(select(func.count()).select_from(Snapshot))
        presence_filters = [
            PresenceSession.status.in_((PresenceStatus.ACTIVE, PresenceStatus.UNCERTAIN))
        ]
        if camera_id is not None:
            presence_filters.append(PresenceSession.camera_id == camera_id)
        confirmed_person_count = await self.session.scalar(
            select(func.count())
            .select_from(PresenceSession)
            .where(*presence_filters, PresenceSession.status == PresenceStatus.ACTIVE)
        )
        uncertain_person_count = await self.session.scalar(
            select(func.count())
            .select_from(PresenceSession)
            .where(*presence_filters, PresenceSession.status == PresenceStatus.UNCERTAIN)
        )
        current_person_count = confirmed_person_count or 0
        return {
            "enter_count": enter_count or 0,
            "exit_count": exit_count or 0,
            "total_events": total_events or 0,
            "total_persons": total_persons or 0,
            "total_cameras": total_cameras or 0,
            "total_snapshots": total_snapshots or 0,
            "current_person_count": current_person_count,
            "confirmed_person_count": confirmed_person_count or 0,
            "uncertain_person_count": uncertain_person_count or 0,
        }
