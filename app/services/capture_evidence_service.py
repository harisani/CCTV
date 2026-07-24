"""Application service for capture-event queries and evidence integrity."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from app.models import (
    CaptureEvent,
    CaptureEventStatus,
    EvidenceAsset,
    EvidenceIntegrityStatus,
)
from app.repository import CaptureEvidenceRepository
from app.services.evidence_access_service import EvidenceAccessService


@dataclass(frozen=True, slots=True)
class IntegrityVerification:
    asset: EvidenceAsset
    actual_checksum_sha256: str | None
    actual_size_bytes: int | None


class CaptureEvidenceService:
    """Coordinate capture metadata without exposing physical storage paths."""

    def __init__(
        self,
        repository: CaptureEvidenceRepository,
        settings: object,
    ) -> None:
        self._repository = repository
        self._access = EvidenceAccessService(settings)

    async def list_events(
        self,
        *,
        camera_id: UUID | None,
        zone_id: UUID | None,
        status: CaptureEventStatus | None,
        start_at: datetime | None,
        end_at: datetime | None,
        offset: int,
        limit: int,
    ) -> tuple[list[CaptureEvent], int]:
        if start_at is not None and end_at is not None and start_at > end_at:
            raise ValueError("start_at must not be after end_at")
        return await self._repository.list_filtered(
            camera_id=camera_id,
            zone_id=zone_id,
            status=status,
            start_at=start_at,
            end_at=end_at,
            offset=offset,
            limit=limit,
        )

    async def get_event(self, capture_event_id: UUID) -> CaptureEvent | None:
        return await self._repository.get_with_assets(capture_event_id)

    async def list_assets(
        self, capture_event_id: UUID
    ) -> list[EvidenceAsset] | None:
        if await self._repository.get(capture_event_id) is None:
            return None
        return await self._repository.list_assets(capture_event_id)

    async def verify_asset(
        self, asset_id: UUID
    ) -> IntegrityVerification | None:
        asset = await self._repository.get_asset(asset_id)
        if asset is None or asset.deleted_at is not None:
            return None
        try:
            path, _media_type = self._access.resolve_asset(asset)
        except FileNotFoundError:
            await self._repository.set_integrity(
                asset,
                status=EvidenceIntegrityStatus.MISSING,
            )
            await self._repository.commit()
            return IntegrityVerification(asset, None, None)

        checksum, size = await asyncio.to_thread(self._hash_file, path)
        expected = asset.checksum_sha256
        integrity = (
            EvidenceIntegrityStatus.VERIFIED
            if expected is None or expected == checksum
            else EvidenceIntegrityStatus.CORRUPT
        )
        await self._repository.set_integrity(
            asset,
            status=integrity,
            checksum_sha256=checksum if expected is None else None,
            size_bytes=size,
        )
        await self._repository.commit()
        return IntegrityVerification(asset, checksum, size)

    @staticmethod
    def _hash_file(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size
