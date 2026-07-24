"""Authenticated and audited access to sensitive CCTV evidence."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_app_settings, get_database_session
from app.api.schemas import EvidenceAccessResponse
from app.api.security import bearer_scheme, require_authenticated_user
from app.config.settings import Settings
from app.models import EvidenceAsset, Snapshot, User
from app.repository import AuditRepository
from app.services.evidence_access_service import EvidenceAccessService

router = APIRouter(prefix="/evidence")


@router.post(
    "/snapshots/{snapshot_id}/access",
    response_model=EvidenceAccessResponse,
)
async def create_snapshot_access(
    snapshot_id: UUID,
    response: Response,
    actor: User = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
    settings: Settings = Depends(get_app_settings),
) -> EvidenceAccessResponse:
    snapshot = await session.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot evidence not found")
    grant = EvidenceAccessService(settings).issue_snapshot(
        snapshot.id,
        actor.id,
        actor.token_version,
    )
    await AuditRepository(session).record(
        actor_user_id=actor.id,
        action="EVIDENCE_ACCESS_GRANTED",
        resource_type="snapshot",
        resource_id=str(snapshot.id),
        details={
            "expires_at": grant.expires_at.isoformat(),
            "grant_id": str(grant.grant_id),
        },
    )
    await session.commit()
    response.headers["Cache-Control"] = "no-store"
    return EvidenceAccessResponse(
        access_token=grant.access_token,
        content_url=grant.content_url,
        expires_at=grant.expires_at,
    )


@router.get("/snapshots/{snapshot_id}/content")
async def read_snapshot_content(
    snapshot_id: UUID,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_database_session),
    settings: Settings = Depends(get_app_settings),
) -> FileResponse:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed evidence bearer token",
        )
    service = EvidenceAccessService(settings)
    try:
        authorization = service.authorize_snapshot(
            credentials.credentials,
            snapshot_id,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        ) from error

    user = await session.get(User, authorization.user_id)
    if (
        user is None
        or not user.is_active
        or user.token_version != authorization.token_version
    ):
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
        details={"grant_id": str(authorization.grant_id)},
    )
    await session.commit()
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.post(
    "/assets/{asset_id}/access",
    response_model=EvidenceAccessResponse,
)
async def create_asset_access(
    asset_id: UUID,
    response: Response,
    actor: User = Depends(require_authenticated_user),
    session: AsyncSession = Depends(get_database_session),
    settings: Settings = Depends(get_app_settings),
) -> EvidenceAccessResponse:
    asset = await session.get(EvidenceAsset, asset_id)
    if asset is None or asset.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Evidence asset not found")
    grant = EvidenceAccessService(settings).issue_asset(
        asset.id,
        actor.id,
        actor.token_version,
    )
    await AuditRepository(session).record(
        actor_user_id=actor.id,
        action="EVIDENCE_ASSET_ACCESS_GRANTED",
        resource_type="evidence_asset",
        resource_id=str(asset.id),
        details={
            "capture_event_id": str(asset.capture_event_id),
            "asset_type": asset.asset_type.value,
            "expires_at": grant.expires_at.isoformat(),
            "grant_id": str(grant.grant_id),
        },
    )
    await session.commit()
    response.headers["Cache-Control"] = "no-store"
    return EvidenceAccessResponse(
        access_token=grant.access_token,
        content_url=grant.content_url,
        expires_at=grant.expires_at,
    )


@router.get("/assets/{asset_id}/content")
async def read_asset_content(
    asset_id: UUID,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_database_session),
    settings: Settings = Depends(get_app_settings),
) -> FileResponse:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed evidence bearer token",
        )
    service = EvidenceAccessService(settings)
    try:
        authorization = service.authorize_asset(
            credentials.credentials,
            asset_id,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
        ) from error
    user = await session.get(User, authorization.user_id)
    if (
        user is None
        or not user.is_active
        or user.token_version != authorization.token_version
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Evidence user session is invalid",
        )
    asset = await session.get(EvidenceAsset, asset_id)
    if asset is None or asset.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Evidence asset not found")
    try:
        path, media_type = service.resolve_asset(asset)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    await AuditRepository(session).record(
        actor_user_id=user.id,
        action="EVIDENCE_ASSET_VIEWED",
        resource_type="evidence_asset",
        resource_id=str(asset.id),
        details={
            "capture_event_id": str(asset.capture_event_id),
            "asset_type": asset.asset_type.value,
            "grant_id": str(authorization.grant_id),
        },
    )
    await session.commit()
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )
