from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.error_handlers import register_exception_handlers
from app.api.router import api_router
from app.config.settings import get_settings
from app.dashboard.realtime import dashboard_hub
from app.database.session import SessionLocal, engine
from app.repository import CameraRuntimeRepository
from app.services.camera_runtime_manager import CameraRuntimeManager
from app.utils.logging import configure_logging
from app.utils.runtime import configure_compute_runtime
from app.services.user_service import ensure_bootstrap_admin
from app.services.backup_scheduler import BackupScheduler
from app.services.disaster_recovery_scheduler import DisasterRecoveryScheduler
from app.services.realtime_pipeline import RealtimePipelineFactory
from app.services.reid_retention_service import ReIdRetentionService
from app.services.presence_reconciliation_scheduler import PresenceReconciliationScheduler
from app.services.container import get_service_container


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Set up and release process-wide resources for the HTTP application."""
    settings = get_settings()
    services = get_service_container()
    configure_logging(settings.log_level)
    configure_compute_runtime(settings)
    await ensure_bootstrap_admin(SessionLocal, settings)
    camera_runtime: CameraRuntimeManager | None = None
    backup_scheduler: BackupScheduler | None = None
    dr_scheduler: DisasterRecoveryScheduler | None = None
    reid_retention: ReIdRetentionService | None = None
    presence_reconciliation: PresenceReconciliationScheduler | None = None
    if settings.enable_backup_scheduler:
        backup_scheduler = BackupScheduler(settings, SessionLocal)
        await backup_scheduler.start()
    if settings.enable_dr_scheduler:
        dr_scheduler = DisasterRecoveryScheduler(settings, SessionLocal)
        await dr_scheduler.start()
    if settings.enable_reid_retention:
        reid_retention = ReIdRetentionService(settings, SessionLocal)
        await reid_retention.start()
    presence_reconciliation = PresenceReconciliationScheduler(
        settings,
        SessionLocal,
        dashboard_hub,
    )
    await presence_reconciliation.start()
    if settings.enable_camera_runtime:
        pipeline_factory = (
            RealtimePipelineFactory(settings, SessionLocal)
            if settings.enable_ai_pipeline
            else None
        )
        camera_runtime = CameraRuntimeManager(
            settings,
            CameraRuntimeRepository(SessionLocal),
            dashboard_hub,
            pipeline_factory=pipeline_factory.create if pipeline_factory else None,
            live_visibility=services.live_visibility,
        )
        await camera_runtime.start()
    try:
        yield
    finally:
        if presence_reconciliation is not None:
            await presence_reconciliation.stop()
        if backup_scheduler is not None:
            await backup_scheduler.stop()
        if dr_scheduler is not None:
            await dr_scheduler.stop()
        if reid_retention is not None:
            await reid_retention.stop()
        if camera_runtime is not None:
            await camera_runtime.stop()
        await engine.dispose()


def create_app() -> FastAPI:
    """Build the ASGI application and keep infrastructure wiring at the edge."""
    settings = get_settings()
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    application = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    register_exception_handlers(application)
    application.include_router(api_router, prefix="/api/v1")
    return application


app = create_app()
