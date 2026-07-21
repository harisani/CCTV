from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Camera
from app.repository.base import BaseRepository


class CameraRepository(BaseRepository[Camera]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Camera)

    async def get_by_name(self, name: str) -> Camera | None:
        return await self.session.scalar(select(Camera).where(Camera.name == name))

    async def list_enabled(self) -> list[Camera]:
        return list((await self.session.scalars(select(Camera).where(Camera.enabled.is_(True)))).all())

    async def list_filtered(
        self,
        *,
        search: str | None = None,
        building: str | None = None,
        floor: str | None = None,
        zone: str | None = None,
        camera_status: str | None = None,
        enabled: bool | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Camera], int]:
        """List cameras for large installations using server-side filtering."""
        statement = select(Camera)
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    Camera.name.ilike(pattern),
                    Camera.location.ilike(pattern),
                    Camera.building.ilike(pattern),
                    Camera.zone.ilike(pattern),
                )
            )
        if building:
            statement = statement.where(Camera.building == building)
        if floor:
            statement = statement.where(Camera.floor == floor)
        if zone:
            statement = statement.where(Camera.zone == zone)
        if camera_status:
            statement = statement.where(Camera.status == camera_status)
        if enabled is not None:
            statement = statement.where(Camera.enabled.is_(enabled))

        total = await self.session.scalar(select(func.count()).select_from(statement.subquery()))
        page = statement.order_by(Camera.display_order, Camera.name).offset(offset).limit(limit)
        return list((await self.session.scalars(page)).all()), total or 0
