import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.calibration import CUSTOM_MARKER_TYPE, detect_scale_marker


def _synthetic_marker(side: int = 300) -> np.ndarray:
    marker = np.full((side, side, 3), 28, dtype=np.uint8)
    silver = (205, 205, 205)
    unit = side / 7

    def rect(x1: float, y1: float, x2: float, y2: float) -> None:
        cv2.rectangle(
            marker,
            (round(x1 * unit), round(y1 * unit)),
            (round(x2 * unit), round(y2 * unit)),
            silver,
            thickness=-1,
        )

    rect(1, 1, 2, 3)
    rect(2, 3, 5.25, 4)
    rect(4.5, 2, 6, 3)
    rect(5, 2, 6, 6)
    rect(4.5, 5, 6, 6)
    rect(1, 4, 2, 5)
    rect(2, 5, 3, 6)
    return marker


def _scene_with_marker() -> tuple[np.ndarray, np.ndarray]:
    scene = np.full((900, 1200, 3), 238, dtype=np.uint8)
    marker = _synthetic_marker()
    source = np.float32([[0, 0], [299, 0], [299, 299], [0, 299]])
    target = np.float32([[390, 250], [735, 285], [690, 660], [350, 610]])
    transform = cv2.getPerspectiveTransform(source, target)
    warped = cv2.warpPerspective(marker, transform, (1200, 900), borderValue=(238, 238, 238))
    mask = cv2.warpPerspective(np.full((300, 300), 255, dtype=np.uint8), transform, (1200, 900))
    scene[mask > 0] = warped[mask > 0]
    return cv2.cvtColor(scene, cv2.COLOR_BGR2RGB), target


def test_detects_custom_50mm_marker_and_returns_area_scale():
    scene, target = _scene_with_marker()

    result = detect_scale_marker(scene)

    expected_area = abs(cv2.contourArea(target))
    expected_mm_per_px = 50.0 / np.sqrt(expected_area)
    assert result.detected
    assert result.usable
    assert result.marker_type == CUSTOM_MARKER_TYPE
    assert result.pattern_score >= 0.78
    assert abs(result.mm_per_px - expected_mm_per_px) / expected_mm_per_px < 0.06


def test_rejects_plain_dark_quadrilateral_without_marker_signature():
    scene = np.full((800, 1000, 3), 235, dtype=np.uint8)
    cv2.rectangle(scene, (280, 180), (650, 570), (25, 25, 25), thickness=-1)

    result = detect_scale_marker(cv2.cvtColor(scene, cv2.COLOR_BGR2RGB))

    assert not result.detected
    assert result.status in {"pattern_mismatch", "not_found"}


def test_legacy_aruco_marker_remains_supported():
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
    # ID 23 is visually the same family as the supplied physical model and is
    # intentionally classified as the project marker. ID 42 exercises fallback.
    marker = cv2.aruco.generateImageMarker(dictionary, 42, 320)
    scene = np.full((700, 900), 255, dtype=np.uint8)
    scene[180:500, 290:610] = marker
    rgb = cv2.cvtColor(scene, cv2.COLOR_GRAY2RGB)

    result = detect_scale_marker(rgb)

    assert result.detected
    assert result.usable
    assert result.marker_type == "aruco"
    assert result.marker_id == 42
