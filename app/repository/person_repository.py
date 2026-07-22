from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Person, PersonEmbedding, Tracking
from app.repository.base import BaseRepository


@dataclass(frozen=True, slots=True)
class EmbeddingCandidate:
    person: Person
    embedding: PersonEmbedding
    similarity: float


class PersonRepository(BaseRepository[Person]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Person)

    async def get_by_reid_key(self, reid_key: str) -> Person | None:
        return await self.session.scalar(select(Person).where(Person.reid_key == reid_key))

    async def list_with_embeddings(self) -> list[Person]:
        """Compatibility path for installations that have not migrated legacy JSON yet."""
        statement = select(Person).where(Person.reid_embedding.is_not(None), Person.is_active.is_(True))
        return list((await self.session.scalars(statement)).all())

    async def find_embedding_candidates(
        self,
        embedding: Sequence[float],
        *,
        model_name: str,
        min_quality: float,
        limit: int,
        at: datetime,
    ) -> list[EmbeddingCandidate]:
        distance = PersonEmbedding.embedding.cosine_distance(list(embedding)).label("distance")
        statement = (
            select(PersonEmbedding, Person, distance)
            .join(Person, Person.id == PersonEmbedding.person_id)
            .where(
                Person.is_active.is_(True),
                PersonEmbedding.is_active.is_(True),
                PersonEmbedding.model_name == model_name,
                PersonEmbedding.quality_score >= min_quality,
                (PersonEmbedding.expires_at.is_(None) | (PersonEmbedding.expires_at > at)),
            )
            .order_by(distance)
            .limit(limit)
        )
        rows = (await self.session.execute(statement)).all()
        return [
            EmbeddingCandidate(person, template, max(-1.0, min(1.0, 1.0 - float(distance_value))))
            for template, person, distance_value in rows
        ]

    async def add_embedding(self, template: PersonEmbedding) -> PersonEmbedding:
        self.session.add(template)
        await self.session.flush()
        return template

    async def record_match(self, embedding_id: UUID, *, matched_at: datetime) -> None:
        await self.session.execute(
            update(PersonEmbedding)
            .where(PersonEmbedding.id == embedding_id)
            .values(
                last_matched_at=matched_at,
                match_count=PersonEmbedding.match_count + 1,
            )
        )

    async def link_embedding_to_tracking(self, embedding_id: UUID, tracking_id: UUID) -> None:
        await self.session.execute(
            update(PersonEmbedding)
            .where(PersonEmbedding.id == embedding_id)
            .values(tracking_id=tracking_id)
        )

    async def list_filtered(
        self,
        *,
        name: str | None,
        offset: int,
        limit: int,
        include_merged: bool = False,
    ) -> tuple[list[Person], int]:
        embedding_count = (
            select(func.count(PersonEmbedding.id))
            .where(PersonEmbedding.person_id == Person.id, PersonEmbedding.is_active.is_(True))
            .correlate(Person)
            .scalar_subquery()
        )
        tracking_count = (
            select(func.count(Tracking.id))
            .where(Tracking.person_id == Person.id)
            .correlate(Person)
            .scalar_subquery()
        )
        filters = []
        if not include_merged:
            filters.append(Person.is_active.is_(True))
        if name:
            filters.append((Person.display_name.ilike(f"%{name}%")) | (Person.reid_key.ilike(f"%{name}%")))

        statement = select(Person, embedding_count.label("embedding_count"), tracking_count.label("tracking_count")).where(*filters)
        rows = (
            await self.session.execute(
                statement.order_by(Person.last_seen_at.desc()).offset(offset).limit(limit)
            )
        ).all()
        items: list[Person] = []
        for person, embeddings, trackings in rows:
            person.embedding_count = int(embeddings or 0)
            person.tracking_count = int(trackings or 0)
            items.append(person)
        total = await self.session.scalar(select(func.count(Person.id)).where(*filters))
        return items, int(total or 0)
