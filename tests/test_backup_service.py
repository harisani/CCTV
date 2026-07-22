import asyncio
import json
import zipfile
from datetime import UTC, date, datetime, time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.backup_scheduler import BackupScheduler
from app.services.backup_service import ARCHIVE_ENTITIES, ArchiveCodec, ArchiveReader


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        backup_max_upload_mb=10,
        backup_max_members=100,
        backup_max_expansion_ratio=100,
    )


def empty_records() -> dict[str, list[dict]]:
    return {entity: [] for entity in ARCHIVE_ENTITIES}


def test_archive_round_trip_and_snapshot_read(tmp_path: Path) -> None:
    snapshot_id = uuid4()
    image = tmp_path / "source.jpg"
    image.write_bytes(b"jpeg-test-content")
    records = empty_records()
    records["events"] = [{"id": str(uuid4()), "event_type": "ENTER"}]
    records["trackings"] = [{"id": str(uuid4()), "byte_track_id": 42}]
    records["snapshots"] = [
        {
            "id": str(snapshot_id),
            "event_id": str(uuid4()),
            "archive_image_path": f"media/{snapshot_id}.jpg",
        }
    ]
    destination = tmp_path / "backup.zip"
    start = datetime(2026, 7, 20, tzinfo=UTC)
    manifest = ArchiveCodec.build(
        destination,
        backup_date=date(2026, 7, 20),
        coverage_start=start,
        coverage_end=start.replace(day=21),
        timezone_name="Asia/Jakarta",
        records=records,
        media=[(f"media/{snapshot_id}.jpg", image)],
    )

    validated, checksum, size = ArchiveCodec.validate(destination, settings())
    assert validated["record_counts"] == manifest["record_counts"]
    assert len(checksum) == 64
    assert size == destination.stat().st_size

    archive = SimpleNamespace(file_path="backup.zip")
    reader = ArchiveReader(tmp_path)
    items, total = reader.list_records(
        archive, "events", search="enter", offset=0, limit=10
    )
    assert total == 1
    assert items[0]["event_type"] == "ENTER"
    content, content_type = reader.snapshot_bytes(archive, snapshot_id)
    assert content == b"jpeg-test-content"
    assert content_type == "image/jpeg"


def test_archive_rejects_path_traversal(tmp_path: Path) -> None:
    malicious = tmp_path / "malicious.zip"
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("../escape.txt", b"blocked")
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": "cctv-people-flow-observational-backup",
                    "schema_version": 1,
                    "backup_date": "2026-07-20",
                    "record_counts": {entity: 0 for entity in ARCHIVE_ENTITIES},
                    "members": [],
                }
            ),
        )
    with pytest.raises(ValueError, match="unsafe"):
        ArchiveCodec.validate(malicious, settings())


def test_scheduler_does_nothing_before_schedule() -> None:
    scheduler_settings = SimpleNamespace(
        backup_timezone="Asia/Jakarta",
        backup_schedule_time="00:15",
    )
    scheduler = BackupScheduler(scheduler_settings, session_factory=None)
    before_schedule = datetime.combine(
        date(2026, 7, 21), time(hour=0, minute=14), tzinfo=scheduler.timezone
    )
    assert asyncio.run(scheduler.run_if_due(before_schedule)) is False
