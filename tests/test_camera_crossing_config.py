import asyncio
import unittest

from pydantic import ValidationError

from app.api.schemas import CameraCrossingConfig
from app.app import create_app
from app.services.crossing_service import CrossingService, CrossingType, VirtualLineConfig
from app.tracker import TrackedDetection


def track(track_id: int, x: float, y: float) -> TrackedDetection:
    return TrackedDetection(
        track_id,
        (x - 10, y - 20, x + 10, y + 20),
        0.95,
        0,
        "person",
        (x, y),
        "down",
        ((x, y),),
    )


class CameraCrossingConfigTest(unittest.TestCase):
    def test_browser_preflight_allows_crossing_config_put(self) -> None:
        async def preflight() -> list[dict]:
            messages: list[dict] = []
            request_sent = False

            async def receive() -> dict:
                nonlocal request_sent
                if request_sent:
                    return {"type": "http.disconnect"}
                request_sent = True
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message: dict) -> None:
                messages.append(message)

            await create_app()(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "OPTIONS",
                    "scheme": "http",
                    "path": "/api/v1/camera/00000000-0000-0000-0000-000000000000/crossing-config",
                    "raw_path": b"/api/v1/camera/00000000-0000-0000-0000-000000000000/crossing-config",
                    "query_string": b"",
                    "headers": [
                        (b"origin", b"http://localhost:5173"),
                        (b"access-control-request-method", b"PUT"),
                        (b"access-control-request-headers", b"authorization,content-type"),
                    ],
                    "client": ("127.0.0.1", 12345),
                    "server": ("testserver", 80),
                    "root_path": "",
                },
                receive,
                send,
            )
            return messages

        response_start = next(
            message for message in asyncio.run(preflight()) if message["type"] == "http.response.start"
        )
        response_headers = {
            key.decode("latin-1"): value.decode("latin-1") for key, value in response_start["headers"]
        }

        self.assertEqual(response_start["status"], 200)
        self.assertIn("PUT", response_headers["access-control-allow-methods"])

    def test_normalized_horizontal_line_scales_to_current_frame(self) -> None:
        config = VirtualLineConfig.from_mapping(
            {
                "line_id": "lobby-door",
                "line_type": "horizontal",
                "position": 0.5,
                "enter_direction": "down",
                "polygon_points": [],
                "enabled": True,
            }
        )
        service = CrossingService(config)
        service.set_frame_size(1280, 720)

        self.assertEqual(service.process([track(7, 400, 300)]), [])
        events = service.process([track(7, 400, 420)])

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, CrossingType.ENTER)
        self.assertEqual(events[0].line_id, "lobby-door")

    def test_disabled_polygon_can_be_saved_without_points(self) -> None:
        payload = CameraCrossingConfig(
            enabled=False,
            line_id="disabled-area",
            line_type="polygon",
            polygon_points=[],
        )
        service = CrossingService(VirtualLineConfig.from_mapping(payload.model_dump()))
        service.set_frame_size(640, 480)

        self.assertEqual(service.process([track(1, 20, 20)]), [])

    def test_active_polygon_requires_three_points(self) -> None:
        with self.assertRaises(ValidationError):
            CameraCrossingConfig(
                enabled=True,
                line_id="area",
                line_type="polygon",
                polygon_points=[{"x": 0.1, "y": 0.1}, {"x": 0.8, "y": 0.1}],
            )

    def test_direction_must_match_line_orientation(self) -> None:
        with self.assertRaises(ValidationError):
            CameraCrossingConfig(
                line_id="door",
                line_type="vertical",
                position=0.4,
                enter_direction="down",
            )


if __name__ == "__main__":
    unittest.main()
