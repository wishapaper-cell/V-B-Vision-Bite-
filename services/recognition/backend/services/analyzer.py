from __future__ import annotations

import base64
import math
import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageFilter, ImageStat

from backend.models.schemas import FoodTrack, MeasurementQuality
from backend.services.calibration import ScaleMetadata, detect_scale_marker
from backend.services.container_detector import ContainerObservation, detect_container
from backend.services.nutrition import FoodProfile, cooking_method_for_key, nutrition_for_weight, profile_for_key
from backend.services.volume_estimator import estimate_weight


MODEL_DIR = Path(__file__).resolve().parents[2] / "models"
DEFAULT_MODEL_PATH = MODEL_DIR / "food_seg_v1.pt"

DESSERT_SNACK_KEYS = {
    "cake",
    "sponge_cake",
    "cake_roll",
    "pork_floss_pastry",
    "cream_cake",
    "egg_tart",
    "bread",
    "sweet_bread",
    "biscuit",
    "cheese_cracker",
    "oreo_cookie",
    "cookie",
    "cracker",
    "wafer",
    "chips",
    "chocolate",
    "candy",
    "packaged_snack",
}

YOLO_NON_FOOD_LABELS = {
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "airplane",
    "bus",
    "train",
    "truck",
    "boat",
    "traffic light",
    "fire hydrant",
    "stop sign",
    "parking meter",
    "bench",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "backpack",
    "umbrella",
    "handbag",
    "tie",
    "suitcase",
    "frisbee",
    "skis",
    "snowboard",
    "sports ball",
    "kite",
    "baseball bat",
    "baseball glove",
    "skateboard",
    "surfboard",
    "tennis racket",
    "bottle",
    "wine glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
    "chair",
    "couch",
    "potted plant",
    "bed",
    "dining table",
    "toilet",
    "tv",
    "laptop",
    "mouse",
    "remote",
    "keyboard",
    "cell phone",
    "microwave",
    "oven",
    "toaster",
    "sink",
    "refrigerator",
    "book",
    "clock",
    "vase",
    "scissors",
    "teddy bear",
    "hair drier",
    "toothbrush",
}

GENERIC_FOOD_LABEL_WORDS = {"food", "meal", "dish", "snack", "dessert", "ingredient"}

FOODSEG103_LABEL_MAP: dict[str, str] = {
    "candy": "candy", "egg tart": "egg_tart", "french fries": "chips",
    "chocolate": "chocolate", "biscuit": "biscuit", "popcorn": "packaged_snack",
    "pudding": "cake", "ice cream": "cream_cake", "cheese butter": "dried_tofu",
    "cake": "cake", "wine": "wine", "milkshake": "milkshake",
    "coffee": "coffee", "juice": "juice", "milk": "soybean",
    "tea": "tea", "almond": "packaged_snack", "red beans": "soybean",
    "cashew": "packaged_snack", "dried cranberries": "packaged_snack",
    "soy": "soybean", "walnut": "packaged_snack", "peanut": "packaged_snack",
    "egg": "egg", "apple": "apple", "date": "apple", "apricot": "apple",
    "avocado": "apple", "banana": "banana", "strawberry": "apple",
    "cherry": "apple", "blueberry": "apple", "raspberry": "apple",
    "mango": "watermelon", "olives": "packaged_snack", "peach": "apple",
    "lemon": "orange", "pear": "apple", "fig": "apple",
    "pineapple": "watermelon", "grape": "apple", "kiwi": "apple",
    "melon": "watermelon", "orange": "orange", "watermelon": "watermelon",
    "steak": "beef", "pork": "pork_lean", "chicken duck": "chicken",
    "sausage": "pork_belly", "fried meat": "pork_belly", "lamb": "lamb",
    "sauce": "sauce", "crab": "shrimp", "fish": "fish",
    "shellfish": "shrimp", "shrimp": "shrimp", "soup": "porridge",
    "bread": "bread", "corn": "corn", "hamburg": "bread",
    "pizza": "fried_rice", "hanamaki baozi": "steamed_bun",
    "wonton dumplings": "dumpling", "pasta": "wheat_noodles",
    "noodles": "wheat_noodles", "rice": "rice", "pie": "cake",
    "tofu": "tofu", "eggplant": "eggplant", "potato": "potato",
    "garlic": "onion", "cauliflower": "cauliflower", "tomato": "tomato",
    "kelp": "kelp", "seaweed": "seaweed",
    "spring onion": "onion", "rape": "bok_choy", "ginger": "ginger",
    "okra": "green_bean", "lettuce": "lettuce", "pumpkin": "pumpkin",
    "cucumber": "cucumber", "white radish": "bok_choy", "carrot": "carrot",
    "asparagus": "celery", "bamboo shoots": "bamboo_shoot",
    "broccoli": "broccoli", "celery stick": "celery",
    "cilantro mint": "bok_choy", "snow peas": "snow_pea",
    "cabbage": "cabbage", "bean sprouts": "bean_sprout",
    "onion": "onion", "pepper": "bell_pepper",
    "green beans": "green_bean", "French beans": "green_bean",
    "king oyster mushroom": "mushroom", "shiitake": "shiitake",
    "enoki mushroom": "enoki", "oyster mushroom": "mushroom",
    "white button mushroom": "mushroom", "salad": "stir_fried_greens",
    "other ingredients": "mixed_ingredients",
}


@dataclass
class DecodedFrame:
    image: Image.Image
    width: int
    height: int
    jpg_bytes: bytes


@dataclass
class FoodComponent:
    bbox: list[int]
    area_px: int
    polygon: list[list[int]]
    score: float
    crop: np.ndarray
    profile_hint: str = "unknown_food"
    profile_confidence: float = 0
    cooking_method: str = "unknown"
    cooking_confidence: float = 0
    wrapper_score: float = 0
    surface_score: float = 0
    skin_score: float = 0
    keyboard_score: float = 0


class FoodAnalyzer:
    """Frame analyzer with optional YOLOv11 and conservative OpenCV fallback."""

    _DESSERT_SNACK_KEYS = DESSERT_SNACK_KEYS

    def __init__(self) -> None:
        self.model = None
        self.model_name = "opencv-fallback"
        self.backend_name = "opencv-fallback"
        self._load_yolo_if_available()

    def _load_yolo_if_available(self) -> None:
        model_path = Path(os.getenv("FOOD_MODEL_PATH", str(DEFAULT_MODEL_PATH)))
        if not model_path.exists():
            return
        try:
            from ultralytics import YOLO  # type: ignore

            self.model = YOLO(str(model_path))
            self.model_name = model_path.name
            self.backend_name = "yolo11-seg"
        except Exception as exc:  # pragma: no cover - runtime dependency path
            self.model = None
            self.model_name = f"opencv-fallback ({exc.__class__.__name__})"
            self.backend_name = "opencv-fallback"

    @staticmethod
    def decode_data_url(data_url: str) -> DecodedFrame:
        header, _, payload = data_url.partition(",")
        if not payload:
            payload = header
        jpg_bytes = base64.b64decode(payload)
        from io import BytesIO

        image = Image.open(BytesIO(jpg_bytes)).convert("RGB")
        return DecodedFrame(image=image, width=image.width, height=image.height, jpg_bytes=jpg_bytes)

    def analyze(self, frame: DecodedFrame, frame_count: int, elapsed_seconds: float) -> tuple[list[FoodTrack], MeasurementQuality, str]:
        arr = np.array(frame.image)
        scale = detect_scale_marker(arr)
        container = detect_container(arr, scale)
        if self.model is not None:
            try:
                tracks = self._analyze_yolo(frame, scale, container)
                if tracks:
                    quality = self._quality(frame, tracks, frame_count, elapsed_seconds, scale, container)
                    return tracks, quality, self._guidance(quality, len(tracks))
            except Exception:
                pass

        tracks = self._analyze_fallback(frame, frame_count, scale, container)
        quality = self._quality(frame, tracks, frame_count, elapsed_seconds, scale, container)
        return tracks, quality, self._guidance(quality, len(tracks))

    def _analyze_yolo(self, frame: DecodedFrame, scale: ScaleMetadata | None = None, container: ContainerObservation | None = None) -> list[FoodTrack]:
        result = self.model.predict(np.array(frame.image), imgsz=640, conf=0.25, verbose=False)[0]
        tracks: list[FoodTrack] = []
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return tracks

        names = getattr(result, "names", {}) or {}
        masks = getattr(result, "masks", None)
        polygons: list[list[list[int]]] = []
        if masks is not None and getattr(masks, "xy", None) is not None:
            for poly in masks.xy:
                polygons.append(self._simplify_polygon([[int(x), int(y)] for x, y in poly]))

        for idx, box in enumerate(boxes):
            xyxy = box.xyxy[0].tolist()
            cls_id = int(box.cls[0].item()) if getattr(box, "cls", None) is not None else -1
            raw_label = str(names.get(cls_id, "food")).lower()
            confidence = float(box.conf[0].item()) if getattr(box, "conf", None) is not None else 0.5
            if self._yolo_label_is_non_food(raw_label):
                continue
            bbox = [int(max(0, xyxy[0])), int(max(0, xyxy[1])), int(min(frame.width, xyxy[2])), int(min(frame.height, xyxy[3]))]
            if self._region_is_unusable(bbox, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]), frame.width, frame.height):
                continue
            profile = self._profile_from_label(raw_label, idx)
            polygon = polygons[idx] if idx < len(polygons) and polygons[idx] else self._bbox_polygon(bbox)
            area_px = max(1, self._polygon_area(polygon) or (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
            crop = np.array(frame.image)[bbox[1] : bbox[3], bbox[0] : bbox[2]]
            region_mask = np.ones(crop.shape[:2], dtype=np.uint8) * 255 if crop.size else np.zeros((0, 0), dtype=np.uint8)
            surface_score, skin_score, keyboard_score = self._non_food_region_scores(crop, region_mask)
            if self._region_is_likely_background(crop, region_mask, surface_score, skin_score, keyboard_score, bbox, frame.width, frame.height, profile.key, confidence):
                continue
            cooking_method, cooking_confidence = (
                self._cooking_method_from_region(crop, region_mask)
                if crop.size
                else ("unknown", 0)
            )
            tracks.append(
                self._track_from_region(
                    f"food_{idx + 1}",
                    profile,
                    bbox,
                    polygon,
                    confidence,
                    frame.width,
                    frame.height,
                    area_px=area_px,
                    cooking_method=cooking_method,
                    cooking_confidence=cooking_confidence,
                    scale=scale,
                    container=container,
                )
            )
        return tracks[:6]

    def _profile_from_label(self, label: str, index: int) -> FoodProfile:
        key = FOODSEG103_LABEL_MAP.get(label)
        if key:
            return profile_for_key(key)
        lower = label.lower()
        key = FOODSEG103_LABEL_MAP.get(lower)
        if key:
            return profile_for_key(key)
        for needle, mapped_key in FOODSEG103_LABEL_MAP.items():
            if needle in lower:
                return profile_for_key(mapped_key)
        return profile_for_key("unknown_food")

    @staticmethod
    def _yolo_label_is_non_food(label: str) -> bool:
        label = label.strip().lower()
        if not label:
            return False
        if label in YOLO_NON_FOOD_LABELS:
            return True
        if any(word in label for word in GENERIC_FOOD_LABEL_WORDS):
            return False
        return any(label == blocked or blocked in label for blocked in YOLO_NON_FOOD_LABELS)

    def _analyze_fallback(self, frame: DecodedFrame, frame_count: int, scale: ScaleMetadata | None = None, container: ContainerObservation | None = None) -> list[FoodTrack]:
        arr = np.array(frame.image)
        height, width = arr.shape[:2]
        if self._looks_like_non_food_scene(arr):
            return []

        mask = self._food_candidate_mask(arr)
        fried_subject_mask = self._fried_subject_mask(arr)
        snack_package_mask = self._snack_package_mask(arr)
        masks = [mask]
        if fried_subject_mask.mean() > 0.035:
            masks.extend([fried_subject_mask, self._smooth_mask(mask | fried_subject_mask)])
        if snack_package_mask.mean() > 0.002:
            masks.extend([snack_package_mask, self._smooth_mask(mask | snack_package_mask)])
        components = self._merge_component_candidates(
            [
                component
                for candidate_mask in masks
                for component in self._food_components(arr, candidate_mask, min_area=max(300, int(width * height * 0.0035)))
            ],
            width,
            height,
        )
        if not components:
            return []

        food_score = self._food_likeness_score(arr, mask, components)
        if food_score < 0.18:
            return []

        subject_components = self._select_subject_components(components, width, height)
        if not subject_components:
            return []
        subject_components = self._suppress_snack_fragments(subject_components)

        tracks: list[FoodTrack] = []
        for idx, component in enumerate(subject_components[:4]):
            profile = profile_for_key(component.profile_hint) if component.profile_confidence >= 0.46 else self._profile_from_color(component.crop, idx)
            if profile.category in {"甜点", "零食"} and component.cooking_method == "deep_fried":
                component.cooking_method = "raw_light"
                component.cooking_confidence = max(component.cooking_confidence, 0.54)
            area_score = component.area_px / max(width * height, 1)
            profile_bonus = min(0.08, max(0.0, component.profile_confidence) * 0.11)
            uncertainty_penalty = 0.06 if profile.key == "unknown_food" else 0
            confidence = min(0.9, 0.34 + food_score * 0.34 + component.score * 0.22 + area_score * 1.1 + frame_count * 0.0015 + profile_bonus - uncertainty_penalty)
            if confidence < 0.38:
                continue
            tracks.append(
                self._track_from_region(
                    f"food_{idx + 1}",
                    profile,
                    component.bbox,
                    component.polygon,
                    confidence,
                    width,
                    height,
                    area_px=component.area_px,
                    cooking_method=component.cooking_method,
                    cooking_confidence=component.cooking_confidence,
                    scale=scale,
                    container=container,
                )
            )
        return tracks

    @staticmethod
    def _suppress_snack_fragments(components: list[FoodComponent]) -> list[FoodComponent]:
        if not components:
            return []
        snack_subjects = [item for item in components if item.profile_hint in DESSERT_SNACK_KEYS and item.profile_confidence >= 0.55]
        if not snack_subjects:
            return components
        largest_snack_area = max(item.area_px for item in snack_subjects)
        filtered: list[FoodComponent] = []
        for component in components:
            is_small_fried_fragment = (
                component.profile_hint not in DESSERT_SNACK_KEYS
                and component.cooking_method == "deep_fried"
                and component.area_px < largest_snack_area * 0.45
            )
            if is_small_fried_fragment:
                continue
            filtered.append(component)
        return filtered

    @staticmethod
    def _merge_component_candidates(components: list[FoodComponent], frame_width: int, frame_height: int) -> list[FoodComponent]:
        if not components:
            return []
        frame_area = max(1, frame_width * frame_height)
        ranked = sorted(
            components,
            key=lambda item: (
                max(item.profile_confidence, item.wrapper_score) + (0.24 if item.profile_hint in DESSERT_SNACK_KEYS else 0),
                item.score + item.wrapper_score * 0.20 - item.surface_score * 0.18 - item.skin_score * 0.14 - item.keyboard_score * 0.16,
                min(item.area_px / frame_area, 0.22),
            ),
            reverse=True,
        )
        merged: list[FoodComponent] = []
        for component in ranked:
            duplicate = False
            for kept in merged:
                if FoodAnalyzer._bbox_iou_raw(component.bbox, kept.bbox) >= 0.42 or FoodAnalyzer._bbox_containment(component.bbox, kept.bbox) >= 0.72:
                    duplicate = True
                    break
            if not duplicate:
                merged.append(component)
            if len(merged) >= 10:
                break
        merged.sort(
            key=lambda item: (
                item.score + max(item.profile_confidence, item.wrapper_score) * 0.24 - item.surface_score * 0.18 - item.skin_score * 0.14 - item.keyboard_score * 0.16,
                item.area_px / frame_area,
            ),
            reverse=True,
        )
        return merged

    @staticmethod
    def _food_candidate_mask(arr: np.ndarray) -> np.ndarray:
        hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        red = arr[:, :, 0].astype(np.int16)
        green = arr[:, :, 1].astype(np.int16)
        blue = arr[:, :, 2].astype(np.int16)
        channel_range = np.max(arr, axis=2).astype(np.int16) - np.min(arr, axis=2).astype(np.int16)

        green_food = (green > red + 14) & (green > blue + 10) & (green > 55) & (saturation > 38)
        warm_food = (red > 120) & (green > 68) & (blue < 172) & ((red - blue) > 22) & (saturation > 35)
        orange_food = (red > 145) & (green > 76) & (green < 198) & (blue < 140)
        pale_food = (red > 158) & (green > 142) & (blue > 110) & (value > 132) & (channel_range < 82)
        tomato_red = (red > 145) & (green < 128) & (blue < 125) & (saturation > 48)
        dark_food = (red > 68) & (red < 145) & (green > 38) & (green < 125) & (blue < 115) & (saturation > 38)

        very_low_texture = (saturation < 25) & (channel_range < 30)
        overexposed = value > 245
        mask = (green_food | warm_food | orange_food | pale_food | tomato_red | dark_food) & (value > 42)
        mask = mask & ~very_low_texture & ~overexposed
        mask = FoodAnalyzer._smooth_mask(mask)
        return FoodAnalyzer._shrink_overfull_mask(arr, mask)

    @staticmethod
    def _fried_subject_mask(arr: np.ndarray) -> np.ndarray:
        hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
        hue = hsv[:, :, 0]
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        lap = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
        edges = cv2.Canny(gray, 60, 140)
        golden = (hue >= 3) & (hue <= 30) & (saturation > 115) & (value > 45)
        textured = (lap > 4.5) | (edges > 0)
        mask = golden & textured
        kernel = np.ones((7, 7), dtype=np.uint8)
        closed = cv2.morphologyEx(mask.astype(np.uint8) * 255, cv2.MORPH_CLOSE, kernel, iterations=2)
        opened = cv2.morphologyEx(closed, cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8), iterations=1)
        return opened > 0

    @staticmethod
    def _snack_package_mask(arr: np.ndarray) -> np.ndarray:
        """Find high-evidence packaged snacks without letting the desk join in."""
        hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
        hue = hsv[:, :, 0]
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        red = arr[:, :, 0].astype(np.int16)
        green = arr[:, :, 1].astype(np.int16)
        blue = arr[:, :, 2].astype(np.int16)

        bright_blue = (hue >= 92) & (hue <= 132) & (saturation > 82) & (value > 62) & (blue > red + 24) & (blue > green + 8)
        saturated_green = (hue >= 38) & (hue <= 88) & (saturation > 76) & (value > 70) & (green > red + 4) & (green > blue - 18)
        label_red = (((hue <= 8) | (hue >= 170)) & (saturation > 82) & (value > 80) & (red > green + 22) & (red > blue + 22))
        seed = bright_blue | saturated_green | label_red
        if float(seed.mean()) < 0.001:
            return np.zeros(seed.shape, dtype=bool)

        closed = cv2.morphologyEx(seed.astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((5, 5), dtype=np.uint8), iterations=1)
        opened = cv2.morphologyEx(closed, cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8), iterations=1)
        return opened > 0

    @staticmethod
    def _shrink_overfull_mask(arr: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """Recover a food-sized blob when color thresholds cover the scene.

        Warm wrappers, paper bags, or a tinted dashboard screenshot can make
        almost every pixel look food-colored. In that case the right answer is
        not "one full-screen food", but a smaller high-saturation subject region.
        """
        height, width = mask.shape
        if float(mask.mean()) <= 0.54:
            return mask

        hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        sat_cutoff = max(135, int(np.percentile(saturation, 64)))
        strong = mask & (saturation >= sat_cutoff) & (value > 68)
        strong = FoodAnalyzer._smooth_mask(strong)

        if float(strong.mean()) > 0.48:
            row_density = strong.mean(axis=1)
            col_density = strong.mean(axis=0)
            y1, y2 = FoodAnalyzer._dense_span(row_density, min_density=0.22, pad=max(8, height // 24))
            x1, x2 = FoodAnalyzer._dense_span(col_density, min_density=0.16, pad=max(8, width // 24))
            if y2 - y1 >= height * 0.18 and x2 - x1 >= width * 0.18:
                limited = np.zeros_like(strong, dtype=bool)
                limited[y1:y2, x1:x2] = strong[y1:y2, x1:x2]
                strong = limited

        if float(strong.mean()) < 0.015 or float(strong.mean()) > 0.48:
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
            edges = cv2.Canny(gray, 50, 130)
            edge_band = cv2.dilate(edges, np.ones((7, 7), dtype=np.uint8), iterations=1) > 0
            textured = mask & edge_band & (saturation > 95)
            strong = FoodAnalyzer._smooth_mask(textured)

        if float(strong.mean()) < 0.01:
            return np.zeros_like(mask, dtype=bool)
        return strong

    @staticmethod
    def _dense_span(density: np.ndarray, min_density: float, pad: int) -> tuple[int, int]:
        active = density >= min_density
        if not active.any():
            return 0, len(density)
        best_start = 0
        best_end = 0
        start: int | None = None
        for idx, item in enumerate(active.tolist() + [False]):
            if item and start is None:
                start = idx
            elif not item and start is not None:
                if idx - start > best_end - best_start:
                    best_start, best_end = start, idx
                start = None
        return max(0, best_start - pad), min(len(density), best_end + pad)

    @staticmethod
    def _wrapper_evidence_score(crop: np.ndarray, component_mask: np.ndarray) -> float:
        if crop.size == 0:
            return 0.0
        selected = crop[component_mask > 0]
        if selected.size == 0:
            return 0.0
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        selected_hsv = hsv[component_mask > 0]
        hue = selected_hsv[:, 0]
        saturation = selected_hsv[:, 1]
        value = selected_hsv[:, 2]
        red = selected[:, 0].astype(np.int16)
        green = selected[:, 1].astype(np.int16)
        blue = selected[:, 2].astype(np.int16)
        mask_area = max(1, int((component_mask > 0).sum()))
        bbox_area = max(1, crop.shape[0] * crop.shape[1])
        fill_ratio = mask_area / bbox_area
        aspect = max(crop.shape[1] / max(crop.shape[0], 1), crop.shape[0] / max(crop.shape[1], 1))

        blue_wrapper = float(((hue >= 92) & (hue <= 132) & (saturation > 72) & (value > 45) & (blue > red + 22) & (blue > green + 6)).mean())
        green_label = float(((hue >= 35) & (hue <= 90) & (saturation > 70) & (value > 60)).mean())
        white_label = float(((saturation < 55) & (value > 160)).mean())
        dark_print = float(((value < 82) & (saturation < 120)).mean())
        red_label = float(((((hue <= 8) | (hue >= 170)) & (saturation > 78) & (value > 75))).mean())
        shape_bonus = 0.16 if aspect >= 1.55 or fill_ratio < 0.55 else 0.04
        score = blue_wrapper * 1.18 + green_label * 0.36 + white_label * 0.24 + dark_print * 0.18 + red_label * 0.22 + shape_bonus
        return float(max(0.0, min(1.0, score)))

    @staticmethod
    def _non_food_region_scores(crop: np.ndarray, component_mask: np.ndarray) -> tuple[float, float, float]:
        if crop.size == 0:
            return 0.0, 0.0, 0.0
        selected = crop[component_mask > 0]
        if selected.size == 0:
            return 0.0, 0.0, 0.0
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        selected_hsv = hsv[component_mask > 0]
        hue = selected_hsv[:, 0]
        saturation = selected_hsv[:, 1]
        value = selected_hsv[:, 2]
        red = selected[:, 0].astype(np.int16)
        green = selected[:, 1].astype(np.int16)
        blue = selected[:, 2].astype(np.int16)
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 55, 135)
        masked_edges = edges[component_mask > 0] > 0
        edge_density = float(masked_edges.mean()) if masked_edges.size else 0.0
        height, width = crop.shape[:2]
        aspect = max(width / max(height, 1), height / max(width, 1))

        wood_like = float(((hue >= 8) & (hue <= 30) & (saturation >= 34) & (saturation <= 165) & (value >= 82) & (value <= 238) & (red > green + 9) & (green > blue + 5)).mean())
        skin_like = float(((hue <= 23) & (saturation >= 22) & (saturation <= 145) & (value >= 78) & (red > green + 10) & (green > blue + 2)).mean())
        dark_keys = float(((value < 105) & (saturation < 95)).mean())

        lines = cv2.HoughLinesP(
            edges,
            1,
            np.pi / 180,
            threshold=max(18, min(width, height) // 5),
            minLineLength=max(20, width // 4),
            maxLineGap=8,
        )
        horizontal_lines = 0
        diagonal_lines = 0
        line_count = 0
        if lines is not None:
            for x1, y1, x2, y2 in FoodAnalyzer._iter_hough_lines(lines):
                length = math.hypot(float(x2 - x1), float(y2 - y1))
                if length < max(18, width * 0.18):
                    continue
                angle = abs(math.degrees(math.atan2(float(y2 - y1), float(x2 - x1))))
                line_count += 1
                if angle <= 24 or angle >= 156:
                    horizontal_lines += 1
                if 18 <= angle <= 68:
                    diagonal_lines += 1

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        rectangles = 0
        for contour in contours[:180]:
            area = cv2.contourArea(contour)
            if area < max(20, width * height * 0.002) or area > width * height * 0.30:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if w <= 0 or h <= 0:
                continue
            rect_aspect = w / h
            extent = area / max(w * h, 1)
            if 0.35 <= rect_aspect <= 6.5 and extent > 0.20:
                rectangles += 1

        wood_line_score = min(1.0, horizontal_lines / 14)
        surface_score = min(1.0, wood_like * 0.56 + wood_line_score * 0.34 + max(0.0, min(aspect - 1.3, 2.5) / 2.5) * 0.10)
        skin_score = min(1.0, skin_like * 0.72 + max(0.0, 0.13 - edge_density) * 1.25 + max(0.0, min(aspect - 1.6, 2.2) / 2.2) * 0.12)
        keyboard_score = min(1.0, dark_keys * 0.42 + min(rectangles / 10, 1.0) * 0.35 + min(line_count / 22, 1.0) * 0.23 + min(diagonal_lines / 8, 1.0) * 0.08)
        return float(surface_score), float(skin_score), float(keyboard_score)

    @staticmethod
    def _iter_hough_lines(lines: np.ndarray) -> np.ndarray:
        normalized = np.asarray(lines)
        if normalized.ndim == 3 and normalized.shape[1] == 1 and normalized.shape[2] == 4:
            normalized = normalized[:, 0, :]
        elif normalized.ndim == 1 and normalized.shape[0] == 4:
            normalized = normalized.reshape(1, 4)
        elif normalized.ndim != 2 or normalized.shape[-1] != 4:
            return np.empty((0, 4), dtype=np.int32)
        return normalized.reshape(-1, 4)

    @staticmethod
    def _region_is_likely_background(
        crop: np.ndarray,
        component_mask: np.ndarray,
        surface_score: float,
        skin_score: float,
        keyboard_score: float,
        bbox: list[int],
        frame_width: int,
        frame_height: int,
        profile_hint: str,
        profile_confidence: float,
    ) -> bool:
        if crop.size == 0:
            return True
        wrapper_score = FoodAnalyzer._wrapper_evidence_score(crop, component_mask)
        negative_score = max(surface_score, skin_score, keyboard_score)
        if profile_hint in DESSERT_SNACK_KEYS and (wrapper_score >= 0.46 or (profile_confidence >= 0.64 and negative_score < 0.62)):
            return False
        x1, y1, x2, y2 = bbox
        bbox_ratio = max(1, (x2 - x1) * (y2 - y1)) / max(1, frame_width * frame_height)
        center_y = (y1 + y2) / 2 / max(frame_height, 1)
        lower_large_surface = surface_score >= 0.72 and bbox_ratio >= 0.045 and center_y >= 0.56
        general_surface = surface_score >= 0.84 and bbox_ratio >= 0.035 and wrapper_score < 0.34
        skin_region = skin_score >= 0.74 and bbox_ratio >= 0.050 and wrapper_score < 0.38
        keyboard_region = keyboard_score >= 0.70 and wrapper_score < 0.38
        return lower_large_surface or general_surface or skin_region or keyboard_region

    def _food_components(self, arr: np.ndarray, mask: np.ndarray, min_area: int) -> list[FoodComponent]:
        height, width = mask.shape
        frame_area = max(width * height, 1)
        labels_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
        components: list[FoodComponent] = []
        for label in range(1, labels_count):
            x = int(stats[label, cv2.CC_STAT_LEFT])
            y = int(stats[label, cv2.CC_STAT_TOP])
            w = int(stats[label, cv2.CC_STAT_WIDTH])
            h = int(stats[label, cv2.CC_STAT_HEIGHT])
            area = int(stats[label, cv2.CC_STAT_AREA])
            bbox = [x, y, x + w, y + h]
            if area < min_area:
                continue

            component_mask = (labels[y : y + h, x : x + w] == label).astype(np.uint8) * 255
            crop = arr[y : y + h, x : x + w]
            refined = self._refine_oversized_component(arr, component_mask, bbox, area, width, height)
            if refined is not None:
                bbox, component_mask, crop, area = refined
                x, y, x2, y2 = bbox
                w, h = x2 - x, y2 - y
            if self._region_is_unusable(bbox, area, width, height):
                continue
            score = self._component_score(crop, component_mask, bbox, area, width, height)
            if score < 0.34:
                continue
            polygon = self._contour_polygon(component_mask, x, y) or self._bbox_polygon(bbox)
            profile_hint, profile_confidence = self._profile_hint_from_region(crop, component_mask)
            cooking_method, cooking_confidence = self._cooking_method_from_region(crop, component_mask)
            wrapper_score = self._wrapper_evidence_score(crop, component_mask)
            surface_score, skin_score, keyboard_score = self._non_food_region_scores(crop, component_mask)
            if self._region_is_likely_background(crop, component_mask, surface_score, skin_score, keyboard_score, bbox, width, height, profile_hint, profile_confidence):
                continue
            if wrapper_score >= 0.50 and profile_hint == "unknown_food":
                profile_hint = "packaged_snack"
                profile_confidence = max(profile_confidence, min(0.88, wrapper_score))
            if profile_hint in self._DESSERT_SNACK_KEYS and cooking_method == "deep_fried":
                cooking_method = "raw_light"
                cooking_confidence = max(cooking_confidence, 0.54)
            components.append(
                FoodComponent(
                    bbox=bbox,
                    area_px=area,
                    polygon=polygon,
                    score=score,
                    crop=crop,
                    profile_hint=profile_hint,
                    profile_confidence=profile_confidence,
                    cooking_method=cooking_method,
                    cooking_confidence=cooking_confidence,
                    wrapper_score=wrapper_score,
                    surface_score=surface_score,
                    skin_score=skin_score,
                    keyboard_score=keyboard_score,
                )
            )
        components.sort(key=lambda item: (item.score, item.area_px / frame_area), reverse=True)
        return components[:8]

    @staticmethod
    def _select_subject_components(components: list[FoodComponent], frame_width: int, frame_height: int) -> list[FoodComponent]:
        if not components:
            return []
        frame_area = max(1, frame_width * frame_height)
        ranked: list[tuple[float, FoodComponent]] = []
        for component in components:
            x1, y1, x2, y2 = component.bbox
            width = max(1, x2 - x1)
            height = max(1, y2 - y1)
            area_ratio = component.area_px / frame_area
            bbox_ratio = width * height / frame_area
            center_x = (x1 + x2) / 2 / max(frame_width, 1)
            center_y = (y1 + y2) / 2 / max(frame_height, 1)
            center_distance = math.hypot(center_x - 0.5, center_y - 0.5)
            centrality = max(0.0, 1.0 - center_distance * 1.55)
            mean_brightness = float(component.crop.mean() / 255) if component.crop.size else 0
            touches_right = x2 >= frame_width - 3
            touches_bottom = y2 >= frame_height - 3
            border_penalty = 0.28 if touches_right and touches_bottom else 0.12 if touches_right or touches_bottom else 0
            food_evidence = max(component.profile_confidence, component.wrapper_score)
            has_strong_evidence = component.profile_hint in DESSERT_SNACK_KEYS and food_evidence >= 0.50
            too_small = area_ratio < 0.010 and bbox_ratio < 0.026 and not has_strong_evidence
            likely_wrapper_or_table = mean_brightness > 0.72 and component.cooking_method not in {"deep_fried", "stir_fried", "pan_fried"}
            likely_table = touches_right and touches_bottom and center_y > 0.68 and component.cooking_method == "deep_fried"
            background_penalty = component.surface_score * 0.32 + component.skin_score * 0.24 + component.keyboard_score * 0.24
            if too_small or likely_wrapper_or_table:
                continue
            if likely_table:
                continue
            if background_penalty >= 0.52 and food_evidence < 0.62:
                continue
            area_term = min(area_ratio / (0.105 if has_strong_evidence else 0.16), 1.0)
            subject_score = (
                component.score * 0.36
                + area_term * 0.23
                + centrality * 0.14
                + component.cooking_confidence * 0.04
                + food_evidence * 0.23
                + (0.08 if component.wrapper_score >= 0.44 else 0)
                - border_penalty
                - background_penalty
            )
            ranked.append((subject_score, component))

        if not ranked:
            return []
        ranked.sort(key=lambda item: item[0], reverse=True)
        best_score = ranked[0][0]
        best_area = ranked[0][1].area_px
        selected_components: list[FoodComponent] = []
        for score, component in ranked:
            area_ratio_to_best = component.area_px / max(best_area, 1)
            strong_food = component.profile_hint in DESSERT_SNACK_KEYS and max(component.profile_confidence, component.wrapper_score) >= 0.55
            enough_area = area_ratio_to_best >= 0.16 or strong_food
            if score >= max(0.36, best_score * 0.58) and enough_area:
                selected_components.append(component)
        return selected_components[:3]

    @staticmethod
    def _refine_oversized_component(
        arr: np.ndarray,
        component_mask: np.ndarray,
        bbox: list[int],
        area: int,
        frame_width: int,
        frame_height: int,
    ) -> tuple[list[int], np.ndarray, np.ndarray, int] | None:
        x1, y1, x2, y2 = bbox
        width = max(1, x2 - x1)
        height = max(1, y2 - y1)
        frame_area = max(1, frame_width * frame_height)
        bbox_ratio = width * height / frame_area
        area_ratio = area / frame_area
        if bbox_ratio <= 0.52 and area_ratio <= 0.36:
            return None

        crop = arr[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        mask_bool = component_mask > 0
        sat_values = saturation[mask_bool]
        if sat_values.size == 0:
            return None
        cutoff = max(145, int(np.percentile(sat_values, 58)))
        subject = mask_bool & (saturation >= cutoff) & (value > 70)
        if float(subject.mean()) < 0.03:
            cutoff = max(115, int(np.percentile(sat_values, 45)))
            subject = mask_bool & (saturation >= cutoff) & (value > 65)

        if float(subject.mean()) < 0.03:
            return None

        row_density = subject.mean(axis=1)
        col_density = subject.mean(axis=0)
        row_threshold = min(0.30, max(0.12, float(np.percentile(row_density[row_density > 0], 24)) if (row_density > 0).any() else 0.12))
        col_threshold = min(0.24, max(0.08, float(np.percentile(col_density[col_density > 0], 18)) if (col_density > 0).any() else 0.08))
        local_y1, local_y2 = FoodAnalyzer._dense_span(row_density, row_threshold, pad=max(6, height // 18))
        local_x1, local_x2 = FoodAnalyzer._dense_span(col_density, col_threshold, pad=max(6, width // 18))
        if local_y2 - local_y1 < frame_height * 0.12 or local_x2 - local_x1 < frame_width * 0.12:
            ys, xs = np.where(subject)
            if len(xs) == 0 or len(ys) == 0:
                return None
            local_x1, local_x2 = int(np.percentile(xs, 2)), int(np.percentile(xs, 98)) + 1
            local_y1, local_y2 = int(np.percentile(ys, 2)), int(np.percentile(ys, 98)) + 1
            pad_x = max(8, width // 22)
            pad_y = max(8, height // 22)
            local_x1, local_x2 = max(0, local_x1 - pad_x), min(width, local_x2 + pad_x)
            local_y1, local_y2 = max(0, local_y1 - pad_y), min(height, local_y2 + pad_y)

        # The high-saturation subject can fragment into crumbs on fried or
        # breaded foods. Use it to locate a food-sized window, then keep the
        # original food-color pixels inside that window for area estimation.
        window_mask = np.zeros_like(mask_bool, dtype=bool)
        window_mask[local_y1:local_y2, local_x1:local_x2] = mask_bool[local_y1:local_y2, local_x1:local_x2]
        window_mask = FoodAnalyzer._smooth_mask(window_mask)
        ys, xs = np.where(window_mask)
        if len(xs) == 0 or len(ys) == 0:
            return None
        rx = int(xs.min())
        ry = int(ys.min())
        rw = int(xs.max() - rx + 1)
        rh = int(ys.max() - ry + 1)
        refined_area = int(window_mask.sum())
        if refined_area < max(300, int(frame_area * 0.003)):
            return None
        global_bbox = [x1 + rx, y1 + ry, x1 + rx + rw, y1 + ry + rh]
        refined_mask = window_mask[ry : ry + rh, rx : rx + rw].astype(np.uint8) * 255
        refined_crop = arr[global_bbox[1] : global_bbox[3], global_bbox[0] : global_bbox[2]]
        return global_bbox, refined_mask, refined_crop, refined_area

    @staticmethod
    def _region_is_unusable(bbox: list[int], area: int, frame_width: int, frame_height: int) -> bool:
        x1, y1, x2, y2 = bbox
        width = max(1, x2 - x1)
        height = max(1, y2 - y1)
        frame_area = max(1, frame_width * frame_height)
        area_ratio = area / frame_area
        bbox_ratio = (width * height) / frame_area
        touches = sum([x1 <= 2, y1 <= 2, x2 >= frame_width - 2, y2 >= frame_height - 2])
        if area_ratio > 0.36 or bbox_ratio > 0.52:
            return True
        if (width / max(frame_width, 1) > 0.94 or height / max(frame_height, 1) > 0.94) and touches >= 1:
            return True
        if touches >= 2 and bbox_ratio > 0.24:
            return True
        aspect = width / height
        if aspect > 8.0 or aspect < 0.12:
            return True
        return False

    @staticmethod
    def _bbox_iou_raw(a: list[int], b: list[int]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        intersection = iw * ih
        union = max(1, (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection)
        return intersection / union

    @staticmethod
    def _bbox_containment(a: list[int], b: list[int]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        smaller = max(1, min((ax2 - ax1) * (ay2 - ay1), (bx2 - bx1) * (by2 - by1)))
        return intersection / smaller

    @staticmethod
    def _component_score(crop: np.ndarray, component_mask: np.ndarray, bbox: list[int], area: int, frame_width: int, frame_height: int) -> float:
        if crop.size == 0:
            return 0
        selected = crop[component_mask > 0]
        if selected.size == 0:
            return 0
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        selected_hsv = hsv[component_mask > 0]
        saturation_mean = float(selected_hsv[:, 1].mean() / 255)
        value_mean = float(selected_hsv[:, 2].mean() / 255)
        color_std = float(np.std(selected, axis=0).mean() / 64)
        x1, y1, x2, y2 = bbox
        bbox_area = max(1, (x2 - x1) * (y2 - y1))
        fill_ratio = area / bbox_area
        frame_center_x = frame_width / 2
        frame_center_y = frame_height / 2
        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2
        distance = math.hypot((center_x - frame_center_x) / frame_width, (center_y - frame_center_y) / frame_height)
        centrality = max(0, 1 - distance * 1.85)
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 70, 150)
        edge_density = float((edges[component_mask > 0] > 0).mean()) if area else 0
        low_food_signal = saturation_mean < 0.16 and color_std < 0.20 and edge_density < 0.035
        if low_food_signal:
            return 0
        score = (
            saturation_mean * 0.34
            + min(color_std, 1.0) * 0.20
            + min(fill_ratio, 1.0) * 0.18
            + centrality * 0.16
            + min(edge_density * 7.0, 1.0) * 0.12
            + min(value_mean, 1.0) * 0.05
        )
        return float(min(1.0, score))

    def _profile_from_color(self, crop: np.ndarray, index: int) -> FoodProfile:
        if crop.size == 0:
            return profile_for_key("unknown_food")
        hint, confidence = self._profile_hint_from_region(crop, np.ones(crop.shape[:2], dtype=np.uint8) * 255)
        if confidence >= 0.42:
            return profile_for_key(hint)
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        hue = hsv[:, :, 0]
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        lap = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
        texture = float(np.percentile(lap, 82) / 28)
        golden = float(((hue >= 5) & (hue <= 34) & (saturation > 55) & (value > 75)).mean())
        pale = float(((saturation < 58) & (value > 148)).mean())
        browned = float(((hue >= 5) & (hue <= 26) & (saturation > 55) & (value > 65) & (value < 205)).mean())
        green_ratio = float(((hue >= 35) & (hue <= 92) & (saturation > 48) & (value > 45)).mean())
        mean = crop.reshape(-1, 3).mean(axis=0)
        r, g, b = mean.tolist()
        brightness = (r + g + b) / 3
        if g > r * 1.12 and g > b * 1.08:
            if brightness < 88:
                return profile_for_key("spinach")
            if brightness < 125:
                return profile_for_key("bok_choy")
            return profile_for_key("broccoli")
        if r > 165 and g > 95 and b < 105 and golden < 0.58 and texture < 0.72:
            return profile_for_key("carrot")
        if r > 158 and g < 108 and b < 115 and (r - g) > 55 and golden < 0.38:
            return profile_for_key("tomato")
        if golden > 0.34 and browned > 0.18 and texture < 1.35:
            if pale > 0.10 or brightness > 132:
                return profile_for_key("bread")
            return profile_for_key("sweet_potato")
        if r > 185 and g > 175 and b > 145:
            return profile_for_key("rice")
        if r > 150 and g > 105 and b < 100:
            return profile_for_key("sweet_potato")
        if r > 112 and g < 108 and b < 100 and texture >= 0.72:
            return profile_for_key("beef")
        if pale > 0.46 and brightness > 145 and texture < 0.80:
            return profile_for_key("tofu")
        if brightness > 148 and pale > 0.30 and abs(r - g) < 28 and abs(g - b) < 32 and texture < 0.50:
            return profile_for_key("fish")
        if brightness < 78 and abs(r - g) < 20 and abs(g - b) < 20:
            return profile_for_key("wood_ear")
        if green_ratio > 0.16:
            return profile_for_key("stir_fried_greens")
        return profile_for_key("unknown_food")

    @staticmethod
    def _profile_hint_from_region(crop: np.ndarray, component_mask: np.ndarray) -> tuple[str, float]:
        if crop.size == 0:
            return "unknown_food", 0.0
        selected = crop[component_mask > 0]
        if selected.size == 0:
            return "unknown_food", 0.0
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        selected_hsv = hsv[component_mask > 0]
        hue = selected_hsv[:, 0]
        saturation = selected_hsv[:, 1]
        value = selected_hsv[:, 2]
        red = selected[:, 0].astype(np.int16)
        green = selected[:, 1].astype(np.int16)
        blue = selected[:, 2].astype(np.int16)
        brightness = float(value.mean() / 255)
        saturation_mean = float(saturation.mean() / 255)
        channel_std = float(np.std(selected, axis=0).mean() / 64)
        mask_area = max(1, int((component_mask > 0).sum()))
        bbox_area = max(1, crop.shape[0] * crop.shape[1])
        fill_ratio = mask_area / bbox_area
        aspect = max(crop.shape[1] / max(crop.shape[0], 1), crop.shape[0] / max(crop.shape[1], 1))
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 55, 135)
        edge_density = float((edges[component_mask > 0] > 0).mean())

        blue_wrapper = ((blue > 135) & (blue > red + 26) & (blue > green + 10) & (saturation > 70)).mean()
        cream_wrapper = ((red > 170) & (green > 165) & (blue > 130) & (saturation < 75) & (value > 145)).mean()
        green_seal = ((hue >= 35) & (hue <= 90) & (saturation > 70) & (value > 65)).mean()
        white_label = ((saturation < 42) & (value > 180)).mean()
        dark_cookie = ((value < 80) & (saturation < 95)).mean()
        golden = ((hue >= 5) & (hue <= 32) & (saturation > 45) & (value > 70)).mean()
        sponge_yellow = ((hue >= 18) & (hue <= 42) & (saturation > 35) & (saturation < 135) & (value > 115)).mean()
        cream = ((saturation < 65) & (value > 155)).mean()
        browned_top = ((hue >= 7) & (hue <= 24) & (saturation > 45) & (value > 75) & (value < 205)).mean()

        wrapper_score = min(1.0, blue_wrapper * 1.35 + cream_wrapper * 0.70 + green_seal * 0.35 + white_label * 0.24 + edge_density * 0.9)
        wrapper_shape = aspect >= 1.85 or fill_ratio < 0.42 or blue_wrapper > 0.08 or green_seal > 0.02
        if wrapper_score >= 0.56 and wrapper_shape and (blue_wrapper > 0.12 or cream_wrapper > 0.42):
            if blue_wrapper > 0.20 and dark_cookie > 0.025:
                return "oreo_cookie", round(max(0.62, wrapper_score), 2)
            if cream_wrapper > 0.42 and green_seal > 0.025:
                return "cheese_cracker", round(max(0.58, wrapper_score), 2)
            return "packaged_snack", round(max(0.52, wrapper_score), 2)

        cake_score = min(1.0, sponge_yellow * 0.85 + cream * 0.40 + browned_top * 0.36 + max(0.0, 0.46 - saturation_mean) * 0.36)
        biscuit_score = min(1.0, golden * 0.45 + browned_top * 0.38 + edge_density * 0.65 + channel_std * 0.16)
        chocolate_score = min(1.0, dark_cookie * 1.15 + edge_density * 0.45)
        exposed_fried_surface = golden > 0.45 and browned_top > 0.34 and edge_density > 0.09 and aspect < 1.72 and blue_wrapper < 0.05 and green_seal < 0.02
        layered_cake = cream > 0.24 and sponge_yellow > 0.035 and edge_density < 0.20 and (fill_ratio < 0.70 or aspect >= 1.12)
        pork_floss_pastry = (
            aspect >= 1.35
            and golden > 0.34
            and browned_top > 0.22
            and brightness > 0.38
            and fill_ratio >= 0.42
            and cream_wrapper < 0.30
            and blue_wrapper < 0.08
        )

        if pork_floss_pastry and (not wrapper_shape or fill_ratio >= 0.50):
            return "pork_floss_pastry", round(max(0.62, biscuit_score, cake_score), 2)

        if layered_cake and cake_score >= 0.46 and not exposed_fried_surface and cream > 0.10 and brightness > 0.48:
            if browned_top > 0.22 and cream > 0.18:
                return "cake_roll", round(max(0.58, cake_score), 2)
            return "cake", round(max(0.52, cake_score), 2)
        if sponge_yellow > 0.26 and golden > 0.20 and brightness > 0.48 and edge_density < 0.18 and not exposed_fried_surface:
            return "sponge_cake", round(max(0.50, cake_score), 2)
        if golden > 0.38 and browned_top > 0.20 and brightness > 0.42 and edge_density < 0.16 and fill_ratio >= 0.46:
            return "bread", round(max(0.48, biscuit_score, cake_score), 2)
        if chocolate_score >= 0.42 and dark_cookie > 0.20:
            return "chocolate", round(max(0.50, chocolate_score), 2)
        biscuit_like_shape = aspect >= 1.85 or fill_ratio < 0.42 or blue_wrapper > 0.08 or green_seal > 0.02 or (cream_wrapper > 0.42 and aspect >= 1.55)
        if biscuit_score >= 0.58 and biscuit_like_shape and not exposed_fried_surface and brightness > 0.38:
            if golden > 0.42 and edge_density > 0.08:
                return "biscuit", round(max(0.54, biscuit_score), 2)
            return "cookie", round(max(0.50, biscuit_score), 2)

        return "unknown_food", 0.0

    @staticmethod
    def _cooking_method_from_region(crop: np.ndarray, component_mask: np.ndarray) -> tuple[str, float]:
        if crop.size == 0:
            return "unknown", 0
        selected = crop[component_mask > 0]
        if selected.size == 0:
            return "unknown", 0
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        selected_hsv = hsv[component_mask > 0]
        hue = selected_hsv[:, 0]
        saturation = selected_hsv[:, 1]
        value = selected_hsv[:, 2]
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        lap = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
        texture = float(np.percentile(lap[component_mask > 0], 82) / 28)
        golden = ((hue >= 5) & (hue <= 28) & (saturation > 95) & (value > 70)).mean()
        brown = ((hue >= 0) & (hue <= 24) & (saturation > 75) & (value > 45) & (value < 190)).mean()
        green = ((hue >= 35) & (hue <= 95) & (saturation > 55)).mean()
        pale = ((saturation < 65) & (value > 145)).mean()
        red_sauce = (((hue <= 8) | (hue >= 170)) & (saturation > 75)).mean()

        fried_score = min(1.0, golden * 0.85 + brown * 0.45 + min(texture, 1.0) * 0.28)
        stir_score = min(1.0, (green + red_sauce) * 0.55 + float(saturation.mean() / 255) * 0.22 + min(texture, 1.0) * 0.12)
        boiled_score = min(1.0, pale * 0.55 + max(0, 0.42 - float(saturation.mean() / 255)) * 0.55)
        baked_score = min(1.0, golden * 0.55 + brown * 0.24 + max(0.0, 0.34 - float(saturation.mean() / 255)) * 0.22)

        if baked_score >= 0.44 and texture < 1.18 and pale > 0.06:
            return "baked", round(max(0.55, baked_score), 2)

        if fried_score >= 0.48 and fried_score >= stir_score:
            return "deep_fried", round(max(0.58, fried_score), 2)
        if stir_score >= 0.42 and stir_score >= boiled_score:
            return "stir_fried", round(max(0.5, stir_score), 2)
        if boiled_score >= 0.38:
            return "boiled_steamed", round(max(0.48, boiled_score), 2)
        return "raw_light", 0.42

    def _track_from_region(
        self,
        track_id: str,
        profile: FoodProfile,
        bbox: list[int],
        polygon: list[list[int]],
        confidence: float,
        frame_width: int,
        frame_height: int,
        area_px: int | None = None,
        cooking_method: str = "unknown",
        cooking_confidence: float = 0,
        scale: ScaleMetadata | None = None,
        container: ContainerObservation | None = None,
    ) -> FoodTrack:
        x1, y1, x2, y2 = bbox
        bbox_area_px = max(1, (x2 - x1) * (y2 - y1))
        true_area_px = max(1, int(area_px or self._polygon_area(polygon) or bbox_area_px))
        frame_area = max(1, frame_width * frame_height)
        area_ratio = min(0.36, true_area_px / frame_area)
        bbox_area_ratio = min(1.0, bbox_area_px / frame_area)
        margin_ratio = min(x1, y1, frame_width - x2, frame_height - y2) / max(min(frame_width, frame_height), 1)
        center_x = (x1 + x2) / 2 / max(frame_width, 1)
        center_y = (y1 + y2) / 2 / max(frame_height, 1)
        centered = max(0.0, 1.0 - math.hypot(center_x - 0.5, center_y - 0.5) * 1.45)
        not_too_close = max(0.0, 1.0 - max(0.0, bbox_area_ratio - 0.30) / 0.34)
        not_too_tiny = min(1.0, max(area_ratio, bbox_area_ratio * 0.45) / 0.055)
        not_clipped = max(0.0, min(1.0, margin_ratio / 0.035))
        scale_view_quality = round(max(0.05, min(1.0, not_too_close * 0.42 + not_too_tiny * 0.22 + not_clipped * 0.20 + centered * 0.16)), 2)

        container_type = container.type if container and container.confidence >= 0.34 else "none"
        container_confidence = container.confidence if container else 0.0
        estimate = estimate_weight(
            mask_area_px=true_area_px,
            bbox_area_px=bbox_area_px,
            frame_area_px=frame_area,
            profile=profile,
            food_confidence=confidence,
            scale=scale,
            mask_confidence=confidence,
            container_type=container_type,
            container_confidence=container_confidence,
        )
        volume_ml = estimate.volume_ml
        estimated_weight = estimate.weight_g
        weight_error = estimate.weight_error_g
        weight_confidence = estimate.confidence
        volume_confidence = round(max(0.2, min(0.90, estimate.confidence * 0.88)), 2)
        cooking = cooking_method_for_key(cooking_method)
        display_name = (
            profile.display_name
            if profile.key == "pork_floss_pastry" or cooking_method in {"unknown", "raw_light"}
            else f"{cooking.display_name}{profile.display_name}"
        )
        return FoodTrack(
            track_id=track_id,
            name=display_name,
            category=profile.category,
            profile_key=profile.key,
            cooking_method=cooking_method,
            cooking_method_name=cooking.display_name,
            cooking_confidence=round(cooking_confidence, 2),
            raw_weight_g=estimated_weight,
            area_ratio=round(area_ratio, 4),
            bbox_area_ratio=round(bbox_area_ratio, 4),
            scale_view_quality=scale_view_quality,
            scale_corrected=False,
            scale_confidence=round(scale.confidence, 2) if scale and scale.detected else round(scale_view_quality * 0.18, 2),
            scale_sample_count=1 if scale and scale.usable else 0,
            scale_status="stable" if scale and scale.usable else "needs_reference",
            reference_detected=bool(scale and scale.detected),
            reference_type=scale.marker_type if scale and scale.detected else "none",
            reference_marker_id=scale.marker_id if scale and scale.detected else None,
            scale_mm_per_px=round(scale.mm_per_px, 6) if scale and scale.usable else 0,
            weight_source=estimate.weight_source,
            weight_estimation_level=estimate.estimation_level,
            area_cm2=estimate.area_cm2,
            estimated_height_cm=estimate.estimated_height_cm,
            shape_factor=estimate.shape_factor,
            container_type=container_type,
            container_confidence=round(container_confidence, 2),
            occlusion_score=round(max(0.0, min(0.65, 1 - not_clipped)), 2),
            bbox=bbox,
            polygon=polygon,
            mask_svg_path=self._polygon_path(polygon),
            color=self._color_for_profile(profile.key),
            confidence=round(confidence, 2),
            volume_ml=volume_ml,
            volume_confidence=volume_confidence,
            density_g_per_ml=profile.density_g_per_ml,
            estimated_weight_g=estimated_weight,
            weight_error_g=weight_error,
            weight_confidence=weight_confidence,
            nutrition=nutrition_for_weight(profile, estimated_weight, cooking_method),
        )

    def _quality(
        self,
        frame: DecodedFrame,
        tracks: list[FoodTrack],
        frame_count: int,
        elapsed_seconds: float,
        scale: ScaleMetadata | None = None,
        container: ContainerObservation | None = None,
    ) -> MeasurementQuality:
        grayscale = frame.image.convert("L")
        stat = ImageStat.Stat(grayscale)
        brightness = stat.mean[0] / 255
        contrast = min(1, stat.stddev[0] / 72)
        edges = grayscale.filter(ImageFilter.FIND_EDGES)
        blur_score = min(1, ImageStat.Stat(edges).mean[0] / 24)
        food_area = sum(self._polygon_area(food.polygon) or max(0, (food.bbox[2] - food.bbox[0]) * (food.bbox[3] - food.bbox[1])) for food in tracks)
        area_ratio = food_area / max(frame.width * frame.height, 1)
        angle = min(0.88, 0.20 + elapsed_seconds / 26)
        depth = min(0.82, 0.14 + elapsed_seconds / 30 + len(tracks) * 0.05)
        stability = min(0.92, 0.28 + frame_count / 90 + len(tracks) * 0.07)
        motion = min(0.88, 0.36 + elapsed_seconds / 30)
        lighting = max(0.15, min(0.95, 1 - abs(brightness - 0.58) * 1.35 + contrast * 0.16))
        plate_visibility = max(0.0, min(0.94, area_ratio * 4.1))
        blur = max(0.15, min(0.95, blur_score))
        overall = np.mean([angle, depth, stability, motion, lighting, plate_visibility, blur]).item()
        return MeasurementQuality(
            angle_coverage=round(angle, 2),
            depth_completeness=round(depth, 2),
            mask_stability=round(stability, 2),
            motion_quality=round(motion, 2),
            lighting=round(lighting, 2),
            blur=round(blur, 2),
            plate_visibility=round(plate_visibility, 2),
            reference_visibility=round(scale.marker_area_ratio * 18, 2) if scale and scale.detected else 0,
            scale_quality=round(scale.confidence, 2) if scale else 0,
            container_visibility=round(container.confidence, 2) if container else 0,
            calibrated_frame_ratio=1.0 if any(food.weight_source in {"aruco_calibrated", "container_model"} for food in tracks) else 0.0,
            overall=round(float(overall), 2),
        )

    @staticmethod
    def _guidance(quality: MeasurementQuality, food_count: int) -> str:
        if food_count == 0:
            return "未检测到稳定食物主体，请让食物占画面中心 1/3 到 2/3，避免拍到键盘、桌面或包装边缘。"
        if quality.lighting < 0.45:
            return "光照偏弱，请靠近光源或调整餐盘位置。"
        if quality.plate_visibility < 0.18:
            return "食物主体太小，请稍微靠近餐盘。"
        if quality.depth_completeness < 0.62:
            return "请缓慢改变角度继续采集，系统会用多帧结果修正重量。"
        if quality.mask_stability < 0.72:
            return "请保持连续推流，等待主体分割和重量结果收敛。"
        return "采集质量良好，继续缓慢移动手机可进一步降低估重误差。"

    @staticmethod
    def _smooth_mask(mask: np.ndarray) -> np.ndarray:
        uint_mask = mask.astype(np.uint8) * 255
        kernel_open = np.ones((3, 3), dtype=np.uint8)
        kernel_close = np.ones((5, 5), dtype=np.uint8)
        opened = cv2.morphologyEx(uint_mask, cv2.MORPH_OPEN, kernel_open, iterations=1)
        closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel_close, iterations=1)
        return closed > 0

    @staticmethod
    def _food_likeness_score(arr: np.ndarray, mask: np.ndarray, components: list[FoodComponent]) -> float:
        height, width = mask.shape
        frame_area = max(width * height, 1)
        mask_ratio = float(mask.mean())
        component_area = sum(item.area_px for item in components) / frame_area
        component_score = sum(item.score for item in components) / len(components) if components else 0
        channel_std = float(np.std(arr.reshape(-1, 3), axis=0).mean() / 80)
        score = mask_ratio * 0.7 + component_area * 1.45 + component_score * 0.42 + channel_std * 0.12
        return float(min(1.0, score))

    @staticmethod
    def _looks_like_non_food_scene(arr: np.ndarray) -> bool:
        height, width = arr.shape[:2]
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        low_saturation_ratio = float((saturation < 45).mean())
        dark_ratio = float((value < 100).mean())
        edges = cv2.Canny(gray, 70, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=45, minLineLength=max(24, width // 20), maxLineGap=8)
        line_count = 0 if lines is None else len(lines)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        rectangular_count = 0
        min_area = max(60, int(width * height * 0.0008))
        max_area = int(width * height * 0.08)
        for contour in contours[:260]:
            area = cv2.contourArea(contour)
            if area < min_area or area > max_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if w <= 0 or h <= 0:
                continue
            aspect = w / h
            extent = area / max(w * h, 1)
            if 0.25 <= aspect <= 6.0 and extent > 0.18:
                rectangular_count += 1
        edge_density = float((edges > 0).mean())
        many_keyboard_shapes = rectangular_count >= 18 and line_count >= 60 and edge_density > 0.035
        mostly_dark_device = dark_ratio > 0.48 and low_saturation_ratio > 0.6 and rectangular_count >= 9
        black_keyboard_like = dark_ratio > 0.62 and line_count >= 120 and edge_density > 0.04
        flat_office_scene = low_saturation_ratio > 0.78 and edge_density > 0.055 and rectangular_count >= 12
        return many_keyboard_shapes or mostly_dark_device or black_keyboard_like or flat_office_scene

    @staticmethod
    def _bbox_polygon(bbox: list[int]) -> list[list[int]]:
        x1, y1, x2, y2 = bbox
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

    @staticmethod
    def _contour_polygon(component_mask: np.ndarray, offset_x: int, offset_y: int) -> list[list[int]]:
        contours, _ = cv2.findContours(component_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return []
        contour = max(contours, key=cv2.contourArea)
        epsilon = max(2.0, cv2.arcLength(contour, True) * 0.018)
        approx = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
        points = [[int(x + offset_x), int(y + offset_y)] for x, y in approx]
        return FoodAnalyzer._simplify_polygon(points)

    @staticmethod
    def _simplify_polygon(points: list[list[int]], max_points: int = 36) -> list[list[int]]:
        if len(points) <= max_points:
            return points
        step = max(1, math.ceil(len(points) / max_points))
        return points[::step][:max_points]

    @staticmethod
    def _polygon_area(polygon: list[list[int]]) -> int:
        if len(polygon) < 3:
            return 0
        pts = np.array(polygon, dtype=np.float32)
        return int(abs(cv2.contourArea(pts)))

    @staticmethod
    def _polygon_path(polygon: list[list[int]]) -> str:
        if not polygon:
            return ""
        start = polygon[0]
        rest = " ".join(f"L {x} {y}" for x, y in polygon[1:])
        return f"M {start[0]} {start[1]} {rest} Z"

    @staticmethod
    def _color_for_profile(key: str) -> str:
        return {
            "rice": "#f3edc8",
            "brown_rice": "#c5a46a",
            "chicken": "#ff9b66",
            "chicken_thigh": "#e58f5d",
            "pork_lean": "#df7d73",
            "pork_belly": "#ffb38f",
            "beef": "#d75c52",
            "fish": "#dce7e8",
            "shrimp": "#ffb07c",
            "egg": "#ffd66e",
            "tofu": "#f2ead2",
            "broccoli": "#72d879",
            "spinach": "#3fa763",
            "bok_choy": "#94dc83",
            "tomato": "#ff685d",
            "carrot": "#f28b38",
            "potato": "#d7b16c",
            "sweet_potato": "#f07f45",
            "pork_floss_pastry": "#d9873f",
            "corn": "#f6d84d",
            "wood_ear": "#5b5149",
            "apple": "#ff6b6b",
        }.get(key, "#7cf4bd")
