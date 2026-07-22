"""Single-process daily backup scheduler."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.models import BackupSource, BackupStatus
from app.repository import BackupRepository
from app.services.backup_service import BackupService


class BackupScheduler:
    def __init__(self, settings: Any, session_factory: Any) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.timezone = ZoneInfo(settings.backup_timezone)
        hour, minute = (int(part) for part in settings.backup_schedule_time.split(":"))
        self.schedule_time = time(hour=hour, minute=minute)
        self.logger = logging.getLogger(__name__)
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            await self._recover_interrupted_jobs()
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="daily-backup-scheduler")
            self.logger.info(
                "Backup scheduler started at %s %s",
                self.settings.backup_schedule_time,
                self.settings.backup_timezone,
            )

    async def _recover_interrupted_jobs(self) -> None:
        async with self.session_factory() as session:
            recovered = await BackupRepository(session).recover_interrupted(
                completed_at=datetime.now(UTC)
            )
            if recovered:
                await session.commit()
                self.logger.warning(
                    "Marked %s interrupted backup job(s) as failed", recovered
                )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_if_due()
            except Exception:
                self.logger.exception("Scheduled backup check failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=60)
            except TimeoutError:
                continue

    async def run_if_due(self, now: datetime | None = None) -> bool:
        local_now = now.astimezone(self.timezone) if now else datetime.now(self.timezone)
        if local_now.time() < self.schedule_time:
            return False
        target_date: date = local_now.date() - timedelta(days=1)
        async with self.session_factory() as session:
            repository = BackupRepository(session)
            existing = await repository.get_automatic_for_date(target_date)
            if existing and existing.status == BackupStatus.READY:
                return False
            if existing and existing.status == BackupStatus.CREATING:
                existing.status = BackupStatus.FAILED
                existing.error_message = "Recovered an interrupted backup job"
                existing.completed_at = local_now
                await session.commit()
            service = BackupService(repository, self.settings)
            await service.create_for_date(
                target_date, source=BackupSource.AUTOMATIC, actor=None
            )
            await service.apply_retention(local_now.date())
        return True
