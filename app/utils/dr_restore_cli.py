"""Offline, explicitly destructive disaster-recovery cutover command."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from app.config.settings import get_settings
from app.services.disaster_recovery_service import (
    CHUNK_SIZE,
    DisasterRecoveryPackage,
    EncryptedArchiveCodec,
)


async def _run_database_command(command: list[str], password: str, timeout: int) -> None:
    environment = os.environ.copy()
    environment["PGPASSWORD"] = password
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError(f"Database command timed out: {command[0]}") from None
    if process.returncode:
        detail = (stderr or stdout).decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"{command[0]} failed: {detail[-1500:]}")


def _digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def _restore_storage(
    package: Path, storage_root: Path, recovery_id: str, manifest: dict
) -> Path:
    rollback_root = storage_root / "pre-restore" / recovery_id
    checksums = {item["path"]: item["sha256"] for item in manifest["members"]}
    with zipfile.ZipFile(package) as zipped:
        for info in zipped.infolist():
            if not info.filename.startswith("storage/") or info.is_dir():
                continue
            DisasterRecoveryPackage._safe_member(info.filename)
            relative = PurePosixPath(info.filename).relative_to("storage")
            target = (storage_root / Path(*relative.parts)).resolve()
            if not target.is_relative_to(storage_root.resolve()):
                raise ValueError("DR storage extraction path is unsafe")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".drtmp")
            with zipped.open(info) as source, temporary.open("wb") as output:
                shutil.copyfileobj(source, output, CHUNK_SIZE)
            expected = checksums[info.filename]
            if _digest(temporary) != expected:
                temporary.unlink(missing_ok=True)
                raise ValueError(f"Restored storage checksum failed: {relative}")
            if target.exists() and _digest(target) != expected:
                rollback = rollback_root / Path(*relative.parts)
                rollback.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, rollback)
            os.replace(temporary, target)
    return rollback_root


async def restore_live(archive_path: Path, confirmation: str) -> None:
    settings = get_settings()
    expected = f"RESTORE LIVE {settings.postgres_db}"
    if not settings.dr_allow_in_place_restore:
        raise RuntimeError("Set DR_ALLOW_IN_PLACE_RESTORE=true before live recovery")
    if confirmation != expected:
        raise ValueError(f"Confirmation must exactly match: {expected}")
    if len(settings.dr_encryption_passphrase) < 16:
        raise ValueError("DR_ENCRYPTION_PASSPHRASE is not configured")
    archive_path = archive_path.resolve()
    if not archive_path.is_file():
        raise FileNotFoundError("DR archive does not exist")

    recovery_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    with tempfile.TemporaryDirectory(prefix="cctv-live-restore-") as raw_tmp:
        temporary = Path(raw_tmp)
        package = temporary / "package.zip"
        dump = temporary / "database.dump"
        await asyncio.to_thread(
            EncryptedArchiveCodec.decrypt,
            archive_path,
            package,
            settings.dr_encryption_passphrase,
        )
        manifest = await asyncio.to_thread(DisasterRecoveryPackage.validate, package)
        with zipfile.ZipFile(package) as zipped:
            with zipped.open("database/database.dump") as source, dump.open("wb") as output:
                shutil.copyfileobj(source, output, CHUNK_SIZE)

        common = [
            "--host",
            settings.postgres_host,
            "--port",
            str(settings.postgres_port),
            "--username",
            settings.postgres_user,
        ]
        database = settings.postgres_db
        escaped = database.replace('"', '""')
        sql = (
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{database}' AND pid <> pg_backend_pid(); "
            f'DROP DATABASE IF EXISTS "{escaped}"; CREATE DATABASE "{escaped}";'
        )
        await _run_database_command(
            [
                "psql",
                "--no-password",
                "--set",
                "ON_ERROR_STOP=1",
                *common,
                "--dbname",
                "postgres",
                "--command",
                sql,
            ],
            settings.postgres_password,
            settings.dr_command_timeout_seconds,
        )
        await _run_database_command(
            [
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                *common,
                "--dbname",
                database,
                str(dump),
            ],
            settings.postgres_password,
            settings.dr_command_timeout_seconds,
        )
        rollback_root = await asyncio.to_thread(
            _restore_storage,
            package,
            Path(settings.storage_path).resolve(),
            recovery_id,
            manifest,
        )
        receipt = Path(settings.storage_path) / "restores" / f"live-{recovery_id}.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(
            json.dumps(
                {
                    "restored_at": datetime.now(UTC).isoformat(),
                    "archive": str(archive_path),
                    "database": database,
                    "manifest": manifest,
                    "previous_files": str(rollback_root),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        os.chmod(receipt, 0o600)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore an encrypted CCTV DR archive into the live database"
    )
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--confirm", required=True)
    arguments = parser.parse_args()
    asyncio.run(restore_live(arguments.archive, arguments.confirm))


if __name__ == "__main__":
    main()
