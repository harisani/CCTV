from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.auth import router as auth_router
from app.api.routes.cameras import router as cameras_router
from app.api.routes.events import router as events_router
from app.api.routes.persons import router as persons_router
from app.api.routes.snapshots import router as snapshots_router
from app.api.routes.statistics import router as statistics_router
from app.api.routes.dashboard_ws import dashboard_websocket
from app.api.routes.users import router as users_router
from app.api.routes.backups import router as backups_router
from app.api.routes.disaster_recovery import router as disaster_recovery_router
from app.api.routes.evidence import router as evidence_router
from app.api.routes.topology import router as topology_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["system"])
api_router.include_router(auth_router, tags=["authentication"])
api_router.include_router(cameras_router, tags=["cameras"])
api_router.include_router(events_router, tags=["events"])
api_router.include_router(persons_router, tags=["persons"])
api_router.include_router(snapshots_router, tags=["snapshots"])
api_router.include_router(statistics_router, tags=["statistics"])
api_router.include_router(users_router, tags=["users"])
api_router.include_router(backups_router, tags=["backups"])
api_router.include_router(disaster_recovery_router, tags=["disaster-recovery"])
api_router.include_router(evidence_router, tags=["evidence"])
api_router.include_router(topology_router, tags=["topology"])
api_router.websocket("/ws/dashboard")(dashboard_websocket)
