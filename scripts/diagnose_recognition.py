"""Offline replay: no desktop capture, no engine, no saved configuration changes.

python scripts/diagnose_recognition.py board.png --platform TT
For a desktop screenshot: --crop LEFT TOP WIDTH HEIGHT
Prints grid coordinates, uncertain cells and the recognized board as JSON.
"""
import argparse
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.chess.grid_recognition import GridClassifier
from app.chess.piece_recognizer import ChessPieceRecognizer
from app.chess.session import BoardSession
from app.chess.checker import PositionChecker
from app.chess.vision_guard import detect_board_grid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    parser.add_argument('--platform', choices=('TT', 'JJ'), default='TT')
    parser.add_argument('--crop', nargs=4, type=int, metavar=('LEFT', 'TOP', 'WIDTH', 'HEIGHT'))
    parser.add_argument('--details', action='store_true', help='Print all 90 square probability candidates')
    parser.add_argument('--locate', action='store_true', help='Locate board within image (after --crop)')
    parser.add_argument('--width', type=int, help='Replay board resized to this pixel width')
    parser.add_argument('--export-crop', type=Path, help='Save only the board crop as a replay fixture')
    args = parser.parse_args()
    image = cv2.imdecode(np.fromfile(args.image, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        parser.error('Cannot read image')
    if args.crop:
        x, y, w, h = args.crop
        if min(x, y) < 0 or min(w, h) <= 0 or y + h > image.shape[0] or x + w > image.shape[1]:
            parser.error('Crop is outside the image')
        image = image[y:y + h, x:x + w]
    located = None
    if args.locate:
        located = detect_board_grid(image)
        if located is None:
            parser.error('No board found in image')
        x, y, w, h = located
        image = image[y:y + h, x:x + w]
    if args.width is not None:
        if args.width < 90:
            parser.error('--width must be at least 90')
        image = cv2.resize(image, (args.width, round(image.shape[0] * args.width / image.shape[1])),
                           interpolation=cv2.INTER_AREA)
    if args.export_crop:
        args.export_crop.parent.mkdir(parents=True, exist_ok=True)
        cv2.imencode('.png', image)[1].tofile(str(args.export_crop))
    config_path = Path(__file__).resolve().parents[1] / 'app/json/game_config.json'
    coords = json.loads(config_path.read_text(encoding='utf-8'))[args.platform]['board_coords']
    model, classifier = ChessPieceRecognizer(args.platform), GridClassifier()
    start = time.perf_counter()
    board, _, uncertain = classifier.recognize(image, coords['x'], coords['y'], model, args.platform)
    duration = time.perf_counter() - start
    session, checker = BoardSession(), PositionChecker()
    if uncertain:
        result = session.invalidate('棋子待确认，不向引擎提交')
    else:
        session.observe(board, checker)
        result = session.observe(board, checker)
    report = classifier.last_report
    if not args.details:
        report['cells'] = [cell for cell in report['cells'] if cell['uncertain'] or cell['piece'] != '-']
    report.update(seconds=round(duration, 3), uncertainty_count=len(uncertain),
                  located_region=located,
                  board_valid=result.accepted, validation=result.reason,
                  analysis_allowed=result.accepted and not uncertain and session.our_turn is True)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
