"""Bridge the health app and the continuous Rokid stream to the CV pipeline.

The Flask application stays usable without the optional computer-vision stack.
Recognition dependencies are imported lazily on the computer backend only; the
Android package can therefore ship the same application sources without
bundling PyTorch, OpenCV or Ultralytics.
"""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_RECOGNITION_ROOT = PROJECT_ROOT / "demo"
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
WORKSPACE_RECOGNITION_ROOT = WORKSPACE_ROOT / "services" / "recognition"

RECORD_NAME_BY_PROFILE = {
    "rice": "白米饭",
    "millet_porridge": "小米粥",
    "wheat_noodles": "面条（煮）",
    "steamed_bun": "馒头",
    "dumpling": "饺子（猪肉白菜）",
    "sweet_potato": "红薯",
    "corn": "玉米",
    "chicken": "鸡胸肉",
    "chicken_thigh": "鸡腿",
    "duck": "鸭肉",
    "pork_lean": "猪瘦肉",
    "beef": "牛肉（瘦）",
    "lamb": "羊肉",
    "salmon": "三文鱼",
    "shrimp": "虾仁",
    "egg": "鸡蛋（煮）",
    "broccoli": "西兰花",
    "spinach": "菠菜",
    "bok_choy": "白菜",
    "napa_cabbage": "白菜",
    "tomato": "西红柿",
    "cucumber": "黄瓜",
    "carrot": "胡萝卜",
    "eggplant": "茄子",
    "potato": "土豆",
    "apple": "苹果",
    "banana": "香蕉",
    "orange": "橙子",
    "watermelon": "西瓜",
    "cake": "蛋糕（奶油）",
    "cream_cake": "蛋糕（奶油）",
    "biscuit": "饼干",
    "chips": "薯片",
    "chocolate": "巧克力",
}


class RecognitionUnavailable(RuntimeError):
    """Raised when the recognizer or one of its optional dependencies is absent."""


_analyzer: Any | None = None
_analyzer_lock = threading.Lock()


def recognition_root() -> Path:
    configured = os.environ.get("RECOGNITION_ALGORITHM_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    if DEFAULT_RECOGNITION_ROOT.is_dir():
        return DEFAULT_RECOGNITION_ROOT
    return WORKSPACE_RECOGNITION_ROOT


def _load_analyzer() -> Any:
    global _analyzer
    if _analyzer is not None:
        return _analyzer

    with _analyzer_lock:
        if _analyzer is not None:
            return _analyzer
        root = recognition_root()
        backend_dir = root / "backend"
        if not backend_dir.is_dir():
            raise RecognitionUnavailable(f"未找到识别算法目录：{root}")
        root_text = str(root)
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
        try:
            from backend.services.analyzer import FoodAnalyzer
        except (ImportError, ModuleNotFoundError) as exc:
            raise RecognitionUnavailable(
                "识别依赖尚未安装，请安装 demo/requirements.txt 中的依赖"
            ) from exc
        try:
            _analyzer = FoodAnalyzer()
        except Exception as exc:
            raise RecognitionUnavailable(f"识别算法初始化失败：{exc}") from exc
        return _analyzer


def analyze_image(image_data_url: str) -> dict[str, Any]:
    """Analyze one image data URL and return the shape consumed by the app UI."""
    if not isinstance(image_data_url, str) or not image_data_url.startswith("data:image/"):
        raise ValueError("image 必须是图片 data URL")

    analyzer = _load_analyzer()
    try:
        frame = analyzer.decode_data_url(image_data_url)
    except Exception as exc:
        raise ValueError("无法解码图片，请选择有效的 JPG、PNG 或 WebP 文件") from exc
    foods, quality, guidance = analyzer.analyze(
        frame=frame,
        frame_count=1,
        elapsed_seconds=0.0,
    )

    utensils: list[dict[str, Any]] = []
    utensil_model = "unavailable"
    try:
        import numpy as np
        from backend.services.utensil_tracker import detect_utensils, detector_name

        observations = detect_utensils(np.array(frame.image), foods)
        utensils = [asdict(observation) for observation in observations]
        utensil_model = detector_name()
    except Exception:
        # Food results remain useful if the optional utensil detector cannot be
        # initialized on a particular development machine.
        pass

    results: list[dict[str, Any]] = []
    for food in foods:
        item = food.model_dump(mode="json")
        record_name = RECORD_NAME_BY_PROFILE.get(food.profile_key)
        item["record_food_name"] = record_name
        item["available_for_record"] = record_name is not None
        results.append(item)

    quality_payload = quality.model_dump(mode="json")
    if utensils:
        quality_payload["utensil_visibility"] = max(
            float(item.get("confidence", 0)) for item in utensils
        )
    return {
        "foods": results,
        "quality": quality_payload,
        "guidance": guidance,
        "analyzer": getattr(analyzer, "backend_name", "unknown"),
        "model_name": getattr(analyzer, "model_name", "unknown"),
        "utensils": utensils,
        "utensil_model": utensil_model,
    }
