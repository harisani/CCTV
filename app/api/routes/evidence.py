"""Authenticated and audited access to sensitive CCTV evidence."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_app_settings, get_database_session
from app.api.schemas import EvidenceAccessResponse
from app.api.security import require_authenticated_user
from app.config.settings import Settings
from app.models import Snapshot, User
from app.repository import AuditRepository
from app.services.evidence_access_service import EvidenceAccessService

router = APIRouter(prefix="/evidence")


@router.post(
    "/snapshots/{snapshot_id}/access",
    response_model=EvidenceAccessResponse,
)
async def create_snapshot_access(
    snapshot_id: UUID,
    actor: User = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
    settings: Settings = Depends(get_app_settings),
) -> EvidenceAccessResponse:
    snapshot = await session.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot evidence not found")
    grant = EvidenceAccessService(settings).issue_snapshot(snapshot.id, actor.id)
    await AuditRepository(session).record(
        actor_user_id=actor.id,
        action="EVIDENCE_ACCESS_GRANTED",
        resource_type="snapshot",
        resource_id=str(snapshot.id),
        details={"expires_at": grant.expires_at.isoformat()},
    )
    await session.commit()
    return EvidenceAccessResponse(
        content_url=grant.content_url,
        expires_at=grant.expires_at,
    )


@router.get("/snapshots/{snapshot_id}/content")
async def read_snapshot_content(
    snapshot_id: UUID,
    access_token: str = Query(min_length=1),
    session: AsyncSession = Depends(get_database_session),
    settings: Settings = Depends(get_app_settings),
) -> FileResponse:
    service = EvidenceAccessService(settings)
    try:
        user_id = service.authorize_snapshot(access_token, snapshot_id)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        ) from error

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Evidence user session is invalid",
        )
    snapshot = await session.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot evidence not found")
    try:
        path, media_type = service.resolve_snapshot(snapshot)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    await AuditRepository(session).record(
        actor_user_id=user.id,
        action="EVIDENCE_SNAPSHOT_VIEWED",
        resource_type="snapshot",
        resource_id=str(snapshot.id),
    )
    await session.commit()
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store"},
    )
