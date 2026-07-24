"""Async persistence and queries for face candidates and identity matches."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    BiometricModality,
    BiometricTemplate,
    CaptureEvent,
    EvidenceAsset,
    FaceCandidate,
    IdentityDecision,
    IdentityMatch,
    IdentityReviewStatus,
    ModelVersion,
    Person,
)
from app.repository.base import BaseRepository


class BiometricRepository(BaseRepository[FaceCandidate]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, FaceCandidate)

    async def get_capture(self, capture_id: UUID) -> CaptureEvent | None:
        return await self.session.scalar(
            select(CaptureEvent)
            .where(CaptureEvent.id == capture_id)
            .options(selectinload(CaptureEvent.evidence_assets))
        )

    async def get_asset(self, asset_id: UUID) -> EvidenceAsset | None:
        return await self.session.get(EvidenceAsset, asset_id)

    async def ensure_model_version(
        self,
        *,
        model_key: str,
        name: str,
        version: str,
        task: str,
        runtime: str,
        checksum: str,
        native_dimension: int | None,
        thresholds: dict[str, Any],
    ) -> ModelVersion:
        model = await self.session.scalar(
            select(ModelVersion).where(
                ModelVersion.model_key == model_key,
                ModelVersion.version == version,
            )
        )
        if model is None:
            model = ModelVersion(
                id=uuid4(),
                model_key=model_key,
                name=name,
                version=version,
                task=task,
                runtime=runtime,
                artifact_checksum_sha256=checksum,
                native_embedding_dimension=native_dimension,
                thresholds=thresholds,
                enabled=True,
            )
            self.session.add(model)
            await self.session.flush()
        elif model.artifact_checksum_sha256 != checksum:
            raise ValueError(
                f"Model checksum mismatch for {model_key}:{version}"
            )
        return model

    async def list_capture_candidates(
        self, capture_id: UUID
    ) -> list[FaceCandidate]:
        return list(
            (
                await self.session.scalars(
                    select(FaceCandidate)
                    .where(FaceCandidate.capture_event_id == capture_id)
                    .order_by(FaceCandidate.sequence_index)
                )
            ).all()
        )

    async def selected_candidate(
        self, capture_id: UUID
    ) -> FaceCandidate | None:
        return await self.session.scalar(
            select(FaceCandidate)
            .where(
                FaceCandidate.capture_event_id == capture_id,
                FaceCandidate.selected.is_(True),
            )
            .order_by(FaceCandidate.quality_score.desc())
            .limit(1)
        )

    async def capture_exists(self, capture_id: UUID) -> bool:
        return (
            await self.session.scalar(
                select(CaptureEvent.id).where(CaptureEvent.id == capture_id)
            )
            is not None
        )

    async def add_candidate(
        self,
        candidate: FaceCandidate,
        assets: list[EvidenceAsset],
    ) -> FaceCandidate:
        self.session.add_all([*assets, candidate])
        await self.session.flush()
        return candidate

    async def active_templates(
        self,
        *,
        model_version_id: UUID,
        modality: BiometricModality,
        at: datetime,
        limit: int,
    ) -> list[BiometricTemplate]:
        return list(
            (
                await self.session.scalars(
                    select(BiometricTemplate)
                    .where(
                        BiometricTemplate.model_version_id
                        == model_version_id,
                        BiometricTemplate.modality == modality,
                        BiometricTemplate.active.is_(True),
                        or_(
                            BiometricTemplate.expires_at.is_(None),
                            BiometricTemplate.expires_at > at,
                        ),
                    )
                    .order_by(
                        BiometricTemplate.quality_score.desc(),
                        BiometricTemplate.enrolled_at.desc(),
                    )
                    .limit(limit)
                )
            ).all()
        )

    async def find_match(
        self, capture_id: UUID, model_version_id: UUID
    ) -> IdentityMatch | None:
        return await self.session.scalar(
            select(IdentityMatch).where(
                IdentityMatch.capture_event_id == capture_id,
                IdentityMatch.model_version_id == model_version_id,
            )
        )

    async def add_match(
        self,
        *,
        capture_id: UUID,
        candidate: FaceCandidate | None,
        template: BiometricTemplate | None,
        model_version: ModelVersion,
        decision: IdentityDecision,
        similarity: float | None,
        confidence: float,
        second_best: float | None,
        reasoning: dict[str, Any],
        review_status: IdentityReviewStatus,
        matched_at: datetime,
    ) -> IdentityMatch:
        match = IdentityMatch(
            id=uuid4(),
            idempotency_key=(
                f"identity:{capture_id}:{model_version.id}"
            ),
            capture_event_id=capture_id,
            face_candidate_id=candidate.id if candidate else None,
            matched_template_id=template.id if template else None,
            candidate_person_id=template.person_id if template else None,
            candidate_external_subject_key=(
                template.external_subject_key if template else None
            ),
            model_version_id=model_version.id,
            modality=BiometricModality.FACE,
            decision=decision,
            similarity_score=similarity,
            confidence_score=confidence,
            second_best_similarity=second_best,
            reasoning_metadata=reasoning,
            review_status=review_status,
            matched_at=matched_at,
        )
        self.session.add(match)
        await self.session.flush()
        return match

    async def enroll_template(
        self,
        *,
        person_id: UUID | None,
        external_subject_key: str | None,
        source_asset_id: UUID,
        model_version_id: UUID,
        embedding: list[float],
        native_dimension: int,
        quality_score: float,
        metadata: dict[str, Any],
        enrolled_at: datetime,
        expires_at: datetime | None,
    ) -> BiometricTemplate:
        if person_id is not None and await self.session.get(Person, person_id) is None:
            raise LookupError("Person not found")
        template = BiometricTemplate(
            id=uuid4(),
            person_id=person_id,
            external_subject_key=external_subject_key,
            source_asset_id=source_asset_id,
            model_version_id=model_version_id,
            modality=BiometricModality.FACE,
            embedding=embedding,
            native_dimension=native_dimension,
            quality_score=quality_score,
            template_metadata=metadata,
            active=True,
            enrolled_at=enrolled_at,
            expires_at=expires_at,
        )
        self.session.add(template)
        await self.session.flush()
        return template

    async def revoke_template(
        self, template_id: UUID, *, revoked_at: datetime
    ) -> BiometricTemplate | None:
        template = await self.session.get(BiometricTemplate, template_id)
        if template is None:
            return None
        template.active = False
        template.revoked_at = revoked_at
        await self.session.flush()
        return template

    async def list_matches(
        self,
        *,
        decision: IdentityDecision | None,
        review_status: IdentityReviewStatus | None,
        capture_id: UUID | None,
        offset: int,
        limit: int,
    ) -> tuple[list[IdentityMatch], int]:
        filters = []
        if decision is not None:
            filters.append(IdentityMatch.decision == decision)
        if review_status is not None:
            filters.append(IdentityMatch.review_status == review_status)
        if capture_id is not None:
            filters.append(IdentityMatch.capture_event_id == capture_id)
        statement = select(IdentityMatch).where(*filters)
        items = list(
            (
                await self.session.scalars(
                    statement.order_by(IdentityMatch.matched_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        return items, int(total or 0)

    async def get_match(self, match_id: UUID) -> IdentityMatch | None:
        return await self.session.get(IdentityMatch, match_id)

    async def list_templates(
        self, *, active: bool | None, offset: int, limit: int
    ) -> tuple[list[BiometricTemplate], int]:
        filters = (
            [] if active is None else [BiometricTemplate.active == active]
        )
        statement = select(BiometricTemplate).where(*filters)
        items = list(
            (
                await self.session.scalars(
                    statement.order_by(
                        BiometricTemplate.enrolled_at.desc()
                    )
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        return items, int(total or 0)

    async def commit(self) -> None:
        await self.session.commit()
