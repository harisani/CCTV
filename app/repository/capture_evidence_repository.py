"""Async persistence for capture envelopes and immutable evidence metadata."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    CaptureEvent,
    CaptureEventStatus,
    EvidenceAsset,
    EvidenceIntegrityStatus,
)
from app.repository.base import BaseRepository


class CaptureEvidenceRepository(BaseRepository[CaptureEvent]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CaptureEvent)

    async def list_filtered(
        self,
        *,
        camera_id: UUID | None = None,
        zone_id: UUID | None = None,
        status: CaptureEventStatus | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[CaptureEvent], int]:
        filters = []
        if camera_id is not None:
            filters.append(CaptureEvent.camera_id == camera_id)
        if zone_id is not None:
            filters.append(CaptureEvent.zone_id == zone_id)
        if status is not None:
            filters.append(CaptureEvent.status == status)
        if start_at is not None:
            filters.append(CaptureEvent.captured_at >= start_at)
        if end_at is not None:
            filters.append(CaptureEvent.captured_at <= end_at)
        statement = select(CaptureEvent).where(*filters)
        items = list(
            (
                await self.session.scalars(
                    statement.order_by(CaptureEvent.captured_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        return items, int(total or 0)

    async def get_with_assets(
        self, capture_event_id: UUID
    ) -> CaptureEvent | None:
        return await self.session.scalar(
            select(CaptureEvent)
            .where(CaptureEvent.id == capture_event_id)
            .options(selectinload(CaptureEvent.evidence_assets))
        )

    async def get_asset(self, asset_id: UUID) -> EvidenceAsset | None:
        return await self.session.get(EvidenceAsset, asset_id)

    async def list_assets(
        self, capture_event_id: UUID
    ) -> list[EvidenceAsset]:
        return list(
            (
                await self.session.scalars(
                    select(EvidenceAsset)
                    .where(
                        EvidenceAsset.capture_event_id == capture_event_id,
                        EvidenceAsset.deleted_at.is_(None),
                    )
                    .order_by(
                        EvidenceAsset.asset_type,
                        EvidenceAsset.sequence_index,
                    )
                )
            ).all()
        )

    async def set_integrity(
        self,
        asset: EvidenceAsset,
        *,
        status: EvidenceIntegrityStatus,
        checksum_sha256: str | None = None,
        size_bytes: int | None = None,
    ) -> None:
        if checksum_sha256 is not None and asset.checksum_sha256 is None:
            asset.checksum_sha256 = checksum_sha256
        if size_bytes is not None:
            asset.size_bytes = size_bytes
        asset.integrity_status = status
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()
