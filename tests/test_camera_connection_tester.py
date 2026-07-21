import unittest

from app.services.camera_connection_tester import CameraConnectionTester


class Frame:
    shape = (480, 720, 3)


class Capture:
    def __init__(self, opened=True, frame=True):
        self.opened = opened
        self.frame = frame
        self.released = False

    def isOpened(self):
        return self.opened

    def read(self):
        return self.frame, Frame() if self.frame else None

    def release(self):
        self.released = True

    def set(self, *_args):
        return True


class FakeCv2:
    CAP_FFMPEG = 1
    CAP_PROP_OPEN_TIMEOUT_MSEC = 2
    CAP_PROP_READ_TIMEOUT_MSEC = 3
    CAP_PROP_BUFFERSIZE = 4
    error = RuntimeError

    def __init__(self, capture):
        self.capture = capture

    def VideoCapture(self, *_args):
        return self.capture


class CameraConnectionTesterTest(unittest.IsolatedAsyncioTestCase):
    async def test_reports_resolution_when_frame_is_available(self) -> None:
        capture = Capture()
        result = await CameraConnectionTester(cv2_module=FakeCv2(capture)).test("rtsp://camera/live")

        self.assertTrue(result.connected)
        self.assertEqual((result.width, result.height), (720, 480))
        self.assertTrue(capture.released)

    async def test_reports_failure_when_source_cannot_open(self) -> None:
        result = await CameraConnectionTester(cv2_module=FakeCv2(Capture(opened=False))).test("rtsp://camera/live")

        self.assertFalse(result.connected)


if __name__ == "__main__":
    unittest.main()
