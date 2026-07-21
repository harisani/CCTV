"""Run with: python examples/camera_service_example.py"""

import logging
import time

from app.config.settings import get_settings
from app.services.camera_service import CameraService

logging.basicConfig(level=logging.INFO)
settings = get_settings()

camera = CameraService(
    camera_id="front-door",
    rtsp_url=settings.rtsp_url,
    target_fps=settings.camera_read_fps,
    width=settings.camera_frame_width,
    height=settings.camera_frame_height,
    reconnect_delay_seconds=settings.camera_reconnect_delay_seconds,
)

if not camera.connect():
    raise SystemExit("RTSP connection failed")

try:
    while True:
        frame = camera.get_frame()
        if frame is not None:
            print(f"Latest frame shape: {frame.shape}")
        time.sleep(1)
except KeyboardInterrupt:
    pass
finally:
    camera.disconnect()
