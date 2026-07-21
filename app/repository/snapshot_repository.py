from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Snapshot, Tracking
from app.repository.base import BaseRepository


class SnapshotRepository(BaseRepository[Snapshot]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Snapshot)

    async def get_by_event_id(self, event_id: UUID) -> Snapshot | None:
        return await self.session.scalar(select(Snapshot).where(Snapshot.event_id == event_id))

    async def list_filtered(
        self, *, camera_id: UUID | None, offset: int, limit: int
    ) -> tuple[list[Snapshot], int]:
        from sqlalchemy import func

        statement = select(Snapshot).join(Event).join(Tracking)
        if camera_id is not None:
            statement = statement.where(Tracking.camera_id == camera_id)
        items = list((await self.session.scalars(statement.order_by(Snapshot.saved_at.desc()).offset(offset).limit(limit))).all())
        total = await self.session.scalar(select(func.count()).select_from(statement.subquery()))
        return items, total or 0
