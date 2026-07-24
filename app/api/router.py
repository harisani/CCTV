from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.auth import router as auth_router
from app.api.routes.cameras import router as cameras_router
from app.api.routes.capture_events import router as capture_events_router
from app.api.routes.events import router as events_router
from app.api.routes.persons import router as persons_router
from app.api.routes.processing_jobs import router as processing_jobs_router
from app.api.routes.snapshots import router as snapshots_router
from app.api.routes.statistics import router as statistics_router
from app.api.routes.dashboard_ws import dashboard_websocket
from app.api.routes.users import router as users_router
from app.api.routes.backups import router as backups_router
from app.api.routes.disaster_recovery import router as disaster_recovery_router
from app.api.routes.evidence import router as evidence_router
from app.api.routes.topology import router as topology_router
from app.api.routes.zone_transitions import router as zone_transitions_router
from app.api.routes.biometrics import router as biometrics_router
from app.api.routes.body_analysis import router as body_analysis_router
from app.api.routes.journeys import router as journeys_router
from app.api.routes.occupancy import router as occupancy_router
from app.api.routes.policies import router as policies_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["system"])
api_router.include_router(auth_router, tags=["authentication"])
api_router.include_router(cameras_router, tags=["cameras"])
api_router.include_router(capture_events_router, tags=["capture-events"])
api_router.include_router(events_router, tags=["events"])
api_router.include_router(persons_router, tags=["persons"])
api_router.include_router(processing_jobs_router, tags=["processing-jobs"])
api_router.include_router(snapshots_router, tags=["snapshots"])
api_router.include_router(statistics_router, tags=["statistics"])
api_router.include_router(users_router, tags=["users"])
api_router.include_router(backups_router, tags=["backups"])
api_router.include_router(disaster_recovery_router, tags=["disaster-recovery"])
api_router.include_router(evidence_router, tags=["evidence"])
api_router.include_router(topology_router, tags=["topology"])
api_router.include_router(zone_transitions_router, tags=["zone-transitions"])
api_router.include_router(biometrics_router, tags=["biometrics"])
api_router.include_router(body_analysis_router, tags=["body-analysis"])
api_router.include_router(journeys_router, tags=["global-journeys"])
api_router.include_router(occupancy_router, tags=["occupancy"])
api_router.include_router(policies_router, tags=["policies", "security-alerts"])
api_router.websocket("/ws/dashboard")(dashboard_websocket)
