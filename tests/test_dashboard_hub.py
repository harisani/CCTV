import unittest

from app.dashboard.realtime import DashboardHub


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.messages: list[dict[str, object]] = []

    async def accept(self) -> None:
        self.accepted = True

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


if __name__ == "__main__":
    unittest.main()
