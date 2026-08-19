import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.analyzer import FoodAnalyzer


def textured_patch(rgb: tuple[int, int, int], size: int = 96, noise: int = 18) -> np.ndarray:
    rng = np.random.default_rng(7)
    base = np.full((size, size, 3), rgb, dtype=np.int16)
    wave = np.indices((size, size)).sum(axis=0) % 17
    texture = np.where(wave[..., None] < 8, noise, -noise)
    random = rng.integers(-noise // 2, noise // 2 + 1, size=(size, size, 3))
    return np.clip(base + texture + random, 0, 255).astype(np.uint8)


def test_warm_pastry_patch_is_not_forced_to_chicken():
    analyzer = FoodAnalyzer()
    crop = textured_patch((205, 156, 82), noise=20)

    profile = analyzer._profile_from_color(crop, 0)
    hint, confidence = analyzer._profile_hint_from_region(crop, np.ones(crop.shape[:2], dtype=np.uint8) * 255)

    assert profile.key != "chicken"
    assert hint in {"bread", "sponge_cake", "pork_floss_pastry", "unknown_food"}
    assert confidence >= 0 or hint == "unknown_food"


def test_low_evidence_color_fallback_returns_unknown_instead_of_rotating_to_chicken():
    analyzer = FoodAnalyzer()
    crop = np.full((96, 96, 3), (132, 128, 121), dtype=np.uint8)

    keys = [analyzer._profile_from_color(crop, index).key for index in range(7)]

    assert keys == ["unknown_food"] * 7


def test_fried_like_potato_color_is_not_rewritten_to_chicken():
    analyzer = FoodAnalyzer()
    crop = textured_patch((185, 118, 48), noise=28)

    profile = analyzer._profile_from_color(crop, 2)

    assert profile.key != "chicken"
    assert profile.key in {"sweet_potato", "bread", "unknown_food", "biscuit", "cookie", "pork_floss_pastry"}


def test_hough_lines_accepts_opencv_5_flat_shape():
    flat = np.array([[4, 8, 40, 12], [9, 5, 12, 48]], dtype=np.int32)
    nested = flat.reshape(2, 1, 4)

    assert FoodAnalyzer._iter_hough_lines(flat).tolist() == flat.tolist()
    assert FoodAnalyzer._iter_hough_lines(nested).tolist() == flat.tolist()
