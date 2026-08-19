#!/bin/bash
# One-click utensil model training on 矩池云 (or any GPU cloud)
#
# Workflow:
#   1. Download COCO utensil images (fork/knife/spoon)
#   2. Merge with pre-converted chopstick data
#   3. Train YOLOv11n detection model
#
# Usage:
#   1. Upload utensil_training_pack.zip to cloud, unzip to /root/utensil_training/
#   2. bash cloud_train.sh
#
# Expected:
#   - ~30 min download COCO
#   - ~2 hours training on RTX 4090
#   - best model at runs/utensil_det_v1/weights/best.pt

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Step 1: Install dependencies ==="
pip install --quiet ultralytics opencv-python-headless -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com

echo ""
echo "=== Step 2: Download COCO utensil data (~672 images) ==="
python download_coco_utensils.py

echo ""
echo "=== Step 3: Merge chopsticks + COCO ==="
python merge_utensil_data.py

echo ""
echo "=== Step 4: Train YOLOv11n detection model ==="
python train_utensil.py

echo ""
echo "=== Done ==="
BEST="runs/utensil_det_v1/weights/best.pt"
if [ -f "$BEST" ]; then
    ls -lh "$BEST"
    echo "Download this file to deploy: demo/models/utensil_det_v1.pt"
fi
