from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models"
TARGET = MODEL_DIR / "yolo11n-seg.pt"


def main() -> None:
    MODEL_DIR.mkdir(exist_ok=True)
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise SystemExit("未安装 ultralytics，请先运行：python -m pip install ultralytics") from exc

    model = YOLO("yolo11n-seg.pt")
    source = Path(getattr(model, "ckpt_path", "") or "yolo11n-seg.pt")
    if source.exists() and source.resolve() != TARGET.resolve():
        shutil.copy2(source, TARGET)
    if not TARGET.exists() and Path("yolo11n-seg.pt").exists():
        shutil.copy2("yolo11n-seg.pt", TARGET)
    if TARGET.exists():
        print(f"YOLOv11 segmentation model ready: {TARGET}")
    else:
        print("模型已由 ultralytics 缓存，但未能定位本地 pt 文件。可设置 FOOD_MODEL_PATH 指向模型文件。")


if __name__ == "__main__":
    main()
