from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Set up and release process-wide resources for the HTTP application."""
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_compute_runtime(settings)
    await ensure_bootstrap_admin(SessionLocal, settings)
    camera_runtime: CameraRuntimeManager | None = None
    if settings.enable_camera_runtime:
        camera_runtime = CameraRuntimeManager(
            settings,
            CameraRuntimeRepository(SessionLocal),
            dashboard_hub,
        )
        await camera_runtime.start()
    try:
        yield
    finally:
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
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    register_exception_handlers(application)
    application.include_router(api_router, prefix="/api/v1")
    application.mount("/storage", StaticFiles(directory=str(settings.storage_path)), name="storage")
    return application


app = create_app()
