from __future__ import annotations

import sys

import cv2
import numpy as np
from PIL import Image


def main(path: str) -> None:
    arr = np.array(Image.open(path).convert("RGB").resize((480, 640)))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    height, width = gray.shape
    edges = cv2.Canny(gray, 70, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=45, minLineLength=max(24, width // 20), maxLineGap=8)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rects = 0
    small_rects = 0
    min_area = max(60, int(width * height * 0.0008))
    max_area = int(width * height * 0.08)
    for contour in contours[:1000]:
        area = cv2.contourArea(contour)
        if min_area <= area <= max_area:
            x, y, w, h = cv2.boundingRect(contour)
            aspect = w / max(h, 1)
            extent = area / max(w * h, 1)
            if 0.25 <= aspect <= 6.0 and extent > 0.18:
                rects += 1
            if 60 <= area <= 3500 and 0.3 <= aspect <= 5 and extent > 0.18:
                small_rects += 1
    print(
        {
            "low_sat": float((sat < 45).mean()),
            "dark": float((val < 100).mean()),
            "edge_density": float((edges > 0).mean()),
            "lines": 0 if lines is None else len(lines),
            "rects": rects,
            "small_rects": small_rects,
            "contours": len(contours),
            "mean_sat": float(sat.mean()),
            "mean_val": float(val.mean()),
            "reject_many_keyboard_shapes": rects >= 18 and (0 if lines is None else len(lines)) >= 60 and float((edges > 0).mean()) > 0.035,
            "reject_mostly_dark_device": float((val < 100).mean()) > 0.48 and float((sat < 45).mean()) > 0.6 and rects >= 9,
            "reject_black_keyboard_like": float((val < 100).mean()) > 0.62 and (0 if lines is None else len(lines)) >= 80 and rects >= 18,
        }
    )


if __name__ == "__main__":
    main(sys.argv[1])
