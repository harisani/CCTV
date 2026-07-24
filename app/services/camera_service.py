"""Low-latency, reconnecting RTSP camera reader built on OpenCV."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol


class VideoCaptureProtocol(Protocol):
    """Small OpenCV capture interface, making CameraService independently testable."""

    def isOpened(self) -> bool: ...

    def read(self) -> tuple[bool, Any]: ...

    def release(self) -> None: ...

    def set(self, prop_id: int, value: float) -> bool: ...


CaptureFactory = Callable[[str], VideoCaptureProtocol]


class OpenCvCaptureFactory:
    """Create FFmpeg captures whose blocking open/read calls have hard deadlines."""

    def __init__(
        self,
        *,
        open_timeout_milliseconds: int,
        read_timeout_milliseconds: int,
        cv2_module: Any | None = None,
    ) -> None:
        self._open_timeout_milliseconds = open_timeout_milliseconds
        self._read_timeout_milliseconds = read_timeout_milliseconds
        self._cv2 = cv2_module

    def __call__(self, rtsp_url: str) -> VideoCaptureProtocol:
        cv2 = self._cv2 or self._import_cv2()
        return cv2.VideoCapture(
            rtsp_url,
            cv2.CAP_FFMPEG,
            [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                self._open_timeout_milliseconds,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                self._read_timeout_milliseconds,
            ],
        )

    @staticmethod
    def _import_cv2() -> Any:
        import cv2

        return cv2


class CameraService:
    """Read the latest frame from one RTSP camera in a daemon thread.

    The service deliberately retains only the newest successful frame. This avoids
    a growing queue and keeps inference close to real time when it is slower than
    the incoming video stream.
    """

    _CAP_PROP_FRAME_WIDTH = 3
    _CAP_PROP_FRAME_HEIGHT = 4
    _CAP_PROP_FPS = 5
    _CAP_PROP_BUFFERSIZE = 38

    def __init__(
        self,
        camera_id: str,
        rtsp_url: str,
        *,
        target_fps: float = 10.0,
        width: int = 1280,
        height: int = 720,
        reconnect_delay_seconds: float = 3.0,
        open_timeout_milliseconds: int = 5_000,
        read_timeout_milliseconds: int = 5_000,
        capture_factory: CaptureFactory | None = None,
    ) -> None:
        if not camera_id.strip():
            raise ValueError("camera_id must not be empty")
        if not rtsp_url.strip():
            raise ValueError("rtsp_url must not be empty")
        if target_fps <= 0:
            raise ValueError("target_fps must be greater than zero")
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be greater than zero")
        if reconnect_delay_seconds <= 0:
            raise ValueError("reconnect_delay_seconds must be greater than zero")
        if open_timeout_milliseconds <= 0:
            raise ValueError("open_timeout_milliseconds must be greater than zero")
        if read_timeout_milliseconds <= 0:
            raise ValueError("read_timeout_milliseconds must be greater than zero")

        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.target_fps = target_fps
        self.width = width
        self.height = height
        self.reconnect_delay_seconds = reconnect_delay_seconds
        self.open_timeout_milliseconds = open_timeout_milliseconds
        self.read_timeout_milliseconds = read_timeout_milliseconds
        self._capture_factory = capture_factory or OpenCvCaptureFactory(
            open_timeout_milliseconds=open_timeout_milliseconds,
            read_timeout_milliseconds=read_timeout_milliseconds,
        )
        self._logger = logging.getLogger(f"{__name__}.{camera_id}")

        self._capture: VideoCaptureProtocol | None = None
        self._latest_frame: Any | None = None
        self._frame_number = 0
        self._frame_lock = threading.Lock()
        self._capture_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._reader_thread: threading.Thread | None = None

    def connect(self) -> bool:
        """Open the stream and start the frame-reader thread once connected."""
        if self.is_connected():
            return True

        with self._capture_lock:
            if self._capture is not None and self._capture.isOpened():
                return True
            self._release_capture_locked()
            try:
                capture = self._capture_factory(self.rtsp_url)
                capture.set(self._CAP_PROP_BUFFERSIZE, 1)
                capture.set(self._CAP_PROP_FRAME_WIDTH, self.width)
                capture.set(self._CAP_PROP_FRAME_HEIGHT, self.height)
                capture.set(self._CAP_PROP_FPS, self.target_fps)
                if not capture.isOpened():
                    capture.release()
                    self._logger.warning("RTSP connection failed")
                    return False
                self._capture = capture
            except Exception:
                self._logger.exception("Unexpected error while opening RTSP stream")
                return False

        self._stop_event.clear()
        if self._reader_thread is None or not self._reader_thread.is_alive():
            self._reader_thread = threading.Thread(
                target=self._read_loop,
                name=f"camera-reader-{self.camera_id}",
                daemon=True,
            )
            self._reader_thread.start()
        self._logger.info("Camera connected")
        return True

    def disconnect(self) -> None:
        """Stop the reader and release the RTSP connection."""
        self._stop_event.set()
        reader = self._reader_thread
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=5)
        self._reader_thread = None
        with self._capture_lock:
            self._release_capture_locked()
        with self._frame_lock:
            self._latest_frame = None
            self._frame_number = 0
        self._logger.info("Camera disconnected")

    def get_frame(self, *, copy: bool = True) -> Any | None:
        """Return the newest frame, or ``None`` until a frame has been received."""
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy() if copy else self._latest_frame

    def get_frame_snapshot(self, *, copy: bool = True) -> tuple[int, Any | None]:
        """Return an atomic frame sequence and image for duplicate suppression."""
        with self._frame_lock:
            if self._latest_frame is None:
                return self._frame_number, None
            frame = self._latest_frame.copy() if copy else self._latest_frame
            return self._frame_number, frame

    def is_connected(self) -> bool:
        """Return whether OpenCV currently reports an open RTSP capture."""
        with self._capture_lock:
            return self._capture is not None and self._capture.isOpened()

    def reconnect(self) -> bool:
        """Release the active stream, then try a fresh RTSP connection."""
        self._logger.info("Reconnecting camera")
        with self._capture_lock:
            self._release_capture_locked()
        return self.connect()

    def _read_loop(self) -> None:
        """Continuously drain RTSP packets while exposing frames at target FPS.

        Sleeping between ``read`` calls lets FFmpeg's internal RTSP queue grow
        whenever the source FPS is higher than ``target_fps``. Keep consuming
        the source instead and throttle only writes to the latest-frame slot.
        """
        interval = 1 / self.target_fps
        next_publish_at = 0.0
        while not self._stop_event.is_set():
            started_at = time.monotonic()
            with self._capture_lock:
                capture = self._capture
            if capture is None or not capture.isOpened():
                self._wait_before_reconnect()
                continue

            try:
                success, frame = capture.read()
            except Exception:
                self._logger.exception("Frame read failed")
                success, frame = False, None

            if not success or frame is None:
                self._logger.warning("RTSP frame unavailable; reconnecting")
                self._wait_before_reconnect()
                continue

            now = time.monotonic()
            if now >= next_publish_at:
                with self._frame_lock:
                    self._latest_frame = frame
                    self._frame_number += 1
                next_publish_at = now + interval

            # A real stream normally blocks until another packet arrives. Test
            # doubles and buffered streams can return immediately, so yield just
            # enough to avoid a CPU spin without allowing stale frames to pile up.
            if now - started_at < 0.001:
                self._stop_event.wait(0.001)

    def _wait_before_reconnect(self) -> None:
        with self._capture_lock:
            self._release_capture_locked()
        with self._frame_lock:
            self._latest_frame = None
        if self._stop_event.wait(self.reconnect_delay_seconds):
            return
        self.connect()

    def _release_capture_locked(self) -> None:
        if self._capture is not None:
            try:
                self._capture.release()
            except Exception:
                self._logger.exception("Failed to release RTSP capture")
            finally:
                self._capture = None
