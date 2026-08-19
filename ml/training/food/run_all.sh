#!/bin/bash
# FoodSeg103 食物分割模型训练一键脚本
# 适用于矩池云 / AutoDL 等云 GPU 平台，也适用于本地
#
# 用法:
#   bash run_all.sh          # 完整流程：下载 → 转换 → 训练
#   bash run_all.sh --train  # 跳过下载和转换，仅训练（数据已准备好）
#
# 环境变量:
#   BATCH_SIZE  批大小（默认 16，云 GPU 可用 32）
#   EPOCHS      训练轮数（默认 100）
#   IMGSZ       图片尺寸（默认 640）

set -e

cd "$(dirname "$0")"
echo "========================================"
echo "  FoodSeg103 食物分割模型训练"
echo "========================================"
echo "工作目录: $(pwd)"
echo ""

# 检查 GPU
echo "--- GPU 信息 ---"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "未检测到 GPU"
echo ""

# 安装依赖
echo "--- 安装依赖 ---"
pip install -q ultralytics huggingface_hub opencv-python-headless numpy Pillow 2>/dev/null
echo "依赖安装完成"
echo ""

# 步骤 1: 下载数据集
if [ "$1" != "--train" ]; then
    echo "--- 步骤 1/3: 下载 FoodSeg103 ---"
    python download_data.py
    echo ""
else
    echo "--- 跳过下载（--train 模式）---"
    echo ""
fi

# 步骤 2: 转换数据集
if [ "$1" != "--train" ]; then
    echo "--- 步骤 2/3: 转换为 YOLO 格式 ---"
    python convert_foodseg103.py
    echo ""
else
    # 检查 food.yaml 是否存在
    if [ ! -f "food.yaml" ]; then
        echo "错误: food.yaml 不存在，请先运行完整流程"
        exit 1
    fi
    echo "--- 跳过转换（--train 模式）---"
    echo ""
fi

# 步骤 3: 训练
echo "--- 步骤 3/3: 开始训练 ---"
echo "  BATCH_SIZE=${BATCH_SIZE:-16}"
echo "  EPOCHS=${EPOCHS:-100}"
echo "  IMGSZ=${IMGSZ:-640}"
echo ""
python train_food.py

echo ""
echo "========================================"
echo "  训练完成!"
echo "========================================"
echo ""
echo "模型文件: ../runs/food_seg_v1/weights/best.pt"
echo "结果图表: ../runs/food_seg_v1/results.png"
echo ""
echo "下载模型到本地（在本地执行）:"
echo "  scp <云服务器>:<项目路径>/training/runs/food_seg_v1/weights/best.pt D:/code/Diet-identification/demo/models/food_seg_v1.pt"
