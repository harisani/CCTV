"""Daily scheduler for encrypted full disaster-recovery backups."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from app.repository import DisasterRecoveryRepository
from app.services.disaster_recovery_service import DisasterRecoveryService


class DisasterRecoveryScheduler:
    def __init__(self, settings: Any, session_factory: Any) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.timezone = ZoneInfo(settings.backup_timezone)
        hour, minute = (int(part) for part in settings.dr_schedule_time.split(":"))
        self.schedule_time = time(hour=hour, minute=minute)
        self.logger = logging.getLogger(__name__)
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        async with self.session_factory() as session:
            recovered = await DisasterRecoveryRepository(session).recover_interrupted(
                completed_at=datetime.now(UTC)
            )
            if recovered:
                await session.commit()
                self.logger.warning("Recovered %s interrupted DR job(s)", recovered)
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="daily-dr-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_if_due()
            except Exception:
                self.logger.exception("Scheduled disaster-recovery backup failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=60)
            except TimeoutError:
                pass

    async def run_if_due(self, now: datetime | None = None) -> bool:
        local_now = now.astimezone(self.timezone) if now else datetime.now(self.timezone)
        if local_now.time() < self.schedule_time:
            return False
        schedule_key = f"DR:{local_now.date().isoformat()}"
        async with self.session_factory() as session:
            repository = DisasterRecoveryRepository(session)
            if await repository.get_by_schedule_key(schedule_key):
                return False
            service = DisasterRecoveryService(repository, self.settings)
            await service.create(actor=None, schedule_key=schedule_key)
            await service.apply_retention(datetime.now(UTC))
        return True
