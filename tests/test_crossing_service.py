import unittest
from uuid import uuid4

from app.services import (
    CrossingService,
    CrossingType,
    MultiLineCrossingService,
    VirtualLineConfig,
)
from app.tracker import TrackedDetection


def track(track_id: int, centroid: tuple[float, float]) -> TrackedDetection:
    return TrackedDetection(track_id, (0, 0, 1, 1), 0.9, 0, "person", centroid, "unknown", ())


class CrossingServiceTest(unittest.TestCase):
    def test_same_track_can_enter_exit_enter_exit(self) -> None:
        service = CrossingService(
            VirtualLineConfig("door", "horizontal", 100, "down", event_cooldown_frames=0)
        )
        self.assertEqual(service.process([track(1, (50, 80))]), [])
        first_enter = service.process([track(1, (50, 120))])
        first_exit = service.process([track(1, (50, 80))])
        second_enter = service.process([track(1, (50, 120))])
        second_exit = service.process([track(1, (50, 80))])

        self.assertEqual(
            [first_enter[0].event_type, first_exit[0].event_type, second_enter[0].event_type, second_exit[0].event_type],
            [CrossingType.ENTER, CrossingType.EXIT, CrossingType.ENTER, CrossingType.EXIT],
        )

    def test_hysteresis_suppresses_jitter_on_the_line(self) -> None:
        service = CrossingService(
            VirtualLineConfig(
                "door",
                "vertical",
                500,
                "right",
                hysteresis_ratio=0.01,
                event_cooldown_frames=0,
            )
        )
        service.set_frame_size(1000, 1000)

        self.assertEqual(service.process([track(1, (480, 50))]), [])
        self.assertEqual(service.process([track(1, (497, 50))]), [])
        self.assertEqual(service.process([track(1, (503, 50))]), [])
        events = service.process([track(1, (520, 50))])

        self.assertEqual(events[0].event_type, CrossingType.ENTER)

    def test_vertical_exit(self) -> None:
        service = CrossingService(VirtualLineConfig("door", "vertical", 100, "right"))
        service.process([track(2, (120, 50))])
        events = service.process([track(2, (80, 50))])
        self.assertEqual(events[0].event_type, CrossingType.EXIT)

    def test_polygon_enter_then_exit(self) -> None:
        service = CrossingService(
            VirtualLineConfig(
                "room",
                "polygon",
                polygon_points=((0, 0), (100, 0), (100, 100), (0, 100)),
                event_cooldown_frames=0,
            )
        )
        service.process([track(3, (150, 50))])
        enter = service.process([track(3, (50, 50))])
        exit_event = service.process([track(3, (150, 50))])
        self.assertEqual(enter[0].event_type, CrossingType.ENTER)
        self.assertEqual(exit_event[0].event_type, CrossingType.EXIT)

    def test_multiple_lines_keep_independent_state_and_zone_direction(self) -> None:
        zone_a = uuid4()
        zone_b = uuid4()
        zone_c = uuid4()
        first_line_id = uuid4()
        second_line_id = uuid4()
        service = MultiLineCrossingService(
            (
                VirtualLineConfig(
                    "a-to-b",
                    "vertical",
                    100,
                    "right",
                    event_cooldown_frames=0,
                    virtual_line_id=first_line_id,
                    from_zone_id=zone_a,
                    to_zone_id=zone_b,
                ),
                VirtualLineConfig(
                    "b-to-c",
                    "vertical",
                    200,
                    "right",
                    event_cooldown_frames=0,
                    virtual_line_id=second_line_id,
                    from_zone_id=zone_b,
                    to_zone_id=zone_c,
                ),
            )
        )

        service.process([track(4, (50, 50))])
        first = service.process([track(4, (150, 50))])
        second = service.process([track(4, (250, 50))])

        self.assertEqual([event.line_id for event in first], ["a-to-b"])
        self.assertEqual(first[0].origin_zone_id, zone_a)
        self.assertEqual(first[0].destination_zone_id, zone_b)
        self.assertEqual(first[0].virtual_line_id, first_line_id)
        self.assertEqual([event.line_id for event in second], ["b-to-c"])
        self.assertEqual(second[0].origin_zone_id, zone_b)
        self.assertEqual(second[0].destination_zone_id, zone_c)


if __name__ == "__main__":
    unittest.main()
