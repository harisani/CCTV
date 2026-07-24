"""Persistence for full-body candidates, embeddings, and PPE observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    BiometricModality,
    BodyCandidate,
    BodyEmbedding,
    CaptureEvent,
    IdentityDecision,
    IdentityMatch,
    IdentityReviewStatus,
    ModelVersion,
    Person,
    PPEAnalysis,
    PPEAnalysisStatus,
)
from app.repository.base import BaseRepository


@dataclass(frozen=True, slots=True)
class BodyEmbeddingCandidate:
    embedding: BodyEmbedding
    person: Person
    similarity: float


class BodyAnalysisRepository(BaseRepository[BodyCandidate]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, BodyCandidate)

    async def get_capture(self, capture_id: UUID) -> CaptureEvent | None:
        return await self.session.scalar(
            select(CaptureEvent)
            .where(CaptureEvent.id == capture_id)
            .options(selectinload(CaptureEvent.evidence_assets))
        )

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

    async def list_candidates(
        self, capture_id: UUID
    ) -> list[BodyCandidate]:
        return list(
            (
                await self.session.scalars(
                    select(BodyCandidate)
                    .where(BodyCandidate.capture_event_id == capture_id)
                    .order_by(BodyCandidate.sequence_index)
                )
            ).all()
        )

    async def add_candidates(
        self, candidates: list[BodyCandidate]
    ) -> None:
        self.session.add_all(candidates)
        await self.session.flush()

    async def selected_candidate(
        self, capture_id: UUID
    ) -> BodyCandidate | None:
        return await self.session.scalar(
            select(BodyCandidate)
            .where(
                BodyCandidate.capture_event_id == capture_id,
                BodyCandidate.selected.is_(True),
            )
            .order_by(BodyCandidate.quality_score.desc())
            .limit(1)
        )

    async def find_embedding(
        self, candidate_id: UUID, model_version_id: UUID
    ) -> BodyEmbedding | None:
        return await self.session.scalar(
            select(BodyEmbedding).where(
                BodyEmbedding.body_candidate_id == candidate_id,
                BodyEmbedding.model_version_id == model_version_id,
            )
        )

    async def add_embedding(
        self,
        *,
        candidate: BodyCandidate,
        model: ModelVersion,
        embedding: Sequence[float],
        person_id: UUID | None,
        source: str,
        expires_at: datetime,
    ) -> BodyEmbedding:
        body_embedding = BodyEmbedding(
            id=uuid4(),
            body_candidate_id=candidate.id,
            person_id=person_id,
            model_version_id=model.id,
            embedding=list(embedding),
            quality_score=candidate.quality_score,
            source=source,
            active=True,
            captured_at=candidate.captured_at,
            expires_at=expires_at,
        )
        self.session.add(body_embedding)
        await self.session.flush()
        return body_embedding

    async def face_anchor_person(self, capture_id: UUID) -> UUID | None:
        return await self.session.scalar(
            select(IdentityMatch.candidate_person_id).where(
                IdentityMatch.capture_event_id == capture_id,
                IdentityMatch.modality == BiometricModality.FACE,
                IdentityMatch.decision == IdentityDecision.CONFIRMED,
                IdentityMatch.candidate_person_id.is_not(None),
            )
        )

    async def body_embedding_candidates(
        self,
        embedding: Sequence[float],
        *,
        model_version_id: UUID,
        min_quality: float,
        at: datetime,
        limit: int,
        exclude_id: UUID,
    ) -> list[BodyEmbeddingCandidate]:
        distance = BodyEmbedding.embedding.cosine_distance(
            list(embedding)
        ).label("distance")
        rows = (
            await self.session.execute(
                select(BodyEmbedding, Person, distance)
                .join(Person, Person.id == BodyEmbedding.person_id)
                .where(
                    BodyEmbedding.id != exclude_id,
                    BodyEmbedding.model_version_id == model_version_id,
                    BodyEmbedding.person_id.is_not(None),
                    BodyEmbedding.active.is_(True),
                    BodyEmbedding.quality_score >= min_quality,
                    or_(
                        BodyEmbedding.expires_at.is_(None),
                        BodyEmbedding.expires_at > at,
                    ),
                    Person.is_active.is_(True),
                )
                .order_by(distance)
                .limit(limit)
            )
        ).all()
        return [
            BodyEmbeddingCandidate(
                template,
                person,
                max(-1.0, min(1.0, 1.0 - float(distance_value))),
            )
            for template, person, distance_value in rows
        ]

    async def find_identity_match(
        self, capture_id: UUID, model_version_id: UUID
    ) -> IdentityMatch | None:
        return await self.session.scalar(
            select(IdentityMatch).where(
                IdentityMatch.capture_event_id == capture_id,
                IdentityMatch.model_version_id == model_version_id,
            )
        )

    async def add_body_match(
        self,
        *,
        capture_id: UUID,
        candidate: BodyCandidate | None,
        body_embedding: BodyEmbedding | None,
        matched_embedding: BodyEmbedding | None,
        model: ModelVersion,
        person_id: UUID | None,
        decision: IdentityDecision,
        similarity: float | None,
        confidence: float,
        second_best: float | None,
        reasoning: dict[str, Any],
        needs_review: bool,
        matched_at: datetime,
    ) -> IdentityMatch:
        match = IdentityMatch(
            id=uuid4(),
            idempotency_key=f"body-identity:{capture_id}:{model.id}",
            capture_event_id=capture_id,
            face_candidate_id=None,
            body_candidate_id=candidate.id if candidate else None,
            matched_template_id=None,
            matched_body_embedding_id=(
                matched_embedding.id if matched_embedding else None
            ),
            candidate_person_id=person_id,
            candidate_external_subject_key=None,
            model_version_id=model.id,
            modality=BiometricModality.BODY,
            decision=decision,
            similarity_score=similarity,
            confidence_score=confidence,
            second_best_similarity=second_best,
            reasoning_metadata={
                **reasoning,
                "body_embedding_id": (
                    str(body_embedding.id) if body_embedding else None
                ),
            },
            review_status=(
                IdentityReviewStatus.PENDING
                if needs_review
                else IdentityReviewStatus.NOT_REQUIRED
            ),
            matched_at=matched_at,
        )
        self.session.add(match)
        await self.session.flush()
        return match

    async def get_ppe_analysis(
        self, capture_id: UUID
    ) -> PPEAnalysis | None:
        return await self.session.scalar(
            select(PPEAnalysis).where(
                PPEAnalysis.capture_event_id == capture_id
            )
        )

    async def add_ppe_analysis(
        self,
        *,
        capture_id: UUID,
        candidate_id: UUID | None,
        model_version_id: UUID | None,
        status: PPEAnalysisStatus,
        detections: list[dict[str, Any]],
        observed_items: dict[str, Any],
        color_observation: dict[str, Any] | None,
        confidence: float,
        reasoning: dict[str, Any],
        needs_review: bool,
        analyzed_at: datetime,
    ) -> PPEAnalysis:
        analysis = PPEAnalysis(
            id=uuid4(),
            capture_event_id=capture_id,
            body_candidate_id=candidate_id,
            model_version_id=model_version_id,
            status=status,
            detections=detections,
            observed_items=observed_items,
            color_observation=color_observation,
            confidence_score=confidence,
            reasoning_metadata=reasoning,
            needs_review=needs_review,
            analyzed_at=analyzed_at,
        )
        self.session.add(analysis)
        await self.session.flush()
        return analysis

    async def capture_requires_review(self, capture_id: UUID) -> bool:
        pending_identity = await self.session.scalar(
            select(func.count(IdentityMatch.id)).where(
                IdentityMatch.capture_event_id == capture_id,
                IdentityMatch.review_status == IdentityReviewStatus.PENDING,
            )
        )
        ppe_review = await self.session.scalar(
            select(func.count(PPEAnalysis.id)).where(
                PPEAnalysis.capture_event_id == capture_id,
                PPEAnalysis.needs_review.is_(True),
            )
        )
        return bool(pending_identity or ppe_review)

    async def list_body_candidates(
        self,
        *,
        capture_id: UUID | None,
        selected: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[BodyCandidate], int]:
        filters = []
        if capture_id is not None:
            filters.append(BodyCandidate.capture_event_id == capture_id)
        if selected is not None:
            filters.append(BodyCandidate.selected == selected)
        statement = select(BodyCandidate).where(*filters)
        items = list(
            (
                await self.session.scalars(
                    statement.order_by(BodyCandidate.captured_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        return items, int(total or 0)

    async def list_body_embeddings(
        self,
        *,
        person_id: UUID | None,
        active: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[BodyEmbedding], int]:
        filters = []
        if person_id is not None:
            filters.append(BodyEmbedding.person_id == person_id)
        if active is not None:
            filters.append(BodyEmbedding.active == active)
        statement = select(BodyEmbedding).where(*filters)
        items = list(
            (
                await self.session.scalars(
                    statement.order_by(BodyEmbedding.captured_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
        )
        total = await self.session.scalar(
            select(func.count()).select_from(statement.subquery())
        )
        return items, int(total or 0)

    async def list_ppe_analyses(
        self,
        *,
        status: PPEAnalysisStatus | None,
        capture_id: UUID | None,
        needs_review: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[PPEAnalysis], int]:
        filters = []
        if status is not None:
            filters.append(PPEAnalysis.status == status)
        if capture_id is not None:
            filters.append(PPEAnalysis.capture_event_id == capture_id)
        if needs_review is not None:
            filters.append(PPEAnalysis.needs_review == needs_review)
        statement = select(PPEAnalysis).where(*filters)
        items = list(
            (
                await self.session.scalars(
                    statement.order_by(PPEAnalysis.analyzed_at.desc())
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
