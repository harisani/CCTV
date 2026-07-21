"""Short-lived database operations used by the camera runtime coordinator."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.models import Camera


class CameraRuntimeRepository:
    """Keep long-running camera workers independent from SQLAlchemy sessions."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def list_enabled(self) -> list[Camera]:
        async with self._session_factory() as session:
            statement = select(Camera).where(Camera.enabled.is_(True)).order_by(Camera.display_order, Camera.name)
            return list((await session.scalars(statement)).all())

    async def update_health(
        self,
        camera_id: UUID,
        *,
        status: str,
        last_frame_at: datetime | None,
        last_error: str | None,
    ) -> None:
        async with self._session_factory() as session:
            camera = await session.get(Camera, camera_id)
            if camera is None:
                return
            camera.status = status
            camera.last_frame_at = last_frame_at
            camera.last_error = last_error
            await session.commit()
