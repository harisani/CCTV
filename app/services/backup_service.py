"""Create and import portable, read-only CCTV observation archives."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import stat
import zipfile
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    AuditLog,
    BackupArchive,
    BackupSource,
    BackupStatus,
    Building,
    Camera,
    CameraRole,
    CameraZoneMapping,
    Event,
    Person,
    PresenceSession,
    Snapshot,
    Tracking,
    User,
    VirtualLine,
    Zone,
    ZoneAdjacency,
)
from app.repository import AuditRepository, BackupRepository

ARCHIVE_FORMAT = "cctv-people-flow-observational-backup"
ARCHIVE_SCHEMA_VERSION = 3
ARCHIVE_ENTITIES_V1 = frozenset(
    {"cameras", "persons", "trackings", "events", "snapshots", "users", "audit_logs"}
)
ARCHIVE_ENTITIES_V2 = ARCHIVE_ENTITIES_V1 | {"presence_sessions"}
ARCHIVE_ENTITIES = ARCHIVE_ENTITIES_V2 | {
    "buildings",
    "zones",
    "camera_roles",
    "camera_zone_mappings",
    "zone_adjacencies",
    "virtual_lines",
}
_backup_lock = asyncio.Lock()


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (UUID, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    raise TypeError(f"Unsupported JSON type: {type(value).__name__}")


def _model_record(instance: Any, *, excluded: set[str] | None = None) -> dict[str, Any]:
    from sqlalchemy import inspect

    omitted = excluded or set()
    return {
        attribute.key: getattr(instance, attribute.key)
        for attribute in inspect(instance).mapper.column_attrs
        if attribute.key not in omitted
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ArchiveCodec:
    """ZIP encoder/validator with path traversal and expansion protections."""

    @staticmethod
    def build(
        destination: Path,
        *,
        backup_date: date,
        coverage_start: datetime,
        coverage_end: datetime,
        timezone_name: str,
        records: dict[str, list[dict[str, Any]]],
        media: list[tuple[str, Path]],
    ) -> dict[str, Any]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        members: list[dict[str, Any]] = []
        try:
            with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                for entity, items in records.items():
                    payload = b"".join(
                        (
                            json.dumps(item, default=_json_default, separators=(",", ":"))
                            + "\n"
                        ).encode("utf-8")
                        for item in items
                    )
                    member = f"data/{entity}.jsonl"
                    archive.writestr(member, payload)
                    members.append(
                        {
                            "path": member,
                            "sha256": hashlib.sha256(payload).hexdigest(),
                            "size_bytes": len(payload),
                        }
                    )

                for member, source_path in media:
                    digest = hashlib.sha256()
                    size = 0
                    with source_path.open("rb") as source, archive.open(member, "w") as target:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            target.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                    members.append(
                        {"path": member, "sha256": digest.hexdigest(), "size_bytes": size}
                    )

                manifest = {
                    "format": ARCHIVE_FORMAT,
                    "schema_version": ARCHIVE_SCHEMA_VERSION,
                    "generated_at": datetime.now(UTC).isoformat(),
                    "backup_date": backup_date.isoformat(),
                    "coverage": {
                        "start_at": coverage_start.isoformat(),
                        "end_at": coverage_end.isoformat(),
                        "timezone": timezone_name,
                    },
                    "record_counts": {key: len(value) for key, value in records.items()},
                    "media_count": len(media),
                    "redacted_fields": {
                        "cameras": ["rtsp_url"],
                        "persons": ["reid_embedding"],
                        "users": [
                            "password_hash",
                            "token_version",
                            "failed_login_attempts",
                            "locked_until",
                        ],
                    },
                    "members": members,
                }
                archive.writestr(
                    "manifest.json",
                    json.dumps(manifest, indent=2, default=_json_default).encode("utf-8"),
                )
            os.replace(temporary, destination)
            os.chmod(destination, 0o600)
            return manifest
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def validate(path: Path, settings: Any) -> tuple[dict[str, Any], str, int]:
        max_upload = settings.backup_max_upload_mb * 1024 * 1024
        size_bytes = path.stat().st_size
        if size_bytes <= 0 or size_bytes > max_upload:
            raise ValueError(
                f"Archive must be between 1 byte and {settings.backup_max_upload_mb} MB"
            )
        if not zipfile.is_zipfile(path):
            raise ValueError("Uploaded file is not a valid ZIP archive")

        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > settings.backup_max_members:
                raise ValueError("Archive contains too many files")
            names: set[str] = set()
            total_uncompressed = 0
            for info in infos:
                ArchiveCodec._validate_member_name(info.filename)
                if info.filename in names:
                    raise ValueError("Archive contains duplicate member names")
                names.add(info.filename)
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise ValueError("Archive symbolic links are not allowed")
                total_uncompressed += info.file_size
                ratio = info.file_size / max(info.compress_size, 1)
                if ratio > settings.backup_max_expansion_ratio:
                    raise ValueError("Archive contains a suspicious compression ratio")
            if total_uncompressed > max_upload * settings.backup_max_expansion_ratio:
                raise ValueError("Archive expands beyond the configured safety limit")
            if "manifest.json" not in names:
                raise ValueError("Archive manifest.json is missing")
            manifest_info = archive.getinfo("manifest.json")
            if manifest_info.file_size > 1024 * 1024:
                raise ValueError("Archive manifest is too large")
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("Archive manifest is invalid JSON") from error
            ArchiveCodec._validate_manifest(archive, manifest, names)
        return manifest, _sha256_file(path), size_bytes

    @staticmethod
    def _validate_member_name(name: str) -> None:
        if "\\" in name:
            raise ValueError("Archive member uses an unsafe path separator")
        member = PurePosixPath(name)
        if member.is_absolute() or ".." in member.parts or not member.parts:
            raise ValueError("Archive member path is unsafe")
        if name != "manifest.json" and member.parts[0] not in {"data", "media"}:
            raise ValueError("Archive contains an unsupported member path")

    @staticmethod
    def _validate_manifest(
        archive: zipfile.ZipFile, manifest: dict[str, Any], actual_names: set[str]
    ) -> None:
        if manifest.get("format") != ARCHIVE_FORMAT:
            raise ValueError("Archive format is not supported")
        schema_version = manifest.get("schema_version")
        if schema_version not in {1, 2, ARCHIVE_SCHEMA_VERSION}:
            raise ValueError("Archive schema version is not supported")
        try:
            date.fromisoformat(manifest["backup_date"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Archive backup_date is invalid") from error

        declared = manifest.get("members")
        if not isinstance(declared, list):
            raise ValueError("Archive member manifest is invalid")
        declared_names: set[str] = set()
        for item in declared:
            if not isinstance(item, dict):
                raise ValueError("Archive member manifest is invalid")
            name = item.get("path")
            expected = item.get("sha256")
            if not isinstance(name, str) or not isinstance(expected, str):
                raise ValueError("Archive member checksum is invalid")
            ArchiveCodec._validate_member_name(name)
            if name in declared_names or name not in actual_names:
                raise ValueError("Archive member manifest does not match ZIP contents")
            declared_names.add(name)
            digest = hashlib.sha256()
            with archive.open(name) as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise ValueError(f"Archive checksum failed for {name}")
        if actual_names != declared_names | {"manifest.json"}:
            raise ValueError("Archive contains undeclared files")

        counts = manifest.get("record_counts")
        if not isinstance(counts, dict):
            raise ValueError("Archive record counts are missing")
        required_entities = {
            1: ARCHIVE_ENTITIES_V1,
            2: ARCHIVE_ENTITIES_V2,
            3: ARCHIVE_ENTITIES,
        }[schema_version]
        for entity in required_entities:
            member = f"data/{entity}.jsonl"
            if member not in declared_names or not isinstance(counts.get(entity), int):
                raise ValueError(f"Archive data set is incomplete: {entity}")
            actual_count = 0
            with archive.open(member) as handle:
                for raw_line in handle:
                    if len(raw_line) > 4 * 1024 * 1024:
                        raise ValueError(f"Archive record is too large: {entity}")
                    if raw_line.strip():
                        try:
                            json.loads(raw_line)
                        except (UnicodeDecodeError, json.JSONDecodeError) as error:
                            raise ValueError(f"Archive contains invalid {entity} JSONL") from error
                        actual_count += 1
            if actual_count != counts[entity]:
                raise ValueError(f"Archive count does not match data: {entity}")


class ArchiveReader:
    def __init__(self, storage_root: Path) -> None:
        self.storage_root = storage_root.resolve()

    def archive_path(self, archive: BackupArchive) -> Path:
        candidate = (self.storage_root / archive.file_path).resolve()
        if not candidate.is_relative_to(self.storage_root) or not candidate.is_file():
            raise FileNotFoundError("Archive file is unavailable")
        return candidate

    def list_records(
        self,
        archive: BackupArchive,
        entity: str,
        *,
        search: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        if entity not in ARCHIVE_ENTITIES:
            raise ValueError("Unsupported archive entity")
        matches: list[dict[str, Any]] = []
        total = 0
        needle = search.casefold().strip() if search else None
        with zipfile.ZipFile(self.archive_path(archive)) as zipped:
            with zipped.open(f"data/{entity}.jsonl") as handle:
                for raw_line in handle:
                    if not raw_line.strip():
                        continue
                    item = json.loads(raw_line)
                    if needle and needle not in json.dumps(item, ensure_ascii=False).casefold():
                        continue
                    if total >= offset and len(matches) < limit:
                        matches.append(item)
                    total += 1
        return matches, total

    def snapshot_bytes(self, archive: BackupArchive, snapshot_id: UUID) -> tuple[bytes, str]:
        target = str(snapshot_id)
        with zipfile.ZipFile(self.archive_path(archive)) as zipped:
            with zipped.open("data/snapshots.jsonl") as handle:
                for raw_line in handle:
                    item = json.loads(raw_line)
                    if str(item.get("id")) != target:
                        continue
                    member = item.get("archive_image_path")
                    if not isinstance(member, str):
                        raise FileNotFoundError("Snapshot image was not included in this backup")
                    ArchiveCodec._validate_member_name(member)
                    content_type = (
                        "image/jpeg"
                        if member.lower().endswith((".jpg", ".jpeg"))
                        else "image/png"
                    )
                    return zipped.read(member), content_type
        raise FileNotFoundError("Snapshot was not found in this archive")


class BackupService:
    def __init__(self, repository: BackupRepository, settings: Any) -> None:
        self.repository = repository
        self.settings = settings
        self.storage_root = Path(settings.storage_path).resolve()
        self.logger = logging.getLogger(__name__)
        try:
            self.timezone = ZoneInfo(settings.backup_timezone)
        except ZoneInfoNotFoundError as error:
            raise RuntimeError(f"Unknown BACKUP_TIMEZONE: {settings.backup_timezone}") from error

    async def create_for_date(
        self,
        backup_date: date,
        *,
        source: BackupSource,
        actor: User | None,
    ) -> BackupArchive:
        async with _backup_lock:
            existing = None
            schedule_key = None
            if source == BackupSource.AUTOMATIC:
                schedule_key = f"AUTO:{backup_date.isoformat()}"
                existing = await self.repository.get_automatic_for_date(backup_date)
                if existing and existing.status in {BackupStatus.CREATING, BackupStatus.READY}:
                    return existing

            archive = existing or BackupArchive(
                id=uuid4(),
                source=source,
                status=BackupStatus.CREATING,
                backup_date=backup_date,
                schedule_key=schedule_key,
                file_path="pending",
                created_by_user_id=actor.id if actor else None,
            )
            relative = Path("backups") / f"{backup_date:%Y}" / f"{backup_date:%m}" / (
                f"{backup_date:%Y%m%d}_{archive.id}.zip"
            )
            archive.file_path = relative.as_posix()
            archive.status = BackupStatus.CREATING
            archive.error_message = None
            if not existing:
                self.repository.session.add(archive)
            try:
                await self.repository.session.commit()
            except IntegrityError:
                await self.repository.session.rollback()
                if source == BackupSource.AUTOMATIC:
                    found = await self.repository.get_automatic_for_date(backup_date)
                    if found:
                        return found
                raise

            destination = self.storage_root / relative
            try:
                records, media, start_at, end_at = await self._collect(backup_date)
                manifest = await asyncio.to_thread(
                    ArchiveCodec.build,
                    destination,
                    backup_date=backup_date,
                    coverage_start=start_at,
                    coverage_end=end_at,
                    timezone_name=self.settings.backup_timezone,
                    records=records,
                    media=media,
                )
                archive.status = BackupStatus.READY
                archive.manifest = manifest
                archive.record_counts = manifest["record_counts"]
                archive.schema_version = ARCHIVE_SCHEMA_VERSION
                archive.size_bytes = destination.stat().st_size
                archive.checksum_sha256 = await asyncio.to_thread(_sha256_file, destination)
                archive.completed_at = datetime.now(UTC)
                await AuditRepository(self.repository.session).record(
                    actor_user_id=actor.id if actor else None,
                    action="BACKUP_CREATED",
                    resource_type="backup",
                    resource_id=str(archive.id),
                    details={"date": backup_date.isoformat(), "source": source.value},
                )
                await self.repository.session.commit()
                await self.repository.session.refresh(archive)
                self.logger.info("Backup ready: %s", destination)
                return archive
            except Exception as error:
                destination.unlink(missing_ok=True)
                await self.repository.session.rollback()
                persisted = await self.repository.get(archive.id)
                if persisted is not None:
                    archive = persisted
                archive.status = BackupStatus.FAILED
                archive.error_message = str(error)[:2000]
                archive.completed_at = datetime.now(UTC)
                await self.repository.session.commit()
                self.logger.exception("Backup failed for %s", backup_date)
                raise

    async def import_archive(
        self, staged_path: Path, *, original_filename: str, actor: User
    ) -> BackupArchive:
        try:
            manifest, checksum, size_bytes = await asyncio.to_thread(
                ArchiveCodec.validate, staged_path, self.settings
            )
            if await self.repository.get_by_checksum(checksum):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This archive has already been imported",
                )
            backup_date = date.fromisoformat(manifest["backup_date"])
            archive_id = uuid4()
            relative = Path("imports") / f"{backup_date:%Y}" / f"{backup_date:%m}" / (
                f"{archive_id}.zip"
            )
            destination = self.storage_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.move, str(staged_path), str(destination))
            os.chmod(destination, 0o600)
            archive = BackupArchive(
                id=archive_id,
                source=BackupSource.IMPORT,
                status=BackupStatus.READY,
                backup_date=backup_date,
                original_filename=Path(original_filename).name[:255],
                file_path=relative.as_posix(),
                checksum_sha256=checksum,
                size_bytes=size_bytes,
                schema_version=manifest["schema_version"],
                record_counts=manifest["record_counts"],
                manifest=manifest,
                created_by_user_id=actor.id,
                completed_at=datetime.now(UTC),
            )
            self.repository.session.add(archive)
            await AuditRepository(self.repository.session).record(
                actor_user_id=actor.id,
                action="BACKUP_IMPORTED",
                resource_type="backup",
                resource_id=str(archive.id),
                details={"filename": archive.original_filename, "checksum": checksum},
            )
            try:
                await self.repository.session.commit()
            except Exception:
                await self.repository.session.rollback()
                destination.unlink(missing_ok=True)
                raise
            await self.repository.session.refresh(archive)
            return archive
        finally:
            staged_path.unlink(missing_ok=True)

    async def apply_retention(self, today: date) -> int:
        cutoff = today - timedelta(days=self.settings.backup_retention_days)
        archives = await self.repository.automatic_older_than(cutoff)
        removed = 0
        for archive in archives:
            try:
                ArchiveReader(self.storage_root).archive_path(archive).unlink(missing_ok=True)
            except FileNotFoundError:
                pass
            await self.repository.session.delete(archive)
            removed += 1
        if removed:
            await self.repository.session.commit()
            self.logger.info("Removed %s automatic backups older than %s", removed, cutoff)
        return removed

    async def _collect(
        self, backup_date: date
    ) -> tuple[dict[str, list[dict[str, Any]]], list[tuple[str, Path]], datetime, datetime]:
        start_local = datetime.combine(backup_date, time.min, tzinfo=self.timezone)
        end_local = start_local + timedelta(days=1)
        start_at = start_local.astimezone(UTC)
        end_at = end_local.astimezone(UTC)
        session = self.repository.session

        cameras = list((await session.scalars(select(Camera).order_by(Camera.name))).all())
        buildings = list(
            (await session.scalars(select(Building).order_by(Building.name))).all()
        )
        zones = list(
            (
                await session.scalars(
                    select(Zone).order_by(Zone.building_id, Zone.name)
                )
            ).all()
        )
        camera_roles = list(
            (
                await session.scalars(
                    select(CameraRole).order_by(CameraRole.camera_id, CameraRole.role)
                )
            ).all()
        )
        camera_zone_mappings = list(
            (
                await session.scalars(
                    select(CameraZoneMapping).order_by(
                        CameraZoneMapping.camera_id, CameraZoneMapping.zone_id
                    )
                )
            ).all()
        )
        zone_adjacencies = list(
            (
                await session.scalars(
                    select(ZoneAdjacency).order_by(
                        ZoneAdjacency.source_zone_id,
                        ZoneAdjacency.target_zone_id,
                    )
                )
            ).all()
        )
        virtual_lines = list(
            (
                await session.scalars(
                    select(VirtualLine).order_by(
                        VirtualLine.camera_id, VirtualLine.display_order
                    )
                )
            ).all()
        )
        event_filter = (Event.occurred_at >= start_at, Event.occurred_at < end_at)
        events = list(
            (
                await session.scalars(
                    select(Event).where(*event_filter).order_by(Event.occurred_at)
                )
            ).all()
        )
        trackings = list(
            (
                await session.scalars(
                    select(Tracking)
                    .where(
                        Tracking.id.in_(
                            select(Event.tracking_id).where(*event_filter)
                        )
                    )
                    .order_by(Tracking.started_at)
                )
            ).all()
        )
        persons = list(
            (
                await session.scalars(
                    select(Person)
                    .where(
                        Person.id.in_(
                            select(Tracking.person_id)
                            .join(Event, Event.tracking_id == Tracking.id)
                            .where(*event_filter, Tracking.person_id.is_not(None))
                        )
                    )
                    .order_by(Person.first_seen_at)
                )
            ).all()
        )
        snapshots = list(
            (
                await session.scalars(
                    select(Snapshot)
                    .join(Event, Snapshot.event_id == Event.id)
                    .where(*event_filter)
                    .order_by(Snapshot.saved_at)
                )
            ).all()
        )
        presence_sessions = list(
            (
                await session.scalars(
                    select(PresenceSession)
                    .where(
                        PresenceSession.entered_at < end_at,
                        (PresenceSession.exited_at.is_(None))
                        | (PresenceSession.exited_at >= start_at),
                    )
                    .order_by(PresenceSession.entered_at)
                )
            ).all()
        )
        users = list((await session.scalars(select(User).order_by(User.username))).all())
        audit_logs = list(
            (
                await session.scalars(
                    select(AuditLog)
                    .where(AuditLog.created_at >= start_at, AuditLog.created_at < end_at)
                    .order_by(AuditLog.created_at)
                )
            ).all()
        )

        media: list[tuple[str, Path]] = []
        snapshot_records: list[dict[str, Any]] = []
        for snapshot in snapshots:
            record = _model_record(snapshot, excluded={"image_path", "metadata_path"})
            if self.settings.backup_include_snapshots:
                image = self._resolve_snapshot_path(snapshot.image_path)
                metadata = self._resolve_snapshot_path(snapshot.metadata_path)
                if image:
                    member = f"media/{snapshot.id}{image.suffix.lower()}"
                    record["archive_image_path"] = member
                    media.append((member, image))
                if metadata:
                    member = f"media/{snapshot.id}.json"
                    record["archive_metadata_path"] = member
                    media.append((member, metadata))
            snapshot_records.append(record)

        records = {
            "buildings": [_model_record(item) for item in buildings],
            "zones": [_model_record(item) for item in zones],
            "cameras": [_model_record(item, excluded={"rtsp_url"}) for item in cameras],
            "camera_roles": [_model_record(item) for item in camera_roles],
            "camera_zone_mappings": [
                _model_record(item) for item in camera_zone_mappings
            ],
            "zone_adjacencies": [
                _model_record(item) for item in zone_adjacencies
            ],
            "virtual_lines": [_model_record(item) for item in virtual_lines],
            "persons": [_model_record(item, excluded={"reid_embedding"}) for item in persons],
            "trackings": [_model_record(item) for item in trackings],
            "events": [_model_record(item) for item in events],
            "presence_sessions": [_model_record(item) for item in presence_sessions],
            "snapshots": snapshot_records,
            "users": [
                _model_record(
                    item,
                    excluded={
                        "password_hash",
                        "token_version",
                        "failed_login_attempts",
                        "locked_until",
                    },
                )
                for item in users
            ],
            "audit_logs": [_model_record(item) for item in audit_logs],
        }
        return records, media, start_at, end_at

    def _resolve_snapshot_path(self, stored_path: str) -> Path | None:
        raw = Path(stored_path)
        candidates = [raw.resolve()] if raw.is_absolute() else [
            (Path.cwd() / raw).resolve(),
            (self.storage_root / raw).resolve(),
        ]
        for candidate in candidates:
            if candidate.is_relative_to(self.storage_root) and candidate.is_file():
                return candidate
        self.logger.warning("Snapshot file missing or outside storage root: %s", stored_path)
        return None
