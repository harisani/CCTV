"""WebSocket hub used by the realtime pipeline and the React dashboard."""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import WebSocket

MAX_CAMERA_SUBSCRIPTIONS = 16


class DashboardHub:
    """Fan out live frames, tracks, events, and occupancy to dashboard clients."""

    def __init__(self) -> None:
        self._connections: dict[WebSocket, set[str]] = {}
        self._logger = logging.getLogger(__name__)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[websocket] = set()
        self._logger.info("Dashboard connected; clients=%s", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.pop(websocket, None)
        self._logger.info("Dashboard disconnected; clients=%s", len(self._connections))

    async def subscribe(self, websocket: WebSocket, camera_ids: list[str]) -> set[str]:
        """Replace a client's camera subscription with at most sixteen unique IDs."""
        if websocket not in self._connections:
            raise ValueError("WebSocket is not connected")
        normalized = {str(camera_id).strip() for camera_id in camera_ids if str(camera_id).strip()}
        if len(normalized) > MAX_CAMERA_SUBSCRIPTIONS:
            raise ValueError(f"A dashboard may subscribe to at most {MAX_CAMERA_SUBSCRIPTIONS} cameras")
        self._connections[websocket] = normalized
        await websocket.send_json({"type": "subscription", "camera_ids": sorted(normalized)})
        return normalized

    async def publish(self, message: dict[str, Any], *, camera_id: str | None = None) -> None:
        """Publish globally, or only to clients subscribed to one camera."""
        stale: list[WebSocket] = []
        for websocket, subscriptions in tuple(self._connections.items()):
            if camera_id is not None and camera_id not in subscriptions:
                continue
            try:
                await websocket.send_json(message)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)

    async def publish_frame(
        self,
        *,
        camera_id: str,
        jpeg_bytes: bytes,
        width: int,
        height: int,
        tracks: list[dict[str, Any]],
    ) -> None:
        await self.publish(
            {
                "type": "frame",
                "camera_id": camera_id,
                "image": base64.b64encode(jpeg_bytes).decode("ascii"),
                "width": width,
                "height": height,
                "tracks": tracks,
            },
            camera_id=camera_id,
        )

    async def publish_event(self, payload: dict[str, Any]) -> None:
        await self.publish({"type": "event", "payload": payload})

    async def publish_occupancy(self, count: int) -> None:
        await self.publish({"type": "occupancy", "count": count})


dashboard_hub = DashboardHub()
