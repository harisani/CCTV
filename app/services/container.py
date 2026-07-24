"""Composition root for lazy, long-lived application services."""

from __future__ import annotations

from functools import cached_property
from threading import Lock
from typing import Any

from app.detector import DetectorService
from app.reid import PersonReIdentificationService
from app.services.camera_service import CameraService
from app.services.crossing_service import CrossingService
from app.services.health_service import HealthService
from app.services.login_rate_limiter import LoginRateLimiter
from app.services.live_visibility_service import LiveVisibilityService, live_visibility_service
from app.storage import SnapshotService
from app.tracker import TrackingService


class ServiceContainer:
    """Construct services at the system boundary, not inside domain logic."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._login_limiter: LoginRateLimiter | None = None
        self._login_limiter_lock = Lock()

    @cached_property
    def detector(self) -> DetectorService:
        return DetectorService(self.settings)

    @cached_property
    def tracker(self) -> TrackingService:
        return TrackingService(self.settings)

    @cached_property
    def crossing(self) -> CrossingService:
        return CrossingService(settings=self.settings)

    @cached_property
    def reidentification(self) -> PersonReIdentificationService:
        return PersonReIdentificationService(self.settings)

    @cached_property
    def snapshots(self) -> SnapshotService:
        return SnapshotService(self.settings)

    @cached_property
    def live_visibility(self) -> LiveVisibilityService:
        return live_visibility_service

    @cached_property
    def health(self) -> HealthService:
        return HealthService()

    @property
    def login_limiter(self) -> LoginRateLimiter:
        if self._login_limiter is None:
            with self._login_limiter_lock:
                if self._login_limiter is None:
                    self._login_limiter = LoginRateLimiter(
                        self.settings.login_rate_limit_attempts,
                        self.settings.login_rate_limit_window_seconds,
                        self.settings.login_rate_limit_max_entries,
                    )
        return self._login_limiter

    def camera(self, camera_id: str, rtsp_url: str) -> CameraService:
        """Create per-camera state; camera readers must not be shared."""
        return CameraService(
            camera_id,
            rtsp_url,
            target_fps=self.settings.camera_read_fps,
            width=self.settings.camera_frame_width,
            height=self.settings.camera_frame_height,
            reconnect_delay_seconds=self.settings.camera_reconnect_delay_seconds,
            open_timeout_milliseconds=self.settings.camera_open_timeout_milliseconds,
            read_timeout_milliseconds=self.settings.camera_read_timeout_milliseconds,
        )


_container: ServiceContainer | None = None
_container_lock = Lock()


def get_service_container() -> ServiceContainer:
    """Return the singleton container without eagerly loading AI weights."""
    global _container
    if _container is None:
        with _container_lock:
            if _container is None:
                from app.config.settings import get_settings

                _container = ServiceContainer(get_settings())
    return _container
