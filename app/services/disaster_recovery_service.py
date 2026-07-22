"""Encrypted PostgreSQL and storage disaster-recovery operations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import struct
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from sqlalchemy.exc import IntegrityError

from app.models import DisasterRecoveryArchive, DisasterRecoveryStatus, User
from app.repository import AuditRepository, DisasterRecoveryRepository

DR_FORMAT = "cctv-people-flow-disaster-recovery"
DR_SCHEMA_VERSION = 1
ENCRYPTED_MAGIC = b"CCTVDR01"
ENCRYPTED_HEADER = struct.Struct(">8sB16s12s")
GCM_TAG_SIZE = 16
CHUNK_SIZE = 1024 * 1024
_DATABASE_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")
_dr_lock = asyncio.Lock()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


class EncryptedArchiveCodec:
    """Streaming AES-256-GCM container using a scrypt-derived key."""

    @staticmethod
    def _key(passphrase: str, salt: bytes) -> bytes:
        return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(
            passphrase.encode("utf-8")
        )

    @classmethod
    def encrypt(cls, source: Path, destination: Path, passphrase: str) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        salt, nonce = os.urandom(16), os.urandom(12)
        encryptor = Cipher(
            algorithms.AES(cls._key(passphrase, salt)), modes.GCM(nonce)
        ).encryptor()
        try:
            with source.open("rb") as plain, temporary.open("wb") as encrypted:
                encrypted.write(ENCRYPTED_HEADER.pack(ENCRYPTED_MAGIC, 1, salt, nonce))
                for chunk in iter(lambda: plain.read(CHUNK_SIZE), b""):
                    encrypted.write(encryptor.update(chunk))
                encrypted.write(encryptor.finalize())
                encrypted.write(encryptor.tag)
            os.replace(temporary, destination)
            os.chmod(destination, 0o600)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    @classmethod
    def decrypt(cls, source: Path, destination: Path, passphrase: str) -> None:
        size = source.stat().st_size
        if size <= ENCRYPTED_HEADER.size + GCM_TAG_SIZE:
            raise ValueError("Encrypted DR archive is truncated")
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        try:
            with source.open("rb") as encrypted:
                header = encrypted.read(ENCRYPTED_HEADER.size)
                magic, version, salt, nonce = ENCRYPTED_HEADER.unpack(header)
                if magic != ENCRYPTED_MAGIC or version != 1:
                    raise ValueError("Unsupported encrypted DR archive format")
                encrypted.seek(-GCM_TAG_SIZE, os.SEEK_END)
                tag = encrypted.read(GCM_TAG_SIZE)
                encrypted.seek(ENCRYPTED_HEADER.size)
                remaining = size - ENCRYPTED_HEADER.size - GCM_TAG_SIZE
                decryptor = Cipher(
                    algorithms.AES(cls._key(passphrase, salt)), modes.GCM(nonce, tag)
                ).decryptor()
                with temporary.open("wb") as plain:
                    while remaining:
                        chunk = encrypted.read(min(CHUNK_SIZE, remaining))
                        if not chunk:
                            raise ValueError("Encrypted DR archive is truncated")
                        plain.write(decryptor.update(chunk))
                        remaining -= len(chunk)
                    plain.write(decryptor.finalize())
            os.replace(temporary, destination)
            os.chmod(destination, 0o600)
        except InvalidTag as error:
            temporary.unlink(missing_ok=True)
            raise ValueError("DR passphrase is incorrect or archive integrity failed") from error
        except Exception:
            temporary.unlink(missing_ok=True)
            raise


class DisasterRecoveryPackage:
    """Build and validate the plaintext package before/after encryption."""

    @staticmethod
    def build(
        destination: Path,
        *,
        database_dump: Path,
        storage_root: Path,
        include_storage: bool,
        database_name: str,
    ) -> dict[str, Any]:
        members: list[dict[str, Any]] = []
        with zipfile.ZipFile(
            destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            DisasterRecoveryPackage._write_file(
                archive, database_dump, "database/database.dump", members
            )
            if include_storage and storage_root.is_dir():
                excluded_roots = {"disaster-recovery", "restores", ".staging"}
                for source in sorted(storage_root.rglob("*")):
                    if not source.is_file() or source.is_symlink():
                        continue
                    relative = source.relative_to(storage_root)
                    if relative.parts and relative.parts[0] in excluded_roots:
                        continue
                    DisasterRecoveryPackage._write_file(
                        archive, source, f"storage/{relative.as_posix()}", members
                    )
            manifest = {
                "format": DR_FORMAT,
                "schema_version": DR_SCHEMA_VERSION,
                "created_at": datetime.now(UTC).isoformat(),
                "database_name": database_name,
                "database_dump_format": "postgresql-custom",
                "storage_included": include_storage,
                "members": members,
            }
            archive.writestr(
                "manifest.json", json.dumps(manifest, indent=2).encode("utf-8")
            )
        return manifest

    @staticmethod
    def _write_file(
        archive: zipfile.ZipFile,
        source: Path,
        member: str,
        members: list[dict[str, Any]],
    ) -> None:
        digest, size = hashlib.sha256(), 0
        with source.open("rb") as input_file, archive.open(member, "w") as output_file:
            for chunk in iter(lambda: input_file.read(CHUNK_SIZE), b""):
                output_file.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        members.append({"path": member, "sha256": digest.hexdigest(), "size_bytes": size})

    @staticmethod
    def validate(path: Path) -> dict[str, Any]:
        if not zipfile.is_zipfile(path):
            raise ValueError("Decrypted DR payload is not a ZIP archive")
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = {item.filename for item in infos}
            if len(names) != len(infos) or "manifest.json" not in names:
                raise ValueError("DR package contains duplicate members or no manifest")
            for info in infos:
                DisasterRecoveryPackage._safe_member(info.filename)
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError("DR manifest is invalid") from error
            if (
                manifest.get("format") != DR_FORMAT
                or manifest.get("schema_version") != DR_SCHEMA_VERSION
            ):
                raise ValueError("DR package format or schema is unsupported")
            declared = manifest.get("members")
            if not isinstance(declared, list):
                raise ValueError("DR member manifest is invalid")
            declared_names: set[str] = set()
            for item in declared:
                name = item.get("path") if isinstance(item, dict) else None
                checksum = item.get("sha256") if isinstance(item, dict) else None
                if not isinstance(name, str) or not isinstance(checksum, str):
                    raise ValueError("DR member manifest is invalid")
                DisasterRecoveryPackage._safe_member(name)
                if name in declared_names or name not in names:
                    raise ValueError("DR manifest does not match package contents")
                declared_names.add(name)
                digest = hashlib.sha256()
                with archive.open(name) as handle:
                    for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
                        digest.update(chunk)
                if digest.hexdigest() != checksum:
                    raise ValueError(f"DR checksum failed for {name}")
            if names != declared_names | {"manifest.json"}:
                raise ValueError("DR package contains undeclared files")
            if "database/database.dump" not in declared_names:
                raise ValueError("DR package has no PostgreSQL dump")
            return manifest

    @staticmethod
    def _safe_member(name: str) -> None:
        member = PurePosixPath(name)
        if (
            "\\" in name
            or member.is_absolute()
            or ".." in member.parts
            or not member.parts
            or (name != "manifest.json" and member.parts[0] not in {"database", "storage"})
        ):
            raise ValueError("DR package contains an unsafe member path")


class DirectoryOffsiteStorage:
    """Atomic adapter for a mounted NAS, removable disk, or replicated directory."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def upload(self, source: Path) -> tuple[str, str]:
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / source.name
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copy2(source, temporary)
        if _sha256_file(source) != _sha256_file(temporary):
            temporary.unlink(missing_ok=True)
            raise IOError("Offsite checksum verification failed")
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
        return str(destination), _sha256_file(destination)


class DisasterRecoveryService:
    def __init__(self, repository: DisasterRecoveryRepository, settings: Any) -> None:
        self.repository = repository
        self.settings = settings
        self.storage_root = Path(settings.storage_path).resolve()
        self.dr_root = self.storage_root / "disaster-recovery"
        self.logger = logging.getLogger(__name__)

    async def create(
        self, *, actor: User | None, schedule_key: str | None = None
    ) -> DisasterRecoveryArchive:
        if len(self.settings.dr_encryption_passphrase) < 16:
            raise ValueError(
                "DR_ENCRYPTION_PASSPHRASE must contain at least 16 characters"
            )
        async with _dr_lock:
            if schedule_key:
                existing = await self.repository.get_by_schedule_key(schedule_key)
                if existing and existing.status in {
                    DisasterRecoveryStatus.CREATING,
                    DisasterRecoveryStatus.READY,
                }:
                    return existing
            archive = DisasterRecoveryArchive(
                id=uuid4(),
                status=DisasterRecoveryStatus.CREATING,
                schedule_key=schedule_key,
                file_path="pending",
                created_by_user_id=actor.id if actor else None,
            )
            relative = Path("disaster-recovery") / f"{datetime.now(UTC):%Y/%m}" / (
                f"cctv_dr_{datetime.now(UTC):%Y%m%d_%H%M%S}_{archive.id}.dr.enc"
            )
            archive.file_path = relative.as_posix()
            self.repository.session.add(archive)
            try:
                await self.repository.session.commit()
            except IntegrityError:
                await self.repository.session.rollback()
                if schedule_key:
                    found = await self.repository.get_by_schedule_key(schedule_key)
                    if found:
                        return found
                raise

            destination = self.storage_root / relative
            try:
                manifest = await self._build(destination)
                archive.status = DisasterRecoveryStatus.READY
                archive.manifest = manifest
                archive.size_bytes = destination.stat().st_size
                archive.checksum_sha256 = await asyncio.to_thread(
                    _sha256_file, destination
                )
                await self._copy_offsite(archive, destination)
                archive.completed_at = datetime.now(UTC)
                await AuditRepository(self.repository.session).record(
                    actor_user_id=actor.id if actor else None,
                    action="DISASTER_RECOVERY_CREATED",
                    resource_type="disaster_recovery",
                    resource_id=str(archive.id),
                    details={"offsite_path": archive.offsite_path, "schedule_key": schedule_key},
                )
                await self.repository.session.commit()
                await self.repository.session.refresh(archive)
                return archive
            except Exception as error:
                destination.unlink(missing_ok=True)
                await self.repository.session.rollback()
                persisted = await self.repository.get(archive.id)
                if persisted:
                    archive = persisted
                archive.status = DisasterRecoveryStatus.FAILED
                archive.error_message = str(error)[:2000]
                archive.completed_at = datetime.now(UTC)
                await self.repository.session.commit()
                self.logger.exception("Disaster-recovery backup failed")
                raise

    async def _build(self, destination: Path) -> dict[str, Any]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="cctv-dr-") as raw_tmp:
            temporary = Path(raw_tmp)
            dump_path = temporary / "database.dump"
            package_path = temporary / "package.zip"
            await self._run(
                [
                    "pg_dump",
                    "--format=custom",
                    "--compress=6",
                    "--no-owner",
                    "--no-privileges",
                    "--file",
                    str(dump_path),
                    "--host",
                    self.settings.postgres_host,
                    "--port",
                    str(self.settings.postgres_port),
                    "--username",
                    self.settings.postgres_user,
                    self.settings.postgres_db,
                ]
            )
            manifest = await asyncio.to_thread(
                DisasterRecoveryPackage.build,
                package_path,
                database_dump=dump_path,
                storage_root=self.storage_root,
                include_storage=self.settings.dr_include_storage,
                database_name=self.settings.postgres_db,
            )
            await asyncio.to_thread(
                EncryptedArchiveCodec.encrypt,
                package_path,
                destination,
                self.settings.dr_encryption_passphrase,
            )
            return manifest

    async def validate(self, archive: DisasterRecoveryArchive) -> dict[str, Any]:
        if len(self.settings.dr_encryption_passphrase) < 16:
            raise ValueError("DR_ENCRYPTION_PASSPHRASE is not configured")
        source = self._archive_path(archive)
        if archive.checksum_sha256 and await asyncio.to_thread(_sha256_file, source) != archive.checksum_sha256:
            raise ValueError("Encrypted DR archive checksum does not match the catalogue")
        with tempfile.TemporaryDirectory(prefix="cctv-dr-validate-") as raw_tmp:
            package = Path(raw_tmp) / "package.zip"
            await asyncio.to_thread(
                EncryptedArchiveCodec.decrypt,
                source,
                package,
                self.settings.dr_encryption_passphrase,
            )
            return await asyncio.to_thread(DisasterRecoveryPackage.validate, package)

    async def import_archive(
        self, staged_path: Path, *, actor: User
    ) -> DisasterRecoveryArchive:
        if len(self.settings.dr_encryption_passphrase) < 16:
            raise ValueError("DR_ENCRYPTION_PASSPHRASE is not configured")
        checksum = await asyncio.to_thread(_sha256_file, staged_path)
        existing = await self.repository.get_by_checksum(checksum)
        if existing:
            raise ValueError("This disaster-recovery archive is already registered")
        with tempfile.TemporaryDirectory(prefix="cctv-dr-import-") as raw_tmp:
            package = Path(raw_tmp) / "package.zip"
            await asyncio.to_thread(
                EncryptedArchiveCodec.decrypt,
                staged_path,
                package,
                self.settings.dr_encryption_passphrase,
            )
            manifest = await asyncio.to_thread(DisasterRecoveryPackage.validate, package)
        archive_id = uuid4()
        relative = Path("disaster-recovery") / "imports" / f"{archive_id}.dr.enc"
        destination = self.storage_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(staged_path), str(destination))
        os.chmod(destination, 0o600)
        archive = DisasterRecoveryArchive(
            id=archive_id,
            status=DisasterRecoveryStatus.READY,
            file_path=relative.as_posix(),
            checksum_sha256=checksum,
            size_bytes=destination.stat().st_size,
            manifest=manifest,
            created_by_user_id=actor.id,
            completed_at=datetime.now(UTC),
        )
        self.repository.session.add(archive)
        await AuditRepository(self.repository.session).record(
            actor_user_id=actor.id,
            action="DISASTER_RECOVERY_IMPORTED",
            resource_type="disaster_recovery",
            resource_id=str(archive.id),
            details={"checksum": checksum},
        )
        try:
            await self.repository.session.commit()
            await self.repository.session.refresh(archive)
            return archive
        except Exception:
            await self.repository.session.rollback()
            destination.unlink(missing_ok=True)
            raise

    async def restore_isolated(
        self, archive: DisasterRecoveryArchive, *, actor: User, confirmation: str
    ) -> DisasterRecoveryArchive:
        target = f"{self.settings.postgres_db}{self.settings.dr_restore_database_suffix}"
        expected = f"RESTORE {target}"
        if confirmation != expected:
            raise ValueError(f"Confirmation must exactly match: {expected}")
        if not _DATABASE_NAME.fullmatch(target) or target == self.settings.postgres_db:
            raise ValueError("Isolated restore database name is unsafe")
        archive.status = DisasterRecoveryStatus.RESTORING
        archive.error_message = None
        await self.repository.session.commit()
        try:
            await self._restore_to_database(archive, target)
            archive.status = DisasterRecoveryStatus.RESTORED
            archive.restore_database = target
            archive.completed_at = datetime.now(UTC)
            await AuditRepository(self.repository.session).record(
                actor_user_id=actor.id,
                action="DISASTER_RECOVERY_RESTORED_ISOLATED",
                resource_type="disaster_recovery",
                resource_id=str(archive.id),
                details={"target_database": target},
            )
            await self.repository.session.commit()
            await self.repository.session.refresh(archive)
            return archive
        except Exception as error:
            await self.repository.session.rollback()
            persisted = await self.repository.get(archive.id)
            if persisted:
                archive = persisted
            archive.status = DisasterRecoveryStatus.FAILED
            archive.error_message = str(error)[:2000]
            archive.completed_at = datetime.now(UTC)
            await self.repository.session.commit()
            raise

    async def _restore_to_database(
        self, archive: DisasterRecoveryArchive, target: str
    ) -> None:
        source = self._archive_path(archive)
        with tempfile.TemporaryDirectory(prefix="cctv-dr-restore-") as raw_tmp:
            temporary = Path(raw_tmp)
            package = temporary / "package.zip"
            await asyncio.to_thread(
                EncryptedArchiveCodec.decrypt,
                source,
                package,
                self.settings.dr_encryption_passphrase,
            )
            await asyncio.to_thread(DisasterRecoveryPackage.validate, package)
            dump = temporary / "database.dump"
            with zipfile.ZipFile(package) as zipped:
                with zipped.open("database/database.dump") as input_file, dump.open("wb") as output_file:
                    shutil.copyfileobj(input_file, output_file, CHUNK_SIZE)
            escaped = target.replace('"', '""')
            sql = (
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{target}' AND pid <> pg_backend_pid(); "
                f'DROP DATABASE IF EXISTS "{escaped}"; CREATE DATABASE "{escaped}";'
            )
            await self._run(self._psql_command("postgres") + ["--command", sql])
            await self._run(
                [
                    "pg_restore",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-privileges",
                    "--host",
                    self.settings.postgres_host,
                    "--port",
                    str(self.settings.postgres_port),
                    "--username",
                    self.settings.postgres_user,
                    "--dbname",
                    target,
                    str(dump),
                ]
            )
            restore_root = self.storage_root / "restores" / str(archive.id)
            await asyncio.to_thread(self._extract_storage, package, restore_root)

    def _extract_storage(self, package: Path, destination: Path) -> None:
        with zipfile.ZipFile(package) as zipped:
            for info in zipped.infolist():
                if not info.filename.startswith("storage/") or info.is_dir():
                    continue
                DisasterRecoveryPackage._safe_member(info.filename)
                relative = PurePosixPath(info.filename).relative_to("storage")
                target = (destination / Path(*relative.parts)).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise ValueError("DR storage extraction path is unsafe")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, CHUNK_SIZE)

    async def apply_retention(self, now: datetime) -> int:
        cutoff = now - timedelta(days=self.settings.dr_retention_days)
        archives = await self.repository.ready_older_than(cutoff)
        removed = 0
        for archive in archives:
            self._archive_path(archive, required=False).unlink(missing_ok=True)
            if archive.offsite_path:
                Path(archive.offsite_path).unlink(missing_ok=True)
            await self.repository.session.delete(archive)
            removed += 1
        if removed:
            await self.repository.session.commit()
        return removed

    async def _copy_offsite(
        self, archive: DisasterRecoveryArchive, source: Path
    ) -> None:
        offsite_path = self.settings.dr_offsite_path
        if not offsite_path:
            if self.settings.dr_offsite_required:
                raise RuntimeError("DR_OFFSITE_REQUIRED is enabled but DR_OFFSITE_PATH is empty")
            return
        path, checksum = await asyncio.to_thread(
            DirectoryOffsiteStorage(Path(offsite_path)).upload, source
        )
        archive.offsite_path = path
        archive.offsite_checksum_sha256 = checksum

    def _archive_path(
        self, archive: DisasterRecoveryArchive, *, required: bool = True
    ) -> Path:
        candidate = (self.storage_root / archive.file_path).resolve()
        if not candidate.is_relative_to(self.storage_root):
            raise ValueError("DR catalogue contains an unsafe archive path")
        if required and not candidate.is_file():
            raise FileNotFoundError("DR archive file is unavailable")
        return candidate

    def archive_path(self, archive: DisasterRecoveryArchive) -> Path:
        """Resolve a catalogued archive without exposing storage traversal."""
        return self._archive_path(archive)

    def _psql_command(self, database: str) -> list[str]:
        return [
            "psql",
            "--no-password",
            "--set",
            "ON_ERROR_STOP=1",
            "--host",
            self.settings.postgres_host,
            "--port",
            str(self.settings.postgres_port),
            "--username",
            self.settings.postgres_user,
            "--dbname",
            database,
        ]

    async def _run(self, command: list[str]) -> None:
        environment = os.environ.copy()
        environment["PGPASSWORD"] = self.settings.postgres_password
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.settings.dr_command_timeout_seconds
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError(f"Database command timed out: {command[0]}") from None
        if process.returncode:
            detail = (stderr or stdout).decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"{command[0]} failed: {detail[-1500:]}")
