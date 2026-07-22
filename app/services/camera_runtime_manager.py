"""Async coordinator that turns database camera records into live dashboard frames."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Callable
from uuid import UUID

from app.services.camera_service import CameraService

if TYPE_CHECKING:
    from app.services.realtime_pipeline import CameraRealtimePipeline, PipelineFrame

CameraFactory = Callable[[str, str], CameraService]
JpegEncoder = Callable[[Any, int], bytes]
PipelineFactory = Callable[[UUID], "CameraRealtimePipeline"]


@dataclass(slots=True)
class _CameraRuntime:
    camera_id: UUID
    name: str
    rtsp_url: str
    service: CameraService
    location: str | None = None
    pipeline: CameraRealtimePipeline | None = None
    last_ai_frame: int = 0
    last_tracks: list[dict[str, Any]] | None = None
    last_published_frame: int = 0
    last_publish_at: float = 0.0
    last_health_at: float = 0.0
    reported_status: str | None = None
    connect_task: asyncio.Task[bool] | None = None
    initial_connection_started: bool = False
    next_connect_at: float = 0.0


class CameraRuntimeManager:
    """Synchronize enabled cameras and publish selected live views efficiently.

    AI inference is intentionally not performed here. This coordinator establishes
    a reliable live source first; detector/tracker workers can consume the same
    ``CameraService`` frames in the next pipeline stage.
    """

    def __init__(
        self,
        settings: Any,
        catalog: Any,
        dashboard_hub: Any,
        *,
        camera_factory: CameraFactory | None = None,
        jpeg_encoder: JpegEncoder | None = None,
        pipeline_factory: PipelineFactory | None = None,
    ) -> None:
        self._settings = settings
        self._catalog = catalog
        self._dashboard_hub = dashboard_hub
        self._camera_factory = camera_factory or self._create_camera
        self._jpeg_encoder = jpeg_encoder or self._encode_jpeg
        self._pipeline_factory = pipeline_factory
        self._runtimes: dict[UUID, _CameraRuntime] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._logger = logging.getLogger(__name__)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="camera-runtime-manager")
        self._logger.info("Camera runtime manager started")

    async def stop(self) -> None:
        self._stop_event.set()
        task = self._task
        if task is not None:
            await task
        self._task = None
        connect_tasks = [runtime.connect_task for runtime in self._runtimes.values() if runtime.connect_task]
        for connect_task in connect_tasks:
            connect_task.cancel()
        await asyncio.gather(
            *(
                runtime.pipeline.stop()
                for runtime in self._runtimes.values()
                if runtime.pipeline is not None
            ),
            return_exceptions=True,
        )
        await asyncio.gather(
            *(asyncio.to_thread(runtime.service.disconnect) for runtime in self._runtimes.values()),
            return_exceptions=True,
        )
        self._runtimes.clear()
        self._logger.info("Camera runtime manager stopped")

    async def _run(self) -> None:
        next_sync_at = 0.0
        while not self._stop_event.is_set():
            now = time.monotonic()
            if now >= next_sync_at:
                await self._synchronize_cameras()
                next_sync_at = now + self._settings.camera_sync_interval_seconds
            await self._maintain_connections()
            await self._process_frames()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=0.05)
            except TimeoutError:
                pass

    async def _synchronize_cameras(self) -> None:
        try:
            cameras = await self._catalog.list_enabled()
        except Exception:
            self._logger.exception("Unable to synchronize enabled cameras")
            return

        definitions = {camera.id: camera for camera in cameras}
        for camera_id, runtime in tuple(self._runtimes.items()):
            camera = definitions.get(camera_id)
            if camera is None or camera.rtsp_url != runtime.rtsp_url:
                if runtime.pipeline is not None:
                    await runtime.pipeline.stop()
                await asyncio.to_thread(runtime.service.disconnect)
                self._runtimes.pop(camera_id, None)
                await self._report_health(runtime, "OFFLINE", None, None, force=True)

        for camera_id, camera in definitions.items():
            if camera_id in self._runtimes:
                continue
            service = self._camera_factory(str(camera_id), camera.rtsp_url)
            pipeline = None
            if self._pipeline_factory is not None:
                try:
                    pipeline = self._pipeline_factory(camera_id)
                    await pipeline.start()
                except Exception:
                    pipeline = None
                    self._logger.exception(
                        "Unable to start AI pipeline camera_id=%s", camera_id
                    )
            self._runtimes[camera_id] = _CameraRuntime(
                camera_id,
                camera.name,
                camera.rtsp_url,
                service,
                location=getattr(camera, "location", None),
                pipeline=pipeline,
                last_tracks=[],
            )
            self._logger.info("Camera runtime registered camera_id=%s name=%s", camera_id, camera.name)

    async def _maintain_connections(self) -> None:
        now = time.monotonic()
        for runtime in self._runtimes.values():
            task = runtime.connect_task
            if task is not None and task.done():
                runtime.connect_task = None
                try:
                    connected = task.result()
                except Exception:
                    connected = False
                    self._logger.exception("Camera connection task failed camera_id=%s", runtime.camera_id)
                if not connected:
                    runtime.initial_connection_started = False
                    runtime.next_connect_at = now + self._settings.camera_reconnect_delay_seconds
                    await self._report_health(
                        runtime, "OFFLINE", None, "Unable to open video source", force=True
                    )
            if not runtime.initial_connection_started and now >= runtime.next_connect_at:
                runtime.initial_connection_started = True
                runtime.connect_task = asyncio.create_task(
                    asyncio.to_thread(runtime.service.connect),
                    name=f"connect-camera-{runtime.camera_id}",
                )
                await self._report_health(runtime, "RECONNECTING", None, None, force=True)

    async def _process_frames(self) -> None:
        if not self._runtimes:
            return
        await asyncio.gather(
            *(self._process_camera(runtime) for runtime in tuple(self._runtimes.values())),
            return_exceptions=True,
        )

    async def _process_camera(self, runtime: _CameraRuntime) -> None:
        try:
            frame_number, frame = runtime.service.get_frame_snapshot(copy=True)
            now = time.monotonic()
            if frame is None:
                status = "RECONNECTING" if runtime.service.is_connected() else "OFFLINE"
                await self._report_health(runtime, status, None, None)
                return

            captured_at = datetime.now(UTC)
            await self._report_health(runtime, "ONLINE", captured_at, None)
            pipeline_result: PipelineFrame | None = None
            if (
                runtime.pipeline is not None
                and frame_number != runtime.last_ai_frame
            ):
                try:
                    pipeline_result = await runtime.pipeline.process(
                        frame, captured_at=captured_at
                    )
                    runtime.last_ai_frame = frame_number
                    runtime.last_tracks = pipeline_result.tracks
                    for payload in pipeline_result.events:
                        payload["camera_id"] = str(runtime.camera_id)
                        payload["camera_name"] = runtime.name
                        payload["camera_location"] = runtime.location
                        await self._dashboard_hub.publish_event(payload)
                    if pipeline_result.occupancy is not None:
                        await self._dashboard_hub.publish_occupancy(
                            pipeline_result.occupancy
                        )
                except Exception:
                    self._logger.exception(
                        "AI pipeline failed camera_id=%s", runtime.camera_id
                    )
            publish_interval = 1 / self._settings.dashboard_stream_fps
            if not self._dashboard_hub.has_subscribers(str(runtime.camera_id)):
                return
            if frame_number == runtime.last_published_frame or now - runtime.last_publish_at < publish_interval:
                return

            jpeg_bytes = await asyncio.to_thread(
                self._jpeg_encoder, frame, self._settings.dashboard_jpeg_quality
            )
            height, width = frame.shape[:2]
            await self._dashboard_hub.publish_frame(
                camera_id=str(runtime.camera_id),
                jpeg_bytes=jpeg_bytes,
                width=int(width),
                height=int(height),
                tracks=runtime.last_tracks or [],
            )
            runtime.last_published_frame = frame_number
            runtime.last_publish_at = now
        except Exception:
            self._logger.exception("Failed to process live frame camera_id=%s", runtime.camera_id)

    async def _report_health(
        self,
        runtime: _CameraRuntime,
        status: str,
        last_frame_at: datetime | None,
        last_error: str | None,
        *,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        periodic_update_due = now - runtime.last_health_at >= self._settings.camera_health_update_seconds
        if not force and runtime.reported_status == status and not (status == "ONLINE" and periodic_update_due):
            return
        try:
            await self._catalog.update_health(
                runtime.camera_id,
                status=status,
                last_frame_at=last_frame_at,
                last_error=last_error,
            )
            runtime.reported_status = status
            runtime.last_health_at = now
        except Exception:
            self._logger.exception("Unable to persist camera health camera_id=%s", runtime.camera_id)

    def _create_camera(self, camera_id: str, rtsp_url: str) -> CameraService:
        return CameraService(
            camera_id,
            rtsp_url,
            target_fps=self._settings.camera_read_fps,
            width=self._settings.camera_frame_width,
            height=self._settings.camera_frame_height,
            reconnect_delay_seconds=self._settings.camera_reconnect_delay_seconds,
        )

    @staticmethod
    def _encode_jpeg(frame: Any, quality: int) -> bytes:
        try:
            import cv2
        except ImportError as error:
            raise RuntimeError("Install OpenCV to publish dashboard frames") from error
        success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not success:
            raise RuntimeError("OpenCV failed to encode dashboard JPEG")
        return encoded.tobytes()
