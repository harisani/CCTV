from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.evidence_access_service import EvidenceAccessService


def settings(storage_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        storage_path=storage_path,
        evidence_signing_secret="evidence-signing-secret-with-at-least-32-characters",
        evidence_access_token_expire_seconds=60,
    )


def test_signed_grant_is_bound_to_snapshot_and_user(tmp_path: Path) -> None:
    service = EvidenceAccessService(settings(tmp_path))
    snapshot_id = uuid4()
    user_id = uuid4()

    grant = service.issue_snapshot(snapshot_id, user_id)
    subject = service.authorize_snapshot(grant.token, snapshot_id)

    assert subject == user_id
    assert str(snapshot_id) in grant.content_url
    with pytest.raises(ValueError, match="not valid for this snapshot"):
        service.authorize_snapshot(grant.token, uuid4())


def test_snapshot_path_must_remain_inside_storage(tmp_path: Path) -> None:
    service = EvidenceAccessService(settings(tmp_path))
    outside = tmp_path.parent / "outside.jpg"
    outside.write_bytes(b"outside")

    with pytest.raises(FileNotFoundError, match="unavailable"):
        service.resolve_snapshot(SimpleNamespace(image_path=str(outside)))


def test_snapshot_path_resolves_jpeg_inside_storage(tmp_path: Path) -> None:
    image = tmp_path / "2026" / "07" / "evidence.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"jpeg")
    service = EvidenceAccessService(settings(tmp_path))

    path, media_type = service.resolve_snapshot(
        SimpleNamespace(image_path=str(image))
    )

    assert path == image.resolve()
    assert media_type == "image/jpeg"
