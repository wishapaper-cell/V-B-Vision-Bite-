"""Test utensil detection model on a single image.

Usage:
    python test_utensil.py <image_path>
    python test_utensil.py C:/Users/admin/Downloads/chopsticks.jpg
"""
from __future__ import annotations

import sys
from pathlib import Path

from ultralytics import YOLO


CLASS_NAMES = {0: "筷子", 1: "勺子", 2: "叉子", 3: "刀"}


def main():
    if len(sys.argv) < 2:
        print("用法: python test_utensil.py <图片路径>")
        print("示例: python test_utensil.py C:/Users/admin/Downloads/chopsticks.jpg")
        sys.exit(1)

    img_path = Path(sys.argv[1])
    if not img_path.exists():
        print(f"文件不存在: {img_path}")
        sys.exit(1)

    model_path = Path(__file__).resolve().parents[1] / "models" / "utensil_det_v1.pt"
    if not model_path.exists():
        print(f"模型不存在: {model_path}")
        sys.exit(1)

    model = YOLO(str(model_path))
    print(f"模型: {model_path.name}")
    print(f"图片: {img_path}")
    print()

    results = model.predict(str(img_path), imgsz=640, conf=0.25, verbose=False)
    result = results[0]

    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        print("未检测到餐具")
        return

    names = getattr(result, "names", {})
    print(f"检测到 {len(boxes)} 个餐具:")
    print("-" * 50)

    for i, box in enumerate(boxes):
        cls_id = int(box.cls[0].item())
        conf = float(box.conf[0].item())
        label_en = names.get(cls_id, "unknown")
        label_cn = CLASS_NAMES.get(cls_id, label_en)
        xyxy = box.xyxy[0].tolist()
        x1, y1, x2, y2 = int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3])
        print(f"  [{i+1}] {label_cn} ({label_en})")
        print(f"      置信度: {conf:.1%}")
        print(f"      位置: ({x1}, {y1}) → ({x2}, {y2})")
        print()

    out_path = img_path.parent / f"{img_path.stem}_utensil_result.jpg"
    result.save(str(out_path))
    print(f"标注图已保存: {out_path}")


if __name__ == "__main__":
    main()
