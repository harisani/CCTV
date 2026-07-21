import unittest

from app.services import CrossingService, CrossingType, VirtualLineConfig
from app.tracker import TrackedDetection


def track(track_id: int, centroid: tuple[float, float]) -> TrackedDetection:
    return TrackedDetection(track_id, (0, 0, 1, 1), 0.9, 0, "person", centroid, "unknown", ())


class CrossingServiceTest(unittest.TestCase):
    def test_horizontal_enter_and_duplicate_is_suppressed(self) -> None:
        service = CrossingService(VirtualLineConfig("door", "horizontal", 100, "down"))
        self.assertEqual(service.process([track(1, (50, 80))]), [])
        events = service.process([track(1, (50, 120))])
        self.assertEqual(events[0].event_type, CrossingType.ENTER)
        service.process([track(1, (50, 80))])  # EXIT may be emitted once.
        self.assertEqual(service.process([track(1, (50, 120))]), [])

    def test_vertical_exit(self) -> None:
        service = CrossingService(VirtualLineConfig("door", "vertical", 100, "right"))
        service.process([track(2, (120, 50))])
        events = service.process([track(2, (80, 50))])
        self.assertEqual(events[0].event_type, CrossingType.EXIT)

    def test_polygon_enter_then_exit(self) -> None:
        service = CrossingService(
            VirtualLineConfig("room", "polygon", polygon_points=((0, 0), (100, 0), (100, 100), (0, 100)))
        )
        service.process([track(3, (150, 50))])
        enter = service.process([track(3, (50, 50))])
        exit_event = service.process([track(3, (150, 50))])
        self.assertEqual(enter[0].event_type, CrossingType.ENTER)
        self.assertEqual(exit_event[0].event_type, CrossingType.EXIT)


if __name__ == "__main__":
    unittest.main()
