"""Lightweight screenshot quality and board geometry checks.

This module deliberately has no application-context or model dependency so the
rules can be exercised with synthetic, repeatable tests.
"""
from __future__ import annotations

from typing import Mapping, Optional, Sequence, Tuple

import cv2
import numpy as np


BOARD_MIN_WIDTH = 180
BOARD_MIN_HEIGHT = 200
BOARD_ASPECT_RANGE = (0.72, 1.08)


def screenshot_to_bgr(frame) -> np.ndarray:
    if isinstance(frame, np.ndarray):
        image = frame
    else:
        image = np.frombuffer(frame.bgra, np.uint8).reshape(frame.height, frame.width, 4)
    if image.ndim != 3 or image.shape[2] < 3:
        raise ValueError("截图格式无效")
    return image[:, :, :3].copy()


def frame_quality(image: np.ndarray) -> Tuple[bool, str]:
    """Reject black/blank/covered frames before recognition or settlement."""
    if image is None or image.size == 0 or image.ndim != 3:
        return False, "empty"
    gray = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY)
    mean = float(gray.mean())
    std = float(gray.std())
    dark_ratio = float(np.mean(gray < 8))
    clipped_ratio = float(max(np.mean(gray < 3), np.mean(gray > 252)))
    edge_ratio = float(np.mean(cv2.Canny(gray, 40, 120) > 0))
    if mean < 5 or dark_ratio > 0.97:
        return False, "black"
    if std < 3.0 or clipped_ratio > 0.985:
        return False, "blank"
    if edge_ratio < 0.002:
        return False, "low-texture"
    return True, "ok"


def validate_board_region(region: Mapping[str, int], window: Optional[Mapping[str, int]] = None) -> Tuple[bool, str]:
    try:
        left, top = int(region["left"]), int(region["top"])
        width, height = int(region["width"]), int(region["height"])
    except (KeyError, TypeError, ValueError):
        return False, "missing-fields"
    if width < BOARD_MIN_WIDTH or height < BOARD_MIN_HEIGHT:
        return False, "too-small"
    ratio = width / float(height)
    if not BOARD_ASPECT_RANGE[0] <= ratio <= BOARD_ASPECT_RANGE[1]:
        return False, f"bad-aspect:{ratio:.3f}"
    if window:
        wl, wt = int(window["left"]), int(window["top"])
        wr, wb = wl + int(window["width"]), wt + int(window["height"])
        if left < wl or top < wt or left + width > wr or top + height > wb:
            return False, "outside-window"
        # A whole portrait game window is not a board.
        if width > int(window["width"] * 0.96) and height > int(window["height"] * 0.96):
            return False, "whole-window"
    return True, "ok"


def _cluster(values: Sequence[int], tolerance: int) -> list[int]:
    if not values:
        return []
    groups = [[int(sorted(values)[0])]]
    for value in sorted(values)[1:]:
        if value - groups[-1][-1] <= tolerance:
            groups[-1].append(int(value))
        else:
            groups.append([int(value)])
    return [int(round(float(np.median(group)))) for group in groups]


def _best_regular_run(values: Sequence[int], count: int) -> Optional[list[int]]:
    values = sorted(values)
    if len(values) < count:
        return None
    best, best_score = None, float("inf")
    for start in range(len(values) - count + 1):
        run = values[start:start + count]
        gaps = np.diff(run).astype(float)
        mean = float(gaps.mean())
        if mean < 12:
            continue
        score = float(gaps.std() / mean)
        if score < best_score:
            best, best_score = run, score
    return best if best_score <= 0.22 else None


def detect_board_grid(image: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """Locate a Xiangqi board from its regular 9-column/10-row grid."""
    valid, _ = frame_quality(image)
    if not valid:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(gray, 45, 135)
    h, w = gray.shape
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=max(35, min(w, h) // 8),
                            minLineLength=max(70, min(w, h) // 3), maxLineGap=max(8, min(w, h) // 30))
    if lines is None:
        return None
    vertical, horizontal = [], []
    for x1, y1, x2, y2 in lines[:, 0]:
        dx, dy = abs(x2 - x1), abs(y2 - y1)
        if dy >= h * 0.28 and dx <= max(4, dy * 0.04):
            vertical.append((x1 + x2) // 2)
        elif dx >= w * 0.28 and dy <= max(4, dx * 0.04):
            horizontal.append((y1 + y2) // 2)
    tolerance = max(3, min(w, h) // 150)
    xs = _best_regular_run(_cluster(vertical, tolerance), 9)
    ys = _best_regular_run(_cluster(horizontal, tolerance), 10)
    if xs is None or ys is None:
        return None
    sx, sy = float(np.median(np.diff(xs))), float(np.median(np.diff(ys)))
    if abs(sx - sy) / max(sx, sy) > 0.25:
        return None
    left = int(round(xs[0] - sx / 2))
    top = int(round(ys[0] - sy / 2))
    right = int(round(xs[-1] + sx / 2))
    bottom = int(round(ys[-1] + sy / 2))
    left, top = max(0, left), max(0, top)
    right, bottom = min(w, right), min(h, bottom)
    region = {"left": left, "top": top, "width": right - left, "height": bottom - top}
    return (left, top, right - left, bottom - top) if validate_board_region(region)[0] else None
