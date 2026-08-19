"""Test food segmentation model on a single image.

Usage:
    python test_food.py <image_path>
    python test_food.py C:/Users/admin/Downloads/rice.jpg
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ultralytics import YOLO
from backend.services.analyzer import FOODSEG103_LABEL_MAP
from backend.services.nutrition import profile_for_key


def main():
    if len(sys.argv) < 2:
        print("用法: python test_food.py <图片路径>")
        print("示例: python test_food.py C:/Users/admin/Downloads/lunch.jpg")
        sys.exit(1)

    img_path = Path(sys.argv[1])
    if not img_path.exists():
        print(f"文件不存在: {img_path}")
        sys.exit(1)

    model_path = Path(__file__).resolve().parents[1] / "models" / "food_seg_v1.pt"
    if not model_path.exists():
        print(f"模型不存在: {model_path}")
        sys.exit(1)

    model = YOLO(str(model_path))
    print(f"模型: {model_path.name} ({len(model.names)} 类)")
    print(f"图片: {img_path}")
    print()

    results = model.predict(str(img_path), imgsz=640, conf=0.25, verbose=False)
    result = results[0]

    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        print("未检测到食物")
        return

    names = getattr(result, "names", {})
    print(f"检测到 {len(boxes)} 个食物:")
    print("-" * 70)

    for i, box in enumerate(boxes):
        cls_id = int(box.cls[0].item())
        conf = float(box.conf[0].item())
        label = names.get(cls_id, "unknown")
        nutrition_key = FOODSEG103_LABEL_MAP.get(label, "unknown_food")
        profile = profile_for_key(nutrition_key)

        xyxy = box.xyxy[0].tolist()
        w = int(xyxy[2] - xyxy[0])
        h = int(xyxy[3] - xyxy[1])

        print(f"  [{i+1}] {label}")
        print(f"      置信度: {conf:.1%}")
        print(f"      框: {w}x{h}px")
        print(f"      营养库: {profile.display_name} ({nutrition_key})")
        print(f"      热量: {profile.calories_kcal_per_100g} kcal/100g")
        print()

    annotated = result.save(str(img_path.parent / f"{img_path.stem}_result.jpg"))
    print(f"标注图已保存: {img_path.parent / f'{img_path.stem}_result.jpg'}")


if __name__ == "__main__":
    main()
