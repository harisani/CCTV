"""OpenCV YuNet/SFace candidate extraction and embedding generation."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class BiometricModelUnavailable(RuntimeError):
    """Raised when a configured biometric model cannot be loaded."""


@dataclass(frozen=True, slots=True)
class FaceCandidateObservation:
    sequence_index: int
    bbox: dict[str, float]
    landmarks: list[dict[str, float]]
    detection_confidence: float
    quality_score: float
    quality_metrics: dict[str, float]
    selected: bool
    rejection_reason: str | None
    face_crop: Any
    periocular_crop: Any | None
    detector_row: Any


class OpenCVBiometricService:
    """Lazy, thread-safe adapter around OpenCV's official YuNet and SFace."""

    EMBEDDING_SIZE = 512
    SFACE_NATIVE_DIMENSION = 128
    DETECTOR_VERSION = "opencv-zoo-2023mar"
    RECOGNIZER_VERSION = "opencv-zoo-2021dec"

    def __init__(
        self,
        settings: Any,
        *,
        cv2_module: Any | None = None,
        numpy_module: Any | None = None,
    ) -> None:
        self._settings = settings
        self._cv2 = cv2_module
        self._np = numpy_module
        self._detector: Any | None = None
        self._recognizer: Any | None = None
        self._checksums: dict[str, str] = {}
        self._lock = threading.RLock()

    def detect_candidates(self, image: Any) -> list[FaceCandidateObservation]:
        """Detect, rank and crop candidates without assigning an identity."""
        if image is None or getattr(image, "size", 0) == 0:
            return []
        cv2, np = self._dependencies()
        detector = self._load_detector()
        height, width = image.shape[:2]
        with self._lock:
            detector.setInputSize((int(width), int(height)))
            _status, rows = detector.detect(image)
        if rows is None:
            return []

        scored: list[tuple[float, Any, dict[str, float]]] = []
        for raw in rows:
            row = np.asarray(raw, dtype=np.float32).reshape(-1)
            if row.size < 15:
                continue
            x, y, box_width, box_height = (float(value) for value in row[:4])
            if min(box_width, box_height) < self._settings.biometric_min_face_size:
                continue
            metrics = self._quality_metrics(
                image,
                x=x,
                y=y,
                width=box_width,
                height=box_height,
                detection_confidence=float(row[14]),
                cv2=cv2,
            )
            scored.append((metrics["quality_score"], row, metrics))

        scored.sort(key=lambda item: item[0], reverse=True)
        observations: list[FaceCandidateObservation] = []
        for index, (_score, row, metrics) in enumerate(
            scored[: self._settings.biometric_max_candidates]
        ):
            x, y, box_width, box_height = (float(value) for value in row[:4])
            face_crop = self._crop(
                image, x, y, box_width, box_height, padding=0.18
            )
            landmarks = [
                {"x": float(row[position]), "y": float(row[position + 1])}
                for position in range(4, 14, 2)
            ]
            periocular = self._periocular_crop(image, landmarks)
            selected = (
                index == 0
                and metrics["quality_score"]
                >= self._settings.biometric_min_quality_score
            )
            observations.append(
                FaceCandidateObservation(
                    sequence_index=index,
                    bbox={
                        "x": x,
                        "y": y,
                        "width": box_width,
                        "height": box_height,
                    },
                    landmarks=landmarks,
                    detection_confidence=float(row[14]),
                    quality_score=metrics["quality_score"],
                    quality_metrics=metrics,
                    selected=selected,
                    rejection_reason=(
                        None
                        if selected
                        else (
                            "LOW_QUALITY"
                            if metrics["quality_score"]
                            < self._settings.biometric_min_quality_score
                            else "LOWER_RANK"
                        )
                    ),
                    face_crop=face_crop,
                    periocular_crop=periocular,
                    detector_row=row,
                )
            )
        return observations

    def extract_embedding(
        self,
        image: Any,
        detector_row: Any,
    ) -> list[float]:
        """Return an L2-normalized SFace feature padded to exactly 512 values."""
        _cv2, np = self._dependencies()
        recognizer = self._load_recognizer()
        with self._lock:
            aligned = recognizer.alignCrop(image, detector_row)
            native = recognizer.feature(aligned)
        vector = np.asarray(native, dtype=np.float32).reshape(-1)
        if vector.size != self.SFACE_NATIVE_DIMENSION:
            raise RuntimeError(
                f"Unexpected SFace embedding dimension: {vector.size}"
            )
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-12:
            raise RuntimeError("SFace produced an empty embedding")
        normalized = vector / norm
        padded = np.zeros(self.EMBEDDING_SIZE, dtype=np.float32)
        padded[: vector.size] = normalized
        return [float(value) for value in padded]

    @staticmethod
    def cosine_similarity(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            raise ValueError("Embeddings must have equal non-zero dimensions")
        dot = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = sum(value * value for value in left) ** 0.5
        right_norm = sum(value * value for value in right) ** 0.5
        if left_norm <= 1e-12 or right_norm <= 1e-12:
            return 0.0
        return max(-1.0, min(1.0, dot / (left_norm * right_norm)))

    def detector_checksum(self) -> str:
        return self._cached_checksum(
            self._settings.biometric_yunet_model_path
        )

    def recognizer_checksum(self) -> str:
        return self._cached_checksum(
            self._settings.biometric_sface_model_path
        )

    def read_image(self, path: Path) -> Any:
        cv2, _np = self._dependencies()
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Evidence image cannot be decoded")
        return image

    def _load_detector(self) -> Any:
        if self._detector is not None:
            return self._detector
        cv2, _np = self._dependencies()
        path = self._model_path(self._settings.biometric_yunet_model_path)
        try:
            with self._lock:
                if self._detector is None:
                    self._detector = cv2.FaceDetectorYN.create(
                        str(path),
                        "",
                        (320, 320),
                        self._settings.biometric_face_detection_threshold,
                        self._settings.biometric_face_nms_threshold,
                        self._settings.biometric_face_top_k,
                    )
        except Exception as error:
            raise BiometricModelUnavailable(
                f"Could not load YuNet model: {path}"
            ) from error
        return self._detector

    def _load_recognizer(self) -> Any:
        if self._recognizer is not None:
            return self._recognizer
        cv2, _np = self._dependencies()
        path = self._model_path(self._settings.biometric_sface_model_path)
        try:
            with self._lock:
                if self._recognizer is None:
                    self._recognizer = cv2.FaceRecognizerSF.create(
                        str(path), ""
                    )
        except Exception as error:
            raise BiometricModelUnavailable(
                f"Could not load SFace model: {path}"
            ) from error
        return self._recognizer

    def _quality_metrics(
        self,
        image: Any,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        detection_confidence: float,
        cv2: Any,
    ) -> dict[str, float]:
        crop = self._crop(image, x, y, width, height)
        if crop is None or getattr(crop, "size", 0) == 0:
            return {
                "quality_score": 0.0,
                "detection": detection_confidence,
                "size": 0.0,
                "sharpness": 0.0,
                "illumination": 0.0,
            }
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        sharpness_value = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        mean_light = float(gray.mean())
        size_score = min(
            1.0,
            min(width, height)
            / max(1.0, self._settings.biometric_min_face_size * 2),
        )
        sharpness_score = min(
            1.0,
            sharpness_value
            / self._settings.biometric_sharpness_reference,
        )
        illumination_score = max(
            0.0, 1.0 - abs(mean_light - 127.5) / 127.5
        )
        quality = (
            0.35 * max(0.0, min(1.0, detection_confidence))
            + 0.25 * size_score
            + 0.25 * sharpness_score
            + 0.15 * illumination_score
        )
        return {
            "quality_score": round(quality, 6),
            "detection": round(detection_confidence, 6),
            "size": round(size_score, 6),
            "sharpness": round(sharpness_score, 6),
            "sharpness_variance": round(sharpness_value, 3),
            "illumination": round(illumination_score, 6),
            "mean_luminance": round(mean_light, 3),
        }

    @staticmethod
    def _crop(
        image: Any,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        padding: float = 0.0,
    ) -> Any:
        image_height, image_width = image.shape[:2]
        pad_x, pad_y = width * padding, height * padding
        left = max(0, int(x - pad_x))
        top = max(0, int(y - pad_y))
        right = min(image_width, int(x + width + pad_x))
        bottom = min(image_height, int(y + height + pad_y))
        return image[top:bottom, left:right].copy()

    @staticmethod
    def _periocular_crop(
        image: Any,
        landmarks: list[dict[str, float]],
    ) -> Any | None:
        if len(landmarks) < 2:
            return None
        left_eye, right_eye = landmarks[0], landmarks[1]
        distance = max(1.0, abs(right_eye["x"] - left_eye["x"]))
        center_x = (left_eye["x"] + right_eye["x"]) / 2
        center_y = (left_eye["y"] + right_eye["y"]) / 2
        return OpenCVBiometricService._crop(
            image,
            center_x - distance * 0.9,
            center_y - distance * 0.55,
            distance * 1.8,
            distance * 1.1,
        )

    def _dependencies(self) -> tuple[Any, Any]:
        if self._cv2 is None:
            try:
                import cv2
            except ImportError as error:
                raise BiometricModelUnavailable(
                    "OpenCV is required for biometric processing"
                ) from error
            self._cv2 = cv2
        if self._np is None:
            try:
                import numpy
            except ImportError as error:
                raise BiometricModelUnavailable(
                    "NumPy is required for biometric processing"
                ) from error
            self._np = numpy
        return self._cv2, self._np

    @staticmethod
    def _model_path(configured: Path | str) -> Path:
        path = Path(configured).expanduser().resolve()
        if not path.is_file():
            raise BiometricModelUnavailable(
                f"Biometric model is missing: {path}"
            )
        return path

    @classmethod
    def _checksum(cls, configured: Path | str) -> str:
        path = cls._model_path(configured)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _cached_checksum(self, configured: Path | str) -> str:
        path = str(self._model_path(configured))
        with self._lock:
            checksum = self._checksums.get(path)
            if checksum is None:
                checksum = self._checksum(path)
                self._checksums[path] = checksum
            return checksum
