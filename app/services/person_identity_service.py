"""Audited, transactional corrections for production ReID identities."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuditLog,
    BiometricTemplate,
    BodyCandidate,
    BodyEmbedding,
    CaptureEvent,
    EvidenceAsset,
    Event,
    GlobalJourney,
    IdentityDecision,
    IdentityMatch,
    IdentityReviewStatus,
    JourneyEvent,
    JourneyStatus,
    Person,
    PersonEmbedding,
    Tracking,
    User,
)


class PersonIdentityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def merge(self, *, target_id: UUID, source_ids: list[UUID], actor: User) -> Person:
        unique_sources = list(dict.fromkeys(source_ids))
        if not unique_sources or target_id in unique_sources:
            raise HTTPException(status_code=422, detail="Choose one target and at least one different source identity")
        ids = [target_id, *unique_sources]
        people = list(
            (
                await self.session.scalars(
                    select(Person).where(Person.id.in_(ids)).with_for_update()
                )
            ).all()
        )
        by_id = {person.id: person for person in people}
        if len(by_id) != len(ids):
            raise HTTPException(status_code=404, detail="One or more identities were not found")
        if any(not by_id[item].is_active for item in ids):
            raise HTTPException(status_code=409, detail="Merged identities cannot be modified again")
        await self._reject_active_tracks(ids)

        target = by_id[target_id]
        sources = [by_id[item] for item in unique_sources]
        await self.session.execute(
            update(Tracking).where(Tracking.person_id.in_(unique_sources)).values(person_id=target_id)
        )
        await self.session.execute(
            update(PersonEmbedding).where(PersonEmbedding.person_id.in_(unique_sources)).values(person_id=target_id)
        )
        await self.session.execute(
            update(BodyEmbedding)
            .where(BodyEmbedding.person_id.in_(unique_sources))
            .values(person_id=target_id)
        )
        await self.session.execute(
            update(BiometricTemplate)
            .where(BiometricTemplate.person_id.in_(unique_sources))
            .values(person_id=target_id)
        )
        await self.session.execute(
            update(IdentityMatch)
            .where(IdentityMatch.candidate_person_id.in_(unique_sources))
            .values(candidate_person_id=target_id)
        )
        await self.session.execute(
            update(GlobalJourney)
            .where(
                GlobalJourney.identity_person_id.in_(unique_sources)
            )
            .values(identity_person_id=target_id)
        )
        await self.session.execute(
            update(JourneyEvent)
            .where(
                JourneyEvent.identity_person_id.in_(unique_sources)
            )
            .values(identity_person_id=target_id)
        )
        target.first_seen_at = min([target.first_seen_at, *(item.first_seen_at for item in sources)])
        target.last_seen_at = max([target.last_seen_at, *(item.last_seen_at for item in sources)])
        target.needs_review = False
        target.identity_version += 1
        for source in sources:
            source.is_active = False
            source.needs_review = False
            source.merged_into_person_id = target_id
            source.identity_version += 1
        self.session.add(
            AuditLog(
                actor_user_id=actor.id,
                action="PERSON_IDENTITIES_MERGED",
                resource_type="person",
                resource_id=str(target_id),
                details={"target_person_id": str(target_id), "source_person_ids": [str(item) for item in unique_sources]},
            )
        )
        await self.session.commit()
        await self.session.refresh(target)
        return target

    async def split(
        self,
        *,
        source_id: UUID,
        tracking_ids: list[UUID],
        display_name: str | None,
        actor: User,
    ) -> Person:
        selected_ids = list(dict.fromkeys(tracking_ids))
        if not selected_ids:
            raise HTTPException(status_code=422, detail="Select at least one historical tracking")
        source = await self.session.scalar(
            select(Person).where(Person.id == source_id).with_for_update()
        )
        if source is None:
            raise HTTPException(status_code=404, detail="Identity not found")
        if not source.is_active:
            raise HTTPException(status_code=409, detail="A merged identity cannot be split")
        tracks = list(
            (
                await self.session.scalars(
                    select(Tracking).where(Tracking.id.in_(selected_ids)).with_for_update()
                )
            ).all()
        )
        if len(tracks) != len(selected_ids) or any(item.person_id != source_id for item in tracks):
            raise HTTPException(status_code=409, detail="Every selected tracking must belong to the source identity")
        if any(item.is_active for item in tracks):
            raise HTTPException(status_code=409, detail="Active tracking cannot be split; wait until it has ended")

        new_person = Person(
            reid_key=str(uuid4()),
            display_name=display_name.strip() if display_name else None,
            reid_embedding=None,
            first_seen_at=min(item.started_at for item in tracks),
            last_seen_at=max(item.ended_at or item.started_at for item in tracks),
        )
        self.session.add(new_person)
        await self.session.flush()
        await self.session.execute(
            update(Tracking).where(Tracking.id.in_(selected_ids)).values(person_id=new_person.id)
        )
        moved_templates = int(
            await self.session.scalar(
                select(func.count(PersonEmbedding.id)).where(PersonEmbedding.tracking_id.in_(selected_ids))
            )
            or 0
        )
        await self.session.execute(
            update(PersonEmbedding)
            .where(PersonEmbedding.tracking_id.in_(selected_ids))
            .values(person_id=new_person.id)
        )
        selected_capture_ids = select(CaptureEvent.id).where(
            CaptureEvent.tracking_id.in_(selected_ids)
        )
        selected_body_candidate_ids = select(BodyCandidate.id).where(
            BodyCandidate.capture_event_id.in_(selected_capture_ids)
        )
        moved_body_embeddings = int(
            await self.session.scalar(
                select(func.count(BodyEmbedding.id)).where(
                    BodyEmbedding.body_candidate_id.in_(
                        selected_body_candidate_ids
                    ),
                    BodyEmbedding.person_id == source_id,
                )
            )
            or 0
        )
        await self.session.execute(
            update(BodyEmbedding)
            .where(
                BodyEmbedding.body_candidate_id.in_(
                    selected_body_candidate_ids
                ),
                BodyEmbedding.person_id == source_id,
            )
            .values(person_id=new_person.id)
        )
        selected_asset_ids = select(EvidenceAsset.id).where(
            EvidenceAsset.capture_event_id.in_(selected_capture_ids)
        )
        moved_biometric_templates = int(
            await self.session.scalar(
                select(func.count(BiometricTemplate.id)).where(
                    BiometricTemplate.source_asset_id.in_(
                        selected_asset_ids
                    ),
                    BiometricTemplate.person_id == source_id,
                )
            )
            or 0
        )
        await self.session.execute(
            update(BiometricTemplate)
            .where(
                BiometricTemplate.source_asset_id.in_(selected_asset_ids),
                BiometricTemplate.person_id == source_id,
            )
            .values(person_id=new_person.id)
        )
        moved_identity_matches = int(
            await self.session.scalar(
                select(func.count(IdentityMatch.id)).where(
                    IdentityMatch.capture_event_id.in_(
                        selected_capture_ids
                    ),
                    IdentityMatch.candidate_person_id == source_id,
                )
            )
            or 0
        )
        await self.session.execute(
            update(IdentityMatch)
            .where(
                IdentityMatch.capture_event_id.in_(selected_capture_ids),
                IdentityMatch.candidate_person_id == source_id,
            )
            .values(candidate_person_id=new_person.id)
        )
        moved_journey_events = int(
            await self.session.scalar(
                select(func.count(JourneyEvent.id)).where(
                    JourneyEvent.capture_event_id.in_(
                        selected_capture_ids
                    ),
                    JourneyEvent.identity_person_id == source_id,
                )
            )
            or 0
        )
        affected_journey_ids = select(JourneyEvent.journey_id).where(
            JourneyEvent.capture_event_id.in_(selected_capture_ids)
        )
        await self.session.execute(
            update(JourneyEvent)
            .where(
                JourneyEvent.capture_event_id.in_(
                    selected_capture_ids
                ),
                JourneyEvent.identity_person_id == source_id,
            )
            .values(identity_person_id=new_person.id)
        )
        await self.session.execute(
            update(GlobalJourney)
            .where(GlobalJourney.id.in_(affected_journey_ids))
            .values(
                identity_decision=IdentityDecision.CONFLICT,
                status=JourneyStatus.NEED_REVIEW,
                review_status=IdentityReviewStatus.PENDING,
            )
        )
        moved_reference_count = (
            moved_templates + moved_body_embeddings
            + moved_biometric_templates
        )
        new_person.needs_review = moved_reference_count == 0
        source.identity_version += 1
        source.needs_review = False
        self.session.add(
            AuditLog(
                actor_user_id=actor.id,
                action="PERSON_IDENTITY_SPLIT",
                resource_type="person",
                resource_id=str(source_id),
                details={
                    "source_person_id": str(source_id),
                    "new_person_id": str(new_person.id),
                    "tracking_ids": [str(item) for item in selected_ids],
                    "moved_embedding_count": moved_templates,
                    "moved_body_embedding_count": moved_body_embeddings,
                    "moved_biometric_template_count": (
                        moved_biometric_templates
                    ),
                    "moved_identity_match_count": moved_identity_matches,
                    "moved_journey_event_count": moved_journey_events,
                },
            )
        )
        await self.session.commit()
        await self.session.refresh(new_person)
        return new_person

    async def tracking_history(self, person_id: UUID) -> list[dict]:
        person = await self.session.get(Person, person_id)
        if person is None:
            raise HTTPException(status_code=404, detail="Identity not found")
        embedding_count = (
            select(func.count(PersonEmbedding.id))
            .where(PersonEmbedding.tracking_id == Tracking.id)
            .correlate(Tracking)
            .scalar_subquery()
        )
        event_count = (
            select(func.count(Event.id)).where(Event.tracking_id == Tracking.id).correlate(Tracking).scalar_subquery()
        )
        rows = (
            await self.session.execute(
                select(Tracking, embedding_count, event_count)
                .where(Tracking.person_id == person_id)
                .order_by(Tracking.started_at.desc())
                .limit(500)
            )
        ).all()
        return [
            {
                "id": tracking.id,
                "camera_id": tracking.camera_id,
                "byte_track_id": tracking.byte_track_id,
                "started_at": tracking.started_at,
                "ended_at": tracking.ended_at,
                "is_active": tracking.is_active,
                "embedding_count": int(embeddings or 0),
                "event_count": int(events or 0),
            }
            for tracking, embeddings, events in rows
        ]

    async def _reject_active_tracks(self, person_ids: list[UUID]) -> None:
        count = int(
            await self.session.scalar(
                select(func.count(Tracking.id)).where(
                    Tracking.person_id.in_(person_ids), Tracking.is_active.is_(True)
                )
            )
            or 0
        )
        if count:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Identity correction is locked while one of its trackings is active",
            )
