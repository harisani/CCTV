import logging
from typing import Any
from uuid import UUID, uuid4

import jwt
from fastapi import WebSocket, WebSocketDisconnect, status

from app.api.request_context import bind_correlation_id, reset_correlation_id
from app.config.settings import get_settings
from app.dashboard.realtime import dashboard_hub
from app.database.session import SessionLocal
from app.models import User

logger = logging.getLogger(__name__)


async def dashboard_websocket(websocket: WebSocket) -> None:
    """Authenticate a JWT query parameter, then keep a dashboard socket open."""
    context_token = bind_correlation_id(str(uuid4()))
    try:
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
                user_id = str(user.id)
        except (jwt.PyJWTError, ValueError):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
            return

        if not await dashboard_hub.connect(websocket):
            return
        logger.info("Dashboard WebSocket connected", extra={"user_id": user_id})
        try:
            while True:
                message = await websocket.receive_json()
                if message.get("action") != "subscribe":
                    await websocket.send_json(
                        {"type": "error", "detail": "Unsupported WebSocket action"}
                    )
                    continue
                camera_ids = message.get("camera_ids")
                if not isinstance(camera_ids, list):
                    await websocket.send_json(
                        {"type": "error", "detail": "camera_ids must be a list"}
                    )
                    continue
                try:
                    await dashboard_hub.subscribe(websocket, camera_ids)
                except ValueError as error:
                    await websocket.send_json({"type": "error", "detail": str(error)})
        except WebSocketDisconnect:
            pass
        finally:
            dashboard_hub.disconnect(websocket)
            logger.info("Dashboard WebSocket disconnected", extra={"user_id": user_id})
    finally:
        reset_correlation_id(context_token)
