from collections.abc import AsyncGenerator, Generator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.database.session import get_session
from app.repository import (
    BackupRepository,
    AIJobRepository,
    BiometricRepository,
    BodyAnalysisRepository,
    CameraRepository,
    CaptureEvidenceRepository,
    DisasterRecoveryRepository,
    EventRepository,
    JourneyRepository,
    OccupancyRepository,
    PersonRepository,
    SnapshotRepository,
    StatisticsRepository,
    TopologyRepository,
    UserRepository,
    ZoneTransitionRepository,
)
from app.services.container import ServiceContainer, get_service_container
from app.services.ai_job_service import AIJobService
from app.services.health_service import HealthService
from app.services.capture_evidence_service import CaptureEvidenceService
from app.services.biometric_identity_service import BiometricIdentityService
from app.services.body_analysis_service import BodyAnalysisService
from app.services.journey_correlation_service import (
    JourneyCorrelationService,
)
from app.services.occupancy_service import OccupancyService
from app.services.login_rate_limiter import LoginRateLimiter
from app.services.topology_service import TopologyService
from app.services.zone_transition_service import ZoneTransitionService


def get_app_settings() -> Generator[Settings, None, None]:
    """FastAPI dependency provider for immutable application settings."""
    yield get_settings()


async def get_database_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide one SQLAlchemy database session for each HTTP request."""
    async for session in get_session():
        yield session


async def get_camera_repository() -> AsyncGenerator[CameraRepository, None]:
    async for session in get_session():
        yield CameraRepository(session)


async def get_event_repository() -> AsyncGenerator[EventRepository, None]:
    async for session in get_session():
        yield EventRepository(session)


async def get_person_repository() -> AsyncGenerator[PersonRepository, None]:
    async for session in get_session():
        yield PersonRepository(session)


async def get_snapshot_repository() -> AsyncGenerator[SnapshotRepository, None]:
    async for session in get_session():
        yield SnapshotRepository(session)


async def get_statistics_repository() -> AsyncGenerator[StatisticsRepository, None]:
    async for session in get_session():
        yield StatisticsRepository(session)


async def get_user_repository() -> AsyncGenerator[UserRepository, None]:
    async for session in get_session():
        yield UserRepository(session)


async def get_backup_repository() -> AsyncGenerator[BackupRepository, None]:
    async for session in get_session():
        yield BackupRepository(session)


async def get_disaster_recovery_repository() -> AsyncGenerator[DisasterRecoveryRepository, None]:
    async for session in get_session():
        yield DisasterRecoveryRepository(session)


async def get_topology_service() -> AsyncGenerator[TopologyService, None]:
    """Provide the topology use-case service with one transaction scope."""
    async for session in get_session():
        yield TopologyService(TopologyRepository(session))


async def get_capture_evidence_service(
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_database_session),
) -> AsyncGenerator[CaptureEvidenceService, None]:
    """Provide capture/evidence use cases in the request transaction."""
    yield CaptureEvidenceService(
        CaptureEvidenceRepository(session),
        settings,
    )


async def get_ai_job_service(
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_database_session),
) -> AsyncGenerator[AIJobService, None]:
    """Provide durable queue observation and administration use cases."""
    yield AIJobService(
        AIJobRepository(session),
        backlog_warning_threshold=settings.ai_queue_backlog_warning_threshold,
    )


async def get_biometric_identity_service(
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_database_session),
) -> AsyncGenerator[BiometricIdentityService, None]:
    """Provide biometric use cases without exposing raw embeddings."""
    yield BiometricIdentityService(BiometricRepository(session), settings)


async def get_body_analysis_service(
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_database_session),
) -> AsyncGenerator[BodyAnalysisService, None]:
    """Provide body ReID and PPE observation use cases."""
    yield BodyAnalysisService(BodyAnalysisRepository(session), settings)


async def get_journey_correlation_service(
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_database_session),
) -> AsyncGenerator[JourneyCorrelationService, None]:
    """Provide global journey correlation and observation queries."""
    yield JourneyCorrelationService(JourneyRepository(session), settings)


async def get_occupancy_service(
    settings: Settings = Depends(get_app_settings),
    session: AsyncSession = Depends(get_database_session),
) -> AsyncGenerator[OccupancyService, None]:
    """Provide Phase 9 occupancy reconstruction and queries."""
    yield OccupancyService(OccupancyRepository(session), settings)


async def get_zone_transition_service(
    session: AsyncSession = Depends(get_database_session),
) -> AsyncGenerator[ZoneTransitionService, None]:
    """Provide local-track and zone-transition observation use cases."""
    yield ZoneTransitionService(ZoneTransitionRepository(session))


def get_services() -> Generator[ServiceContainer, None, None]:
    """Expose long-lived services through FastAPI dependency injection."""
    yield get_service_container()


def get_health_service() -> Generator[HealthService, None, None]:
    """Provide the stateless health probe service."""
    yield get_service_container().health


def get_login_rate_limiter() -> Generator[LoginRateLimiter, None, None]:
    """Provide the process-local singleton login limiter."""
    yield get_service_container().login_limiter
