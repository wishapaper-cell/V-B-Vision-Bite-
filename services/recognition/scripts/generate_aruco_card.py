from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def build_card(marker_id: int, marker_size_mm: float, dpi: int, output: Path) -> None:
    aruco = cv2.aruco
    dictionary = aruco.getPredefinedDictionary(aruco.DICT_5X5_100)
    marker_px = int(round(marker_size_mm / 25.4 * dpi))
    border_px = int(round(10 / 25.4 * dpi))
    label_px = int(round(14 / 25.4 * dpi))
    card_px = marker_px + border_px * 2
    marker = aruco.generateImageMarker(dictionary, marker_id, marker_px)

    canvas = Image.new("RGB", (card_px, card_px + label_px), "white")
    marker_img = Image.fromarray(marker).convert("RGB")
    canvas.paste(marker_img, (border_px, border_px))

    draw = ImageDraw.Draw(canvas)
    text = f"ArUco 5x5 ID {marker_id} - marker {marker_size_mm:.0f}mm"
    try:
        font = ImageFont.truetype("arial.ttf", max(12, dpi // 18))
    except Exception:
        font = ImageFont.load_default()
    text_box = draw.textbbox((0, 0), text, font=font)
    x = max(0, (card_px - (text_box[2] - text_box[0])) // 2)
    draw.text((x, card_px + max(2, label_px // 5)), text, fill="black", font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, dpi=(dpi, dpi))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate printable 50mm ArUco calibration cards.")
    parser.add_argument("--ids", nargs="+", type=int, default=[23, 42])
    parser.add_argument("--marker-size-mm", type=float, default=50.0)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--output-dir", type=Path, default=Path("assets/calibration_cards"))
    args = parser.parse_args()

    for marker_id in args.ids:
        output = args.output_dir / f"aruco_5x5_100_id_{marker_id}_{int(args.marker_size_mm)}mm.png"
        build_card(marker_id, args.marker_size_mm, args.dpi, output)
        print(output)


if __name__ == "__main__":
    main()
