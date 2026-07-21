"""Run with: python examples/detector_service_example.py /path/to/image.jpg"""

import sys

import cv2

from app.detector import DetectorService

if len(sys.argv) != 2:
    raise SystemExit("Usage: python examples/detector_service_example.py /path/to/image.jpg")

frame = cv2.imread(sys.argv[1])
if frame is None:
    raise SystemExit("Image could not be read")

detector = DetectorService()
for detection in detector.predict(frame):
    detector.draw_bbox(frame, detection)
    detector.draw_label(frame, detection)
    print(detection)

cv2.imwrite("detections.jpg", frame)
