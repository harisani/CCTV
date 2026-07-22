"""Process-local registry for people visible in the latest AI frames."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID


class LiveVisibilityService:
    """Count unique visible identities across every active camera."""

    def __init__(self) -> None:
        self._identities_by_camera: dict[UUID, set[str]] = {}
        self._lock = asyncio.Lock()

    async def update(self, camera_id: UUID, tracks: list[dict[str, Any]]) -> tuple[int, bool]:
        identities = {
            self._identity_key(camera_id, track)
            for track in tracks
            if track.get("tracking_id") is not None
        }
        async with self._lock:
            previous = self._total_unlocked()
            self._identities_by_camera[camera_id] = identities
            current = self._total_unlocked()
            return current, current != previous

    async def clear_camera(self, camera_id: UUID) -> tuple[int, bool]:
        async with self._lock:
            previous = self._total_unlocked()
            self._identities_by_camera.pop(camera_id, None)
            current = self._total_unlocked()
            return current, current != previous

    async def clear(self) -> None:
        async with self._lock:
            self._identities_by_camera.clear()

    async def total(self, camera_id: UUID | None = None) -> int:
        async with self._lock:
            if camera_id is not None:
                return len(self._identities_by_camera.get(camera_id, set()))
            return self._total_unlocked()

    def _total_unlocked(self) -> int:
        return len(set().union(*self._identities_by_camera.values())) if self._identities_by_camera else 0

    @staticmethod
    def _identity_key(camera_id: UUID, track: dict[str, Any]) -> str:
        person_id = track.get("person_id")
        if person_id:
            return f"person:{person_id}"
        return f"track:{camera_id}:{track['tracking_id']}"


live_visibility_service = LiveVisibilityService()
