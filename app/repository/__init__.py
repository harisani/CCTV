"""Async repository implementations."""

from app.repository.audit_repository import AuditRepository
from app.repository.ai_job_repository import AIJobRepository
from app.repository.backup_repository import BackupRepository
from app.repository.biometric_repository import BiometricRepository
from app.repository.body_analysis_repository import BodyAnalysisRepository
from app.repository.journey_repository import JourneyRepository
from app.repository.camera_repository import CameraRepository
from app.repository.capture_evidence_repository import CaptureEvidenceRepository
from app.repository.camera_runtime_repository import CameraRuntimeRepository
from app.repository.disaster_recovery_repository import DisasterRecoveryRepository
from app.repository.event_repository import EventRepository
from app.repository.person_repository import PersonRepository
from app.repository.pipeline_repository import PipelineRepository
from app.repository.snapshot_repository import SnapshotRepository
from app.repository.statistics_repository import StatisticsRepository
from app.repository.topology_repository import TopologyRepository
from app.repository.user_repository import UserRepository
from app.repository.zone_transition_repository import (
    ZoneTransitionRepository,
)

__all__ = [
    "AuditRepository",
    "AIJobRepository",
    "BackupRepository",
    "BiometricRepository",
    "BodyAnalysisRepository",
    "JourneyRepository",
    "CameraRepository",
    "CaptureEvidenceRepository",
    "CameraRuntimeRepository",
    "DisasterRecoveryRepository",
    "EventRepository",
    "PersonRepository",
    "PipelineRepository",
    "SnapshotRepository",
    "StatisticsRepository",
    "TopologyRepository",
    "UserRepository",
    "ZoneTransitionRepository",
]
