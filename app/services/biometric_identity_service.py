"""Use cases for candidate selection, enrollment, and fail-safe matching."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.ai import OpenCVBiometricService
from app.models import (
    BiometricModality,
    BiometricTemplate,
    CaptureEvent,
    EvidenceAsset,
    EvidenceAssetType,
    EvidenceIntegrityStatus,
    FaceCandidate,
    IdentityDecision,
    IdentityMatch,
    IdentityReviewStatus,
)
from app.repository import BiometricRepository
from app.storage.evidence_storage_service import (
    EvidenceFile,
    EvidenceStorageService,
)


@dataclass(frozen=True, slots=True)
class CandidateSelectionResult:
    capture_id: UUID
    candidate_count: int
    selected_candidate_id: UUID | None


@dataclass(frozen=True, slots=True)
class IdentityProcessingResult:
    match: IdentityMatch
    needs_review: bool


class BiometricIdentityService:
    """Keep biometric decisions explainable, versioned, and conservative."""

    def __init__(
        self,
        repository: BiometricRepository,
        settings: Any,
        *,
        engine: OpenCVBiometricService | None = None,
        storage: EvidenceStorageService | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._engine = engine or OpenCVBiometricService(settings)
        self._storage = storage or EvidenceStorageService(settings)

    async def select_candidates(
        self, capture_id: UUID
    ) -> CandidateSelectionResult:
        capture = await self._required_capture(capture_id)
        existing = await self._repository.list_capture_candidates(capture_id)
        if existing:
            selected = next(
                (candidate for candidate in existing if candidate.selected),
                None,
            )
            return CandidateSelectionResult(
                capture_id, len(existing), selected.id if selected else None
            )

        detector_model = await self._detector_model()
        source, image = await self._capture_image(capture)
        observations = await asyncio.to_thread(
            self._engine.detect_candidates, image
        )
        retention_until = capture.captured_at + timedelta(
            days=self._settings.evidence_default_retention_days
        )
        persisted: list[FaceCandidate] = []
        for observation in observations:
            face_file = await asyncio.to_thread(
                self._storage.write_image,
                self._derived_key(
                    capture, "face", observation.sequence_index
                ),
                observation.face_crop,
                asset_type=EvidenceAssetType.FACE_CROP,
                sequence_index=observation.sequence_index,
                metadata={"source_asset_id": str(source.id)},
                idempotent=True,
            )
            periocular_file = None
            if (
                observation.periocular_crop is not None
                and getattr(observation.periocular_crop, "size", 0) > 0
            ):
                periocular_file = await asyncio.to_thread(
                    self._storage.write_image,
                    self._derived_key(
                        capture, "periocular", observation.sequence_index
                    ),
                    observation.periocular_crop,
                    asset_type=EvidenceAssetType.PERIOCULAR_CROP,
                    sequence_index=observation.sequence_index,
                    metadata={
                        "source_asset_id": str(source.id),
                        "matching_enabled": False,
                    },
                    idempotent=True,
                )
            assets = [
                self._asset_from_file(
                    face_file, capture=capture, retention_until=retention_until
                )
            ]
            if periocular_file is not None:
                assets.append(
                    self._asset_from_file(
                        periocular_file,
                        capture=capture,
                        retention_until=retention_until,
                    )
                )
            candidate = FaceCandidate(
                capture_event_id=capture.id,
                face_asset_id=face_file.asset_id,
                periocular_asset_id=(
                    periocular_file.asset_id if periocular_file else None
                ),
                detector_model_version_id=detector_model.id,
                sequence_index=observation.sequence_index,
                bbox=observation.bbox,
                landmarks=observation.landmarks,
                detection_confidence=observation.detection_confidence,
                quality_score=observation.quality_score,
                quality_metrics=observation.quality_metrics,
                selected=observation.selected,
                rejection_reason=observation.rejection_reason,
                captured_at=capture.captured_at,
            )
            persisted.append(
                await self._repository.add_candidate(candidate, assets)
            )
        await self._repository.commit()
        selected = next(
            (candidate for candidate in persisted if candidate.selected), None
        )
        return CandidateSelectionResult(
            capture.id, len(persisted), selected.id if selected else None
        )

    async def match_identity(
        self, capture_id: UUID
    ) -> IdentityProcessingResult:
        await self._required_capture(capture_id)
        model = await self._recognizer_model()
        existing = await self._repository.find_match(capture_id, model.id)
        if existing is not None:
            return IdentityProcessingResult(
                existing,
                existing.review_status == IdentityReviewStatus.PENDING,
            )

        now = datetime.now(UTC)
        candidate = await self._repository.selected_candidate(capture_id)
        if candidate is None or candidate.face_asset_id is None:
            match = await self._store_no_match(
                capture_id,
                model=model,
                candidate=candidate,
                decision=IdentityDecision.UNRESOLVED,
                reason="NO_QUALIFIED_FACE_CANDIDATE",
                now=now,
                needs_review=True,
            )
            return IdentityProcessingResult(match, True)

        face_asset = await self._repository.get_asset(candidate.face_asset_id)
        if face_asset is None or face_asset.deleted_at is not None:
            match = await self._store_no_match(
                capture_id,
                model=model,
                candidate=candidate,
                decision=IdentityDecision.UNRESOLVED,
                reason="FACE_EVIDENCE_UNAVAILABLE",
                now=now,
                needs_review=True,
            )
            return IdentityProcessingResult(match, True)

        image = await asyncio.to_thread(
            self._engine.read_image,
            self._storage.resolve_key(face_asset.storage_key),
        )
        observations = await asyncio.to_thread(
            self._engine.detect_candidates, image
        )
        if not observations:
            match = await self._store_no_match(
                capture_id,
                model=model,
                candidate=candidate,
                decision=IdentityDecision.UNRESOLVED,
                reason="FACE_ALIGNMENT_FAILED",
                now=now,
                needs_review=True,
            )
            return IdentityProcessingResult(match, True)
        embedding = await asyncio.to_thread(
            self._engine.extract_embedding,
            image,
            observations[0].detector_row,
        )
        templates = await self._repository.active_templates(
            model_version_id=model.id,
            modality=BiometricModality.FACE,
            at=now,
            limit=self._settings.biometric_candidate_limit,
        )
        if not templates:
            match = await self._store_no_match(
                capture_id,
                model=model,
                candidate=candidate,
                decision=IdentityDecision.UNKNOWN,
                reason="NO_ACTIVE_REFERENCE_TEMPLATES",
                now=now,
                needs_review=False,
            )
            return IdentityProcessingResult(match, False)

        ranked = self._rank_distinct_subjects(embedding, templates)
        best_similarity, best_template = ranked[0]
        second_best = ranked[1][0] if len(ranked) > 1 else None
        margin = (
            best_similarity - second_best
            if second_best is not None
            else 2.0
        )
        decision, needs_review, reason = self._decision(
            best_similarity, margin
        )
        confidence = max(
            0.0,
            min(
                1.0,
                ((best_similarity + 1.0) / 2.0)
                * candidate.quality_score,
            ),
        )
        match = await self._repository.add_match(
            capture_id=capture_id,
            candidate=candidate,
            template=(
                best_template
                if decision
                in {
                    IdentityDecision.CONFIRMED,
                    IdentityDecision.PROBABLE,
                    IdentityDecision.CONFLICT,
                }
                else None
            ),
            model_version=model,
            decision=decision,
            similarity=best_similarity,
            confidence=round(confidence, 6),
            second_best=second_best,
            reasoning={
                "reason": reason,
                "quality_score": candidate.quality_score,
                "distinct_subject_count": len(ranked),
                "margin": round(margin, 6),
                "confirmed_threshold": (
                    self._settings.biometric_confirmed_threshold
                ),
                "probable_threshold": (
                    self._settings.biometric_probable_threshold
                ),
                "conflict_margin": self._settings.biometric_conflict_margin,
            },
            review_status=(
                IdentityReviewStatus.PENDING
                if needs_review
                else IdentityReviewStatus.NOT_REQUIRED
            ),
            matched_at=now,
        )
        await self._repository.commit()
        return IdentityProcessingResult(match, needs_review)

    async def enroll(
        self,
        *,
        source_asset_id: UUID,
        person_id: UUID | None,
        external_subject_key: str | None,
    ) -> BiometricTemplate:
        subject_key = (
            external_subject_key.strip() if external_subject_key else None
        )
        if person_id is None and not subject_key:
            raise ValueError(
                "person_id or external_subject_key must be provided"
            )
        asset = await self._repository.get_asset(source_asset_id)
        if (
            asset is None
            or asset.deleted_at is not None
            or asset.asset_type != EvidenceAssetType.FACE_CROP
        ):
            raise LookupError("Available FACE_CROP evidence asset not found")
        image = await asyncio.to_thread(
            self._engine.read_image,
            self._storage.resolve_key(asset.storage_key),
        )
        observations = await asyncio.to_thread(
            self._engine.detect_candidates, image
        )
        if not observations:
            raise ValueError("No alignable face found in source evidence")
        observation = observations[0]
        if (
            observation.quality_score
            < self._settings.biometric_min_quality_score
        ):
            raise ValueError("Face quality is below enrollment threshold")
        embedding = await asyncio.to_thread(
            self._engine.extract_embedding,
            image,
            observation.detector_row,
        )
        model = await self._recognizer_model()
        now = datetime.now(UTC)
        template = await self._repository.enroll_template(
            person_id=person_id,
            external_subject_key=subject_key,
            source_asset_id=source_asset_id,
            model_version_id=model.id,
            embedding=embedding,
            native_dimension=self._engine.SFACE_NATIVE_DIMENSION,
            quality_score=observation.quality_score,
            metadata={
                "source": "FACE_CROP",
                "embedding_storage_dimension": (
                    self._engine.EMBEDDING_SIZE
                ),
            },
            enrolled_at=now,
            expires_at=now
            + timedelta(
                days=self._settings.biometric_template_retention_days
            ),
        )
        await self._repository.commit()
        return template

    async def revoke_template(
        self, template_id: UUID
    ) -> BiometricTemplate | None:
        template = await self._repository.revoke_template(
            template_id, revoked_at=datetime.now(UTC)
        )
        await self._repository.commit()
        return template

    async def list_matches(self, **filters: Any) -> Any:
        return await self._repository.list_matches(**filters)

    async def list_candidates(
        self, capture_id: UUID
    ) -> list[FaceCandidate] | None:
        if not await self._repository.capture_exists(capture_id):
            return None
        return await self._repository.list_capture_candidates(capture_id)

    async def get_match(self, match_id: UUID) -> IdentityMatch | None:
        return await self._repository.get_match(match_id)

    async def list_templates(self, **filters: Any) -> Any:
        return await self._repository.list_templates(**filters)

    async def _required_capture(self, capture_id: UUID) -> CaptureEvent:
        capture = await self._repository.get_capture(capture_id)
        if capture is None:
            raise LookupError("Capture event not found")
        return capture

    async def _capture_image(
        self, capture: CaptureEvent
    ) -> tuple[EvidenceAsset, Any]:
        available = [
            asset
            for asset in capture.evidence_assets
            if asset.deleted_at is None
        ]
        priority = {
            EvidenceAssetType.FULL_BODY: 0,
            EvidenceAssetType.ORIGINAL_SNAPSHOT: 1,
            EvidenceAssetType.ANNOTATED_SNAPSHOT: 2,
        }
        sources = sorted(
            (asset for asset in available if asset.asset_type in priority),
            key=lambda asset: priority[asset.asset_type],
        )
        if not sources:
            raise LookupError("Capture has no usable image evidence")
        source = sources[0]
        image = await asyncio.to_thread(
            self._engine.read_image,
            self._storage.resolve_key(source.storage_key),
        )
        if (
            source.asset_type != EvidenceAssetType.FULL_BODY
            and capture.bbox
        ):
            bbox = capture.bbox
            x1 = float(bbox.get("x1", bbox.get("x", 0)))
            y1 = float(bbox.get("y1", bbox.get("y", 0)))
            x2 = float(
                bbox.get("x2", x1 + float(bbox.get("width", 0)))
            )
            y2 = float(
                bbox.get("y2", y1 + float(bbox.get("height", 0)))
            )
            cropped = self._engine._crop(
                image, x1, y1, x2 - x1, y2 - y1, padding=0.05
            )
            if getattr(cropped, "size", 0) > 0:
                image = cropped
        return source, image

    async def _detector_model(self) -> Any:
        checksum = await asyncio.to_thread(self._engine.detector_checksum)
        return await self._repository.ensure_model_version(
            model_key="opencv-yunet-face-detector",
            name="YuNet face detector",
            version=self._engine.DETECTOR_VERSION,
            task="FACE_DETECTION",
            runtime="OpenCV DNN",
            checksum=checksum,
            native_dimension=None,
            thresholds={
                "score": self._settings.biometric_face_detection_threshold,
                "nms": self._settings.biometric_face_nms_threshold,
                "minimum_face_size": self._settings.biometric_min_face_size,
            },
        )

    async def _recognizer_model(self) -> Any:
        checksum = await asyncio.to_thread(self._engine.recognizer_checksum)
        return await self._repository.ensure_model_version(
            model_key="opencv-sface-recognizer",
            name="SFace face recognizer",
            version=self._engine.RECOGNIZER_VERSION,
            task="FACE_RECOGNITION",
            runtime="OpenCV DNN",
            checksum=checksum,
            native_dimension=self._engine.SFACE_NATIVE_DIMENSION,
            thresholds={
                "confirmed": self._settings.biometric_confirmed_threshold,
                "probable": self._settings.biometric_probable_threshold,
                "conflict_margin": self._settings.biometric_conflict_margin,
            },
        )

    async def _store_no_match(
        self,
        capture_id: UUID,
        *,
        model: Any,
        candidate: FaceCandidate | None,
        decision: IdentityDecision,
        reason: str,
        now: datetime,
        needs_review: bool,
    ) -> IdentityMatch:
        match = await self._repository.add_match(
            capture_id=capture_id,
            candidate=candidate,
            template=None,
            model_version=model,
            decision=decision,
            similarity=None,
            confidence=0.0,
            second_best=None,
            reasoning={"reason": reason},
            review_status=(
                IdentityReviewStatus.PENDING
                if needs_review
                else IdentityReviewStatus.NOT_REQUIRED
            ),
            matched_at=now,
        )
        await self._repository.commit()
        return match

    def _rank_distinct_subjects(
        self,
        embedding: list[float],
        templates: list[BiometricTemplate],
    ) -> list[tuple[float, BiometricTemplate]]:
        best_by_subject: dict[
            tuple[str, str], tuple[float, BiometricTemplate]
        ] = {}
        for template in templates:
            subject = (
                ("person", str(template.person_id))
                if template.person_id is not None
                else ("external", template.external_subject_key or "")
            )
            similarity = self._engine.cosine_similarity(
                embedding, list(template.embedding)
            )
            current = best_by_subject.get(subject)
            if current is None or similarity > current[0]:
                best_by_subject[subject] = (similarity, template)
        return sorted(
            best_by_subject.values(), key=lambda item: item[0], reverse=True
        )

    def _decision(
        self, similarity: float, margin: float
    ) -> tuple[IdentityDecision, bool, str]:
        if similarity >= self._settings.biometric_confirmed_threshold:
            if margin < self._settings.biometric_conflict_margin:
                return IdentityDecision.CONFLICT, True, "AMBIGUOUS_TOP_MATCH"
            return IdentityDecision.CONFIRMED, False, "THRESHOLD_AND_MARGIN_MET"
        if similarity >= self._settings.biometric_probable_threshold:
            return IdentityDecision.PROBABLE, True, "PROBABLE_REQUIRES_REVIEW"
        return IdentityDecision.UNKNOWN, False, "BELOW_MATCH_THRESHOLD"

    @staticmethod
    def _derived_key(
        capture: CaptureEvent, kind: str, sequence: int
    ) -> str:
        captured = capture.captured_at
        return (
            f"biometric/{captured:%Y/%m/%d}/{capture.id}/"
            f"{kind}-{sequence}.jpg"
        )

    @staticmethod
    def _asset_from_file(
        file: EvidenceFile,
        *,
        capture: CaptureEvent,
        retention_until: datetime,
    ) -> EvidenceAsset:
        return EvidenceAsset(
            id=file.asset_id,
            capture_event_id=capture.id,
            asset_type=file.asset_type,
            sequence_index=file.sequence_index,
            storage_key=file.storage_key,
            checksum_sha256=file.checksum_sha256,
            integrity_status=EvidenceIntegrityStatus.VERIFIED,
            mime_type=file.mime_type,
            size_bytes=file.size_bytes,
            width=file.width,
            height=file.height,
            is_primary=False,
            asset_metadata=file.metadata,
            captured_at=capture.captured_at,
            retention_until=retention_until,
        )
