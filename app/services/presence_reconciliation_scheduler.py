"""Close stale presence sessions at local midnight with auditable EXIT events."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, time
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models import Camera, Event, EventType, PresenceSession, PresenceStatus


class PresenceReconciliationScheduler:
    """Reconcile yesterday's open entries after 00:00 in the configured timezone."""

    def __init__(self, settings: Any, session_factory: Any, dashboard_hub: Any) -> None:
        self._session_factory = session_factory
        self._dashboard_hub = dashboard_hub
        self._timezone = ZoneInfo(settings.presence_timezone)
        self._interval_seconds = settings.presence_reconcile_interval_seconds
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._logger = logging.getLogger(__name__)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="presence-midnight-reconciliation")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
        self._task = None

    async def reconcile(self, now: datetime | None = None) -> list[dict[str, Any]]:
        local_now = now.astimezone(self._timezone) if now else datetime.now(self._timezone)
        cutoff = datetime.combine(local_now.date(), time.min, tzinfo=self._timezone).astimezone(UTC)
        async with self._session_factory() as session:
            sessions = list(
                (
                    await session.scalars(
                        select(PresenceSession)
                        .where(
                            PresenceSession.status.in_((PresenceStatus.ACTIVE, PresenceStatus.UNCERTAIN)),
                            PresenceSession.entered_at < cutoff,
                        )
                        .with_for_update()
                    )
                ).all()
            )
            if not sessions:
                return []
            camera_ids = {item.camera_id for item in sessions if item.camera_id is not None}
            cameras = {
                camera.id: camera
                for camera in (
                    await session.scalars(select(Camera).where(Camera.id.in_(camera_ids)))
                ).all()
            } if camera_ids else {}
            payloads: list[dict[str, Any]] = []
            for presence in sessions:
                event = None
                if presence.entry_tracking_id is not None:
                    event = Event(
                        id=uuid4(),
                        tracking_id=presence.entry_tracking_id,
                        event_type=EventType.EXIT,
                        line_id="system-midnight",
                        centroid={"x": None, "y": None},
                        occurred_at=cutoff,
                        event_metadata={
                            "system_generated": True,
                            "reason": "MIDNIGHT_NO_EXIT",
                            "presence_session_id": str(presence.id),
                        },
                    )
                    session.add(event)
                presence.status = PresenceStatus.CLOSED
                presence.exit_event_id = event.id if event else None
                presence.exit_tracking_id = presence.entry_tracking_id
                presence.exited_at = cutoff
                presence.uncertain_since = None
                presence.updated_at = cutoff
                if event is not None:
                    camera = cameras.get(presence.camera_id)
                    payloads.append(
                        {
                            "id": str(event.id),
                            "tracking_id": str(event.tracking_id),
                            "byte_track_id": None,
                            "person_id": str(presence.person_id) if presence.person_id else None,
                            "event_type": EventType.EXIT.value,
                            "line_id": event.line_id,
                            "centroid": event.centroid,
                            "occurred_at": cutoff.isoformat(),
                            "snapshot_path": None,
                            "snapshot_url": None,
                            "system_generated": True,
                            "camera_id": str(presence.camera_id) if presence.camera_id else None,
                            "camera_name": camera.name if camera else "Rekonsiliasi sistem",
                            "camera_location": camera.location if camera else None,
                        }
                    )
            await session.commit()
        self._logger.info("Midnight reconciliation closed sessions=%s cutoff=%s", len(sessions), cutoff)
        return payloads

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                for payload in await self.reconcile():
                    await self._dashboard_hub.publish_event(payload)
            except Exception:
                self._logger.exception("Midnight presence reconciliation failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                pass
