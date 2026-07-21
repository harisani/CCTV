import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.services import CrossingEvent, CrossingType
from app.storage import SnapshotService
from app.tracker import TrackedDetection


class TestSettings:
    def __init__(self, root: str) -> None:
        self.storage_path = root
        self.snapshot_jpeg_quality = 95


class FakeFrame:
    def copy(self) -> "FakeFrame":
        return FakeFrame()


class FakeCv2:
    IMWRITE_JPEG_QUALITY = 1
    FONT_HERSHEY_SIMPLEX = 0
    LINE_AA = 0

    @staticmethod
    def rectangle(*_args: object) -> None:
        pass

    @staticmethod
    def putText(*_args: object) -> None:
        pass

    @staticmethod
    def imwrite(path: str, *_args: object) -> bool:
        Path(path).write_bytes(b"fake-jpeg")
        return True


class SnapshotServiceTest(unittest.TestCase):
    def test_saves_dated_jpeg_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            occurred_at = datetime(2026, 7, 21, 10, 30, 40, tzinfo=UTC)
            event = CrossingEvent(uuid4(), CrossingType.ENTER, "door", 9, (50, 60), occurred_at)
            person = TrackedDetection(9, (10, 20, 90, 160), 0.9, 0, "person", (50, 60), "down", ())
            result = SnapshotService(TestSettings(directory), cv2_module=FakeCv2).save(
                FakeFrame(), event, person, camera_id="camera-a"
            )

            self.assertTrue(result.image_path.is_file())
            self.assertEqual(result.image_path.parent, Path(directory) / "2026" / "07" / "21")
            self.assertTrue(result.image_path.name.endswith(".jpg"))
            metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["event"]["event_type"], "ENTER")
            self.assertEqual(metadata["person"]["bbox"], [10, 20, 90, 160])


if __name__ == "__main__":
    unittest.main()
