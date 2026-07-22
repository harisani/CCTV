import asyncio
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
        self.frame_number += 1
        return self.frame_number, FakeFrame()


class FakeCatalog:
    def __init__(self, camera: object) -> None:
        self.camera = camera
        self.health: list[str] = []

    async def list_enabled(self) -> list[object]:
        return [self.camera]

    async def update_health(self, _camera_id: object, *, status: str, **_fields: object) -> None:
        self.health.append(status)


class FakeHub:
    def __init__(self) -> None:
        self.frames: list[dict[str, object]] = []
        self.events: list[dict[str, object]] = []
        self.occupancies: list[int] = []

    def has_subscribers(self, _camera_id: str) -> bool:
        return True

    async def publish_frame(self, **payload: object) -> None:
        self.frames.append(payload)

    async def publish_event(self, payload: dict[str, object]) -> None:
        self.events.append(payload)

    async def publish_occupancy(self, count: int) -> None:
        self.occupancies.append(count)


class FakePipeline:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def process(self, _frame: object, **_fields: object) -> PipelineFrame:
        return PipelineFrame(
            True,
            [{"tracking_id": 4, "bbox": [1, 2, 30, 40], "direction": "down"}],
            [{"id": "event-1", "event_type": "ENTER"}],
            1,
        )


class TestSettings:
    camera_sync_interval_seconds = 0.02
    camera_reconnect_delay_seconds = 0.01
    camera_health_update_seconds = 0.02
    dashboard_stream_fps = 10.0
    dashboard_jpeg_quality = 70
    camera_read_fps = 10.0
    camera_frame_width = 720
    camera_frame_height = 480


class CameraRuntimeManagerTest(unittest.IsolatedAsyncioTestCase):
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
        self.assertTrue(pipeline.stopped)
        self.assertGreaterEqual(len(hub.events), 1)
        self.assertEqual(hub.events[0]["camera_name"], "AI Demo")
        self.assertEqual(hub.events[0]["camera_location"], "Lobby")
        self.assertIn(1, hub.occupancies)
        self.assertEqual(hub.frames[-1]["tracks"][0]["tracking_id"], 4)


if __name__ == "__main__":
    unittest.main()
