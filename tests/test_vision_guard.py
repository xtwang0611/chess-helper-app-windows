import unittest

import cv2
import numpy as np

from app.chess.checker import PositionChecker
from app.chess.processor import ChessProcess
from app.chess.recognizer import RecognitionErrorType
from app.chess.vision_guard import detect_board_grid, frame_contains_board, frame_quality, validate_board_region


class VisionGuardTests(unittest.TestCase):
    def test_rejects_whole_portrait_window(self):
        window = {"left": 10, "top": 20, "width": 491, "height": 930}
        ok, reason = validate_board_region(dict(window), window)
        self.assertFalse(ok)
        self.assertIn(reason, {"bad-aspect:0.528", "whole-window"})

    def test_rejects_black_frame(self):
        ok, reason = frame_quality(np.zeros((400, 400, 3), dtype=np.uint8))
        self.assertFalse(ok)
        self.assertEqual(reason, "black")

    def test_detects_synthetic_endgame_grid_without_pieces(self):
        image = np.full((640, 600, 3), 205, dtype=np.uint8)
        x0, y0, spacing = 100, 80, 48
        for col in range(9):
            cv2.line(image, (x0 + col * spacing, y0), (x0 + col * spacing, y0 + 9 * spacing), (30, 30, 30), 2)
        for row in range(10):
            cv2.line(image, (x0, y0 + row * spacing), (x0 + 8 * spacing, y0 + row * spacing), (30, 30, 30), 2)
        region = detect_board_grid(image)
        self.assertIsNotNone(region)
        left, top, width, height = region
        self.assertLessEqual(abs(left - (x0 - spacing // 2)), 5)
        self.assertLessEqual(abs(top - (y0 - spacing // 2)), 5)
        self.assertLessEqual(abs(width - 9 * spacing), 8)
        self.assertLessEqual(abs(height - 10 * spacing), 8)

    def test_detects_grid_with_river_break_and_piece_occlusion(self):
        image = np.full((900, 500, 3), 190, dtype=np.uint8)
        x0, y0, spacing = 38, 220, 53
        for col in range(9):
            x = x0 + col * spacing
            cv2.line(image, (x, y0), (x, y0 + 4 * spacing), (35, 35, 35), 2)
            cv2.line(image, (x, y0 + 5 * spacing), (x, y0 + 9 * spacing), (35, 35, 35), 2)
        for row in range(10):
            y = y0 + row * spacing
            cv2.line(image, (x0, y), (x0 + 8 * spacing, y), (35, 35, 35), 2)
        # Pieces hide portions of several grid lines in real endgames.
        for center in [(x0 + spacing, y0 + spacing), (x0 + 4 * spacing, y0 + 2 * spacing),
                       (x0 + 2 * spacing, y0 + 7 * spacing)]:
            cv2.circle(image, center, 24, (205, 160, 90), -1)
            cv2.circle(image, center, 24, (60, 60, 60), 2)
        self.assertIsNotNone(detect_board_grid(image))

    def test_detects_strong_board_outline_when_grid_is_obscured(self):
        image = np.full((940, 500, 3), 85, dtype=np.uint8)
        cv2.rectangle(image, (5, 200), (495, 748), (205, 155, 90), -1)
        cv2.rectangle(image, (5, 200), (495, 748), (30, 30, 30), 3)
        # Deliberately omit the grid; outline fallback must still find the board.
        region = detect_board_grid(image)
        self.assertIsNotNone(region)
        self.assertLessEqual(abs(region[0] - 5), 4)
        self.assertLessEqual(abs(region[1] - 200), 4)

    def test_board_frame_guard_rejects_unrelated_text_content(self):
        image = np.full((540, 490, 3), 250, dtype=np.uint8)
        for y in range(40, 500, 55):
            cv2.putText(image, "not a chess board", (15, y), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (30, 30, 30), 2)
        self.assertFalse(frame_contains_board(image))


class SettlementDebounceTests(unittest.TestCase):
    def setUp(self):
        self.checker = PositionChecker()
        self.one_king = [["-"] * 9 for _ in range(10)]
        self.one_king[0][4] = "k"

    def test_single_bad_frame_does_not_settle(self):
        self.assertFalse(self.checker.check_settlement(self.one_king, True))
        self.assertFalse(self.checker.in_settlement_screen)

    def test_settlement_requires_three_frames_and_recovers(self):
        self.assertFalse(self.checker.check_settlement(self.one_king, True))
        self.assertFalse(self.checker.check_settlement(self.one_king, True))
        self.assertTrue(self.checker.check_settlement(self.one_king, True))
        valid = [["-"] * 9 for _ in range(10)]
        valid[0][4], valid[9][4] = "k", "K"
        self.assertTrue(self.checker.check_settlement(valid, False))
        self.assertFalse(self.checker.check_settlement(valid, False))

    def test_invalid_frame_is_not_settlement_evidence(self):
        self.checker.check_settlement(self.one_king, True)
        self.checker.check_settlement(None, False, frame_valid=False)
        self.checker.check_settlement(self.one_king, True)
        self.assertFalse(self.checker.in_settlement_screen)


class RecognitionPolicyTests(unittest.TestCase):
    def test_missing_marker_is_not_a_fatal_recognition_error(self):
        self.assertFalse(ChessProcess._is_fatal_recognition_error(RecognitionErrorType.MARKER_MISSING))
        self.assertFalse(ChessProcess._is_fatal_recognition_error(RecognitionErrorType.LOW_CONFIDENCE))
        self.assertTrue(ChessProcess._is_fatal_recognition_error(RecognitionErrorType.COVERED))


if __name__ == "__main__":
    unittest.main()
