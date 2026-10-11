"""Real ONNX screenshot regressions, and asynchronous advice lifecycle tests."""
import copy
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import cv2
import numpy as np

from app.chess.checker import PositionChecker
from app.chess.grid_recognition import GridClassifier
from app.chess.piece_recognizer import ChessPieceRecognizer
from app.chess.processor import ChessProcess, BoardAnalysisState
from app.chess.message import Message, MessageType
from app.chess.session import BoardSession

FIXTURES = Path(__file__).parent / 'fixtures'
XS = [45 + i * 89 for i in range(9)]
YS = [47, 138, 227, 316, 405, 494, 583, 672, 761, 850]
EXPECTED_309 = '---a-k---/-N-----R-/---abc---/--N------/---------/---------/---------/-n--B----/--p-p----/c--K--B--'
EXPECTED_310 = '--ba-----/---------/-----k---/p-------p/------b--/--Pn-N---/----r---P/-----A---/---K-----/-----A-R-'


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = ChessPieceRecognizer('TT')

    def test_complete_real_endgames_and_scaled_versions(self):
        for name, expected in [('tt_endgame_309.png', EXPECTED_309), ('tt_endgame_310.png', EXPECTED_310)]:
            for scale in (1., .8, 1.25):
                with self.subTest(name=name, scale=scale):
                    image = cv2.imread(str(FIXTURES / name))
                    image = cv2.resize(image, None, fx=scale, fy=scale)
                    classifier = GridClassifier()
                    board, _, uncertain = classifier.recognize(image, XS, YS, self.model, 'TT')
                    self.assertEqual('/'.join(''.join(row) for row in board), expected)
                    self.assertFalse(uncertain)

    def test_real_menu_frame_is_not_trusted(self):
        image = cv2.imread(str(FIXTURES / 'tt_menu_occluded.png'))
        classifier = GridClassifier()
        _, _, uncertain = classifier.recognize(image, XS, YS, self.model, 'TT')
        self.assertTrue(uncertain)

    def test_valid_frame_recovers_after_menu_and_cache_reset(self):
        classifier = GridClassifier()
        bad = cv2.imread(str(FIXTURES / 'tt_menu_occluded.png'))
        good = cv2.imread(str(FIXTURES / 'tt_endgame_309.png'))
        classifier.recognize(bad, XS, YS, self.model, 'TT')
        classifier.reset()
        board, _, uncertain = classifier.recognize(good, XS, YS, self.model, 'TT')
        self.assertFalse(uncertain)
        self.assertEqual('/'.join(''.join(row) for row in board), EXPECTED_309)


class FakeContext:
    def __init__(self, engine):
        self.engine = engine
        self.session = BoardSession()
        self.analysis_token = 0
        self.pipeline_lock = threading.RLock()
        self.recognizer = object()
        self.checker = PositionChecker()
        self.history = None
    def get_recognizer(self):
        return self.recognizer
    def invalidate_analysis(self):
        self.analysis_token += 1
        self.engine.stop_analysis()


class DeferredEngine:
    is_initialized = True
    def __init__(self):
        self.started, self.release = threading.Event(), threading.Event()
        self.calls = []
    def stop_analysis(self):
        pass  # Deliberately simulate an engine that delivers a late result anyway.
    def get_bestmove(self, fen, side, callback, **kwargs):
        self.calls.append((fen, side, kwargs))
        self.started.set()
        self.release.wait(2)
        callback(Message(MessageType.STATUS, 'late thinking'))
        return 'a3a4', fen, ['a3a4', 'c3c4']


class TurnAndCallbackTests(unittest.TestCase):
    def setUp(self):
        self.engine = DeferredEngine()
        self.ctx = FakeContext(self.engine)
        self.proc = ChessProcess(self.ctx.checker, self.engine, None, self.ctx)
        self.messages = []
        self.publisher = patch('app.chess.processor.message_bus.publish', side_effect=self.messages.append)
        self.publisher.start()

    def tearDown(self):
        self.engine.release.set()
        if hasattr(self.proc, 'analysis_thread'):
            self.proc.analysis_thread.join(2)
        self.publisher.stop()

    def feed(self, board):
        with self.ctx.pipeline_lock:
            observation = self.ctx.session.observe(board, self.ctx.checker)
            self.proc._handle_status(BoardAnalysisState(observation))

    def start_board(self):
        board = copy.deepcopy(PositionChecker.START_RED)
        self.feed(board)
        self.feed(board)
        self.assertTrue(self.engine.started.wait(1))
        return board

    def test_late_bestmove_after_our_move_cannot_leak(self):
        board = self.start_board()
        board[6][0], board[5][0] = '-', 'P'
        self.feed(board)
        self.feed(board)
        self.engine.release.set()
        self.proc.analysis_thread.join(2)
        self.assertFalse(self.ctx.session.our_turn)
        self.assertEqual(len(self.engine.calls), 1)
        self.assertFalse(any(m.type == MessageType.MOVE_CODE and m.content for m in self.messages))
        self.assertFalse(any(m.content == 'late thinking' for m in self.messages))
        for _ in range(4):
            self.feed(board)
        self.assertEqual(len(self.engine.calls), 1)

    def test_unknown_endgame_rendered_without_engine(self):
        board = [list(row) for row in EXPECTED_309.split('/')]
        self.feed(board)
        self.feed(board)
        self.assertFalse(self.engine.calls)
        self.assertTrue(any(m.type == MessageType.CHANGE for m in self.messages))
        self.proc.confirm_turn(False)
        self.proc.request_alternative_move()
        self.assertFalse(self.engine.calls)

    def test_black_frame_cancels_old_advice_but_does_not_clear_pieces(self):
        self.start_board()
        with self.ctx.pipeline_lock:
            self.proc._handle_status(self.proc._process_image(np.zeros((540, 490, 3), np.uint8)))
        self.engine.release.set()
        self.proc.analysis_thread.join(2)
        self.assertFalse(any(m.type == MessageType.NON_GAME_SCREEN for m in self.messages))
        self.assertFalse(any(m.type == MessageType.MOVE_CODE and m.content for m in self.messages))
        self.assertIsNotNone(self.ctx.session.board)

    def test_anchor_turn_stays_correct_after_two_plies(self):
        board = self.start_board()
        self.engine.release.set()
        self.proc.analysis_thread.join(2)
        board[6][0], board[5][0] = '-', 'P'
        self.feed(board)
        self.feed(board)
        board[3][0], board[4][0] = '-', 'p'
        self.feed(board)
        self.feed(board)
        self.proc.analysis_thread.join(2)
        self.assertEqual(self.ctx.session.moves, ['a3a4', 'a6a5'])
        self.assertTrue(self.engine.calls[-1][1])
        self.assertEqual(self.engine.calls[-1][2]['moves'], 'a3a4 a6a5')

    def test_unknown_anchor_replaced_on_first_observed_move(self):
        board = [list(row) for row in EXPECTED_310.split('/')]
        self.feed(board)
        self.feed(board)
        board[6][4], board[6][3] = '-', 'r'
        self.feed(board)
        self.feed(board)
        self.engine.release.set()
        self.proc.analysis_thread.join(2)
        self.assertTrue(self.engine.calls[-1][1])
        self.assertEqual(self.engine.calls[-1][2]['moves'], '')


if __name__ == '__main__':
    unittest.main()
