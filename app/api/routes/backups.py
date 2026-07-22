from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response

from app.api.dependencies import get_app_settings, get_backup_repository
from app.api.schemas import (
    ArchiveRecordPage,
    BackupArchiveResponse,
    BackupCreate,
    Page,
)
from app.api.security import require_roles
from app.config.settings import Settings
from app.models import BackupArchive, BackupSource, BackupStatus, User, UserRole
from app.repository import BackupRepository
from app.services.backup_service import ARCHIVE_ENTITIES, ArchiveReader, BackupService

router = APIRouter(
    prefix="/backups", dependencies=[Depends(require_roles(UserRole.SUPER_ADMIN))]
)


def _stage_upload(source: object, destination: Path, maximum_bytes: int) -> None:
    written = 0
    try:
        with destination.open("wb") as target:
            while True:
                chunk = source.read(1024 * 1024)  # type: ignore[attr-defined]
                if not chunk:
                    break
                written += len(chunk)
                if written > maximum_bytes:
                    raise ValueError("Uploaded backup exceeds the configured size limit")
                target.write(chunk)
        os.chmod(destination, 0o600)
    except Exception:
        destination.unlink(missing_ok=True)
        raise


async def _ready_archive(archive_id: UUID, repository: BackupRepository) -> BackupArchive:
    archive = await repository.get(archive_id)
    if archive is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
    if archive.status != BackupStatus.READY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Backup is not ready"
        )
    return archive


@router.get("", response_model=Page[BackupArchiveResponse])
async def list_backups(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    repository: BackupRepository = Depends(get_backup_repository),
) -> Page[BackupArchiveResponse]:
    items, total = await repository.list_recent(offset=offset, limit=limit)
    return Page[BackupArchiveResponse](items=items, total=total, offset=offset, limit=limit)


@router.post("", response_model=BackupArchiveResponse, status_code=status.HTTP_201_CREATED)
async def create_backup(
    payload: BackupCreate,
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
    repository: BackupRepository = Depends(get_backup_repository),
    settings: Settings = Depends(get_app_settings),
) -> BackupArchive:
    service = BackupService(repository, settings)
    backup_date = payload.backup_date or datetime.now(service.timezone).date()
    return await service.create_for_date(
        backup_date, source=BackupSource.MANUAL, actor=actor
    )


@router.post(
    "/import", response_model=BackupArchiveResponse, status_code=status.HTTP_201_CREATED
)
async def import_backup(
    archive_file: UploadFile = File(),
    actor: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
    repository: BackupRepository = Depends(get_backup_repository),
    settings: Settings = Depends(get_app_settings),
) -> BackupArchive:
    filename = archive_file.filename or "backup.zip"
    if Path(filename).suffix.lower() != ".zip":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Backup import requires a .zip file",
        )
    staging_root = Path(settings.storage_path) / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix="backup-", suffix=".zip", dir=staging_root)
    os.close(descriptor)
    staged_path = Path(raw_path)
    try:
        await asyncio.to_thread(
            _stage_upload,
            archive_file.file,
            staged_path,
            settings.backup_max_upload_mb * 1024 * 1024,
        )
        return await BackupService(repository, settings).import_archive(
            staged_path, original_filename=filename, actor=actor
        )
    except HTTPException:
        raise
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    finally:
        staged_path.unlink(missing_ok=True)
        await archive_file.close()


@router.get("/{archive_id}/download")
async def download_backup(
    archive_id: UUID,
    repository: BackupRepository = Depends(get_backup_repository),
    settings: Settings = Depends(get_app_settings),
) -> FileResponse:
    archive = await _ready_archive(archive_id, repository)
    try:
        path = ArchiveReader(Path(settings.storage_path)).archive_path(archive)
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"cctv_backup_{archive.backup_date:%Y%m%d}.zip",
    )


@router.get("/{archive_id}/records/{entity}", response_model=ArchiveRecordPage)
async def list_archive_records(
    archive_id: UUID,
    entity: str,
    search: str | None = Query(default=None, max_length=150),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    repository: BackupRepository = Depends(get_backup_repository),
    settings: Settings = Depends(get_app_settings),
) -> ArchiveRecordPage:
    if entity not in ARCHIVE_ENTITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported archive entity",
        )
    archive = await _ready_archive(archive_id, repository)
    reader = ArchiveReader(Path(settings.storage_path))
    try:
        items, total = await asyncio.to_thread(
            reader.list_records,
            archive,
            entity,
            search=search,
            offset=offset,
            limit=limit,
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return ArchiveRecordPage(
        items=items, total=total, offset=offset, limit=limit, entity=entity
    )


@router.get("/{archive_id}/snapshots/{snapshot_id}")
async def read_archive_snapshot(
    archive_id: UUID,
    snapshot_id: UUID,
    repository: BackupRepository = Depends(get_backup_repository),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    archive = await _ready_archive(archive_id, repository)
    reader = ArchiveReader(Path(settings.storage_path))
    try:
        content, content_type = await asyncio.to_thread(
            reader.snapshot_bytes, archive, snapshot_id
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return Response(content=content, media_type=content_type)
