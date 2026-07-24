"""Application queries for Phase 5 local observations and zone movement."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.models import Tracking, ZoneEvent, ZoneEventType
from app.repository import ZoneTransitionRepository


class ZoneTransitionService:
    def __init__(self, repository: ZoneTransitionRepository) -> None:
        self._repository = repository

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
        self._validate_range(start_at, end_at)
        return await self._repository.list_events(
            camera_id=camera_id,
            zone_id=zone_id,
            tracking_id=tracking_id,
            event_type=event_type,
            start_at=start_at,
            end_at=end_at,
            offset=offset,
            limit=limit,
        )

    async def get_event(self, event_id: UUID) -> ZoneEvent | None:
        return await self._repository.get(event_id)

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
        self._validate_range(start_at, end_at)
        return await self._repository.list_tracks(
            camera_id=camera_id,
            person_id=person_id,
            active=active,
            start_at=start_at,
            end_at=end_at,
            offset=offset,
            limit=limit,
        )

    @staticmethod
    def _validate_range(
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> None:
        if start_at is not None and end_at is not None and start_at > end_at:
            raise ValueError("start_at must not be after end_at")
