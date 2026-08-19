"""Convert FoodSeg103 parquet dataset to YOLO polygon format.

Handles HuggingFace parquet format where:
- image column: dict with 'bytes' and 'path' keys
- label column: dict with 'bytes' and 'path' keys (segmentation mask PNG)

Usage:
    python convert_foodseg103.py
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get(
    "FOODSEG_DIR",
    str(SCRIPT_DIR / "datasets" / "FoodSeg103"),
))
YOLO_DIR = Path(os.environ.get(
    "YOLO_DIR",
    str(SCRIPT_DIR / "datasets" / "foodseg103_yolo"),
))

MIN_CONTOUR_AREA = 100
MIN_CONTOUR_POINTS = 10


def load_categories(data_dir: Path) -> dict[int, str]:
    """Load categories from id2label.json."""
    f = data_dir / "id2label.json"
    if f.exists():
        with open(f, encoding="utf-8") as fp:
            raw = json.load(fp)
        return {int(k): v for k, v in raw.items()}
    print("警告: 未找到 id2label.json，使用默认类别名")
    return {i: f"class_{i}" for i in range(1, 104)}


def mask_to_yolo_polygons(mask: np.ndarray, num_classes: int = 103) -> list[str]:
    """Convert a PNG mask to YOLO polygon format lines."""
    h, w = mask.shape[:2]
    lines = []

    for class_id_raw in np.unique(mask):
        if class_id_raw == 0 or class_id_raw > num_classes:
            continue

        yolo_id = int(class_id_raw) - 1
        binary = (mask == class_id_raw).astype(np.uint8)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for contour in contours:
            if cv2.contourArea(contour) < MIN_CONTOUR_AREA:
                continue
            epsilon = 0.005 * cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, epsilon, True)
            if len(approx) < MIN_CONTOUR_POINTS:
                continue

            points = approx.reshape(-1, 2).astype(float)
            points[:, 0] /= w
            points[:, 1] /= h
            coords = " ".join(f"{x:.6f} {y:.6f}" for x, y in points)
            lines.append(f"{yolo_id} {coords}")

    return lines


def generate_food_yaml(yolo_dir: Path, categories: dict[int, str]) -> Path:
    """Generate food.yaml config file."""
    yaml_path = yolo_dir / "food.yaml"
    food_cats = {k: v for k, v in categories.items() if k != 0}
    lines = [
        f"path: {yolo_dir.as_posix()}",
        "train: images/train",
        "val: images/val",
        "",
        f"nc: {len(food_cats)}",
        "names:",
    ]
    for cat_id in sorted(food_cats.keys()):
        yolo_id = cat_id - 1
        name = food_cats[cat_id].strip()
        lines.append(f"  {yolo_id}: {name}")
    yaml_path.write_text("\n".join(lines), encoding="utf-8")
    return yaml_path


def process_parquet(parquet_path: Path, split_name: str, yolo_dir: Path) -> tuple[int, int, int]:
    """Process a single parquet file, return (success, empty, total)."""
    import pandas as pd

    df = pd.read_parquet(parquet_path)
    success = 0
    empty = 0

    for idx, row in df.iterrows():
        if (idx + 1) % 500 == 0:
            print(f"  {idx + 1}/{len(df)}...")

        img_data = row["image"]
        img_bytes = img_data["bytes"] if isinstance(img_data, dict) else img_data
        img = Image.open(io.BytesIO(img_bytes))

        label_data = row["label"]
        mask_bytes = label_data["bytes"] if isinstance(label_data, dict) else label_data
        mask = np.array(Image.open(io.BytesIO(mask_bytes)))

        lines = mask_to_yolo_polygons(mask)
        if not lines:
            empty += 1
            continue

        img_id = row.get("id", idx)
        stem = f"{int(img_id):08d}"

        label_path = yolo_dir / "labels" / split_name / f"{stem}.txt"
        label_path.write_text("\n".join(lines), encoding="utf-8")

        img_path = yolo_dir / "images" / split_name / f"{stem}.jpg"
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(img_path, "JPEG")

        success += 1

    return success, empty, len(df)


def main():
    if not DATA_DIR.exists():
        print(f"错误: 数据集目录不存在: {DATA_DIR}")
        print("请先运行: python download_data.py")
        sys.exit(1)

    categories = load_categories(DATA_DIR)
    food_cats = {k: v for k, v in categories.items() if k != 0}
    print(f"加载了 {len(food_cats)} 个食物类别")

    if YOLO_DIR.exists():
        shutil.rmtree(YOLO_DIR)
    for sub in ["images/train", "images/val", "labels/train", "labels/val"]:
        (YOLO_DIR / sub).mkdir(parents=True, exist_ok=True)

    data_dir = DATA_DIR / "data"
    train_files = sorted(data_dir.glob("train-*.parquet"))
    val_files = sorted(data_dir.glob("validation-*.parquet"))

    if not train_files:
        print(f"错误: 在 {data_dir} 中未找到 train-*.parquet 文件")
        sys.exit(1)

    print(f"训练文件: {len(train_files)} 个")
    print(f"验证文件: {len(val_files)} 个\n")

    total_success = 0
    total_empty = 0
    total_rows = 0

    for pf in train_files:
        print(f"处理 {pf.name}...")
        s, e, t = process_parquet(pf, "train", YOLO_DIR)
        total_success += s
        total_empty += e
        total_rows += t
        print(f"  成功: {s}, 空标注: {e}, 总计: {t}\n")

    for pf in val_files:
        print(f"处理 {pf.name}...")
        s, e, t = process_parquet(pf, "val", YOLO_DIR)
        total_success += s
        total_empty += e
        total_rows += t
        print(f"  成功: {s}, 空标注: {e}, 总计: {t}\n")

    yaml_path = generate_food_yaml(YOLO_DIR, categories)
    print(f"food.yaml 已生成: {yaml_path}")
    print(f"\n转换完成:")
    print(f"  总图片: {total_rows}")
    print(f"  成功: {total_success}")
    print(f"  空标注: {total_empty}")
    print(f"  输出目录: {YOLO_DIR}")


if __name__ == "__main__":
    main()
