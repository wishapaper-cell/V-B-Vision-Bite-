from __future__ import annotations

import math
from dataclasses import dataclass

from backend.services.calibration import ScaleMetadata
from backend.services.nutrition import FoodProfile


@dataclass(frozen=True)
class FoodVolumeProfile:
    profile_key: str
    volume_model: str
    default_height_cm: float
    min_height_cm: float
    max_height_cm: float
    shape_factor: float
    volume_confidence: float


@dataclass(frozen=True)
class WeightEstimate:
    weight_g: float
    weight_error_g: float
    volume_ml: float
    area_cm2: float
    estimated_height_cm: float
    shape_factor: float
    density_g_per_ml: float
    weight_source: str
    estimation_level: str
    confidence: float
    relative_error: float


DEFAULT_VOLUME_PROFILE = FoodVolumeProfile("unknown_food", "unknown", 2.2, 0.8, 4.0, 0.48, 0.32)

FOOD_VOLUME_PROFILES: dict[str, FoodVolumeProfile] = {
    "rice": FoodVolumeProfile("rice", "mound", 2.6, 1.4, 4.2, 0.65, 0.62),
    "brown_rice": FoodVolumeProfile("brown_rice", "mound", 2.5, 1.4, 4.0, 0.65, 0.60),
    "fried_rice": FoodVolumeProfile("fried_rice", "mound", 2.5, 1.4, 4.0, 0.62, 0.56),
    "wheat_noodles": FoodVolumeProfile("wheat_noodles", "mound", 2.4, 1.3, 3.8, 0.55, 0.48),
    "rice_noodles": FoodVolumeProfile("rice_noodles", "mound", 2.4, 1.3, 3.8, 0.55, 0.48),
    "chicken": FoodVolumeProfile("chicken", "block_solid", 1.8, 0.9, 3.0, 0.75, 0.70),
    "chicken_thigh": FoodVolumeProfile("chicken_thigh", "block_solid", 2.0, 1.0, 3.4, 0.76, 0.68),
    "pork_lean": FoodVolumeProfile("pork_lean", "block_solid", 1.8, 0.9, 3.0, 0.75, 0.70),
    "beef": FoodVolumeProfile("beef", "block_solid", 1.8, 0.9, 3.0, 0.75, 0.70),
    "fish": FoodVolumeProfile("fish", "block_solid", 1.5, 0.8, 2.6, 0.72, 0.66),
    "egg": FoodVolumeProfile("egg", "block_solid", 1.2, 0.6, 2.2, 0.72, 0.58),
    "tofu": FoodVolumeProfile("tofu", "block_solid", 2.0, 1.0, 3.5, 0.78, 0.64),
    "potato": FoodVolumeProfile("potato", "block_solid", 1.8, 0.9, 3.2, 0.74, 0.62),
    "sweet_potato": FoodVolumeProfile("sweet_potato", "block_solid", 1.9, 0.9, 3.4, 0.74, 0.62),
    "cake": FoodVolumeProfile("cake", "block_solid", 3.2, 1.8, 5.0, 0.80, 0.72),
    "sponge_cake": FoodVolumeProfile("sponge_cake", "block_solid", 3.0, 1.8, 5.0, 0.78, 0.70),
    "bread": FoodVolumeProfile("bread", "block_solid", 3.0, 1.5, 5.0, 0.72, 0.62),
    "biscuit": FoodVolumeProfile("biscuit", "flat_solid", 0.6, 0.25, 1.2, 0.86, 0.70),
    "cookie": FoodVolumeProfile("cookie", "flat_solid", 0.7, 0.3, 1.4, 0.86, 0.68),
    "cracker": FoodVolumeProfile("cracker", "flat_solid", 0.4, 0.2, 0.9, 0.88, 0.68),
    "chips": FoodVolumeProfile("chips", "flat_solid", 0.3, 0.1, 0.8, 0.58, 0.38),
    "broccoli": FoodVolumeProfile("broccoli", "loose_leafy", 2.5, 1.0, 5.0, 0.38, 0.42),
    "bok_choy": FoodVolumeProfile("bok_choy", "loose_leafy", 3.0, 1.2, 5.2, 0.35, 0.40),
    "spinach": FoodVolumeProfile("spinach", "loose_leafy", 2.8, 1.0, 5.0, 0.34, 0.38),
    "stir_fried_greens": FoodVolumeProfile("stir_fried_greens", "loose_leafy", 2.8, 1.0, 5.0, 0.38, 0.42),
    "tomato_egg": FoodVolumeProfile("tomato_egg", "mound", 2.2, 1.0, 3.8, 0.55, 0.48),
    "mapo_tofu": FoodVolumeProfile("mapo_tofu", "container_fill", 2.2, 1.0, 4.0, 0.62, 0.44),
    "porridge": FoodVolumeProfile("porridge", "container_fill", 1.8, 0.8, 4.0, 0.80, 0.34),
    "millet_porridge": FoodVolumeProfile("millet_porridge", "container_fill", 1.8, 0.8, 4.0, 0.80, 0.34),
}


def profile_for_volume(profile_key: str) -> FoodVolumeProfile:
    return FOOD_VOLUME_PROFILES.get(profile_key, DEFAULT_VOLUME_PROFILE)


def estimate_weight(
    *,
    mask_area_px: int,
    bbox_area_px: int,
    frame_area_px: int,
    profile: FoodProfile,
    food_confidence: float,
    scale: ScaleMetadata | None,
    mask_confidence: float,
    container_type: str = "none",
    container_confidence: float = 0.0,
) -> WeightEstimate:
    volume_profile = profile_for_volume(profile.key)
    if scale and scale.usable:
        return _estimate_calibrated(mask_area_px, profile, volume_profile, scale, food_confidence, mask_confidence, container_type, container_confidence)
    return _estimate_fallback(mask_area_px, bbox_area_px, frame_area_px, profile, volume_profile, food_confidence)


def estimate_bite_weight(
    *,
    carried_food_area_px: int,
    profile: FoodProfile,
    utensil_type: str,
    scale: ScaleMetadata | None,
    confidence: float,
) -> WeightEstimate:
    volume_profile = profile_for_volume(profile.key)
    if not scale or not scale.usable or carried_food_area_px <= 0:
        fallback = _estimate_fallback(carried_food_area_px, carried_food_area_px, max(carried_food_area_px * 40, 1), profile, volume_profile, confidence)
        return WeightEstimate(**{**fallback.__dict__, "weight_source": "visual_fallback", "estimation_level": "rough", "confidence": min(fallback.confidence, 0.42)})

    area_cm2 = carried_food_area_px * scale.mm_per_px * scale.mm_per_px / 100.0
    utensil_factor = {"chopsticks": 0.72, "spoon": 0.86, "fork": 0.78}.get(utensil_type, 0.70)
    height_cm = _clamp(volume_profile.default_height_cm * utensil_factor, volume_profile.min_height_cm * 0.5, volume_profile.max_height_cm)
    shape_factor = _clamp(volume_profile.shape_factor * utensil_factor, 0.22, 0.95)
    volume_ml = max(0.5, area_cm2 * height_cm * shape_factor)
    weight_g = volume_ml * profile.density_g_per_ml
    rel_error = min(0.72, 0.22 + (1 - scale.confidence) * 0.22 + (1 - confidence) * 0.24 + _height_uncertainty(volume_profile) * 0.18)
    return WeightEstimate(
        weight_g=round(weight_g, 1),
        weight_error_g=round(max(1.5, weight_g * rel_error), 1),
        volume_ml=round(volume_ml, 1),
        area_cm2=round(area_cm2, 2),
        estimated_height_cm=round(height_cm, 2),
        shape_factor=round(shape_factor, 2),
        density_g_per_ml=profile.density_g_per_ml,
        weight_source="aruco_calibrated",
        estimation_level="approximate",
        confidence=round(max(0.16, min(0.82, scale.confidence * 0.45 + confidence * 0.35 + volume_profile.volume_confidence * 0.20)), 2),
        relative_error=round(rel_error, 3),
    )


def _estimate_calibrated(
    mask_area_px: int,
    profile: FoodProfile,
    volume_profile: FoodVolumeProfile,
    scale: ScaleMetadata,
    food_confidence: float,
    mask_confidence: float,
    container_type: str,
    container_confidence: float,
) -> WeightEstimate:
    area_cm2 = mask_area_px * scale.mm_per_px * scale.mm_per_px / 100.0
    height_cm = _height_for_context(volume_profile, container_type, container_confidence)
    shape_factor = volume_profile.shape_factor
    volume_ml = max(1.0, area_cm2 * height_cm * shape_factor)
    weight_g = volume_ml * profile.density_g_per_ml
    height_error = _height_uncertainty(volume_profile)
    container_penalty = 0.08 if container_type in {"bowl", "box"} and container_confidence < 0.45 else 0.0
    density_error = profile.density_std_g_per_ml / max(profile.density_g_per_ml, 0.1)
    rel_error = min(0.74, 0.10 + (1 - scale.confidence) * 0.20 + (1 - mask_confidence) * 0.20 + height_error * 0.30 + density_error * 0.20 + container_penalty)
    estimation_level = "calibrated" if volume_profile.volume_confidence >= 0.55 and rel_error <= 0.42 else "approximate"
    confidence = max(0.16, min(0.92, scale.confidence * 0.34 + mask_confidence * 0.24 + food_confidence * 0.20 + volume_profile.volume_confidence * 0.22 - container_penalty))
    return WeightEstimate(
        weight_g=round(weight_g, 1),
        weight_error_g=round(max(3.5, weight_g * rel_error), 1),
        volume_ml=round(volume_ml, 1),
        area_cm2=round(area_cm2, 2),
        estimated_height_cm=round(height_cm, 2),
        shape_factor=round(shape_factor, 2),
        density_g_per_ml=profile.density_g_per_ml,
        weight_source="container_model" if container_type in {"bowl", "box"} else "aruco_calibrated",
        estimation_level=estimation_level,
        confidence=round(confidence, 2),
        relative_error=round(rel_error, 3),
    )


def _estimate_fallback(
    mask_area_px: int,
    bbox_area_px: int,
    frame_area_px: int,
    profile: FoodProfile,
    volume_profile: FoodVolumeProfile,
    food_confidence: float,
) -> WeightEstimate:
    area_ratio = min(0.36, max(mask_area_px, 1) / max(frame_area_px, 1))
    compactness = min(1.06, max(0.48, math.sqrt(area_ratio) * 2.05))
    volume_ml = max(8.0, area_ratio * 980.0 * compactness)
    weight_g = volume_ml * profile.density_g_per_ml
    density_error = profile.density_std_g_per_ml / max(profile.density_g_per_ml, 0.1)
    rel_error = min(0.68, 0.28 + density_error + (1 - food_confidence) * 0.26 + (1 - volume_profile.volume_confidence) * 0.12)
    return WeightEstimate(
        weight_g=round(weight_g, 1),
        weight_error_g=round(max(5.0, weight_g * rel_error), 1),
        volume_ml=round(volume_ml, 1),
        area_cm2=0.0,
        estimated_height_cm=0.0,
        shape_factor=round(compactness, 2),
        density_g_per_ml=profile.density_g_per_ml,
        weight_source="visual_fallback",
        estimation_level="rough",
        confidence=round(max(0.12, min(0.62, food_confidence * 0.58)), 2),
        relative_error=round(rel_error, 3),
    )


def _height_for_context(volume_profile: FoodVolumeProfile, container_type: str, container_confidence: float) -> float:
    height = volume_profile.default_height_cm
    if volume_profile.volume_model == "container_fill" and container_type in {"bowl", "box"}:
        height *= 1.0 + min(0.28, container_confidence * 0.20)
    return _clamp(height, volume_profile.min_height_cm, volume_profile.max_height_cm)


def _height_uncertainty(profile: FoodVolumeProfile) -> float:
    spread = max(0.1, profile.max_height_cm - profile.min_height_cm)
    return _clamp(spread / max(profile.default_height_cm * 2.4, 0.1), 0.08, 0.72)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))
