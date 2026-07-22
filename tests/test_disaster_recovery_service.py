import json
import zipfile
from pathlib import Path

import pytest

from app.services.disaster_recovery_service import (
    DirectoryOffsiteStorage,
    DisasterRecoveryPackage,
    EncryptedArchiveCodec,
)


PASSPHRASE = "a-strong-test-passphrase-only"


def test_encrypted_archive_round_trip_and_wrong_key(tmp_path: Path) -> None:
    source = tmp_path / "source.zip"
    source.write_bytes(b"private disaster recovery payload" * 100)
    encrypted = tmp_path / "backup.dr.enc"
    decrypted = tmp_path / "restored.zip"

    EncryptedArchiveCodec.encrypt(source, encrypted, PASSPHRASE)
    assert encrypted.read_bytes() != source.read_bytes()
    EncryptedArchiveCodec.decrypt(encrypted, decrypted, PASSPHRASE)
    assert decrypted.read_bytes() == source.read_bytes()

    with pytest.raises(ValueError, match="passphrase|integrity"):
        EncryptedArchiveCodec.decrypt(
            encrypted, tmp_path / "wrong.zip", "a-different-long-passphrase"
        )


def test_package_round_trip_includes_database_and_storage(tmp_path: Path) -> None:
    database = tmp_path / "database.dump"
    database.write_bytes(b"postgres-custom-dump")
    storage = tmp_path / "storage"
    (storage / "2026" / "07").mkdir(parents=True)
    (storage / "2026" / "07" / "snapshot.jpg").write_bytes(b"jpeg")
    excluded = storage / "disaster-recovery" / "old.dr.enc"
    excluded.parent.mkdir(parents=True)
    excluded.write_bytes(b"must-not-be-recursive")
    package = tmp_path / "package.zip"

    manifest = DisasterRecoveryPackage.build(
        package,
        database_dump=database,
        storage_root=storage,
        include_storage=True,
        database_name="cctv",
    )
    validated = DisasterRecoveryPackage.validate(package)

    assert validated == manifest
    names = {member["path"] for member in manifest["members"]}
    assert "database/database.dump" in names
    assert "storage/2026/07/snapshot.jpg" in names
    assert not any("old.dr.enc" in name for name in names)


def test_package_rejects_undeclared_and_traversal_member(tmp_path: Path) -> None:
    package = tmp_path / "bad.zip"
    with zipfile.ZipFile(package, "w") as zipped:
        zipped.writestr("database/database.dump", b"dump")
        zipped.writestr("../escape", b"bad")
        zipped.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": "cctv-people-flow-disaster-recovery",
                    "schema_version": 1,
                    "members": [],
                }
            ),
        )
    with pytest.raises(ValueError, match="unsafe"):
        DisasterRecoveryPackage.validate(package)


def test_offsite_copy_is_verified(tmp_path: Path) -> None:
    source = tmp_path / "backup.dr.enc"
    source.write_bytes(b"encrypted")
    path, checksum = DirectoryOffsiteStorage(tmp_path / "nas").upload(source)
    destination = Path(path)
    assert destination.read_bytes() == source.read_bytes()
    assert len(checksum) == 64
