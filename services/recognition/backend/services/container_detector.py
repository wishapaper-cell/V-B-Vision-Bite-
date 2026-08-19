from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from backend.services.calibration import ScaleMetadata

try:
    import cv2
except Exception:  # pragma: no cover - exercised only in minimal runtimes.
    cv2 = None


@dataclass(frozen=True)
class ContainerObservation:
    container_id: str = "container_none"
    type: str = "none"
    bbox: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    polygon: list[list[int]] = field(default_factory=list)
    confidence: float = 0.0
    area_px: float = 0.0
    area_cm2: float = 0.0
    fill_ratio: float = 0.0
    depth_model: str = "none"


def detect_container(rgb: np.ndarray, scale: ScaleMetadata | None = None) -> ContainerObservation:
    if rgb.size == 0:
        return ContainerObservation()
    if cv2 is None:
        return ContainerObservation()
    height, width = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 70, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    frame_area = max(1, width * height)
    best = ContainerObservation()

    for contour in contours[:220]:
        area = float(abs(cv2.contourArea(contour)))
        if area < frame_area * 0.035 or area > frame_area * 0.86:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if w <= 0 or h <= 0:
            continue
        extent = area / max(w * h, 1)
        aspect = w / max(h, 1)
        polygon = _simplify_contour(contour)
        container_type = "unknown"
        confidence = 0.22
        depth_model = "surface"

        if len(contour) >= 5:
            (_, _), (major, minor), _ = cv2.fitEllipse(contour)
            ellipse_ratio = min(major, minor) / max(major, minor, 1)
            if 0.38 <= ellipse_ratio <= 1.0 and 0.28 <= extent <= 0.88:
                container_type = "plate" if ellipse_ratio > 0.72 else "bowl"
                confidence = min(0.82, 0.30 + ellipse_ratio * 0.32 + min(area / frame_area, 0.34) * 0.85)
                depth_model = "shallow" if container_type == "plate" else "bowl"

        approx = cv2.approxPolyDP(contour, 0.035 * cv2.arcLength(contour, True), True)
        if len(approx) == 4 and 0.45 <= aspect <= 2.4 and extent > 0.36:
            box_conf = min(0.78, 0.28 + extent * 0.38 + min(area / frame_area, 0.32) * 0.80)
            if box_conf > confidence:
                container_type = "box"
                confidence = box_conf
                depth_model = "box"
                polygon = _simplify_contour(approx)

        if confidence > best.confidence:
            area_cm2 = area * scale.mm_per_px * scale.mm_per_px / 100.0 if scale and scale.usable else 0.0
            best = ContainerObservation(
                container_id="container_1",
                type=container_type,
                bbox=[int(x), int(y), int(x + w), int(y + h)],
                polygon=polygon,
                confidence=round(float(confidence), 2),
                area_px=round(area, 1),
                area_cm2=round(area_cm2, 2),
                fill_ratio=0.0,
                depth_model=depth_model,
            )
    return best


def _simplify_contour(contour: np.ndarray) -> list[list[int]]:
    epsilon = 0.018 * cv2.arcLength(contour, True)
    approx = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
    if len(approx) > 18:
        step = max(1, len(approx) // 18)
        approx = approx[::step]
    return [[int(x), int(y)] for x, y in approx.tolist()]
