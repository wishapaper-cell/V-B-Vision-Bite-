from __future__ import annotations

import math
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from backend.models.schemas import FoodTrack

try:
    import cv2
except Exception:  # pragma: no cover - exercised only in minimal runtimes.
    cv2 = None


@dataclass(frozen=True)
class UtensilObservation:
    utensil_id: str
    utensil_type: str
    bbox: list[int]
    confidence: float
    tip_point: list[float] | None = None
    motion_vector: list[float] = field(default_factory=lambda: [0.0, 0.0])
    contact_food_track_id: str | None = None
    carried_food_area_px: int = 0
    frame_width: int = 0
    frame_height: int = 0


CLASS_ID_TO_TYPE: dict[int, str] = {
    0: "chopsticks",
    1: "spoon",
    2: "fork",
    3: "knife",
}

_MODEL_DIR = Path(__file__).resolve().parents[2] / "models"
_DEFAULT_MODEL_PATH = _MODEL_DIR / "utensil_det_v1.pt"

_model: Any | None = None
_model_lock = threading.Lock()
_model_error: Exception | None = None


def _model_path() -> Path:
    configured = os.environ.get("UTENSIL_MODEL_PATH")
    return Path(configured).expanduser().resolve() if configured else _DEFAULT_MODEL_PATH


def _load_model() -> Any | None:
    global _model, _model_error
    if _model is not None:
        return _model
    if _model_error is not None:
        return None

    with _model_lock:
        if _model is not None:
            return _model
        path = _model_path()
        if not path.exists():
            _model_error = FileNotFoundError(f"餐具模型未找到: {path}")
            return None
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception as exc:  # pragma: no cover - runtime dependency path
            _model_error = exc
            return None
        try:
            _model = YOLO(str(path))
            _model.fuse()
        except Exception as exc:  # pragma: no cover
            _model_error = exc
            return None
    return _model


def detect_utensils(rgb: np.ndarray, foods: list[FoodTrack]) -> list[UtensilObservation]:
    """Detect utensils using the trained YOLO model.

    Falls back to an empty list if the model file is missing or ultralytics is
    not installed, so food-only analysis keeps working.
    """
    if rgb.size == 0:
        return []

    model = _load_model()
    if model is None:
        return []

    height, width = rgb.shape[:2]
    try:
        results = model.predict(rgb, imgsz=640, conf=0.25, verbose=False)
    except Exception:  # pragma: no cover
        return []

    result = results[0] if results else None
    if result is None:
        return []

    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []

    names = getattr(result, "names", {}) or {}
    observations: list[UtensilObservation] = []
    for idx, box in enumerate(boxes):
        xyxy = box.xyxy[0].tolist()
        cls_id = int(box.cls[0].item()) if getattr(box, "cls", None) is not None else -1
        confidence = float(box.conf[0].item()) if getattr(box, "conf", None) is not None else 0.0
        utensil_type = CLASS_ID_TO_TYPE.get(cls_id)
        if utensil_type is None:
            raw_label = str(names.get(cls_id, "")).lower()
            utensil_type = _label_to_type(raw_label)
            if utensil_type is None:
                continue

        x1 = int(max(0, xyxy[0]))
        y1 = int(max(0, xyxy[1]))
        x2 = int(min(width, xyxy[2]))
        y2 = int(min(height, xyxy[3]))
        if x2 <= x1 or y2 <= y1:
            continue

        bbox = [x1, y1, x2, y2]
        tip_point = _tip_point(bbox, utensil_type)
        contact_id, carried_area = _contact_food(bbox, tip_point, foods)
        observations.append(
            UtensilObservation(
                utensil_id=f"utensil_{idx + 1}",
                utensil_type=utensil_type,
                bbox=bbox,
                confidence=round(confidence, 2),
                tip_point=tip_point,
                contact_food_track_id=contact_id,
                carried_food_area_px=carried_area,
                frame_width=width,
                frame_height=height,
            )
        )

    observations.sort(key=lambda item: item.confidence, reverse=True)
    return observations[:4]


def _label_to_type(label: str) -> str | None:
    label = label.strip().lower()
    mapping = {
        "chopsticks": "chopsticks",
        "chopstick": "chopsticks",
        "spoon": "spoon",
        "fork": "fork",
        "knife": "knife",
    }
    return mapping.get(label)


def _tip_point(bbox: list[int], utensil_type: str) -> list[float]:
    x1, y1, x2, y2 = bbox
    if utensil_type in {"spoon", "fork", "knife"}:
        return [float((x1 + x2) / 2), float(y2)]
    # Chopsticks: tip is at the end of the long axis. We cannot tell thin end from
    # thick end from a bbox alone, so we pick the dominant-axis end; this is more
    # robust than always assuming bottom-right.
    width = max(1, x2 - x1)
    height = max(1, y2 - y1)
    if width >= height:
        return [float(x2), float((y1 + y2) / 2)]
    return [float((x1 + x2) / 2), float(y2)]


def _contact_food(bbox: list[int], tip_point: list[float] | None, foods: list[FoodTrack]) -> tuple[str | None, int]:
    ux1, uy1, ux2, uy2 = bbox
    utensil_area = max(1, (ux2 - ux1) * (uy2 - uy1))
    best_id: str | None = None
    best_score = 0.0
    for food in foods:
        fx1, fy1, fx2, fy2 = food.bbox
        ix1 = max(ux1, fx1)
        iy1 = max(uy1, fy1)
        ix2 = min(ux2, fx2)
        iy2 = min(uy2, fy2)
        overlap = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        overlap_ratio = overlap / max(1, (fx2 - fx1) * (fy2 - fy1))

        tip_distance_score = 0.0
        if tip_point is not None:
            tip_x, tip_y = tip_point
            nearest_x = max(fx1, min(tip_x, fx2))
            nearest_y = max(fy1, min(tip_y, fy2))
            distance = math.hypot(tip_x - nearest_x, tip_y - nearest_y)
            food_size = max(1, fx2 - fx1, fy2 - fy1)
            tip_distance_score = max(0.0, 1.0 - distance / (food_size * 0.6))

        if tip_point is not None:
            score = tip_distance_score * 0.7 + overlap_ratio * 0.3
        else:
            score = overlap_ratio
        if score > best_score and score > 0.35:
            best_score = score
            best_id = food.track_id
    carried_area = int(best_score * utensil_area) if best_id else 0
    return best_id, carried_area
