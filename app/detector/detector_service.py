"""Ultralytics YOLOv11 detection service."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Detection:
    """One object returned by YOLO in pixel coordinates."""

    bbox: tuple[float, float, float, float]
    confidence: float
    class_id: int
    class_name: str
    centroid: tuple[float, float]


ModelFactory = Callable[[str], Any]


class DetectorService:
    """Load YOLOv11 once and run single or batch object detection.

    GPU selection follows ``YOLO_DEVICE``. With its default ``auto`` value, CUDA
    is selected only when PyTorch reports it is available; otherwise CPU is used.
    """

    def __init__(
        self,
        settings: Any | None = None,
        *,
        model_factory: ModelFactory | None = None,
        torch_module: Any | None = None,
    ) -> None:
        self._settings = settings or self._load_settings()
        self._model_factory = model_factory
        self._torch_module = torch_module
        self._model: Any | None = None
        self._device: str | None = None
        self._logger = logging.getLogger(__name__)

    @property
    def device(self) -> str | None:
        """Device selected after model loading."""
        return self._device

    def load_model(self) -> None:
        """Load the configured YOLOv11 weights once."""
        if self._model is not None:
            return
        self._device = self._resolve_device()
        factory = self._model_factory or self._ultralytics_model_factory
        self._logger.info("Loading YOLO model '%s' on %s", self._settings.yolo_model, self._device)
        self._model = factory(self._settings.yolo_model)
        self._logger.info("YOLO model loaded")

    def predict(self, frame: Any) -> list[Detection]:
        """Detect objects in one OpenCV BGR frame."""
        self.load_model()
        result = self._model.predict(**self._prediction_arguments(frame))[0]
        return self._to_detections(result)

    def predict_batch(self, frames: Sequence[Any]) -> list[list[Detection]]:
        """Detect objects in multiple frames in one YOLO inference call."""
        if not frames:
            return []
        self.load_model()
        results = self._model.predict(**self._prediction_arguments(list(frames)))
        return [self._to_detections(result) for result in results]

    def draw_bbox(
        self,
        frame: Any,
        detection: Detection,
        *,
        color: tuple[int, int, int] = (0, 255, 0),
        thickness: int = 2,
    ) -> Any:
        """Draw a detection rectangle on the supplied BGR frame and return it."""
        cv2 = self._import_cv2()
        x1, y1, x2, y2 = (round(value) for value in detection.bbox)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        return frame

    def draw_label(
        self,
        frame: Any,
        detection: Detection,
        *,
        color: tuple[int, int, int] = (0, 255, 0),
        scale: float = 0.5,
        thickness: int = 1,
    ) -> Any:
        """Draw class name and confidence above a detection on a BGR frame."""
        cv2 = self._import_cv2()
        x1, y1, _, _ = (round(value) for value in detection.bbox)
        label = f"{detection.class_name} {detection.confidence:.2f}"
        baseline_y = max(20, y1 - 8)
        cv2.putText(
            frame,
            label,
            (x1, baseline_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            color,
            thickness,
            cv2.LINE_AA,
        )
        return frame

    def _prediction_arguments(self, source: Any) -> dict[str, Any]:
        return {
            "source": source,
            "conf": self._settings.confidence_threshold,
            "imgsz": self._settings.yolo_image_size,
            "max_det": self._settings.yolo_max_detections,
            "device": self._device,
            "half": bool(getattr(self._settings, "yolo_half_precision", True) and self._device and self._device.startswith("cuda")),
            "verbose": False,
        }

    def _resolve_device(self) -> str:
        requested_device = self._settings.yolo_device.strip().lower()
        if requested_device != "auto":
            return requested_device
        torch = self._torch_module or self._import_torch()
        return "cuda:0" if torch.cuda.is_available() else "cpu"

    @staticmethod
    def _to_detections(result: Any) -> list[Detection]:
        boxes = result.boxes
        if boxes is None:
            return []
        class_names = result.names
        coordinates = boxes.xyxy.cpu().tolist()
        confidences = boxes.conf.cpu().tolist()
        class_ids = boxes.cls.cpu().tolist()
        detections: list[Detection] = []
        for bbox, confidence, class_id in zip(coordinates, confidences, class_ids, strict=True):
            x1, y1, x2, y2 = (float(value) for value in bbox)
            numeric_class_id = int(class_id)
            class_name = str(class_names[numeric_class_id])
            detections.append(
                Detection(
                    bbox=(x1, y1, x2, y2),
                    confidence=float(confidence),
                    class_id=numeric_class_id,
                    class_name=class_name,
                    centroid=((x1 + x2) / 2, (y1 + y2) / 2),
                )
            )
        return detections

    @staticmethod
    def _ultralytics_model_factory(model_path: str) -> Any:
        try:
            from ultralytics import YOLO
        except ImportError as error:
            raise RuntimeError("Install dependencies from requirements.txt to use YOLO detection") from error
        return YOLO(model_path)

    @staticmethod
    def _load_settings() -> Any:
        """Import application configuration only for a real, non-test instance."""
        from app.config.settings import get_settings

        return get_settings()

    @staticmethod
    def _import_torch() -> Any:
        try:
            import torch
        except ImportError as error:
            raise RuntimeError("Install PyTorch to select the YOLO device") from error
        return torch

    @staticmethod
    def _import_cv2() -> Any:
        try:
            import cv2
        except ImportError as error:
            raise RuntimeError("Install OpenCV to draw detection annotations") from error
        return cv2
