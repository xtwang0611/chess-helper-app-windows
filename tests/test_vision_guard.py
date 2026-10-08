import unittest

import cv2
import numpy as np

from app.chess.checker import PositionChecker
from app.chess.vision_guard import detect_board_grid, frame_quality, validate_board_region


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


if __name__ == "__main__":
    unittest.main()
