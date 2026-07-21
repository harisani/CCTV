import asyncio
import unittest
from types import SimpleNamespace
from uuid import uuid4

from app.services.camera_runtime_manager import CameraRuntimeManager


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

    def has_subscribers(self, _camera_id: str) -> bool:
        return True

    async def publish_frame(self, **payload: object) -> None:
        self.frames.append(payload)


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


if __name__ == "__main__":
    unittest.main()
