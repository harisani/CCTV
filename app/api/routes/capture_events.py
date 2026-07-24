"""Authenticated capture-event and evidence metadata queries."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.capture_schemas import (
    CaptureEventDetailResponse,
    CaptureEventResponse,
    EvidenceAssetResponse,
    EvidenceIntegrityResponse,
)
from app.api.dependencies import (
    get_capture_evidence_service,
    get_database_session,
)
from app.api.schemas import Page
from app.api.security import require_authenticated_user, require_roles
from app.models import CaptureEventStatus, User, UserRole
from app.repository import AuditRepository
from app.services.capture_evidence_service import CaptureEvidenceService

router = APIRouter(
    prefix="/capture-events",
    dependencies=[Depends(require_authenticated_user)],
)


@router.get("", response_model=Page[CaptureEventResponse])
async def list_capture_events(
    camera_id: UUID | None = None,
    zone_id: UUID | None = None,
    capture_status: CaptureEventStatus | None = Query(
        default=None, alias="status"
    ),
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: CaptureEvidenceService = Depends(get_capture_evidence_service),
) -> Page[CaptureEventResponse]:
    try:
        items, total = await service.list_events(
            camera_id=camera_id,
            zone_id=zone_id,
            status=capture_status,
            start_at=start_at,
            end_at=end_at,
            offset=offset,
            limit=limit,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Page[CaptureEventResponse](
        items=items,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/{capture_event_id}",
    response_model=CaptureEventDetailResponse,
)
async def get_capture_event(
    capture_event_id: UUID,
    service: CaptureEvidenceService = Depends(get_capture_evidence_service),
) -> CaptureEventDetailResponse:
    event = await service.get_event(capture_event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Capture event not found")
    return CaptureEventDetailResponse.model_validate(event)


@router.get(
    "/{capture_event_id}/assets",
    response_model=list[EvidenceAssetResponse],
)
async def list_capture_assets(
    capture_event_id: UUID,
    service: CaptureEvidenceService = Depends(get_capture_evidence_service),
) -> list[EvidenceAssetResponse]:
    assets = await service.list_assets(capture_event_id)
    if assets is None:
        raise HTTPException(status_code=404, detail="Capture event not found")
    return [
        EvidenceAssetResponse.model_validate(asset) for asset in assets
    ]


@router.post(
    "/assets/{asset_id}/verify",
    response_model=EvidenceIntegrityResponse,
    dependencies=[
        Depends(
            require_roles(
                UserRole.SUPER_ADMIN,
                UserRole.ADMIN,
                UserRole.AUDITOR,
            )
        )
    ],
)
async def verify_evidence_asset(
    asset_id: UUID,
    actor: User = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
    service: CaptureEvidenceService = Depends(get_capture_evidence_service),
) -> EvidenceIntegrityResponse:
    result = await service.verify_asset(asset_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Evidence asset not found")
    await AuditRepository(session).record(
        actor_user_id=actor.id,
        action="EVIDENCE_INTEGRITY_VERIFIED",
        resource_type="evidence_asset",
        resource_id=str(result.asset.id),
        details={
            "integrity_status": result.asset.integrity_status.value,
            "actual_checksum_sha256": result.actual_checksum_sha256,
            "actual_size_bytes": result.actual_size_bytes,
        },
    )
    await session.commit()
    return EvidenceIntegrityResponse(
        asset=EvidenceAssetResponse.model_validate(result.asset),
        actual_checksum_sha256=result.actual_checksum_sha256,
        actual_size_bytes=result.actual_size_bytes,
    )
