"""Spectator geometry, real model scale replay and console-noise regression."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.chess.grid_recognition import GridClassifier, centered_crop
from app.chess.piece_recognizer import ChessPieceRecognizer
from app.chess.vision_guard import detect_board_grid
from app.tools.log_config import ConsoleRateLimit

FIXTURES = Path(__file__).parent / 'fixtures'
XS = [45 + i * 89 for i in range(9)]
YS = [47, 138, 227, 316, 405, 494, 583, 672, 761, 850]
EXPECTED = {
    'tt_spectator.png': '---K-A---/----A----/--N-c----/---------/----r----/--b---b-p/p---p----/-----a---/----k----/---R-----',
    'tt_endgame_309.png': '---a-k---/-N-----R-/---abc---/--N------/---------/---------/---------/-n--B----/--p-p----/c--K--B--',
    'tt_endgame_310.png': '--ba-----/---------/-----k---/p-------p/------b--/--Pn-N---/----r---P/-----A---/---K-----/-----A-R-',
}


class SmallBoardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = ChessPieceRecognizer('TT')

    def test_real_boards_at_small_sizes(self):
        for name, expected in EXPECTED.items():
            raw = cv2.imread(str(FIXTURES / name))
            for width in (raw.shape[1], 360, 320, 280, 246):
                with self.subTest(name=name, width=width):
                    image = cv2.resize(raw, (width, round(raw.shape[0] * width / raw.shape[1])),
                                       interpolation=cv2.INTER_AREA)
                    classifier = GridClassifier()
                    board, _, unsure = classifier.recognize(image, XS, YS, self.model, 'TT')
                    self.assertEqual('/'.join(''.join(row) for row in board), expected)
                    self.assertFalse(unsure)

    def test_spectator_false_grid_cannot_extend_into_sidebar(self):
        # Only board pixels are stored; simulate the sidebar's false ninth file.
        image = np.full((941, 501, 3), 90, np.uint8)
        raw = cv2.imread(str(FIXTURES / 'tt_spectator.png'))
        image[68:68 + raw.shape[0], 15:15 + raw.shape[1]] = raw
        false_x = [83 + 42 * i for i in range(9)]
        true_y = [93 + 42 * i for i in range(10)]
        with patch('app.chess.vision_guard._best_regular_run', side_effect=[false_x, true_y]):
            box = detect_board_grid(image)
        self.assertIsNotNone(box)
        x, y, w, h = box
        self.assertLess(abs(x - 15), 5)
        self.assertLess(abs(y - 68), 5)
        classifier = GridClassifier()
        board, _, unsure = classifier.recognize(image[y:y+h, x:x+w], XS, YS, self.model, 'TT')
        self.assertFalse(unsure)
        self.assertEqual('/'.join(''.join(row) for row in board), EXPECTED['tt_spectator.png'])

    def test_small_unreadable_frame_is_not_forced_confident(self):
        raw = cv2.imread(str(FIXTURES / 'tt_endgame_310.png'))
        image = cv2.resize(raw, (197, 219), interpolation=cv2.INTER_AREA)
        classifier = GridClassifier()
        _, _, unsure = classifier.recognize(image, XS, YS, self.model, 'TT')
        self.assertTrue(unsure)
        self.assertLess(classifier.last_report['source_cell_pixels'], 28)

    def test_small_refinement_is_cached_without_repeating_inference(self):
        raw = cv2.imread(str(FIXTURES / 'tt_spectator.png'))
        image = cv2.resize(raw, (246, 272), interpolation=cv2.INTER_AREA)
        classifier = GridClassifier()
        with patch('app.chess.grid_recognition.time.monotonic', return_value=10.):
            first = classifier.recognize(image, XS, YS, self.model, 'TT')
            self.assertGreater(classifier.last_report['refined_squares'], 0)
            second = classifier.recognize(image, XS, YS, self.model, 'TT')
        self.assertEqual(first, second)
        self.assertEqual(classifier.last_report['inferred_squares'], 0)

    def test_scaled_menu_is_still_rejected(self):
        raw = cv2.imread(str(FIXTURES / 'tt_menu_occluded.png'))
        for width in (320, 246):
            image = cv2.resize(raw, (width, round(raw.shape[0]*width/raw.shape[1])),
                               interpolation=cv2.INTER_AREA)
            _, _, unsure = GridClassifier().recognize(image, XS, YS, self.model, 'TT')
            self.assertTrue(unsure)

    def test_disagreeing_retry_crops_do_not_force_a_piece(self):
        class Model:
            calls = 0
            def recognize_batch(self, crops):
                self.calls += 1
                if self.calls == 1:
                    result = [{'class_name': '-', 'confidence': 1.} for _ in crops]
                    result[90] = result[91] = {'class_name': 'r', 'confidence': .51,
                                               'probabilities': {'r': .51, 'n': .49}}
                    return result
                return [{'class_name': p, 'confidence': .99,
                         'probabilities': {p: .99, '-': .01}} for p in ('r', 'r', 'r', 'n', 'n')]
        model = Model()
        classifier = GridClassifier()
        _, _, unsure = classifier.recognize(np.full((333, 300, 3), 180, np.uint8),
                                             XS, YS, model, 'TT')
        self.assertEqual(model.calls, 2)
        self.assertTrue(any(r == 5 and c == 0 for r, c, _, _ in unsure))
        self.assertEqual(classifier.last_report['refined_squares'], 0)

    def test_local_padding_matches_original_at_all_edges(self):
        image = np.random.default_rng(1).integers(0, 256, (60, 50, 3), dtype=np.uint8)
        radius = 12
        padded = cv2.copyMakeBorder(image, radius, radius, radius, radius, cv2.BORDER_REPLICATE)
        for x in (0, 2, 25, 49):
            for y in (0, 2, 30, 59):
                np.testing.assert_array_equal(centered_crop(image, x, y, radius),
                                              padded[y:y+2*radius, x:x+2*radius])

    def test_locator_prefers_grid_and_retries_black_capture(self):
        from app.chess.board_locator import BoardLocator, PieceError, CombsError
        locator = object.__new__(BoardLocator)
        locator.logger = SimpleNamespace(debug=lambda *args: None)
        with patch.object(locator, '_locate_board_from_grid', return_value=(1, 2, 390, 433)), \
                patch.object(locator, '_locate_board_from_combs') as legacy:
            self.assertEqual(locator._locate_board(), (1, 2, 390, 433))
            legacy.assert_not_called()
        with patch.object(locator, '_locate_board_from_grid', side_effect=PieceError('black')), \
                patch.object(locator, '_locate_board_from_combs') as legacy:
            with self.assertRaises(PieceError):
                locator._locate_board()
            legacy.assert_not_called()
        with patch.object(locator, '_locate_board_from_grid', side_effect=CombsError('no grid')), \
                patch.object(locator, '_locate_board_from_combs', return_value=(1, 2, 390, 433)):
            self.assertEqual(locator._locate_board(), (1, 2, 390, 433))


class ConsoleTests(unittest.TestCase):
    def record(self, message, event=None, level='INFO'):
        return {'extra': {'name': 'test', 'event': event}, 'name': 'test',
                'level': SimpleNamespace(name=level), 'message': message}

    def test_fluctuating_uncertain_counts_are_throttled(self):
        clock = [0.]
        limit = ConsoleRateLimit(clock=lambda: clock[0])
        for i in range(20):
            clock[0] = i * .5
            self.assertEqual(limit(self.record(f'{i}处待确认', 'recognition-status')), i == 0)
        clock[0] = 10.
        self.assertTrue(limit(self.record('2处待确认', 'recognition-status')))

    def test_first_distinct_error_visible_and_memory_bounded(self):
        limit = ConsoleRateLimit(clock=lambda: 0.)
        self.assertTrue(limit(self.record('capture failed', level='ERROR')))
        self.assertFalse(limit(self.record('capture failed', level='ERROR')))
        self.assertTrue(limit(self.record('model failed', level='ERROR')))
        for i in range(300):
            limit(self.record(str(i)))
        self.assertLessEqual(len(limit.seen), 256)


if __name__ == '__main__':
    unittest.main()
