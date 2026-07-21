"""Minimal detection-to-ByteTrack example; run after installing requirements.txt."""

from app.detector import Detection
from app.tracker import TrackingService

tracker = TrackingService()

# Normally this list comes from DetectorService.predict(frame).
first_frame = [
    Detection(
        bbox=(100.0, 50.0, 200.0, 250.0),
        confidence=0.95,
        class_id=0,
        class_name="person",
        centroid=(150.0, 150.0),
    )
]
second_frame = [
    Detection(
        bbox=(105.0, 60.0, 205.0, 260.0),
        confidence=0.94,
        class_id=0,
        class_name="person",
        centroid=(155.0, 160.0),
    )
]

print(tracker.update(first_frame))
print(tracker.update(second_frame))
