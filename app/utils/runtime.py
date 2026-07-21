"""Process-wide CPU/GPU runtime tuning applied once during application startup."""

from __future__ import annotations

import logging
from typing import Any


def configure_compute_runtime(settings: Any) -> None:
    """Limit CPU thread contention while leaving GPU selection to AI services.

    A zero value retains the library default. CUDA is still selected per service by
    ``YOLO_DEVICE`` and ``REID_DEVICE``; both support the ``auto`` value.
    """
    logger = logging.getLogger(__name__)
    if settings.opencv_num_threads:
        try:
            import cv2

            cv2.setNumThreads(settings.opencv_num_threads)
            logger.info("OpenCV threads configured: %s", settings.opencv_num_threads)
        except ImportError:
            logger.warning("OpenCV unavailable; no OpenCV thread limit applied")
    if settings.torch_num_threads:
        try:
            import torch

            torch.set_num_threads(settings.torch_num_threads)
            logger.info("PyTorch CPU threads configured: %s", settings.torch_num_threads)
        except ImportError:
            logger.warning("PyTorch unavailable; no PyTorch thread limit applied")
