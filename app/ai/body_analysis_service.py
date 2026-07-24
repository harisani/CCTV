"""Full-body quality scoring, OSNet embeddings, and configurable PPE inference."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.reid import PersonReIdentificationService


class BodyModelUnavailable(RuntimeError):
    """Raised when the pinned OSNet artifact cannot be verified."""


@dataclass(frozen=True, slots=True)
class PPEInference:
    model_available: bool
    detections: list[dict[str, Any]]
    observed_items: dict[str, dict[str, Any]]
    color_observation: dict[str, Any] | None
    reason: str


class BodyAnalysisEngine:
    """Lazy AI adapter shared by Phase 7 asynchronous workers."""

    def __init__(
        self,
        settings: Any,
        *,
        reid_service: PersonReIdentificationService | None = None,
        model_factory: Any | None = None,
        cv2_module: Any | None = None,
        torch_module: Any | None = None,
    ) -> None:
        self._settings = settings
        self._reid = reid_service or PersonReIdentificationService(settings)
        self._model_factory = model_factory
        self._cv2 = cv2_module
        self._torch = torch_module
        self._ppe_model: Any | None = None
        self._ppe_device: str | None = None
        self._lock = threading.RLock()
        self._checksums: dict[str, str] = {}

    def read_image(self, path: Path) -> Any:
        cv2 = self._get_cv2()
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Full-body evidence cannot be decoded")
        return image

    def body_quality(
        self, image: Any, *, detector_confidence: float
    ) -> tuple[float, dict[str, float]]:
        if image is None or getattr(image, "size", 0) == 0:
            return 0.0, {"quality_score": 0.0}
        cv2 = self._get_cv2()
        height, width = image.shape[:2]
        aspect_ratio = width / max(1, height)
        ratio_score = (
            1.0
            if self._settings.body_min_aspect_ratio
            <= aspect_ratio
            <= self._settings.body_max_aspect_ratio
            else 0.25
        )
        minimum_area = (
            self._settings.reid_min_crop_width
            * self._settings.reid_min_crop_height
        )
        size_score = min(1.0, (width * height) / max(1, minimum_area * 6))
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        sharpness_value = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        sharpness_score = min(
            1.0,
            sharpness_value / self._settings.reid_sharpness_reference,
        )
        detector_score = max(0.0, min(1.0, detector_confidence))
        quality = (
            0.30 * detector_score
            + 0.25 * size_score
            + 0.30 * sharpness_score
            + 0.15 * ratio_score
        )
        metrics = {
            "quality_score": round(quality, 6),
            "detector_confidence": round(detector_score, 6),
            "size": round(size_score, 6),
            "sharpness": round(sharpness_score, 6),
            "sharpness_variance": round(sharpness_value, 3),
            "aspect_ratio": round(aspect_ratio, 6),
            "aspect_ratio_score": round(ratio_score, 6),
            "width": float(width),
            "height": float(height),
        }
        return metrics["quality_score"], metrics

    def extract_body_embedding(self, image: Any) -> list[float]:
        return list(self._reid.extract_embedding(image))

    def osnet_checksum(self) -> str:
        return self._checksum(
            self._settings.reid_model_artifact_path,
            expected="",
            model_name="OSNet",
        )

    def ppe_checksum(self) -> str:
        path = self._settings.ppe_model_path.strip()
        if not path:
            raise BodyModelUnavailable("PPE model path is not configured")
        return self._checksum(
            path,
            expected=self._settings.ppe_model_sha256.strip().lower(),
            model_name="PPE",
        )

    def analyze_ppe(self, image: Any) -> PPEInference:
        color = (
            self._dominant_body_color(image)
            if self._settings.ppe_color_analysis_enabled
            else None
        )
        if not self._settings.ppe_analysis_enabled:
            return PPEInference(
                False, [], {}, color, "PPE_ANALYSIS_DISABLED"
            )
        if not self._settings.ppe_model_path.strip():
            return PPEInference(
                False, [], {}, color, "PPE_MODEL_NOT_CONFIGURED"
            )
        try:
            model = self._load_ppe_model()
        except BodyModelUnavailable as error:
            return PPEInference(False, [], {}, color, str(error))
        arguments = {
            "source": image,
            "conf": self._settings.ppe_confidence_threshold,
            "imgsz": self._settings.ppe_image_size,
            "max_det": self._settings.ppe_max_detections,
            "device": self._ppe_device,
            "half": bool(
                self._settings.ppe_half_precision
                and self._ppe_device
                and self._ppe_device.startswith("cuda")
            ),
            "verbose": False,
        }
        with self._lock:
            results = model.predict(**arguments)
        result = results[0]
        boxes = result.boxes
        detections: list[dict[str, Any]] = []
        observed: dict[str, dict[str, Any]] = {}
        if boxes is not None:
            names = result.names
            for bbox, confidence, class_id in zip(
                boxes.xyxy.cpu().tolist(),
                boxes.conf.cpu().tolist(),
                boxes.cls.cpu().tolist(),
                strict=True,
            ):
                raw_name = str(names[int(class_id)])
                canonical = self._settings.ppe_class_mapping.get(
                    raw_name.casefold()
                )
                detection = {
                    "bbox": {
                        "x1": float(bbox[0]),
                        "y1": float(bbox[1]),
                        "x2": float(bbox[2]),
                        "y2": float(bbox[3]),
                    },
                    "confidence": float(confidence),
                    "class_id": int(class_id),
                    "class_name": raw_name,
                    "canonical": canonical,
                }
                detections.append(detection)
                if canonical:
                    item, state = self._canonical_item(canonical)
                    current = observed.get(item)
                    if current is None or float(confidence) > current[
                        "confidence"
                    ]:
                        observed[item] = {
                            "state": state,
                            "confidence": float(confidence),
                            "source_class": raw_name,
                        }
        reason = (
            "PPE_OBSERVATIONS_RECORDED"
            if observed
            else (
                "UNMAPPED_PPE_CLASSES"
                if detections
                else "NO_PPE_OBJECT_DETECTED"
            )
        )
        return PPEInference(True, detections, observed, color, reason)

    def _load_ppe_model(self) -> Any:
        if self._ppe_model is not None:
            return self._ppe_model
        path = Path(self._settings.ppe_model_path).expanduser().resolve()
        if not path.is_file():
            raise BodyModelUnavailable(f"PPE model is missing: {path}")
        self.ppe_checksum()
        factory = self._model_factory or self._default_model_factory
        with self._lock:
            if self._ppe_model is None:
                self._ppe_device = self._resolve_device()
                self._ppe_model = factory(str(path))
        return self._ppe_model

    def _dominant_body_color(self, image: Any) -> dict[str, Any] | None:
        if image is None or getattr(image, "size", 0) == 0:
            return None
        cv2 = self._get_cv2()
        height, width = image.shape[:2]
        torso = image[
            max(0, round(height * 0.15)) : max(1, round(height * 0.68)),
            max(0, round(width * 0.08)) : max(1, round(width * 0.92)),
        ]
        if getattr(torso, "size", 0) == 0:
            return None
        hsv = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV)
        hue, saturation, value = (
            hsv[:, :, 0],
            hsv[:, :, 1],
            hsv[:, :, 2],
        )
        minimum_saturation = self._settings.ppe_color_min_saturation
        masks = {
            "BLACK": value < 45,
            "WHITE": (value > 190) & (saturation < minimum_saturation),
            "GRAY": (
                (value >= 45)
                & (value <= 190)
                & (saturation < minimum_saturation)
            ),
            "RED": (
                (saturation >= minimum_saturation)
                & ((hue < 10) | (hue >= 170))
            ),
            "ORANGE": (
                (saturation >= minimum_saturation)
                & (hue >= 10)
                & (hue < 23)
            ),
            "YELLOW": (
                (saturation >= minimum_saturation)
                & (hue >= 23)
                & (hue < 38)
            ),
            "GREEN": (
                (saturation >= minimum_saturation)
                & (hue >= 38)
                & (hue < 85)
            ),
            "BLUE": (
                (saturation >= minimum_saturation)
                & (hue >= 85)
                & (hue < 135)
            ),
            "PURPLE": (
                (saturation >= minimum_saturation)
                & (hue >= 135)
                & (hue < 170)
            ),
        }
        counts = {
            name: int(mask.sum()) for name, mask in masks.items()
        }
        total = max(1, sum(counts.values()))
        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        dominant, count = ranked[0]
        return {
            "dominant_color": dominant,
            "confidence": round(count / total, 6),
            "distribution": {
                name: round(value_count / total, 6)
                for name, value_count in ranked
            },
            "method": "HSV_TORSO_REGION",
        }

    def _resolve_device(self) -> str:
        requested = self._settings.ppe_device.strip().lower()
        if requested != "auto":
            return requested
        torch = self._torch
        if torch is None:
            try:
                import torch as imported_torch
            except ImportError as error:
                raise BodyModelUnavailable(
                    "PyTorch is required for PPE inference"
                ) from error
            torch = imported_torch
            self._torch = torch
        return "cuda:0" if torch.cuda.is_available() else "cpu"

    def _checksum(
        self,
        configured: Path | str,
        *,
        expected: str,
        model_name: str,
    ) -> str:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise BodyModelUnavailable(
                f"{model_name} model is missing: {path}"
            )
        key = str(path)
        with self._lock:
            checksum = self._checksums.get(key)
            if checksum is None:
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(
                        lambda: handle.read(1024 * 1024), b""
                    ):
                        digest.update(chunk)
                checksum = digest.hexdigest()
                self._checksums[key] = checksum
        if expected and checksum != expected:
            raise BodyModelUnavailable(
                f"{model_name} model checksum does not match configuration"
            )
        return checksum

    @staticmethod
    def _canonical_item(canonical: str) -> tuple[str, str]:
        for suffix, state in (
            ("_PRESENT", "PRESENT"),
            ("_MISSING", "MISSING"),
        ):
            if canonical.endswith(suffix):
                return canonical[: -len(suffix)], state
        return canonical, "OBSERVED"

    @staticmethod
    def _default_model_factory(path: str) -> Any:
        try:
            from ultralytics import YOLO
        except ImportError as error:
            raise BodyModelUnavailable(
                "Ultralytics is required for PPE inference"
            ) from error
        return YOLO(path)

    def _get_cv2(self) -> Any:
        if self._cv2 is not None:
            return self._cv2
        try:
            import cv2
        except ImportError as error:
            raise BodyModelUnavailable(
                "OpenCV is required for body analysis"
            ) from error
        self._cv2 = cv2
        return cv2
