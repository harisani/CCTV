"""Atomic, path-safe storage for immutable CCTV evidence objects."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from app.models import EvidenceAssetType


@dataclass(frozen=True, slots=True)
class EvidenceFile:
    asset_id: UUID
    asset_type: EvidenceAssetType
    sequence_index: int
    storage_key: str
    path: Path
    checksum_sha256: str
    mime_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    is_primary: bool = False
    metadata: dict[str, Any] | None = None


class EvidenceStorageService:
    """Write evidence once, atomically, below the configured storage root."""

    def __init__(
        self,
        settings: Any,
        *,
        cv2_module: Any | None = None,
    ) -> None:
        self._root = Path(settings.storage_path).expanduser().resolve()
        self._jpeg_quality = settings.snapshot_jpeg_quality
        self._cv2_module = cv2_module

    @property
    def root(self) -> Path:
        return self._root

    def write_image(
        self,
        storage_key: str,
        image: Any,
        *,
        asset_type: EvidenceAssetType,
        sequence_index: int = 0,
        is_primary: bool = False,
        metadata: dict[str, Any] | None = None,
        idempotent: bool = False,
    ) -> EvidenceFile:
        target = self.resolve_key(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(
            f".{target.stem}.{uuid4().hex}.tmp{target.suffix}"
        )
        try:
            cv2 = self._get_cv2()
            if not cv2.imwrite(
                str(temporary),
                image,
                [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality],
            ):
                raise OSError("OpenCV could not encode evidence image")
            self._publish_once(
                temporary,
                target,
                idempotent=idempotent,
            )
        finally:
            temporary.unlink(missing_ok=True)

        width, height = self._image_dimensions(image)
        return self._describe(
            target,
            asset_type=asset_type,
            sequence_index=sequence_index,
            mime_type="image/jpeg",
            width=width,
            height=height,
            is_primary=is_primary,
            metadata=metadata,
        )

    def write_json(
        self,
        storage_key: str,
        payload: dict[str, Any],
        *,
        asset_type: EvidenceAssetType = EvidenceAssetType.METADATA_JSON,
        sequence_index: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> EvidenceFile:
        target = self.resolve_key(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            self._publish_once(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return self._describe(
            target,
            asset_type=asset_type,
            sequence_index=sequence_index,
            mime_type="application/json",
            metadata=metadata,
        )

    def resolve_key(self, storage_key: str) -> Path:
        key = PurePosixPath(storage_key)
        if (
            not storage_key
            or key.is_absolute()
            or ".." in key.parts
            or "." in key.parts
        ):
            raise ValueError("Evidence storage key must be a safe relative path")
        resolved = (self._root / Path(*key.parts)).resolve()
        if not resolved.is_relative_to(self._root):
            raise ValueError("Evidence storage key escapes configured storage")
        return resolved

    @staticmethod
    def remove(files: tuple[EvidenceFile, ...] | list[EvidenceFile]) -> None:
        for file in files:
            file.path.unlink(missing_ok=True)

    @classmethod
    def _publish_once(
        cls,
        temporary: Path,
        target: Path,
        *,
        idempotent: bool = False,
    ) -> None:
        try:
            os.link(temporary, target)
        except FileExistsError as error:
            if idempotent and cls._file_checksum(temporary) == cls._file_checksum(
                target
            ):
                temporary.unlink()
                return
            raise FileExistsError(
                "Immutable evidence target already exists"
            ) from error
        temporary.unlink()
        target.chmod(0o640)

    @staticmethod
    def _file_checksum(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _describe(
        self,
        path: Path,
        *,
        asset_type: EvidenceAssetType,
        sequence_index: int,
        mime_type: str,
        width: int | None = None,
        height: int | None = None,
        is_primary: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> EvidenceFile:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return EvidenceFile(
            asset_id=uuid4(),
            asset_type=asset_type,
            sequence_index=sequence_index,
            storage_key=path.relative_to(self._root).as_posix(),
            path=path,
            checksum_sha256=digest.hexdigest(),
            mime_type=mime_type,
            size_bytes=path.stat().st_size,
            width=width,
            height=height,
            is_primary=is_primary,
            metadata=metadata,
        )

    @staticmethod
    def _image_dimensions(image: Any) -> tuple[int | None, int | None]:
        shape = getattr(image, "shape", None)
        if shape is None or len(shape) < 2:
            return None, None
        return int(shape[1]), int(shape[0])

    def _get_cv2(self) -> Any:
        if self._cv2_module is not None:
            return self._cv2_module
        try:
            import cv2
        except ImportError as error:
            raise RuntimeError("Install OpenCV to store evidence") from error
        self._cv2_module = cv2
        return cv2
