import hashlib
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np

from app.models import (
    EvidenceAsset,
    EvidenceAssetType,
    EvidenceIntegrityStatus,
)
from app.services.capture_evidence_service import CaptureEvidenceService
from app.services.crossing_service import CrossingEvent, CrossingType
from app.services.evidence_access_service import EvidenceAccessService
from app.storage import EvidenceStorageService, SnapshotService
from app.tracker import TrackedDetection


class EvidenceSettings:
    def __init__(self, root: str) -> None:
        self.storage_path = root
        self.snapshot_jpeg_quality = 90
        self.evidence_thumbnail_width = 64
        self.evidence_signing_secret = (
            "phase-three-test-evidence-signing-secret-value"
        )
        self.evidence_access_token_expire_seconds = 60


class FakeEvidenceRepository:
    def __init__(self, asset: EvidenceAsset) -> None:
        self.asset = asset
        self.committed = False

    async def get_asset(self, asset_id):
        return self.asset if asset_id == self.asset.id else None

    async def set_integrity(
        self,
        asset,
        *,
        status,
        checksum_sha256=None,
        size_bytes=None,
    ):
        if checksum_sha256 is not None and asset.checksum_sha256 is None:
            asset.checksum_sha256 = checksum_sha256
        if size_bytes is not None:
            asset.size_bytes = size_bytes
        asset.integrity_status = status

    async def commit(self):
        self.committed = True


class CaptureEvidencePhase3Test(unittest.IsolatedAsyncioTestCase):
    def test_capture_writes_checksum_verified_bundle_with_relative_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            frame = np.zeros((180, 240, 3), dtype=np.uint8)
            occurred_at = datetime(2026, 7, 24, 9, 30, tzinfo=UTC)
            crossing = CrossingEvent(
                uuid4(),
                CrossingType.ENTER,
                "main-door",
                17,
                (100, 90),
                occurred_at,
            )
            person = TrackedDetection(
                17,
                (40, 20, 160, 170),
                0.94,
                0,
                "person",
                (100, 95),
                "down",
                ((100, 95),),
            )

            result = SnapshotService(
                EvidenceSettings(directory)
            ).save(frame, crossing, person, camera_id=str(uuid4()))

            asset_types = {asset.asset_type for asset in result.assets}
            self.assertEqual(
                asset_types,
                {
                    EvidenceAssetType.ORIGINAL_SNAPSHOT,
                    EvidenceAssetType.ANNOTATED_SNAPSHOT,
                    EvidenceAssetType.FULL_BODY,
                    EvidenceAssetType.THUMBNAIL,
                    EvidenceAssetType.METADATA_JSON,
                },
            )
            self.assertEqual(result.capture_event_id, crossing.event_id)
            self.assertEqual(
                result.idempotency_key, f"crossing:{crossing.event_id}"
            )
            for asset in result.assets:
                self.assertFalse(Path(asset.storage_key).is_absolute())
                self.assertTrue(asset.path.is_file())
                self.assertEqual(
                    asset.checksum_sha256,
                    hashlib.sha256(asset.path.read_bytes()).hexdigest(),
                )
            sidecar = json.loads(
                result.metadata_path.read_text(encoding="utf-8")
            )
            self.assertEqual(sidecar["schema_version"], 2)
            self.assertNotIn("image_path", sidecar)

    def test_storage_rejects_traversal_and_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = EvidenceStorageService(EvidenceSettings(directory))
            with self.assertRaisesRegex(ValueError, "safe relative path"):
                storage.write_json(
                    "../escape.json",
                    {},
                )
            storage.write_json("2026/07/24/event.json", {"first": True})
            with self.assertRaisesRegex(
                FileExistsError, "already exists"
            ):
                storage.write_json(
                    "2026/07/24/event.json",
                    {"second": True},
                )

    async def test_integrity_verification_enrolls_legacy_checksum_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "2026" / "07" / "24" / "legacy.jpg"
            evidence.parent.mkdir(parents=True)
            evidence.write_bytes(b"legacy-evidence")
            asset = EvidenceAsset(
                id=uuid4(),
                capture_event_id=uuid4(),
                asset_type=EvidenceAssetType.ANNOTATED_SNAPSHOT,
                sequence_index=0,
                storage_key=evidence.relative_to(root).as_posix(),
                checksum_sha256=None,
                integrity_status=EvidenceIntegrityStatus.UNVERIFIED,
                mime_type="image/jpeg",
                size_bytes=0,
                is_primary=True,
                captured_at=datetime.now(UTC),
            )
            repository = FakeEvidenceRepository(asset)
            service = CaptureEvidenceService(
                repository,
                EvidenceSettings(directory),
            )

            result = await service.verify_asset(asset.id)

            self.assertIsNotNone(result)
            self.assertEqual(
                asset.integrity_status, EvidenceIntegrityStatus.VERIFIED
            )
            self.assertEqual(
                asset.checksum_sha256,
                hashlib.sha256(b"legacy-evidence").hexdigest(),
            )
            self.assertEqual(asset.size_bytes, len(b"legacy-evidence"))
            self.assertTrue(repository.committed)

    async def test_integrity_verification_detects_corruption_and_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "asset.jpg"
            evidence.write_bytes(b"changed")
            asset = EvidenceAsset(
                id=uuid4(),
                capture_event_id=uuid4(),
                asset_type=EvidenceAssetType.ANNOTATED_SNAPSHOT,
                sequence_index=0,
                storage_key="asset.jpg",
                checksum_sha256=hashlib.sha256(b"original").hexdigest(),
                integrity_status=EvidenceIntegrityStatus.VERIFIED,
                mime_type="image/jpeg",
                size_bytes=len(b"original"),
                is_primary=True,
                captured_at=datetime.now(UTC),
            )
            repository = FakeEvidenceRepository(asset)
            service = CaptureEvidenceService(
                repository,
                EvidenceSettings(directory),
            )

            result = await service.verify_asset(asset.id)
            self.assertIsNotNone(result)
            self.assertEqual(
                asset.integrity_status, EvidenceIntegrityStatus.CORRUPT
            )

            evidence.unlink()
            result = await service.verify_asset(asset.id)
            self.assertIsNotNone(result)
            self.assertEqual(
                asset.integrity_status, EvidenceIntegrityStatus.MISSING
            )

    def test_asset_grant_is_bound_to_asset_and_resolves_safe_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "asset.json"
            path.write_text("{}", encoding="utf-8")
            settings = EvidenceSettings(directory)
            service = EvidenceAccessService(settings)
            asset_id = uuid4()
            user_id = uuid4()
            grant = service.issue_asset(asset_id, user_id, 3)

            authorization = service.authorize_asset(
                grant.access_token, asset_id
            )
            self.assertEqual(authorization.user_id, user_id)
            with self.assertRaisesRegex(
                ValueError, "not valid for this asset"
            ):
                service.authorize_asset(grant.access_token, uuid4())
            resolved, media_type = service.resolve_asset(
                SimpleNamespace(
                    storage_key="asset.json",
                    mime_type="application/json",
                )
            )
            self.assertEqual(resolved, path)
            self.assertEqual(media_type, "application/json")
