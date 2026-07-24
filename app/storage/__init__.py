"""Snapshot storage adapters."""

from app.storage.evidence_storage_service import EvidenceFile, EvidenceStorageService
from app.storage.snapshot_service import SnapshotResult, SnapshotService

__all__ = [
    "EvidenceFile",
    "EvidenceStorageService",
    "SnapshotResult",
    "SnapshotService",
]
