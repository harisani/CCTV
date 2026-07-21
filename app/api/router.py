from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.auth import router as auth_router
from app.api.routes.cameras import router as cameras_router
from app.api.routes.events import router as events_router
from app.api.routes.persons import router as persons_router
from app.api.routes.snapshots import router as snapshots_router
from app.api.routes.statistics import router as statistics_router
from app.api.routes.dashboard_ws import dashboard_websocket

api_router = APIRouter()
api_router.include_router(health_router, tags=["system"])
api_router.include_router(auth_router, tags=["authentication"])
api_router.include_router(cameras_router, tags=["cameras"])
api_router.include_router(events_router, tags=["events"])
api_router.include_router(persons_router, tags=["persons"])
api_router.include_router(snapshots_router, tags=["snapshots"])
api_router.include_router(statistics_router, tags=["statistics"])
api_router.websocket("/ws/dashboard")(dashboard_websocket)
