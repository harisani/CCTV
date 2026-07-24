import time
import unittest

from app.services.camera_service import CameraService, OpenCvCaptureFactory


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


class FakeCv2:
    CAP_FFMPEG = 1900
    CAP_PROP_OPEN_TIMEOUT_MSEC = 53
    CAP_PROP_READ_TIMEOUT_MSEC = 54

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, list[int]]] = []

    def VideoCapture(self, url: str, backend: int, params: list[int]) -> FakeCapture:
        self.calls.append((url, backend, params))
        return FakeCapture(url)


class CameraServiceTest(unittest.TestCase):
    def test_opencv_factory_bounds_open_and_read_operations(self) -> None:
        cv2 = FakeCv2()
        factory = OpenCvCaptureFactory(
            open_timeout_milliseconds=1_500,
            read_timeout_milliseconds=2_500,
            cv2_module=cv2,
        )

        capture = factory("rtsp://example.invalid/live")

        self.assertTrue(capture.isOpened())
        self.assertEqual(
            cv2.calls,
            [
                (
                    "rtsp://example.invalid/live",
                    cv2.CAP_FFMPEG,
                    [
                        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                        1_500,
                        cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                        2_500,
                    ],
                )
            ],
        )

    def test_rejects_non_positive_capture_timeouts(self) -> None:
        with self.assertRaisesRegex(ValueError, "open_timeout_milliseconds"):
            CameraService(
                "test-camera",
                "rtsp://example.invalid/live",
                open_timeout_milliseconds=0,
            )
        with self.assertRaisesRegex(ValueError, "read_timeout_milliseconds"):
            CameraService(
                "test-camera",
                "rtsp://example.invalid/live",
                read_timeout_milliseconds=0,
            )

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
        frame_number, frame = service.get_frame_snapshot()
        self.assertGreater(frame_number, 0)
        self.assertIsNotNone(frame)
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

    def test_drains_source_faster_than_published_frame_rate(self) -> None:
        captures: list[FakeCapture] = []

        def factory(url: str) -> FakeCapture:
            capture = FakeCapture(url)
            captures.append(capture)
            return capture

        service = CameraService(
            "low-latency-camera",
            "rtsp://example.invalid/live",
            target_fps=5,
            capture_factory=factory,
        )
        self.assertTrue(service.connect())
        time.sleep(0.03)
        published_frames, latest = service.get_frame_snapshot()
        service.disconnect()

        self.assertEqual(published_frames, 1)
        self.assertIsNotNone(latest)
        self.assertGreater(captures[0].frame_number, published_frames)


if __name__ == "__main__":
    unittest.main()
