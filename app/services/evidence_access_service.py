"""Short-lived, path-safe access to sensitive snapshot evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import jwt


@dataclass(frozen=True, slots=True)
class EvidenceGrant:
    access_token: str
    content_url: str
    expires_at: datetime
    grant_id: UUID


@dataclass(frozen=True, slots=True)
class EvidenceAuthorization:
    user_id: UUID
    token_version: int
    grant_id: UUID


class EvidenceAccessService:
    algorithm = "HS256"

    def __init__(self, settings: Any) -> None:
        self._storage_root = Path(settings.storage_path).resolve()
        self._secret = settings.evidence_signing_secret
        self._expire_seconds = settings.evidence_access_token_expire_seconds
        if len(self._secret) < 32:
            raise ValueError("Evidence signing secret must contain at least 32 characters")

    def issue_snapshot(
        self,
        snapshot_id: UUID,
        user_id: UUID,
        token_version: int,
    ) -> EvidenceGrant:
        expires_at = datetime.now(UTC) + timedelta(seconds=self._expire_seconds)
        grant_id = uuid4()
        token = jwt.encode(
            {
                "typ": "evidence-access",
                "snapshot_id": str(snapshot_id),
                "sub": str(user_id),
                "ver": token_version,
                "jti": str(grant_id),
                "exp": expires_at,
            },
            self._secret,
            algorithm=self.algorithm,
        )
        return EvidenceGrant(
            access_token=token,
            content_url=f"/api/v1/evidence/snapshots/{snapshot_id}/content",
            expires_at=expires_at,
            grant_id=grant_id,
        )

    def authorize_snapshot(
        self,
        token: str,
        snapshot_id: UUID,
    ) -> EvidenceAuthorization:
        try:
            payload = jwt.decode(token, self._secret, algorithms=[self.algorithm])
            if payload.get("typ") != "evidence-access":
                raise ValueError("Evidence token has an invalid purpose")
            if payload.get("snapshot_id") != str(snapshot_id):
                raise ValueError("Evidence token is not valid for this snapshot")
            token_version = payload["ver"]
            if type(token_version) is not int:
                raise TypeError("Evidence token version must be an integer")
            return EvidenceAuthorization(
                user_id=UUID(payload["sub"]),
                token_version=token_version,
                grant_id=UUID(payload["jti"]),
            )
        except jwt.PyJWTError as error:
            raise ValueError("Evidence token is invalid or expired") from error
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, ValueError) and str(error).startswith("Evidence token"):
                raise
            raise ValueError("Evidence token payload is invalid") from error

    def resolve_snapshot(self, snapshot: Any) -> tuple[Path, str]:
        raw = Path(snapshot.image_path)
        candidates = (
            [raw.resolve()]
            if raw.is_absolute()
            else [(Path.cwd() / raw).resolve(), (self._storage_root / raw).resolve()]
        )
        path = next(
            (
                candidate
                for candidate in candidates
                if candidate.is_relative_to(self._storage_root) and candidate.is_file()
            ),
            None,
        )
        if path is None:
            raise FileNotFoundError("Snapshot evidence is unavailable")
        suffix = path.suffix.lower()
        media_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
        }
        if suffix not in media_types:
            raise FileNotFoundError("Snapshot evidence type is not supported")
        return path, media_types[suffix]
