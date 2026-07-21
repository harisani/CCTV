import time
import unittest

from app.services.camera_service import CameraService


class FakeCapture:
    def __init__(self, _: str) -> None:
        self.opened = True
        self.released = False
        self.frame_number = 0
        self.properties: dict[int, float] = {}

    def isOpened(self) -> bool:
        return self.opened

    def read(self) -> tuple[bool, list[int] | None]:
        if not self.opened:
            return False, None
        self.frame_number += 1
        return True, [self.frame_number]

    def release(self) -> None:
        self.released = True
        self.opened = False

    def set(self, prop_id: int, value: float) -> bool:
        self.properties[prop_id] = value
        return True


class BrokenCapture(FakeCapture):
    def read(self) -> tuple[bool, None]:
        self.opened = False
        return False, None


class CameraServiceTest(unittest.TestCase):
    def test_reads_latest_frame_and_disconnects(self) -> None:
        service = CameraService(
            "test-camera",
            "rtsp://example.invalid/live",
            target_fps=60,
            reconnect_delay_seconds=0.01,
            capture_factory=FakeCapture,
        )
        self.assertTrue(service.connect())
        time.sleep(0.05)
        self.assertIsNotNone(service.get_frame())
        self.assertTrue(service.is_connected())
        service.disconnect()
        self.assertFalse(service.is_connected())

    def test_reconnects_after_a_frame_read_failure(self) -> None:
        captures: list[FakeCapture] = []

        def factory(url: str) -> FakeCapture:
            capture = BrokenCapture(url) if not captures else FakeCapture(url)
            captures.append(capture)
            return capture

        service = CameraService(
            "reconnecting-camera",
            "rtsp://example.invalid/live",
            target_fps=60,
            reconnect_delay_seconds=0.01,
            capture_factory=factory,
        )
        self.assertTrue(service.connect())
        time.sleep(0.08)
        self.assertGreaterEqual(len(captures), 2)
        self.assertIsNotNone(service.get_frame())
        service.disconnect()


if __name__ == "__main__":
    unittest.main()
