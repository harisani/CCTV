from typing import Any

import jwt
from fastapi import WebSocket, WebSocketDisconnect, status

from app.config.settings import get_settings
from app.dashboard.realtime import dashboard_hub
from app.database.session import SessionLocal
from app.models import User
from uuid import UUID


async def dashboard_websocket(websocket: WebSocket) -> None:
    """Authenticate a JWT query parameter, then keep a dashboard socket open."""
    settings = get_settings()
    token = websocket.query_params.get("token")
    try:
        payload: dict[str, Any] = jwt.decode(
            token or "", settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        subject = UUID(payload.get("sub", ""))
        async with SessionLocal() as session:
            user = await session.get(User, subject)
            if user is None or not user.is_active or payload.get("ver") != user.token_version:
                raise jwt.InvalidTokenError("Invalid user session")
    except (jwt.PyJWTError, ValueError):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return

    if not await dashboard_hub.connect(websocket):
        return
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("action") != "subscribe":
                await websocket.send_json({"type": "error", "detail": "Unsupported WebSocket action"})
                continue
            camera_ids = message.get("camera_ids")
            if not isinstance(camera_ids, list):
                await websocket.send_json({"type": "error", "detail": "camera_ids must be a list"})
                continue
            try:
                await dashboard_hub.subscribe(websocket, camera_ids)
            except ValueError as error:
                await websocket.send_json({"type": "error", "detail": str(error)})
    except WebSocketDisconnect:
        pass
    finally:
        dashboard_hub.disconnect(websocket)
