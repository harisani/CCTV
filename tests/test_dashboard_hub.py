import asyncio
import logging
import unittest
from uuid import UUID

import pytest
from fastapi import status

import app.api.routes.dashboard_ws as dashboard_ws_module
from app.dashboard.realtime import DashboardHub


class FakeWebSocket:
    def __init__(self, query_params: dict[str, str] | None = None) -> None:
        self.accepted = False
        self.close_code: int | None = None
        self.messages: list[dict[str, object]] = []
        self.query_params = query_params or {}

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int, reason: str = "") -> None:
        self.close_code = code

    async def send_json(self, message: dict[str, object]) -> None:
        self.messages.append(message)


class DisconnectedWebSocket(FakeWebSocket):
    async def accept(self) -> None:
        raise RuntimeError("client disconnected")


class DashboardHubTest(unittest.IsolatedAsyncioTestCase):
    async def test_new_dashboard_receives_latest_visible_count(self) -> None:
        hub = DashboardHub()
        await hub.publish_occupancy({"total": 3})
        websocket = FakeWebSocket()

        await hub.connect(websocket)

        self.assertEqual(websocket.messages[0], {"type": "occupancy", "count": 3, "total": 3})

    async def test_disconnect_during_handshake_is_not_registered(self) -> None:
        hub = DashboardHub()
        websocket = DisconnectedWebSocket()

        self.assertFalse(await hub.connect(websocket))
        self.assertFalse(hub.has_subscribers("camera-a"))

    async def test_frames_only_reach_subscribed_dashboard(self) -> None:
        hub = DashboardHub()
        first = FakeWebSocket()
        second = FakeWebSocket()
        await hub.connect(first)
        await hub.connect(second)
        await hub.subscribe(first, ["camera-a"])
        await hub.subscribe(second, ["camera-b"])

        await hub.publish_frame(
            camera_id="camera-a",
            jpeg_bytes=b"jpeg",
            width=640,
            height=360,
            tracks=[],
        )

        self.assertEqual(first.messages[-1]["type"], "frame")
        self.assertNotEqual(second.messages[-1]["type"], "frame")

    async def test_subscription_is_limited_to_sixteen_cameras(self) -> None:
        hub = DashboardHub()
        websocket = FakeWebSocket()
        await hub.connect(websocket)
        with self.assertRaises(ValueError):
            await hub.subscribe(websocket, [f"camera-{index}" for index in range(17)])


def test_dashboard_websocket_binds_context_without_logging_token(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bound: list[str] = []
    reset: list[object] = []
    marker = object()

    monkeypatch.setattr(
        dashboard_ws_module,
        "bind_correlation_id",
        lambda value: bound.append(value) or marker,
    )
    monkeypatch.setattr(
        dashboard_ws_module,
        "reset_correlation_id",
        lambda token: reset.append(token),
    )
    websocket = FakeWebSocket(query_params={"token": "secret-websocket-token"})

    with caplog.at_level(logging.INFO):
        asyncio.run(dashboard_ws_module.dashboard_websocket(websocket))

    UUID(bound[0])
    assert reset == [marker]
    assert websocket.close_code == status.WS_1008_POLICY_VIOLATION
    assert "secret-websocket-token" not in caplog.text


if __name__ == "__main__":
    unittest.main()
