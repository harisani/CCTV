from collections.abc import AsyncGenerator, Generator

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.database.session import get_session
from app.repository import BackupRepository, CameraRepository, DisasterRecoveryRepository, EventRepository, PersonRepository, SnapshotRepository, StatisticsRepository, UserRepository
from app.services.container import ServiceContainer, get_service_container
from app.services.health_service import HealthService


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


def get_services() -> Generator[ServiceContainer, None, None]:
    """Expose long-lived services through FastAPI dependency injection."""
    yield get_service_container()


def get_health_service() -> Generator[HealthService, None, None]:
    """Provide the stateless health probe service."""
    yield get_service_container().health
