from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover - exercised only in minimal runtimes.
    cv2 = None


MARKER_SIZE_MM = 50.0
VALID_MARKER_IDS = {23, 42}
CUSTOM_MARKER_ID = 5001
CUSTOM_MARKER_TYPE = "adventurex_custom_50mm"
MIN_SCALE_CONFIDENCE = 0.55
MAX_DETECTION_DIMENSION = 1280
MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "reference_marker_v1.json"


@dataclass(frozen=True)
class ScaleMetadata:
    detected: bool = False
    marker_id: int | None = None
    marker_type: str = "none"
    marker_size_mm: float = MARKER_SIZE_MM
    corners_px: list[list[float]] = field(default_factory=list)
    edge_lengths_px: list[float] = field(default_factory=list)
    mm_per_px: float = 0.0
    px_per_mm: float = 0.0
    marker_area_px: float = 0.0
    marker_area_ratio: float = 0.0
    perspective_score: float = 0.0
    sharpness_score: float = 0.0
    pattern_score: float = 0.0
    confidence: float = 0.0
    status: str = "not_found"

    @property
    def usable(self) -> bool:
        return self.detected and self.confidence >= MIN_SCALE_CONFIDENCE and self.mm_per_px > 0


def detect_scale_marker(rgb: np.ndarray) -> ScaleMetadata:
    """Detect either the project 50 mm marker or the legacy ArUco marker.

    The custom marker is evaluated first because it is the physical reference used by
    the product. ArUco support remains as a backwards-compatible fallback.
    """
    if rgb.size == 0:
        return ScaleMetadata(status="empty_frame")
    if cv2 is None:
        return ScaleMetadata(status="opencv_unavailable")

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    custom = _detect_custom_marker(gray)
    if custom.detected:
        return custom
    aruco = _detect_aruco_marker(gray)
    if aruco.detected:
        return aruco
    if custom.status not in {"not_found", "pattern_mismatch"}:
        return custom
    return aruco if aruco.status != "not_found" else custom


def _detect_custom_marker(gray: np.ndarray) -> ScaleMetadata:
    model = _load_custom_model()
    signature = np.asarray(model.get("signature", []), dtype=np.float32)
    if signature.shape != (8, 8):
        return ScaleMetadata(status="custom_model_unavailable")

    detection_gray, resize_scale = _resize_for_detection(gray)
    frame_area_small = max(1, detection_gray.shape[0] * detection_gray.shape[1])
    kernel = np.ones((5, 5), dtype=np.uint8)
    best: tuple[float, np.ndarray, float] | None = None
    seen: set[tuple[int, int, int, int]] = set()

    # Multiple absolute thresholds make the black printed/3D-printed plate robust to
    # white-balance and exposure changes without making the appearance model lax.
    for threshold in (50, 70, 90, 110, 130, 150, 170):
        _, binary = cv2.threshold(detection_gray, threshold, 255, cv2.THRESH_BINARY_INV)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = float(cv2.contourArea(contour))
            area_ratio = area / frame_area_small
            if area_ratio < 0.00015 or area_ratio > 0.25:
                continue
            perimeter = float(cv2.arcLength(contour, True))
            quad = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
            if len(quad) != 4 or not cv2.isContourConvex(quad):
                continue
            points = quad.reshape(4, 2).astype(np.float32)
            edges = [_distance(points[i], points[(i + 1) % 4]) for i in range(4)]
            if min(edges) < 20 or min(edges) / max(edges) < 0.48:
                continue
            rect_w, rect_h = cv2.minAreaRect(contour)[1]
            if area / max(rect_w * rect_h, 1e-6) < 0.68:
                continue
            key = tuple(int(round(value / 4) * 4) for value in cv2.boundingRect(contour))
            if key in seen:
                continue
            seen.add(key)
            pattern_score, contrast = _custom_pattern_score(detection_gray, points, signature)
            rank_score = pattern_score + min(0.08, contrast / 1200.0)
            if best is None or rank_score > best[0]:
                best = (rank_score, points, pattern_score)

    min_pattern_score = float(model.get("min_pattern_score", 0.78))
    if best is None:
        return ScaleMetadata(status="not_found")
    _, points_small, pattern_score = best
    if pattern_score < min_pattern_score:
        return ScaleMetadata(pattern_score=round(pattern_score, 3), status="pattern_mismatch")

    points = _order_corners(points_small) / resize_scale
    return _metadata_from_corners(
        points,
        marker_id=int(model.get("marker_id", CUSTOM_MARKER_ID)),
        marker_type=str(model.get("marker_type", CUSTOM_MARKER_TYPE)),
        gray=gray,
        frame_area=max(1, gray.shape[0] * gray.shape[1]),
        pattern_score=pattern_score,
    )


def _detect_aruco_marker(gray: np.ndarray) -> ScaleMetadata:
    aruco = getattr(cv2, "aruco", None)
    if aruco is None:
        return ScaleMetadata(status="aruco_unavailable")
    try:
        dictionary = aruco.getPredefinedDictionary(aruco.DICT_5X5_100)
        parameters = aruco.DetectorParameters()
        if hasattr(aruco, "ArucoDetector"):
            corners, ids, _ = aruco.ArucoDetector(dictionary, parameters).detectMarkers(gray)
        else:
            corners, ids, _ = aruco.detectMarkers(gray, dictionary, parameters=parameters)
    except Exception:
        return ScaleMetadata(status="aruco_error")
    if ids is None or len(ids) == 0:
        return ScaleMetadata(status="not_found")

    candidates: list[ScaleMetadata] = []
    frame_area = max(1, gray.shape[0] * gray.shape[1])
    for raw_corners, raw_id in zip(corners, ids.flatten()):
        marker_id = int(raw_id)
        if marker_id not in VALID_MARKER_IDS:
            continue
        points = np.asarray(raw_corners, dtype=np.float32).reshape(-1, 2)
        if points.shape == (4, 2):
            candidates.append(_metadata_from_corners(points, marker_id, "aruco", gray, frame_area, 1.0))
    if not candidates:
        return ScaleMetadata(status="invalid_id")
    return max(candidates, key=lambda item: (item.confidence, item.marker_area_px))


def _metadata_from_corners(
    points: np.ndarray,
    marker_id: int | None,
    marker_type: str,
    gray: np.ndarray,
    frame_area: int,
    pattern_score: float,
) -> ScaleMetadata:
    points = _order_corners(points)
    edges = [_distance(points[i], points[(i + 1) % 4]) for i in range(4)]
    edge_px = float(np.mean(edges))
    if edge_px <= 1:
        return ScaleMetadata(marker_id=marker_id, marker_type=marker_type, status="too_small")

    area_px = float(abs(cv2.contourArea(points)))
    area_ratio = area_px / frame_area
    edge_ratio = min(edges) / max(max(edges), 1e-6)
    perspective_score = _clamp((edge_ratio - 0.42) / (0.90 - 0.42))
    area_score = _clamp(area_ratio / 0.015)
    sharpness_score = _marker_sharpness(gray, points)
    confidence = _clamp(
        pattern_score * 0.45 + area_score * 0.20 + perspective_score * 0.15 + sharpness_score * 0.20
    )

    status = "detected"
    if area_score < 0.12:
        status = "too_small"
    elif perspective_score < 0.08:
        status = "too_skewed"
    elif sharpness_score < 0.18:
        status = "too_blurry"

    # The square root of the projected quadrilateral area gives the equivalent
    # side length. It is less biased than averaging the four edges when the card
    # is viewed obliquely, and is exactly the scale needed by pixel-area based
    # food volume estimation near the reference plane.
    equivalent_edge_px = math.sqrt(max(area_px, 1e-6))
    mm_per_px = MARKER_SIZE_MM / equivalent_edge_px
    return ScaleMetadata(
        detected=True,
        marker_id=marker_id,
        marker_type=marker_type,
        marker_size_mm=MARKER_SIZE_MM,
        corners_px=[[round(float(x), 2), round(float(y), 2)] for x, y in points.tolist()],
        edge_lengths_px=[round(float(edge), 3) for edge in edges],
        mm_per_px=round(float(mm_per_px), 6),
        px_per_mm=round(float(1.0 / mm_per_px), 3),
        marker_area_px=round(area_px, 2),
        marker_area_ratio=round(area_ratio, 5),
        perspective_score=round(perspective_score, 3),
        sharpness_score=round(sharpness_score, 3),
        pattern_score=round(pattern_score, 3),
        confidence=round(confidence, 3),
        status=status,
    )


def _custom_pattern_score(gray: np.ndarray, points: np.ndarray, signature: np.ndarray) -> tuple[float, float]:
    size = 224
    destination = np.float32([[0, 0], [size - 1, 0], [size - 1, size - 1], [0, size - 1]])
    transform = cv2.getPerspectiveTransform(_order_corners(points), destination)
    warped = cv2.warpPerspective(gray, transform, (size, size))
    low = float(np.percentile(warped, 15))
    high = float(np.percentile(warped, 88))
    contrast = high - low
    if contrast < 18:
        return 0.0, contrast

    best = -1.0
    for rotation in range(4):
        rotated = np.rot90(warped, rotation)
        normalized = np.clip((rotated.astype(np.float32) - low) / max(contrast, 1e-6), 0, 1)
        feature = normalized.reshape(8, 28, 8, 28).mean(axis=(1, 3))
        score = _correlation(feature, signature)
        best = max(best, score)
    return _clamp(best), contrast


@lru_cache(maxsize=1)
def _load_custom_model() -> dict[str, object]:
    try:
        return json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _resize_for_detection(gray: np.ndarray) -> tuple[np.ndarray, float]:
    height, width = gray.shape[:2]
    scale = min(1.0, MAX_DETECTION_DIMENSION / max(height, width))
    if scale >= 1.0:
        return gray, 1.0
    return cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA), scale


def _order_corners(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    return np.float32(
        [points[np.argmin(sums)], points[np.argmin(differences)], points[np.argmax(sums)], points[np.argmax(differences)]]
    )


def _marker_sharpness(gray: np.ndarray, points: np.ndarray) -> float:
    x, y, w, h = cv2.boundingRect(points.astype(np.int32))
    pad = max(3, int(max(w, h) * 0.08))
    x1, y1 = max(0, x - pad), max(0, y - pad)
    x2, y2 = min(gray.shape[1], x + w + pad), min(gray.shape[0], y + h + pad)
    crop = gray[y1:y2, x1:x2]
    if crop.size == 0:
        return 0.0
    return _clamp(float(cv2.Laplacian(crop, cv2.CV_64F).var()) / 260.0)


def _correlation(left: np.ndarray, right: np.ndarray) -> float:
    left_flat = left.astype(np.float32).reshape(-1)
    right_flat = right.astype(np.float32).reshape(-1)
    left_flat -= float(left_flat.mean())
    right_flat -= float(right_flat.mean())
    denominator = float(np.linalg.norm(left_flat) * np.linalg.norm(right_flat))
    if denominator <= 1e-8:
        return 0.0
    return float(np.dot(left_flat, right_flat) / denominator)


def _distance(a: np.ndarray, b: np.ndarray) -> float:
    return float(math.hypot(float(a[0] - b[0]), float(a[1] - b[1])))


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))
