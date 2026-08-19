from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np


GRID_SIZE = 8
WARP_SIZE = 224
DEFAULT_SEED_SIGNATURE = np.asarray(
    [
        [0.1, 0, 0, 0, 0.1, 0.1, 0.1, 0.1],
        [0.1, 0.7, 0.3, 0, 0, 0, 0, 0],
        [0, 0.7, 0.3, 0, 0.3, 0.6, 0.5, 0],
        [0, 0.3, 0.5, 0.5, 0.7, 0.9, 0.7, 0],
        [0, 0.4, 0.5, 0.5, 0.5, 0.7, 0.7, 0],
        [0, 0.5, 0.4, 0.1, 0.1, 0.5, 0.7, 0],
        [0, 0, 0.6, 0.3, 0.4, 0.8, 0.6, 0.1],
        [0.1, 0, 0, 0, 0, 0, 0, 0.1],
    ],
    dtype=np.float32,
)


def train(positive_paths: list[Path], output: Path, min_pattern_score: float = 0.78) -> dict[str, object]:
    features: list[np.ndarray] = []
    scores: list[float] = []
    for path in positive_paths:
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError(f"Cannot read positive image: {path}")
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        feature, score = _best_marker_feature(gray, DEFAULT_SEED_SIGNATURE)
        if feature is None or score < 0.72:
            raise ValueError(f"No valid reference marker found in {path}; best score={score:.3f}")
        features.append(feature)
        scores.append(score)

    signature = np.mean(features, axis=0)
    model: dict[str, object] = {
        "version": 1,
        "marker_type": "adventurex_custom_50mm",
        "marker_id": 5001,
        "marker_size_mm": 50.0,
        "min_pattern_score": min_pattern_score,
        "training_positive_scores": [round(float(score), 4) for score in scores],
        "signature": [[round(float(value), 4) for value in row] for row in signature],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return model


def _best_marker_feature(gray: np.ndarray, signature: np.ndarray) -> tuple[np.ndarray | None, float]:
    scale = min(1.0, 1280 / max(gray.shape[:2]))
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    frame_area = max(1, small.shape[0] * small.shape[1])
    kernel = np.ones((5, 5), dtype=np.uint8)
    best_feature: np.ndarray | None = None
    best_score = -1.0
    for threshold in (50, 70, 90, 110, 130, 150, 170):
        _, binary = cv2.threshold(small, threshold, 255, cv2.THRESH_BINARY_INV)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if not 0.00015 <= area / frame_area <= 0.25:
                continue
            perimeter = float(cv2.arcLength(contour, True))
            quad = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
            if len(quad) != 4 or not cv2.isContourConvex(quad):
                continue
            points = quad.reshape(4, 2).astype(np.float32)
            edges = [float(np.linalg.norm(points[i] - points[(i + 1) % 4])) for i in range(4)]
            rect_w, rect_h = cv2.minAreaRect(contour)[1]
            if min(edges) < 20 or min(edges) / max(edges) < 0.48 or area / max(rect_w * rect_h, 1e-6) < 0.68:
                continue
            feature, score = _oriented_feature(small, points, signature)
            if score > best_score:
                best_feature, best_score = feature, score
    return best_feature, best_score


def _oriented_feature(gray: np.ndarray, points: np.ndarray, signature: np.ndarray) -> tuple[np.ndarray, float]:
    destination = np.float32([[0, 0], [223, 0], [223, 223], [0, 223]])
    warped = cv2.warpPerspective(gray, cv2.getPerspectiveTransform(_order(points), destination), (WARP_SIZE, WARP_SIZE))
    low, high = float(np.percentile(warped, 15)), float(np.percentile(warped, 88))
    best_feature = np.zeros((GRID_SIZE, GRID_SIZE), dtype=np.float32)
    best_score = -1.0
    for rotation in range(4):
        rotated = np.rot90(warped, rotation)
        normalized = np.clip((rotated.astype(np.float32) - low) / max(high - low, 1e-6), 0, 1)
        feature = normalized.reshape(GRID_SIZE, 28, GRID_SIZE, 28).mean(axis=(1, 3))
        score = float(np.corrcoef(feature.reshape(-1), signature.reshape(-1))[0, 1])
        if score > best_score:
            best_feature, best_score = feature, score
    return best_feature, best_score


def _order(points: np.ndarray) -> np.ndarray:
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    return np.float32(
        [points[np.argmin(sums)], points[np.argmin(differences)], points[np.argmax(sums)], points[np.argmax(differences)]]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the compact AdventureX 50 mm reference-marker appearance model.")
    parser.add_argument("positives", nargs="+", type=Path, help="Real photographs containing one complete marker.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("services/recognition/models/reference_marker_v1.json"),
    )
    parser.add_argument("--min-pattern-score", type=float, default=0.78)
    args = parser.parse_args()
    model = train(args.positives, args.output, args.min_pattern_score)
    print(f"trained {len(args.positives)} positives -> {args.output}")
    print(f"positive scores: {model['training_positive_scores']}")


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(2) from exc
