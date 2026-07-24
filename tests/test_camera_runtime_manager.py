import asyncio
import threading
import time
import unittest
from types import SimpleNamespace
from uuid import uuid4

from app.services.camera_runtime_manager import CameraRuntimeManager
from app.services.realtime_pipeline import PipelineFrame


class FakeFrame:
    shape = (480, 720, 3)

    def copy(self) -> "FakeFrame":
        return FakeFrame()


class FakeCameraService:
    def __init__(self) -> None:
        self.connected = False
        self.frame_number = 0
        self.freeze = False

    def connect(self) -> bool:
        self.connected = True
        return True

    def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def get_frame_snapshot(self, *, copy: bool = True) -> tuple[int, FakeFrame | None]:
        if not self.connected:
            return self.frame_number, None
        if not self.freeze:
            self.frame_number += 1
        return self.frame_number, FakeFrame()


class CoordinatedDisconnectCameraService(FakeCameraService):
    def __init__(
        self,
        all_disconnects_started: threading.Event,
        counter: list[int],
        counter_lock: threading.Lock,
    ) -> None:
        super().__init__()
        self._all_disconnects_started = all_disconnects_started
        self._counter = counter
        self._counter_lock = counter_lock

    def disconnect(self) -> None:
        with self._counter_lock:
            self._counter[0] += 1
            if self._counter[0] == 3:
                self._all_disconnects_started.set()
        self._all_disconnects_started.wait(timeout=1)
        super().disconnect()


class FakeCatalog:
    def __init__(self, camera: object) -> None:
        self.camera = camera
        self.health: list[str] = []

    async def list_enabled(self) -> list[object]:
        return [self.camera]

    async def update_health(self, _camera_id: object, *, status: str, **_fields: object) -> None:
        self.health.append(status)


class MultiCameraCatalog(FakeCatalog):
    def __init__(self, cameras: list[object]) -> None:
        super().__init__(cameras[0])
        self.cameras = cameras

    async def list_enabled(self) -> list[object]:
        return self.cameras


class FakeHub:
    def __init__(self) -> None:
        self.frames: list[dict[str, object]] = []
        self.events: list[dict[str, object]] = []
        self.occupancies: list[int] = []
        self.camera_statuses: list[str] = []

    def has_subscribers(self, _camera_id: str) -> bool:
        return True

    async def publish_frame(self, **payload: object) -> None:
        self.frames.append(payload)

    async def publish_event(self, payload: dict[str, object]) -> None:
        self.events.append(payload)

    async def publish_occupancy(self, occupancy: dict[str, int]) -> None:
        self.occupancies.append(occupancy["total"])

    async def publish_camera_status(self, **payload: object) -> None:
        self.camera_statuses.append(str(payload["status"]))


class FakePipeline:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.crossing_configs: list[object] = []

    def configure_crossing(self, config: object) -> None:
        self.crossing_configs.append(config)

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def process(self, _frame: object, **_fields: object) -> PipelineFrame:
        return PipelineFrame(
            True,
            [{"tracking_id": 4, "bbox": [1, 2, 30, 40], "direction": "down"}],
            [{"id": "event-1", "event_type": "ENTER"}],
            {"confirmed": 1, "uncertain": 0, "total": 1},
        )

    async def mark_camera_uncertain(self, *_args: object) -> dict[str, int]:
        return {"confirmed": 0, "uncertain": 1, "total": 0}


class HangingStopPipeline(FakePipeline):
    def __init__(self) -> None:
        super().__init__()
        self.stop_started = asyncio.Event()

    async def stop(self) -> None:
        self.stop_started.set()
        await asyncio.Event().wait()


class TestSettings:
    camera_sync_interval_seconds = 0.02
    camera_reconnect_delay_seconds = 0.01
    camera_health_update_seconds = 0.02
    camera_stale_timeout_seconds = 0.03
    dashboard_stream_fps = 10.0
    dashboard_jpeg_quality = 70
    camera_read_fps = 10.0
    camera_frame_width = 720
    camera_frame_height = 480
    camera_open_timeout_milliseconds = 1500
    camera_read_timeout_milliseconds = 2500
    camera_shutdown_timeout_seconds = 0.5


class CameraRuntimeManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_uses_all_enabled_database_virtual_lines(self) -> None:
        camera_id = uuid4()
        zone_a = uuid4()
        zone_b = uuid4()
        lines = [
            SimpleNamespace(
                id=uuid4(),
                line_key="line-a",
                line_type=SimpleNamespace(value="vertical"),
                position=0.25,
                points=None,
                enter_direction="right",
                from_zone_id=zone_a,
                to_zone_id=zone_b,
                enabled=True,
            ),
            SimpleNamespace(
                id=uuid4(),
                line_key="disabled",
                line_type=SimpleNamespace(value="horizontal"),
                position=0.75,
                points=None,
                enter_direction="down",
                from_zone_id=None,
                to_zone_id=zone_b,
                enabled=False,
            ),
        ]
        camera = SimpleNamespace(
            id=camera_id,
            name="Transition camera",
            location="Mixing",
            rtsp_url="rtsp://example/transition",
            crossing_config=None,
            virtual_lines=lines,
        )
        pipeline = FakePipeline()
        manager = CameraRuntimeManager(
            TestSettings(),
            FakeCatalog(camera),
            FakeHub(),
            camera_factory=lambda _camera_id, _url: FakeCameraService(),
            jpeg_encoder=lambda _frame, _quality: b"jpeg",
            pipeline_factory=lambda _camera_id: pipeline,
        )

        await manager.start()
        await asyncio.sleep(0.06)
        await manager.stop()

        configured = pipeline.crossing_configs[0]
        self.assertIsInstance(configured, list)
        self.assertEqual(len(configured), 1)
        self.assertEqual(configured[0]["line_id"], "line-a")
        self.assertEqual(configured[0]["from_zone_id"], str(zone_a))
        self.assertEqual(configured[0]["to_zone_id"], str(zone_b))

    async def test_shutdown_deadline_contains_stuck_pipeline_cleanup(self) -> None:
        camera = SimpleNamespace(
            id=uuid4(),
            name="Stuck AI",
            rtsp_url="rtsp://example/stuck",
            crossing_config=None,
        )
        settings = TestSettings()
        settings.camera_shutdown_timeout_seconds = 0.05
        pipeline = HangingStopPipeline()
        manager = CameraRuntimeManager(
            settings,
            FakeCatalog(camera),
            FakeHub(),
            camera_factory=lambda _camera_id, _url: FakeCameraService(),
            jpeg_encoder=lambda _frame, _quality: b"jpeg",
            pipeline_factory=lambda _camera_id: pipeline,
        )
        await manager.start()
        for _ in range(20):
            if pipeline.started:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(pipeline.started)

        started_at = time.monotonic()
        await manager.stop()

        self.assertTrue(pipeline.stop_started.is_set())
        self.assertLess(time.monotonic() - started_at, 0.2)

    async def test_disconnects_multiple_cameras_concurrently_during_shutdown(self) -> None:
        cameras = [
            SimpleNamespace(id=uuid4(), name=f"Camera {index}", rtsp_url=f"rtsp://camera/{index}")
            for index in range(3)
        ]
        catalog = MultiCameraCatalog(cameras)
        all_disconnects_started = threading.Event()
        counter = [0]
        counter_lock = threading.Lock()
        manager = CameraRuntimeManager(
            TestSettings(),
            catalog,
            FakeHub(),
            camera_factory=lambda _camera_id, _url: CoordinatedDisconnectCameraService(
                all_disconnects_started, counter, counter_lock
            ),
            jpeg_encoder=lambda _frame, _quality: b"jpeg",
        )
        await manager.start()
        await asyncio.sleep(0.04)

        started_at = time.monotonic()
        await manager.stop()

        self.assertTrue(all_disconnects_started.is_set())
        self.assertLess(time.monotonic() - started_at, 0.5)

    async def test_default_camera_has_bounded_capture_timeouts(self) -> None:
        camera = SimpleNamespace(id=uuid4(), name="Demo", rtsp_url="rtsp://example/demo")
        manager = CameraRuntimeManager(TestSettings(), FakeCatalog(camera), FakeHub())

        service = manager._create_camera(str(camera.id), camera.rtsp_url)

        self.assertEqual(service.open_timeout_milliseconds, 1500)
        self.assertEqual(service.read_timeout_milliseconds, 2500)

    async def test_connects_publishes_and_reports_online(self) -> None:
        camera = SimpleNamespace(id=uuid4(), name="Demo", rtsp_url="rtsp://example/demo")
        catalog = FakeCatalog(camera)
        hub = FakeHub()
        service = FakeCameraService()
        manager = CameraRuntimeManager(
            TestSettings(),
            catalog,
            hub,
            camera_factory=lambda _camera_id, _url: service,
            jpeg_encoder=lambda _frame, _quality: b"jpeg",
        )

        await manager.start()
        await asyncio.sleep(0.16)
        await manager.stop()

        self.assertIn("RECONNECTING", catalog.health)
        self.assertIn("ONLINE", catalog.health)
        self.assertGreaterEqual(len(hub.frames), 1)
        self.assertFalse(service.connected)

    async def test_pipeline_events_tracks_and_occupancy_reach_dashboard(self) -> None:
        camera = SimpleNamespace(
            id=uuid4(),
            name="AI Demo",
            location="Lobby",
            rtsp_url="rtsp://example/ai",
            crossing_config={
                "enabled": True,
                "line_id": "door",
                "line_type": "horizontal",
                "position": 0.4,
                "enter_direction": "down",
                "polygon_points": [],
            },
        )
        catalog = FakeCatalog(camera)
        hub = FakeHub()
        service = FakeCameraService()
        pipeline = FakePipeline()
        manager = CameraRuntimeManager(
            TestSettings(),
            catalog,
            hub,
            camera_factory=lambda _camera_id, _url: service,
            jpeg_encoder=lambda _frame, _quality: b"jpeg",
            pipeline_factory=lambda _camera_id: pipeline,
        )

        await manager.start()
        await asyncio.sleep(0.12)
        await manager.stop()

        self.assertTrue(pipeline.started)
        self.assertEqual(pipeline.crossing_configs[0]["position"], 0.4)
        self.assertTrue(pipeline.stopped)
        self.assertGreaterEqual(len(hub.events), 1)
        self.assertEqual(hub.events[0]["camera_name"], "AI Demo")
        self.assertEqual(hub.events[0]["camera_location"], "Lobby")
        self.assertIn(1, hub.occupancies)
        self.assertEqual(hub.frames[-1]["tracks"][0]["tracking_id"], 4)

    async def test_refreshes_crossing_config_without_restarting_camera(self) -> None:
        camera = SimpleNamespace(
            id=uuid4(),
            name="Door",
            location="Lobby",
            rtsp_url="rtsp://example/door",
            crossing_config=None,
        )
        catalog = FakeCatalog(camera)
        pipeline = FakePipeline()
        manager = CameraRuntimeManager(
            TestSettings(),
            catalog,
            FakeHub(),
            camera_factory=lambda _camera_id, _url: FakeCameraService(),
            jpeg_encoder=lambda _frame, _quality: b"jpeg",
            pipeline_factory=lambda _camera_id: pipeline,
        )

        await manager.start()
        await asyncio.sleep(0.05)
        camera.crossing_config = {
            "enabled": True,
            "line_id": "new-door",
            "line_type": "vertical",
            "position": 0.65,
            "enter_direction": "right",
            "polygon_points": [],
        }
        await asyncio.sleep(0.06)
        await manager.stop()

        self.assertIn(camera.crossing_config, pipeline.crossing_configs)
        self.assertTrue(pipeline.started)
        self.assertTrue(pipeline.stopped)

    async def test_reports_offline_when_frames_stop_changing(self) -> None:
        camera = SimpleNamespace(
            id=uuid4(),
            name="Frozen camera",
            location="Door",
            rtsp_url="rtsp://example/frozen",
            crossing_config=None,
        )
        catalog = FakeCatalog(camera)
        hub = FakeHub()
        service = FakeCameraService()
        pipeline = FakePipeline()
        manager = CameraRuntimeManager(
            TestSettings(),
            catalog,
            hub,
            camera_factory=lambda _camera_id, _url: service,
            jpeg_encoder=lambda _frame, _quality: b"jpeg",
            pipeline_factory=lambda _camera_id: pipeline,
        )

        await manager.start()
        await asyncio.sleep(0.06)
        service.freeze = True
        await asyncio.sleep(0.08)
        await manager.stop()

        self.assertIn("ONLINE", catalog.health)
        self.assertIn("OFFLINE", catalog.health)
        self.assertIn("OFFLINE", hub.camera_statuses)
        self.assertIn(0, hub.occupancies)


if __name__ == "__main__":
    unittest.main()
