from types import SimpleNamespace

import cv2
import numpy as np

from app.ai.body_analysis_service import BodyAnalysisEngine


def settings(**overrides):
    values = {
        "ppe_color_analysis_enabled": True,
        "ppe_color_min_saturation": 45,
        "ppe_analysis_enabled": True,
        "ppe_model_path": "",
        "body_min_aspect_ratio": 0.2,
        "body_max_aspect_ratio": 1.2,
        "reid_min_crop_width": 32,
        "reid_min_crop_height": 64,
        "reid_sharpness_reference": 150.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_missing_ppe_model_is_reported_without_fake_detection():
    image = np.zeros((200, 80, 3), dtype=np.uint8)
    image[:, :] = (255, 0, 0)
    engine = BodyAnalysisEngine(settings(), cv2_module=cv2)

    result = engine.analyze_ppe(image)

    assert result.model_available is False
    assert result.reason == "PPE_MODEL_NOT_CONFIGURED"
    assert result.detections == []
    assert result.observed_items == {}
    assert result.color_observation["dominant_color"] == "BLUE"


def test_body_quality_penalizes_invalid_aspect_ratio():
    image = np.zeros((100, 300, 3), dtype=np.uint8)
    engine = BodyAnalysisEngine(settings(), cv2_module=cv2)

    _quality, metrics = engine.body_quality(
        image, detector_confidence=0.9
    )

    assert metrics["aspect_ratio_score"] == 0.25


def test_canonical_ppe_class_does_not_infer_absence():
    assert BodyAnalysisEngine._canonical_item("HELMET_PRESENT") == (
        "HELMET",
        "PRESENT",
    )
    assert BodyAnalysisEngine._canonical_item("VEST_MISSING") == (
        "VEST",
        "MISSING",
    )
