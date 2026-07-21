"""Bounded camera connectivity probe used by Camera Management."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CameraProbeResult:
    connected: bool
    latency_ms: int
    width: int | None
    height: int | None
    detail: str


class CameraConnectionTester:
    def __init__(self, *, timeout_seconds: float = 8.0, cv2_module: Any | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self._cv2 = cv2_module

    async def test(self, url: str) -> CameraProbeResult:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._probe, url), timeout=self.timeout_seconds + 1
            )
        except TimeoutError:
            return CameraProbeResult(False, round(self.timeout_seconds * 1000), None, None, "Connection timed out")

    def _probe(self, url: str) -> CameraProbeResult:
        cv2 = self._cv2 or self._import_cv2()
        started = time.monotonic()
        timeout_ms = round(self.timeout_seconds * 1000)
        capture = None
        try:
            params = [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                timeout_ms,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                timeout_ms,
                cv2.CAP_PROP_BUFFERSIZE,
                1,
            ]
            try:
                capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)
            except (TypeError, cv2.error):
                capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not capture.isOpened():
                return self._result(started, False, None, "Video source could not be opened")
            success, frame = capture.read()
            if not success or frame is None:
                return self._result(started, False, None, "Connected, but no video frame was received")
            height, width = frame.shape[:2]
            return self._result(started, True, (int(width), int(height)), "Connection and frame read succeeded")
        except Exception:
            return self._result(started, False, None, "Video connection test failed")
        finally:
            if capture is not None:
                capture.release()

    @staticmethod
    def _result(started: float, connected: bool, size: tuple[int, int] | None, detail: str) -> CameraProbeResult:
        return CameraProbeResult(
            connected,
            round((time.monotonic() - started) * 1000),
            size[0] if size else None,
            size[1] if size else None,
            detail,
        )

    @staticmethod
    def _import_cv2() -> Any:
        import cv2

        return cv2
