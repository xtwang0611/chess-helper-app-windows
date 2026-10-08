"""Run board geometry detection against a saved screenshot."""
import argparse
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.chess.vision_guard import detect_board_grid, frame_quality


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--output")
    args = parser.parse_args()
    image = cv2.imread(args.image)
    if image is None:
        raise SystemExit(f"cannot read {args.image}")
    print("shape:", image.shape)
    print("quality:", frame_quality(image))
    region = detect_board_grid(image)
    print("board:", region)
    if region and args.output:
        x, y, w, h = region
        cv2.rectangle(image, (x, y), (x + w, y + h), (0, 0, 255), 3)
        cv2.imwrite(args.output, image)


if __name__ == "__main__":
    main()
