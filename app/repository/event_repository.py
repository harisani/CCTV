from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Camera, Event, Snapshot, Tracking
from app.repository.base import BaseRepository


class EventRepository(BaseRepository[Event]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Event)

    async def list_by_camera(self, camera_id: UUID, *, offset: int = 0, limit: int = 100) -> list[Event]:
        statement = (
            select(Event)
            .join(Tracking)
            .where(Tracking.camera_id == camera_id)
            .order_by(Event.occurred_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).all())

    async def list_filtered(
        self,
        *,
        camera_id: UUID | None = None,
        event_type: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[tuple[Event, str | None, UUID, str, str | None]], int]:
        from sqlalchemy import func

        filters = []
        if camera_id is not None:
            filters.append(Tracking.camera_id == camera_id)
        if event_type is not None:
            filters.append(Event.event_type == event_type)
        if start_at is not None:
            filters.append(Event.occurred_at >= start_at)
        if end_at is not None:
            filters.append(Event.occurred_at <= end_at)
        event_statement = select(Event).join(Tracking).where(*filters)
        statement = (
            event_statement
            .outerjoin(Snapshot, Snapshot.event_id == Event.id)
            .join(Camera, Camera.id == Tracking.camera_id)
            .add_columns(Snapshot.image_path, Tracking.camera_id, Camera.name, Camera.location)
        )
        items = list((await self.session.execute(statement.order_by(Event.occurred_at.desc()).offset(offset).limit(limit))).all())
        total = await self.session.scalar(select(func.count()).select_from(event_statement.subquery()))
        return items, total or 0
