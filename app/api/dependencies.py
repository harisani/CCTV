from collections.abc import AsyncGenerator, Generator

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.database.session import get_session
from app.repository import (
    AccessCameraMatchRepository,
    AccessEventRepository,
    BackupRepository,
    CameraRepository,
    DisasterRecoveryRepository,
    EmployeeRepository,
    EventRepository,
    PersonRepository,
    RFIDCardRepository,
    RFIDReaderRepository,
    SnapshotRepository,
    StatisticsRepository,
    UserRepository,
)
from app.services.container import ServiceContainer, get_service_container
from app.services.employee_service import EmployeeService
from app.services.rfid_simulator_service import RFIDSimulatorService


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


async def get_employee_repository() -> AsyncGenerator[EmployeeRepository, None]:
    async for session in get_session():
        yield EmployeeRepository(session)


async def get_rfid_card_repository() -> AsyncGenerator[RFIDCardRepository, None]:
    async for session in get_session():
        yield RFIDCardRepository(session)


async def get_rfid_reader_repository() -> AsyncGenerator[RFIDReaderRepository, None]:
    async for session in get_session():
        yield RFIDReaderRepository(session)


async def get_access_event_repository() -> AsyncGenerator[AccessEventRepository, None]:
    async for session in get_session():
        yield AccessEventRepository(session)


async def get_access_camera_match_repository() -> AsyncGenerator[
    AccessCameraMatchRepository, None
]:
    async for session in get_session():
        yield AccessCameraMatchRepository(session)


async def get_employee_service() -> AsyncGenerator[EmployeeService, None]:
    """Provide employee and card repositories backed by one request session."""
    async for session in get_session():
        yield EmployeeService(
            EmployeeRepository(session),
            RFIDCardRepository(session),
        )


async def get_rfid_simulator_service() -> AsyncGenerator[RFIDSimulatorService, None]:
    """Provide all RFID simulator repositories within one transaction boundary."""
    settings = get_settings()
    async for session in get_session():
        yield RFIDSimulatorService(
            settings,
            RFIDReaderRepository(session),
            RFIDCardRepository(session),
            EmployeeRepository(session),
            AccessEventRepository(session),
        )


def get_services() -> Generator[ServiceContainer, None, None]:
    """Expose long-lived services through FastAPI dependency injection."""
    yield get_service_container()
