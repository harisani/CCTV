"""OSNet-based person re-identification and identity persistence."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


EmbeddingExtractor = Callable[[Any], Sequence[float]]
PersonFactory = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class ReIdentificationResult:
    """Identity selected for a crop and the embedding used to select it."""

    person_id: UUID
    matched_existing: bool
    similarity: float | None
    embedding: tuple[float, ...]


class PersonReIdentificationService:
    """Extract OSNet embeddings and match them to persisted person identities."""

    def __init__(
        self,
        settings: Any | None = None,
        *,
        embedding_extractor: EmbeddingExtractor | None = None,
        person_factory: PersonFactory | None = None,
        torch_module: Any | None = None,
    ) -> None:
        self._settings = settings or self._load_settings()
        self._embedding_extractor = embedding_extractor
        self._person_factory = person_factory
        self._torch_module = torch_module
        self._model: Any | None = None
        self._device: str | None = None
        self._logger = logging.getLogger(__name__)

    @property
    def device(self) -> str | None:
        return self._device

    def load_model(self) -> None:
        """Load pretrained OSNet once, targeting CUDA when configured and available."""
        if self._embedding_extractor is not None or self._model is not None:
            return
        torch = self._torch_module or self._import_torch()
        self._device = self._resolve_device(torch)
        try:
            import torchreid
        except ImportError as error:
            raise RuntimeError("Install torchreid to use OSNet person re-identification") from error
        self._logger.info("Loading ReID model '%s' on %s", self._settings.reid_model, self._device)
        self._model = torchreid.models.build_model(
            name=self._settings.reid_model,
            num_classes=1000,
            loss="softmax",
            pretrained=True,
        )
        self._model.to(self._device)
        self._model.eval()
        self._logger.info("ReID model loaded")

    def extract_embedding(self, person_crop: Any) -> tuple[float, ...]:
        """Return one normalized 512-value OSNet feature vector from a person crop."""
        if person_crop is None or getattr(person_crop, "size", 0) == 0:
            raise ValueError("person_crop must contain image data")
        if self._embedding_extractor is not None:
            embedding = tuple(float(value) for value in self._embedding_extractor(person_crop))
        else:
            self.load_model()
            embedding = self._extract_with_osnet(person_crop)
        if len(embedding) != self._settings.reid_embedding_dimension:
            raise ValueError(
                f"Expected {self._settings.reid_embedding_dimension}-dimensional embedding, got {len(embedding)}"
            )
        return _l2_normalize(embedding)

    async def identify(self, person_crop: Any, person_repository: Any) -> ReIdentificationResult:
        """Extract a crop embedding and persist/use the most similar person identity."""
        return await self.identify_embedding(self.extract_embedding(person_crop), person_repository)

    async def identify_embedding(
        self, embedding: Sequence[float], person_repository: Any
    ) -> ReIdentificationResult:
        """Match a precomputed embedding or create and persist a new person."""
        normalized_embedding = _l2_normalize(tuple(float(value) for value in embedding))
        if len(normalized_embedding) != self._settings.reid_embedding_dimension:
            raise ValueError("Embedding dimension does not match REID_EMBEDDING_DIMENSION")

        best_person: Any | None = None
        best_similarity = -1.0
        for person in await person_repository.list_with_embeddings():
            candidate = _embedding_from_record(person.reid_embedding)
            if candidate is None or len(candidate) != len(normalized_embedding):
                continue
            similarity = cosine_similarity(normalized_embedding, candidate)
            if similarity > best_similarity:
                best_person, best_similarity = person, similarity

        now = datetime.now(UTC)
        if best_person is not None and best_similarity >= self._settings.reid_similarity_threshold:
            best_person.last_seen_at = now
            await person_repository.session.commit()
            self._logger.info("ReID matched existing person %s (similarity %.3f)", best_person.id, best_similarity)
            return ReIdentificationResult(best_person.id, True, best_similarity, normalized_embedding)

        person = self._create_person(normalized_embedding, now)
        await person_repository.add(person)
        await person_repository.session.commit()
        self._logger.info("ReID created person %s", person.id)
        return ReIdentificationResult(person.id, False, best_similarity if best_similarity >= 0 else None, normalized_embedding)

    def crop_person(self, frame: Any, bbox: tuple[float, float, float, float]) -> Any:
        """Extract a bounded copy of the YOLO person bounding box from an OpenCV frame."""
        frame_height, frame_width = frame.shape[:2]
        x1, y1, x2, y2 = (round(value) for value in bbox)
        x1, x2 = max(0, x1), min(frame_width, x2)
        y1, y2 = max(0, y1), min(frame_height, y2)
        if x2 <= x1 or y2 <= y1:
            raise ValueError("Bounding box does not overlap the frame")
        return frame[y1:y2, x1:x2].copy()

    def _extract_with_osnet(self, person_crop: Any) -> tuple[float, ...]:
        torch = self._torch_module or self._import_torch()
        cv2 = self._import_cv2()
        resized = cv2.resize(person_crop, (self._settings.reid_image_width, self._settings.reid_image_height))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype("float32") / 255.0
        rgb = (rgb - (0.485, 0.456, 0.406)) / (0.229, 0.224, 0.225)
        tensor = torch.from_numpy(rgb.transpose(2, 0, 1)).unsqueeze(0).to(self._device)
        with torch.no_grad():
            feature = self._model(tensor)[0].detach().cpu().tolist()
        return tuple(float(value) for value in feature)

    def _resolve_device(self, torch: Any) -> str:
        requested = self._settings.reid_device.strip().lower()
        if requested != "auto":
            return requested
        return "cuda:0" if torch.cuda.is_available() else "cpu"

    def _create_person(self, embedding: tuple[float, ...], now: datetime) -> Any:
        factory = self._person_factory or self._default_person_factory
        return factory(
            reid_key=str(uuid4()),
            reid_embedding={"model": self._settings.reid_model, "vector": list(embedding)},
            first_seen_at=now,
            last_seen_at=now,
        )

    @staticmethod
    def _default_person_factory(**fields: Any) -> Any:
        from app.models import Person

        return Person(**fields)

    @staticmethod
    def _load_settings() -> Any:
        from app.config.settings import get_settings

        return get_settings()

    @staticmethod
    def _import_torch() -> Any:
        try:
            import torch
        except ImportError as error:
            raise RuntimeError("Install PyTorch to use OSNet") from error
        return torch

    @staticmethod
    def _import_cv2() -> Any:
        try:
            import cv2
        except ImportError as error:
            raise RuntimeError("Install OpenCV to preprocess OSNet crops") from error
        return cv2


def cosine_similarity(first: Sequence[float], second: Sequence[float]) -> float:
    """Compute cosine similarity without adding a NumPy dependency to matching logic."""
    if len(first) != len(second) or not first:
        raise ValueError("Embeddings must be non-empty and have matching dimensions")
    denominator = math.sqrt(sum(value * value for value in first)) * math.sqrt(
        sum(value * value for value in second)
    )
    return sum(left * right for left, right in zip(first, second, strict=True)) / denominator if denominator else 0.0


def _l2_normalize(embedding: Sequence[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in embedding))
    if norm == 0:
        raise ValueError("Embedding norm cannot be zero")
    return tuple(value / norm for value in embedding)


def _embedding_from_record(record: Any) -> tuple[float, ...] | None:
    if not isinstance(record, dict) or not isinstance(record.get("vector"), list):
        return None
    return _l2_normalize(tuple(float(value) for value in record["vector"]))
