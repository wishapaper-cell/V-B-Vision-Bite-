"""Merge chopstick annotations with COCO utensil data into one YOLO dataset.

Inputs:
    datasets/chopsticks_yolo/     (from convert_anylabeling.py)
    datasets/coco_utensils/       (from download_coco_utensils.py)

Output:
    datasets/utensils_merged/
        images/train/   images/val/
        labels/train/   labels/val/
        utensil.yaml

Train/val split: 9:1 per source, stratified by source.

Usage:
    python merge_utensil_data.py
"""
from __future__ import annotations

import random
import shutil
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
CHOPSTICKS_DIR = SCRIPT_DIR / "datasets" / "chopsticks_yolo"
COCO_DIR = SCRIPT_DIR / "datasets" / "coco_utensils"
OUTPUT_DIR = SCRIPT_DIR / "datasets" / "utensils_merged"

VAL_RATIO = 0.1
RANDOM_SEED = 42


def collect_pairs(img_dir: Path, label_dir: Path) -> list[tuple[Path, Path]]:
    pairs = []
    for label_file in sorted(label_dir.glob("*.txt")):
        stem = label_file.stem
        for ext in (".jpg", ".jpeg", ".png"):
            img = img_dir / f"{stem}{ext}"
            if img.exists():
                pairs.append((img, label_file))
                break
    return pairs


def split_pairs(pairs: list, val_ratio: float, rng: random.Random):
    pairs = list(pairs)
    rng.shuffle(pairs)
    n_val = max(1, int(len(pairs) * val_ratio))
    return pairs[n_val:], pairs[:n_val]


def copy_pairs(pairs, img_out: Path, lbl_out: Path, prefix: str = ""):
    img_out.mkdir(parents=True, exist_ok=True)
    lbl_out.mkdir(parents=True, exist_ok=True)
    for img, lbl in pairs:
        stem = f"{prefix}{img.stem}"
        ext = img.suffix.lower()
        shutil.copy2(img, img_out / f"{stem}{ext}")
        shutil.copy2(lbl, lbl_out / f"{stem}.txt")


def main():
    if not CHOPSTICKS_DIR.exists():
        print(f"请先运行 convert_anylabeling.py（未找到 {CHOPSTICKS_DIR}）")
        return
    if not COCO_DIR.exists():
        print(f"请先运行 download_coco_utensils.py（未找到 {COCO_DIR}）")
        return

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)

    chop_pairs = collect_pairs(CHOPSTICKS_DIR / "images", CHOPSTICKS_DIR / "labels")
    coco_pairs = collect_pairs(COCO_DIR / "images", COCO_DIR / "labels")

    print(f"筷子数据: {len(chop_pairs)} 张")
    print(f"COCO 餐具: {len(coco_pairs)} 张")

    rng = random.Random(RANDOM_SEED)
    chop_train, chop_val = split_pairs(chop_pairs, VAL_RATIO, rng)
    coco_train, coco_val = split_pairs(coco_pairs, VAL_RATIO, rng)

    copy_pairs(
        chop_train,
        OUTPUT_DIR / "images" / "train",
        OUTPUT_DIR / "labels" / "train",
        prefix="chop_",
    )
    copy_pairs(
        chop_val,
        OUTPUT_DIR / "images" / "val",
        OUTPUT_DIR / "labels" / "val",
        prefix="chop_",
    )
    copy_pairs(
        coco_train,
        OUTPUT_DIR / "images" / "train",
        OUTPUT_DIR / "labels" / "train",
        prefix="coco_",
    )
    copy_pairs(
        coco_val,
        OUTPUT_DIR / "images" / "val",
        OUTPUT_DIR / "labels" / "val",
        prefix="coco_",
    )

    yaml_content = f"""path: {OUTPUT_DIR.as_posix()}
train: images/train
val: images/val

nc: 4
names:
  0: chopsticks
  1: spoon
  2: fork
  3: knife
"""
    yaml_path = OUTPUT_DIR / "utensil.yaml"
    yaml_path.write_text(yaml_content, encoding="utf-8")

    print(f"\n合并完成:")
    print(f"  训练集: {len(chop_train) + len(coco_train)} 张")
    print(f"    - 筷子: {len(chop_train)}")
    print(f"    - COCO 餐具: {len(coco_train)}")
    print(f"  验证集: {len(chop_val) + len(coco_val)} 张")
    print(f"    - 筷子: {len(chop_val)}")
    print(f"    - COCO 餐具: {len(coco_val)}")
    print(f"  配置: {yaml_path}")

    from collections import Counter
    counter = Counter()
    for split in ["train", "val"]:
        lbl_dir = OUTPUT_DIR / "labels" / split
        for lbl in lbl_dir.glob("*.txt"):
            for line in lbl.read_text(encoding="utf-8").splitlines():
                cls = int(line.split()[0])
                counter[cls] += 1

    names = {0: "chopsticks", 1: "spoon", 2: "fork", 3: "knife"}
    print(f"\n标注框统计:")
    for cls, name in names.items():
        print(f"  {name}: {counter.get(cls, 0)}")


if __name__ == "__main__":
    main()
