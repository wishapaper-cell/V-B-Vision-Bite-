"""Download COCO utensil images (fork, knife, spoon) and convert to YOLO format.

Only downloads images that contain fork/knife/spoon annotations (~672 images),
not the full COCO dataset.

Usage:
    python download_coco_utensils.py

Output:
    datasets/coco_utensils/
        images/
            *.jpg
        labels/
            *.txt
        utensil_classes.yaml
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.request
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.environ.get("COCO_UTENSIL_DIR", str(SCRIPT_DIR / "datasets" / "coco_utensils")))

# COCO category IDs for utensils
COCO_UTENSIL_CATEGORIES = {
    48: "fork",
    49: "knife",
    50: "spoon",
}

# Remap to our YOLO class IDs
# chopsticks=0, spoon=1, fork=2, knife=3
YOLO_CLASS_MAP = {
    "fork": 2,
    "knife": 3,
    "spoon": 1,
}

COCO_ANN_URL = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
COCO_IMG_BASE = "http://images.cocodataset.org/train2017/"


def download_file(url: str, dest: Path) -> bool:
    try:
        urllib.request.urlretrieve(url, dest)
        return True
    except Exception as e:
        print(f"下载失败 {url}: {e}")
        return False


def main():
    import zipfile

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "images").mkdir(exist_ok=True)
    (OUTPUT_DIR / "labels").mkdir(exist_ok=True)

    # Step 1: Download COCO annotations
    ann_zip = OUTPUT_DIR / "annotations_trainval2017.zip"
    ann_dir = OUTPUT_DIR / "annotations"
    ann_file = ann_dir / "annotations" / "instances_train2017.json"
    if not ann_file.exists():
        print("下载 COCO 标注文件 (~250MB)...")
        if not download_file(COCO_ANN_URL, ann_zip):
            print("下载失败，请检查网络")
            sys.exit(1)
        print("解压标注文件...")
        with zipfile.ZipFile(ann_zip, "r") as zf:
            zf.extractall(ann_dir)
        ann_zip.unlink()
    else:
        print("标注文件已存在，跳过下载")

    print(f"加载标注文件...")
    with open(ann_file, encoding="utf-8") as f:
        coco = json.load(f)

    # Build category map
    cat_id_to_name = {}
    for cat in coco["categories"]:
        if cat["id"] in COCO_UTENSIL_CATEGORIES:
            cat_id_to_name[cat["id"]] = cat["name"]

    print(f"目标类别: {cat_id_to_name}")

    # Find images with utensil annotations
    utensil_image_ids = set()
    annotations_by_image = {}

    for ann in coco["annotations"]:
        if ann["category_id"] in COCO_UTENSIL_CATEGORIES:
            img_id = ann["image_id"]
            utensil_image_ids.add(img_id)
            if img_id not in annotations_by_image:
                annotations_by_image[img_id] = []
            cat_name = COCO_UTENSIL_CATEGORIES[ann["category_id"]]
            annotations_by_image[img_id].append({
                "category": cat_name,
                "bbox": ann["bbox"],  # [x, y, width, height]
                "area": ann["area"],
            })

    print(f"找到 {len(utensil_image_ids)} 张含餐具的图片")

    # Build image info map
    image_info = {}
    for img in coco["images"]:
        if img["id"] in utensil_image_ids:
            image_info[img["id"]] = img

    # Step 3: Download images and convert annotations
    success = 0
    fail = 0

    for i, img_id in enumerate(sorted(utensil_image_ids)):
        if (i + 1) % 50 == 0:
            print(f"  下载进度: {i+1}/{len(utensil_image_ids)}")

        info = image_info[img_id]
        file_name = info["file_name"]
        img_url = COCO_IMG_BASE + file_name
        img_path = OUTPUT_DIR / "images" / file_name
        label_path = OUTPUT_DIR / "labels" / (Path(file_name).stem + ".txt")

        if label_path.exists():
            success += 1
            continue

        if not download_file(img_url, img_path):
            fail += 1
            continue

        # Convert bbox to YOLO format
        w, h = info["width"], info["height"]
        lines = []
        for ann in annotations_by_image[img_id]:
            cat_name = ann["category"]
            yolo_cls = YOLO_CLASS_MAP[cat_name]
            x, y, bw, bh = ann["bbox"]
            # YOLO format: class_id x_center y_center width height (normalized)
            x_center = (x + bw / 2) / w
            y_center = (y + bh / 2) / h
            bw_norm = bw / w
            bh_norm = bh / h
            lines.append(f"{yolo_cls} {x_center:.6f} {y_center:.6f} {bw_norm:.6f} {bh_norm:.6f}")

        label_path.write_text("\n".join(lines), encoding="utf-8")
        success += 1

    print(f"\n下载完成: 成功 {success}, 失败 {fail}")

    # Step 4: Generate YAML
    yaml_content = f"""path: {OUTPUT_DIR.as_posix()}
train: images
val: images

nc: 4
names:
  0: chopsticks
  1: spoon
  2: fork
  3: knife
"""
    yaml_path = OUTPUT_DIR / "utensil_classes.yaml"
    yaml_path.write_text(yaml_content, encoding="utf-8")
    print(f"配置文件: {yaml_path}")

    # Statistics
    from collections import Counter
    class_counts = Counter()
    for img_id in utensil_image_ids:
        for ann in annotations_by_image[img_id]:
            class_counts[ann["category"]] += 1
    print(f"\n标注统计:")
    for name, count in sorted(class_counts.items()):
        print(f"  {name}: {count} 个标注")


if __name__ == "__main__":
    main()
