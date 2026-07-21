from __future__ import annotations

from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Reusable async CRUD operations for one ORM entity type."""

    def __init__(self, session: AsyncSession, model_type: type[ModelType]) -> None:
        self.session = session
        self.model_type = model_type

    async def get(self, entity_id: UUID) -> ModelType | None:
        return await self.session.get(self.model_type, entity_id)

    async def list(self, *, offset: int = 0, limit: int = 100) -> list[ModelType]:
        statement = select(self.model_type).offset(offset).limit(limit)
        return list((await self.session.scalars(statement)).all())

    async def add(self, entity: ModelType) -> ModelType:
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity
