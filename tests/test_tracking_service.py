import unittest

import numpy as np

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
    def test_tracker_input_supports_boolean_slicing_and_xywh(self) -> None:
        service = TrackingService(TestSettings())
        detection = Detection((10, 20, 50, 100), 0.9, 0, "person", (30, 60))
        results = service._to_tracker_input([detection])
        selected = results[np.asarray([True])]

        self.assertEqual(selected.xywh.tolist(), [[30.0, 60.0, 40.0, 80.0]])
        self.assertAlmostEqual(selected.conf.tolist()[0], 0.9, places=5)

    def test_supports_new_bytetrack_constructor_without_frame_rate(self) -> None:
        class NewByteTracker:
            def __init__(self, arguments: object) -> None:
                self.arguments = arguments

        arguments = object()
        tracker = TrackingService._instantiate_bytetracker(
            NewByteTracker, arguments, 10
        )
        self.assertIs(tracker.arguments, arguments)

    def test_supports_legacy_bytetrack_constructor_with_frame_rate(self) -> None:
        class LegacyByteTracker:
            def __init__(self, arguments: object, frame_rate: int = 30) -> None:
                self.arguments = arguments
                self.frame_rate = frame_rate

        tracker = TrackingService._instantiate_bytetracker(
            LegacyByteTracker, object(), 12
        )
        self.assertEqual(tracker.frame_rate, 12)

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
