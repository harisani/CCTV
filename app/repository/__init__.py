"""Async repository implementations."""

from app.repository.access_event_repository import (
    AccessCameraMatchRepository,
    AccessEventRepository,
)
from app.repository.camera_repository import CameraRepository
from app.repository.camera_runtime_repository import CameraRuntimeRepository
from app.repository.event_repository import EventRepository
from app.repository.employee_repository import EmployeeRepository
from app.repository.person_repository import PersonRepository
from app.repository.snapshot_repository import SnapshotRepository
from app.repository.statistics_repository import StatisticsRepository
from app.repository.tracking_repository import TrackingRepository
from app.repository.user_repository import UserRepository
from app.repository.audit_repository import AuditRepository
from app.repository.backup_repository import BackupRepository
from app.repository.disaster_recovery_repository import DisasterRecoveryRepository
from app.repository.pipeline_repository import PipelineRepository
from app.repository.rfid_card_repository import RFIDCardRepository
from app.repository.rfid_reader_repository import RFIDReaderRepository

__all__ = [
    "AccessCameraMatchRepository",
    "AccessEventRepository",
    "AuditRepository",
    "BackupRepository",
    "CameraRepository",
    "CameraRuntimeRepository",
    "DisasterRecoveryRepository",
    "EmployeeRepository",
    "EventRepository",
    "PersonRepository",
    "PipelineRepository",
    "RFIDCardRepository",
    "RFIDReaderRepository",
    "SnapshotRepository",
    "StatisticsRepository",
    "TrackingRepository",
    "UserRepository",
]
