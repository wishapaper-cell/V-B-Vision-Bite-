"""Convert AnyLabeling JSON annotations to YOLO txt format for utensil data.

Reads JSON files produced by AnyLabeling (rectangle shape, labels:
chopsticks/spoon/fork/knife) and writes YOLO detection labels.

Supports multiple source folders to merge batches.

Output class IDs:
    0 chopsticks
    1 spoon
    2 fork
    3 knife

Usage:
    python convert_anylabeling.py
"""
from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "datasets" / "chopsticks_yolo"

# List all annotation source folders here
SOURCE_DIRS = [
    SCRIPT_DIR.parent.parent / "Camera_XHS_17848269904601040g2sg31cjhnrb2ge6等46项文件",
    SCRIPT_DIR.parent.parent / "Camera_1040g3qo31q54jhhqmu7049ki99jcuvedjp01等86项文件",
]

LABEL_TO_CLASS = {
    "chopsticks": 0,
    "spoon": 1,
    "fork": 2,
    "knife": 3,
}


def convert_one(json_path: Path, img_path: Path, out_dir: Path, prefix: str) -> int:
    """Convert a single JSON annotation file to YOLO txt. Returns box count."""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    w = data.get("imageWidth")
    h = data.get("imageHeight")
    if not w or not h:
        return 0

    lines = []
    unknown_labels = set()
    for shape in data.get("shapes", []):
        if shape.get("shape_type") != "rectangle":
            continue
        label = (shape.get("label") or "").strip()
        if label not in LABEL_TO_CLASS:
            unknown_labels.add(label)
            continue

        points = shape.get("points", [])
        if len(points) != 2:
            continue

        (x1, y1), (x2, y2) = points
        xmin, xmax = min(x1, x2), max(x1, x2)
        ymin, ymax = min(y1, y2), max(y1, y2)

        cx = (xmin + xmax) / 2 / w
        cy = (ymin + ymax) / 2 / h
        bw = (xmax - xmin) / w
        bh = (ymax - ymin) / h

        if bw <= 0 or bh <= 0:
            continue

        cx = max(0.0, min(1.0, cx))
        cy = max(0.0, min(1.0, cy))
        bw = max(0.0, min(1.0, bw))
        bh = max(0.0, min(1.0, bh))

        cls = LABEL_TO_CLASS[label]
        lines.append(f"{cls} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")

    if unknown_labels:
        print(f"  警告: {json_path.name} 有未识别标签 {unknown_labels}")

    stem = f"{prefix}{img_path.stem}"
    ext = img_path.suffix.lower()
    shutil.copy2(img_path, out_dir / "images" / f"{stem}{ext}")
    (out_dir / "labels" / f"{stem}.txt").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    return len(lines)


def main():
    valid_sources = []
    for src in SOURCE_DIRS:
        if src.exists():
            valid_sources.append(src)
        else:
            print(f"跳过（不存在）: {src}")

    if not valid_sources:
        print("没有有效的标注目录")
        return

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    for sub in ["images", "labels"]:
        (OUTPUT_DIR / sub).mkdir(parents=True, exist_ok=True)

    total_boxes = 0
    total_pairs = 0
    class_counter = Counter()

    for src in valid_sources:
        prefix = f"{src.name}_"
        pairs = []
        for json_file in sorted(src.glob("*.json")):
            img_file = json_file.with_suffix(".jpg")
            if not img_file.exists():
                img_file = json_file.with_suffix(".png")
            if img_file.exists():
                pairs.append((json_file, img_file))
            else:
                print(f"跳过（无对应图片）: {json_file.name}")

        print(f"处理 {src.name}: {len(pairs)} 张")

        for json_file, img_file in pairs:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)
            for shape in data.get("shapes", []):
                label = (shape.get("label") or "").strip()
                class_counter[label] += 1

            n = convert_one(json_file, img_file, OUTPUT_DIR, prefix)
            total_boxes += n
            total_pairs += 1

    print(f"\n转换完成:")
    print(f"  图片数: {total_pairs}")
    print(f"  标注框数: {total_boxes}")
    print(f"  标签分布: {dict(class_counter)}")
    print(f"  输出目录: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
