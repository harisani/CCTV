"""Bounded retention of biometric templates without deleting operational history."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select

from app.models import PersonEmbedding


class ReIdRetentionService:
    def __init__(self, settings: Any, session_factory: Any) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.logger = logging.getLogger(__name__)
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="reid-retention")
            self.logger.info(
                "ReID retention started retention_days=%s min=%s max=%s",
                self.settings.reid_embedding_retention_days,
                self.settings.reid_min_embeddings_per_person,
                self.settings.reid_max_embeddings_per_person,
            )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                deleted = await self.apply()
                if deleted:
                    self.logger.info("ReID retention removed %s expired/excess templates", deleted)
            except Exception:
                self.logger.exception("ReID retention failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.settings.reid_retention_interval_hours * 3600
                )
            except TimeoutError:
                continue

    async def apply(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        PersonEmbedding.id,
                        PersonEmbedding.person_id,
                        PersonEmbedding.quality_score,
                        PersonEmbedding.expires_at,
                        PersonEmbedding.last_matched_at,
                        PersonEmbedding.captured_at,
                    )
                    .where(PersonEmbedding.is_active.is_(True))
                    .order_by(PersonEmbedding.person_id, PersonEmbedding.quality_score.desc(), PersonEmbedding.captured_at.desc())
                )
            ).all()
            grouped: dict[Any, list[Any]] = {}
            for row in rows:
                grouped.setdefault(row.person_id, []).append(row)
            delete_ids = []
            minimum = self.settings.reid_min_embeddings_per_person
            maximum = self.settings.reid_max_embeddings_per_person
            for templates in grouped.values():
                protected = {item.id for item in templates[:minimum]}
                for index, item in enumerate(templates):
                    expired = item.expires_at is not None and item.expires_at <= now
                    excess = index >= maximum
                    if item.id not in protected and (expired or excess):
                        delete_ids.append(item.id)
            if delete_ids:
                await session.execute(delete(PersonEmbedding).where(PersonEmbedding.id.in_(delete_ids)))
                await session.commit()
            return len(delete_ids)
