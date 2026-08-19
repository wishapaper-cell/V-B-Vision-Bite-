"""Download FoodSeg103 dataset from HuggingFace.

Usage:
    python download_data.py

Environment variables:
    FOODSEG_DIR  - override download directory (default: ../../datasets/FoodSeg103)
"""
import os
import sys
from pathlib import Path

DATA_DIR = Path(os.environ.get(
    "FOODSEG_DIR",
    str(Path(__file__).resolve().parents[2] / "datasets" / "FoodSeg103"),
))


def main():
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("安装 huggingface_hub ...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "huggingface_hub"])
        from huggingface_hub import snapshot_download

    DATA_DIR.parent.mkdir(parents=True, exist_ok=True)

    print(f"下载 FoodSeg103 到: {DATA_DIR}")
    print("数据集约 2-3GB，请耐心等待...\n")

    snapshot_download(
        repo_id="EduardoPacheco/FoodSeg103",
        repo_type="dataset",
        local_dir=str(DATA_DIR),
    )

    print(f"\n下载完成: {DATA_DIR}")
    print("目录结构:")
    for item in sorted(DATA_DIR.iterdir()):
        if item.is_dir():
            count = sum(1 for _ in item.rglob("*") if _.is_file())
            print(f"  {item.name}/ ({count} files)")
        else:
            print(f"  {item.name}")


if __name__ == "__main__":
    main()
