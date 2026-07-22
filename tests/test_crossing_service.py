import unittest

from app.services import CrossingService, CrossingType, VirtualLineConfig
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


if __name__ == "__main__":
    unittest.main()
