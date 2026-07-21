from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tracking
from app.repository.base import BaseRepository


class TrackingRepository(BaseRepository[Tracking]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Tracking)

    async def get_active(self, camera_id: UUID, byte_track_id: int) -> Tracking | None:
        statement = select(Tracking).where(
            Tracking.camera_id == camera_id,
            Tracking.byte_track_id == byte_track_id,
            Tracking.is_active.is_(True),
        )
        return await self.session.scalar(statement)
