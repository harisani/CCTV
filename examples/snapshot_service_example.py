"""Save an annotated ENTER snapshot from an image file."""

from datetime import UTC, datetime
from uuid import uuid4

import cv2

from app.services import CrossingEvent, CrossingType
from app.storage import SnapshotService
from app.tracker import TrackedDetection

frame = cv2.imread("frame.jpg")
if frame is None:
    raise SystemExit("Place an input image at frame.jpg")

person = TrackedDetection(
    tracking_id=7,
    bbox=(100, 80, 260, 420),
    confidence=0.93,
    class_id=0,
    class_name="person",
    centroid=(180, 250),
    direction="down",
    history=(),
)
event = CrossingEvent(uuid4(), CrossingType.ENTER, "main-door", 7, person.centroid, datetime.now(UTC))
result = SnapshotService().save(frame, event, person, camera_id="front-door")
print(result.image_path)
print(result.metadata_path)
