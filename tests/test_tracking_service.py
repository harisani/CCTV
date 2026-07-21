import unittest

from app.detector import Detection
from app.tracker import TrackingService


class TestSettings:
    bytetrack_frame_rate = 10
    bytetrack_track_high_threshold = 0.5
    bytetrack_track_low_threshold = 0.1
    bytetrack_new_track_threshold = 0.6
    bytetrack_track_buffer = 30
    bytetrack_match_threshold = 0.8
    bytetrack_history_size = 3
    bytetrack_direction_min_pixels = 3.0
    bytetrack_max_inactive_frames = 10


class FakeTracker:
    def __init__(self) -> None:
        self.calls = 0

    def update(self, _input: object) -> list[list[float]]:
        self.calls += 1
        return [[100, 50, 200, 250, 42, 0.95, 0, 0]]


class TrackingServiceTest(unittest.TestCase):
    def test_assigns_tracking_id_and_maintains_history(self) -> None:
        fake_tracker = FakeTracker()
        service = TrackingService(
            TestSettings(),
            tracker_factory=lambda _arguments, _frame_rate: fake_tracker,
            array_factory=lambda values: values,
        )
        first = Detection((100, 50, 200, 250), 0.95, 0, "person", (150, 150))
        second = Detection((105, 60, 205, 260), 0.94, 0, "person", (155, 160))

        initial_tracks = service.update([first])
        next_tracks = service.update([second])

        self.assertEqual(initial_tracks[0].tracking_id, 42)
        self.assertEqual(initial_tracks[0].direction, "unknown")
        self.assertEqual(next_tracks[0].direction, "down")
        self.assertEqual(next_tracks[0].history, ((150, 150), (155, 160)))


if __name__ == "__main__":
    unittest.main()
