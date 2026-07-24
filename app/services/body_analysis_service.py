"""Phase 7 use cases for body evidence, OSNet correlation, and PPE facts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.ai import BodyAnalysisEngine
from app.models import (
    BodyCandidate,
    BodyEmbedding,
    CaptureEvent,
    EvidenceAsset,
    EvidenceAssetType,
    IdentityDecision,
    IdentityMatch,
    PPEAnalysis,
    PPEAnalysisStatus,
)
from app.repository import BodyAnalysisRepository
from app.storage.evidence_storage_service import EvidenceStorageService


@dataclass(frozen=True, slots=True)
class BodyProcessingResult:
    match: IdentityMatch
    embedding_id: UUID | None
    candidate_count: int
    needs_review: bool


@dataclass(frozen=True, slots=True)
class PPEProcessingResult:
    analysis: PPEAnalysis
    capture_needs_review: bool


class BodyAnalysisService:
    """Make conservative body decisions and persist every reasoning signal."""

    def __init__(
        self,
        repository: BodyAnalysisRepository,
        settings: Any,
        *,
        engine: BodyAnalysisEngine | None = None,
        storage: EvidenceStorageService | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._engine = engine or BodyAnalysisEngine(settings)
        self._storage = storage or EvidenceStorageService(settings)

    async def process_body(
        self, capture_id: UUID
    ) -> BodyProcessingResult:
        capture = await self._required_capture(capture_id)
        candidates = await self._ensure_candidates(capture)
        model = await self._osnet_model()
        existing = await self._repository.find_identity_match(
            capture_id, model.id
        )
        if existing is not None:
            return BodyProcessingResult(
                existing,
                self._embedding_id(existing),
                len(candidates),
                existing.review_status.value == "PENDING",
            )

        selected = next(
            (candidate for candidate in candidates if candidate.selected),
            None,
        )
        now = datetime.now(UTC)
        if selected is None:
            match = await self._repository.add_body_match(
                capture_id=capture_id,
                candidate=None,
                body_embedding=None,
                matched_embedding=None,
                model=model,
                person_id=None,
                decision=IdentityDecision.UNRESOLVED,
                similarity=None,
                confidence=0.0,
                second_best=None,
                reasoning={"reason": "NO_QUALIFIED_FULL_BODY_CANDIDATE"},
                needs_review=True,
                matched_at=now,
            )
            await self._repository.commit()
            return BodyProcessingResult(match, None, len(candidates), True)

        asset = self._asset_for_candidate(capture, selected)
        image = await asyncio.to_thread(
            self._engine.read_image,
            self._storage.resolve_key(asset.storage_key),
        )
        embedding_values = await asyncio.to_thread(
            self._engine.extract_body_embedding, image
        )
        face_anchor = await self._repository.face_anchor_person(capture_id)
        body_embedding = await self._repository.find_embedding(
            selected.id, model.id
        )
        if body_embedding is None:
            body_embedding = await self._repository.add_embedding(
                candidate=selected,
                model=model,
                embedding=embedding_values,
                person_id=face_anchor,
                source=(
                    "FACE_CONFIRMED_ANCHOR"
                    if face_anchor
                    else "UNLABELED_CAPTURE"
                ),
                expires_at=selected.captured_at
                + timedelta(
                    days=self._settings.reid_embedding_retention_days
                ),
            )
        elif face_anchor is not None and body_embedding.person_id is None:
            body_embedding.person_id = face_anchor
            body_embedding.source = "FACE_CONFIRMED_ANCHOR"

        if face_anchor is not None:
            decision = IdentityDecision.CONFIRMED
            person_id = face_anchor
            similarity = None
            second_best = None
            matched_embedding = None
            needs_review = False
            reason = "FACE_CONFIRMED_SAME_CAPTURE"
            confidence = selected.quality_score
        else:
            ranked = await self._rank_distinct_people(
                embedding_values,
                model_version_id=model.id,
                at=selected.captured_at,
                exclude_id=body_embedding.id,
            )
            (
                decision,
                person_id,
                similarity,
                second_best,
                matched_embedding,
                needs_review,
                reason,
                confidence,
            ) = self._body_decision(ranked, selected.quality_score)

        match = await self._repository.add_body_match(
            capture_id=capture_id,
            candidate=selected,
            body_embedding=body_embedding,
            matched_embedding=matched_embedding,
            model=model,
            person_id=person_id,
            decision=decision,
            similarity=similarity,
            confidence=confidence,
            second_best=second_best,
            reasoning={
                "reason": reason,
                "quality_score": selected.quality_score,
                "similarity_threshold": (
                    self._settings.reid_similarity_threshold
                ),
                "ambiguity_margin": self._settings.reid_match_margin,
                "body_only_match_is_confirmed": False,
            },
            needs_review=needs_review,
            matched_at=now,
        )
        await self._repository.commit()
        return BodyProcessingResult(
            match, body_embedding.id, len(candidates), needs_review
        )

    async def process_ppe(
        self, capture_id: UUID
    ) -> PPEProcessingResult:
        capture = await self._required_capture(capture_id)
        existing = await self._repository.get_ppe_analysis(capture_id)
        if existing is not None:
            return PPEProcessingResult(
                existing,
                await self._repository.capture_requires_review(capture_id),
            )
        candidates = await self._ensure_candidates(capture)
        selected = next(
            (candidate for candidate in candidates if candidate.selected),
            None,
        )
        now = datetime.now(UTC)
        if selected is None:
            analysis = await self._repository.add_ppe_analysis(
                capture_id=capture_id,
                candidate_id=None,
                model_version_id=None,
                status=PPEAnalysisStatus.UNRESOLVED,
                detections=[],
                observed_items={},
                color_observation=None,
                confidence=0.0,
                reasoning={"reason": "NO_QUALIFIED_FULL_BODY_CANDIDATE"},
                needs_review=True,
                analyzed_at=now,
            )
            await self._repository.commit()
            return PPEProcessingResult(analysis, True)

        asset = self._asset_for_candidate(capture, selected)
        image = await asyncio.to_thread(
            self._engine.read_image,
            self._storage.resolve_key(asset.storage_key),
        )
        inference = await asyncio.to_thread(
            self._engine.analyze_ppe, image
        )
        if not inference.model_available:
            status = PPEAnalysisStatus.MODEL_UNAVAILABLE
            model = None
            needs_review = False
        else:
            model = await self._ppe_model()
            status = (
                PPEAnalysisStatus.COMPLETED
                if inference.observed_items
                else PPEAnalysisStatus.PARTIAL
            )
            needs_review = False
        confidences = [
            float(item["confidence"])
            for item in inference.observed_items.values()
            if "confidence" in item
        ]
        confidence = max(confidences, default=0.0)
        analysis = await self._repository.add_ppe_analysis(
            capture_id=capture_id,
            candidate_id=selected.id,
            model_version_id=model.id if model else None,
            status=status,
            detections=inference.detections,
            observed_items=inference.observed_items,
            color_observation=inference.color_observation,
            confidence=confidence,
            reasoning={
                "reason": inference.reason,
                "policy_evaluated": False,
                "absence_inferred_from_no_detection": False,
                "quality_score": selected.quality_score,
            },
            needs_review=needs_review,
            analyzed_at=now,
        )
        await self._repository.commit()
        return PPEProcessingResult(
            analysis,
            await self._repository.capture_requires_review(capture_id),
        )

    async def list_candidates(self, **filters: Any) -> Any:
        return await self._repository.list_body_candidates(**filters)

    async def list_embeddings(self, **filters: Any) -> Any:
        return await self._repository.list_body_embeddings(**filters)

    async def list_ppe(self, **filters: Any) -> Any:
        return await self._repository.list_ppe_analyses(**filters)

    async def _ensure_candidates(
        self, capture: CaptureEvent
    ) -> list[BodyCandidate]:
        existing = await self._repository.list_candidates(capture.id)
        if existing:
            return existing
        body_assets = [
            asset
            for asset in capture.evidence_assets
            if asset.deleted_at is None
            and asset.asset_type == EvidenceAssetType.FULL_BODY
        ][: self._settings.body_max_candidates]
        scored: list[
            tuple[float, dict[str, float], EvidenceAsset, float]
        ] = []
        detector_confidence = float(
            (capture.capture_quality or {}).get(
                "detector_confidence", 0.0
            )
        )
        for asset in body_assets:
            image = await asyncio.to_thread(
                self._engine.read_image,
                self._storage.resolve_key(asset.storage_key),
            )
            quality, metrics = await asyncio.to_thread(
                self._engine.body_quality,
                image,
                detector_confidence=detector_confidence,
            )
            scored.append(
                (quality, metrics, asset, detector_confidence)
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        candidates: list[BodyCandidate] = []
        for sequence, (
            quality,
            metrics,
            asset,
            confidence,
        ) in enumerate(scored):
            selected = (
                sequence == 0
                and quality >= self._settings.reid_min_quality_score
            )
            candidates.append(
                BodyCandidate(
                    capture_event_id=capture.id,
                    body_asset_id=asset.id,
                    sequence_index=sequence,
                    bbox=self._bbox_from_asset(asset),
                    detector_confidence=confidence,
                    quality_score=quality,
                    quality_metrics=metrics,
                    selected=selected,
                    rejection_reason=(
                        None
                        if selected
                        else (
                            "LOW_QUALITY"
                            if quality
                            < self._settings.reid_min_quality_score
                            else "LOWER_RANK"
                        )
                    ),
                    captured_at=capture.captured_at,
                )
            )
        if candidates:
            await self._repository.add_candidates(candidates)
            await self._repository.commit()
        return candidates

    async def _required_capture(self, capture_id: UUID) -> CaptureEvent:
        capture = await self._repository.get_capture(capture_id)
        if capture is None:
            raise LookupError("Capture event not found")
        return capture

    async def _osnet_model(self) -> Any:
        checksum = await asyncio.to_thread(self._engine.osnet_checksum)
        return await self._repository.ensure_model_version(
            model_key=f"osnet:{self._settings.reid_model}",
            name=f"OSNet {self._settings.reid_model}",
            version=self._settings.reid_model_version,
            task="BODY_REIDENTIFICATION",
            runtime="TorchReID/PyTorch",
            checksum=checksum,
            native_dimension=self._settings.reid_embedding_dimension,
            thresholds={
                "similarity": self._settings.reid_similarity_threshold,
                "margin": self._settings.reid_match_margin,
                "minimum_quality": self._settings.reid_min_quality_score,
            },
        )

    async def _ppe_model(self) -> Any:
        checksum = await asyncio.to_thread(self._engine.ppe_checksum)
        return await self._repository.ensure_model_version(
            model_key="site-ppe-yolo",
            name="Site-specific PPE detector",
            version=self._settings.ppe_model_version,
            task="PPE_DETECTION",
            runtime="Ultralytics/PyTorch",
            checksum=checksum,
            native_dimension=None,
            thresholds={
                "confidence": self._settings.ppe_confidence_threshold,
                "image_size": self._settings.ppe_image_size,
            },
        )

    async def _rank_distinct_people(
        self,
        embedding: list[float],
        *,
        model_version_id: UUID,
        at: datetime,
        exclude_id: UUID,
    ) -> list[Any]:
        candidates = await self._repository.body_embedding_candidates(
            embedding,
            model_version_id=model_version_id,
            min_quality=self._settings.reid_min_quality_score,
            at=at,
            limit=self._settings.reid_candidate_limit,
            exclude_id=exclude_id,
        )
        distinct = []
        seen: set[UUID] = set()
        for candidate in candidates:
            if candidate.person.id not in seen:
                distinct.append(candidate)
                seen.add(candidate.person.id)
        return distinct

    def _body_decision(
        self, ranked: list[Any], quality: float
    ) -> tuple[
        IdentityDecision,
        UUID | None,
        float | None,
        float | None,
        BodyEmbedding | None,
        bool,
        str,
        float,
    ]:
        if not ranked:
            return (
                IdentityDecision.UNKNOWN,
                None,
                None,
                None,
                None,
                False,
                "NO_LABELED_BODY_REFERENCE",
                0.0,
            )
        best = ranked[0]
        second = ranked[1].similarity if len(ranked) > 1 else None
        margin = (
            best.similarity - second if second is not None else 2.0
        )
        confidence = round(
            max(0.0, min(1.0, best.similarity * quality)), 6
        )
        if best.similarity >= self._settings.reid_similarity_threshold:
            if margin < self._settings.reid_match_margin:
                return (
                    IdentityDecision.CONFLICT,
                    best.person.id,
                    best.similarity,
                    second,
                    best.embedding,
                    True,
                    "AMBIGUOUS_BODY_MATCH",
                    confidence,
                )
            return (
                IdentityDecision.PROBABLE,
                best.person.id,
                best.similarity,
                second,
                best.embedding,
                True,
                "BODY_ONLY_MATCH_REQUIRES_CORRELATION",
                confidence,
            )
        return (
            IdentityDecision.UNKNOWN,
            None,
            best.similarity,
            second,
            None,
            False,
            "BELOW_BODY_MATCH_THRESHOLD",
            confidence,
        )

    @staticmethod
    def _bbox_from_asset(asset: EvidenceAsset) -> dict[str, float] | None:
        raw = (asset.asset_metadata or {}).get("bbox")
        if isinstance(raw, list) and len(raw) == 4:
            return {
                "x1": float(raw[0]),
                "y1": float(raw[1]),
                "x2": float(raw[2]),
                "y2": float(raw[3]),
            }
        if isinstance(raw, dict):
            return {
                str(key): float(value)
                for key, value in raw.items()
                if isinstance(value, (int, float))
            }
        return None

    @staticmethod
    def _asset_for_candidate(
        capture: CaptureEvent, candidate: BodyCandidate
    ) -> EvidenceAsset:
        asset = next(
            (
                item
                for item in capture.evidence_assets
                if item.id == candidate.body_asset_id
                and item.deleted_at is None
            ),
            None,
        )
        if asset is None:
            raise LookupError("Selected full-body evidence is unavailable")
        return asset

    @staticmethod
    def _embedding_id(match: IdentityMatch) -> UUID | None:
        raw = match.reasoning_metadata.get("body_embedding_id")
        if not raw:
            return None
        try:
            return UUID(str(raw))
        except ValueError:
            return None
