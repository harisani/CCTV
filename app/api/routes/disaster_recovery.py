from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.api.dependencies import (
    get_app_settings,
    get_disaster_recovery_repository,
)
from app.api.schemas import (
    DisasterRecoveryResponse,
    DisasterRecoveryRestore,
    Page,
)
from app.api.security import require_roles
from app.config.settings import Settings
from app.models import DisasterRecoveryArchive, DisasterRecoveryStatus, User, UserRole
from app.repository import DisasterRecoveryRepository
from app.services.disaster_recovery_service import DisasterRecoveryService

router = APIRouter(
    prefix="/disaster-recovery",
    dependencies=[Depends(require_roles(UserRole.SUPER_ADMIN))],
)


async def _get_archive(
    archive_id: UUID, repository: DisasterRecoveryRepository
) -> DisasterRecoveryArchive:
    archive = await repository.get(archive_id)
    if archive is None:
        raise HTTPException(status_code=404, detail="Disaster-recovery archive not found")
    return archive


@router.get("", response_model=Page[DisasterRecoveryResponse])
async def list_archives(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    repository: DisasterRecoveryRepository = Depends(
        get_disaster_recovery_repository
    ),
) -> Page[DisasterRecoveryResponse]:
    items, total = await repository.list_recent(offset=offset, limit=limit)
    return Page[DisasterRecoveryResponse](
        items=items, total=total, offset=offset, limit=limit
    )


@router.post(
    "", response_model=DisasterRecoveryResponse, status_code=status.HTTP_201_CREATED
)
async def create_archive(
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
    repository: DisasterRecoveryRepository = Depends(
        get_disaster_recovery_repository
    ),
    settings: Settings = Depends(get_app_settings),
) -> DisasterRecoveryArchive:
    return await DisasterRecoveryService(repository, settings).create(actor=actor)


def _copy_upload(source: object, destination: Path, maximum_bytes: int) -> None:
    written = 0
    try:
        with destination.open("wb") as output:
            while chunk := source.read(1024 * 1024):  # type: ignore[attr-defined]
                written += len(chunk)
                if written > maximum_bytes:
                    raise ValueError("Uploaded DR archive exceeds the size limit")
                output.write(chunk)
        os.chmod(destination, 0o600)
    except Exception:
        destination.unlink(missing_ok=True)
        raise


@router.post(
    "/import",
    response_model=DisasterRecoveryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_archive(
    archive_file: UploadFile = File(),
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
    repository: DisasterRecoveryRepository = Depends(
        get_disaster_recovery_repository
    ),
    settings: Settings = Depends(get_app_settings),
) -> DisasterRecoveryArchive:
    if not (archive_file.filename or "").endswith(".dr.enc"):
        raise HTTPException(status_code=422, detail="A .dr.enc file is required")
    staging = Path(settings.storage_path) / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(suffix=".dr.enc", dir=staging)
    os.close(descriptor)
    path = Path(raw_path)
    try:
        await asyncio.to_thread(
            _copy_upload,
            archive_file.file,
            path,
            settings.backup_max_upload_mb * 1024 * 1024,
        )
        return await DisasterRecoveryService(repository, settings).import_archive(
            path, actor=actor
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        path.unlink(missing_ok=True)
        await archive_file.close()


@router.post("/{archive_id}/validate")
async def validate_archive(
    archive_id: UUID,
    repository: DisasterRecoveryRepository = Depends(
        get_disaster_recovery_repository
    ),
    settings: Settings = Depends(get_app_settings),
) -> dict:
    archive = await _get_archive(archive_id, repository)
    if archive.status not in {
        DisasterRecoveryStatus.READY,
        DisasterRecoveryStatus.RESTORED,
    }:
        raise HTTPException(status_code=409, detail="DR archive is not ready")
    try:
        manifest = await DisasterRecoveryService(repository, settings).validate(archive)
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"valid": True, "manifest": manifest}


@router.post("/{archive_id}/restore", response_model=DisasterRecoveryResponse)
async def restore_archive(
    archive_id: UUID,
    payload: DisasterRecoveryRestore,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
    repository: DisasterRecoveryRepository = Depends(
        get_disaster_recovery_repository
    ),
    settings: Settings = Depends(get_app_settings),
) -> DisasterRecoveryArchive:
    archive = await _get_archive(archive_id, repository)
    if archive.status not in {
        DisasterRecoveryStatus.READY,
        DisasterRecoveryStatus.RESTORED,
    }:
        raise HTTPException(status_code=409, detail="DR archive is not ready")
    try:
        return await DisasterRecoveryService(repository, settings).restore_isolated(
            archive, actor=actor, confirmation=payload.confirmation
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/{archive_id}/download")
async def download_archive(
    archive_id: UUID,
    repository: DisasterRecoveryRepository = Depends(
        get_disaster_recovery_repository
    ),
    settings: Settings = Depends(get_app_settings),
) -> FileResponse:
    archive = await _get_archive(archive_id, repository)
    if archive.status not in {
        DisasterRecoveryStatus.READY,
        DisasterRecoveryStatus.RESTORED,
    }:
        raise HTTPException(status_code=409, detail="DR archive is not ready")
    try:
        path = DisasterRecoveryService(repository, settings).archive_path(archive)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=path.name,
    )
