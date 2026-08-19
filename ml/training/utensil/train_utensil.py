"""Train YOLOv11n detection model on merged utensil dataset.

Classes:
    0 chopsticks
    1 spoon
    2 fork
    3 knife

Prerequisites:
    python convert_anylabeling.py
    python download_coco_utensils.py
    python merge_utensil_data.py

Usage:
    python train_utensil.py

Hardware:
    RTX 4050 (6GB VRAM): batch=16, imgsz=640
    RTX 4090 (24GB):     batch=32
    CPU fallback:        batch=4, imgsz=512
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import torch
from ultralytics import YOLO


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR / "runs"
DATASET_YAML = SCRIPT_DIR / "datasets" / "utensils_merged" / "utensil.yaml"
BASE_MODEL = SCRIPT_DIR / "yolo11n.pt"


def main():
    if not DATASET_YAML.exists():
        print(f"数据集未找到: {DATASET_YAML}")
        print("请先运行: convert_anylabeling.py -> download_coco_utensils.py -> merge_utensil_data.py")
        sys.exit(1)

    if not BASE_MODEL.exists():
        print(f"下载基础模型 yolo11n.pt ...")
        import urllib.request
        url = "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11n.pt"
        urllib.request.urlretrieve(url, BASE_MODEL)
        print(f"已下载: {BASE_MODEL}")

    device = 0 if torch.cuda.is_available() else "cpu"
    vram_gb = 0
    if device == 0:
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        print(f"GPU: {torch.cuda.get_device_name(0)}, {vram_gb:.1f} GB")
    else:
        print("使用 CPU 训练（会很慢）")

    if vram_gb >= 20:
        batch = 32
        imgsz = 640
    elif vram_gb >= 5:
        batch = 16
        imgsz = 640
    else:
        batch = 4
        imgsz = 512

    print(f"训练参数: batch={batch}, imgsz={imgsz}, device={device}")
    print(f"数据集: {DATASET_YAML}")
    print(f"基础模型: {BASE_MODEL}")

    model = YOLO(str(BASE_MODEL))
    results = model.train(
        data=str(DATASET_YAML),
        epochs=150,
        imgsz=imgsz,
        batch=batch,
        device=device,
        patience=30,
        workers=4,
        amp=False,
        project=str(PROJECT_DIR),
        name="utensil_det_v1",
        exist_ok=True,
        task="detect",
    )

    best = PROJECT_DIR / "utensil_det_v1" / "weights" / "best.pt"
    print(f"\n训练完成! 最佳模型: {best}")
    print(f"复制部署: cp {best} ../../demo/models/utensil_det_v1.pt")


if __name__ == "__main__":
    main()
