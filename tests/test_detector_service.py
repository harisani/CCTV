import unittest
from types import SimpleNamespace

from app.detector.detector_service import DetectorService


class FakeTensor:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def cpu(self) -> "FakeTensor":
        return self

    def tolist(self) -> list[object]:
        return self.values


class FakeModel:
    def __init__(self, _: str) -> None:
        self.calls: list[dict[str, object]] = []

    def predict(self, **kwargs: object) -> list[object]:
        self.calls.append(kwargs)
        source = kwargs["source"]
        item_count = len(source) if isinstance(source, list) else 1
        return [
            SimpleNamespace(
                boxes=SimpleNamespace(
                    xyxy=FakeTensor([[10, 20, 110, 220]]),
                    conf=FakeTensor([0.91]),
                    cls=FakeTensor([0]),
                ),
                names={0: "person"},
            )
            for _ in range(item_count)
        ]


class FakeTorch:
    class cuda:
        @staticmethod
        def is_available() -> bool:
            return False


class TestSettings:
    yolo_model = "yolo11n.pt"
    yolo_device = "auto"
    confidence_threshold = 0.45
    yolo_image_size = 640
    yolo_max_detections = 100


class DetectorServiceTest(unittest.TestCase):
    def test_predict_returns_normalized_detection(self) -> None:
        service = DetectorService(TestSettings(), model_factory=FakeModel, torch_module=FakeTorch)
        detections = service.predict(frame="frame")
        self.assertEqual(service.device, "cpu")
        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].bbox, (10.0, 20.0, 110.0, 220.0))
        self.assertEqual(detections[0].centroid, (60.0, 120.0))
        self.assertEqual(detections[0].class_name, "person")

    def test_predict_batch_returns_one_result_per_frame(self) -> None:
        service = DetectorService(TestSettings(), model_factory=FakeModel, torch_module=FakeTorch)
        detections = service.predict_batch(["frame-1", "frame-2"])
        self.assertEqual(len(detections), 2)
        self.assertEqual(len(detections[0]), 1)


if __name__ == "__main__":
    unittest.main()
