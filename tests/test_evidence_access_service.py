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
    token_version = 7

    grant = service.issue_snapshot(snapshot_id, user_id, token_version)
    authorization = service.authorize_snapshot(grant.access_token, snapshot_id)

    assert authorization.user_id == user_id
    assert authorization.token_version == token_version
    assert authorization.grant_id == grant.grant_id
    assert grant.content_url == f"/api/v1/evidence/snapshots/{snapshot_id}/content"
    assert "?" not in grant.content_url
    assert grant.access_token not in grant.content_url
    with pytest.raises(ValueError, match="not valid for this snapshot"):
        service.authorize_snapshot(grant.access_token, uuid4())


def test_snapshot_path_must_remain_inside_storage(tmp_path: Path) -> None:
    service = EvidenceAccessService(settings(tmp_path))
    outside = tmp_path.parent / "outside.jpg"
    outside.write_bytes(b"outside")

    with pytest.raises(FileNotFoundError, match="unavailable"):
        service.resolve_snapshot(SimpleNamespace(image_path=str(outside)))


def test_relative_parent_path_cannot_escape_storage(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    (tmp_path / "outside.jpg").write_bytes(b"outside")
    service = EvidenceAccessService(settings(storage))

    with pytest.raises(FileNotFoundError, match="unavailable"):
        service.resolve_snapshot(SimpleNamespace(image_path="../outside.jpg"))


def test_symlink_inside_storage_cannot_point_outside(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"outside")
    link = storage / "evidence.jpg"
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"platform does not support symbolic links: {error}")
    service = EvidenceAccessService(settings(storage))

    with pytest.raises(FileNotFoundError, match="unavailable"):
        service.resolve_snapshot(SimpleNamespace(image_path=str(link)))


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
