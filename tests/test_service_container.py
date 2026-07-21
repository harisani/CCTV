import unittest

from app.services.container import ServiceContainer


class TestSettings:
    yolo_model = "yolo11n.pt"
    yolo_device = "cpu"
    confidence_threshold = 0.45
    yolo_image_size = 640
    yolo_max_detections = 100
    yolo_half_precision = True
    bytetrack_frame_rate = 10
    bytetrack_track_high_threshold = 0.5
    bytetrack_track_low_threshold = 0.1
    bytetrack_new_track_threshold = 0.6
    bytetrack_track_buffer = 30
    bytetrack_match_threshold = 0.8
    bytetrack_history_size = 30
    bytetrack_direction_min_pixels = 3.0
    bytetrack_max_inactive_frames = 300
    crossing_line_id = "door"
    crossing_line_type = "horizontal"
    crossing_line_position = 100.0
    crossing_enter_direction = "down"
    crossing_polygon_points = ""
    crossing_max_inactive_frames = 300
    reid_model = "osnet_x1_0"
    reid_device = "cpu"
    reid_image_width = 128
    reid_image_height = 256
    reid_embedding_dimension = 512
    reid_similarity_threshold = 0.75
    storage_path = "storage"
    snapshot_jpeg_quality = 95
    camera_read_fps = 10.0
    camera_frame_width = 1280
    camera_frame_height = 720
    camera_reconnect_delay_seconds = 3.0


class ServiceContainerTest(unittest.TestCase):
    def test_reuses_stateless_services_and_creates_isolated_camera_readers(self) -> None:
        container = ServiceContainer(TestSettings())

        self.assertIs(container.detector, container.detector)
        self.assertIs(container.tracker, container.tracker)
        self.assertIsNot(container.camera("one", "rtsp://one"), container.camera("two", "rtsp://two"))


if __name__ == "__main__":
    unittest.main()
