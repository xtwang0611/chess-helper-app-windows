import copy
import queue
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from app.chess.checker import PositionChecker
from app.chess.context import context
from app.chess.engine import ChessEngine
from app.chess.grid_recognition import calibrate_grid, centered_crop, decode_square, GridClassifier
from app.chess.hash_checker import StableFrameDetector
from app.chess.message import MessageType
from app.chess.processor import ChessProcess, BoardAnalysisState, start_process_worker
from app.chess.session import BoardSession


def endgame():
    board = [['-'] * 9 for _ in range(10)]
    for r, c, piece in [(0, 5, 'k'), (8, 3, 'K'), (7, 4, 'B'), (9, 6, 'B'),
                         (3, 0, 'p'), (6, 0, 'P'), (9, 0, 'R'), (0, 8, 'r')]:
        board[r][c] = piece
    return board


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.checker, self.session = PositionChecker(), BoardSession()

    def accept(self, board):
        self.session.observe(board, self.checker)
        return self.session.observe(board, self.checker)

    def test_endgame_is_renderable_but_turn_unknown(self):
        self.assertTrue(self.accept(endgame()).accepted)
        self.assertIsNone(self.session.our_turn)

    def test_initial_start_has_red_to_move(self):
        self.accept(self.checker.START_RED)
        self.assertTrue(self.session.our_turn)

    def test_flipped_start_is_opponent_turn(self):
        self.accept(self.checker.START_BLACK)
        self.assertFalse(self.session.our_turn)

    def test_move_and_capture_switch_turn_without_markers(self):
        board = endgame()
        self.accept(board)
        self.session.our_turn = True
        board[6][0], board[5][0] = '-', 'P'
        result = self.accept(board)
        self.assertTrue(result.changed)
        self.assertFalse(self.session.our_turn)
        board[3][0], board[4][0] = '-', 'p'
        self.accept(board)
        self.assertTrue(self.session.our_turn)
        board[5][0], board[4][0] = '-', 'P'
        self.accept(board)
        self.assertFalse(self.session.our_turn)

    def test_kings_are_valid_everywhere_in_palace(self):
        for r in range(7, 10):
            for c in range(3, 6):
                self.assertTrue(self.checker.is_position_valid('K', c, r, True))

    def test_both_elephants_missing_is_not_a_new_position(self):
        board = endgame()
        self.accept(board)
        missing = copy.deepcopy(board)
        missing[7][4] = missing[9][6] = '-'
        for _ in range(8):
            self.assertFalse(self.session.observe(missing, self.checker).accepted)
        self.assertEqual(self.session.board, board)
        self.assertFalse(self.session.ready)
        self.assertTrue(self.accept(board).recovered)

    def test_missing_king_never_declares_settlement(self):
        board = endgame()
        self.accept(board)
        missing = copy.deepcopy(board)
        missing[8][3] = '-'
        for _ in range(8):
            self.session.observe(missing, self.checker)
        self.assertFalse(self.checker.in_settlement_screen)
        self.assertTrue(self.accept(board).accepted)

    def test_nonconsecutive_candidates_do_not_confirm(self):
        a, b = endgame(), endgame()
        b[0][8], b[1][8] = '-', 'r'
        for board in (a, b, a, b):
            self.assertFalse(self.session.observe(board, self.checker).accepted)

    def test_black_frame_breaks_candidate_confirmation(self):
        self.session.observe(endgame(), self.checker)
        self.session.invalidate('black')
        self.assertFalse(self.session.observe(endgame(), self.checker).accepted)

    def test_resync_does_not_assume_our_turn(self):
        self.accept(self.checker.START_RED)
        for _ in range(3):
            result = self.session.observe(endgame(), self.checker)
        self.assertTrue(result.accepted)
        self.assertIsNone(self.session.our_turn)

    def test_invalid_piece_position_rejected_even_after_count_increase(self):
        self.accept(endgame())
        board = endgame()
        board[4][8] = 'a'
        for _ in range(4):
            self.assertFalse(self.session.observe(board, self.checker).accepted)

    def test_move_with_changed_identity_is_not_legal(self):
        before, after = endgame(), endgame()
        after[0][8], after[1][8] = '-', 'n'
        self.assertFalse(self.checker.check_position_changes(before, after, True).is_opponent_step)

    def test_new_standard_game_restores_known_turn(self):
        self.accept(endgame())
        for _ in range(3):
            result = self.session.observe(self.checker.START_RED, self.checker)
        self.assertTrue(result.accepted)
        self.assertTrue(self.session.our_turn)

    def test_facing_kings_are_not_sent_to_engine(self):
        board = endgame()
        board[0][5], board[0][3] = '-', 'k'
        self.assertFalse(self.accept(board).accepted)


class ClassificationTests(unittest.TestCase):
    def test_pawn_disambiguates_illegal_advisor_with_visual_support(self):
        piece, _, uncertain = decode_square({'a': .58, 'p': .40, '-': .02}, 4, 0, True)
        self.assertEqual(piece, 'p')
        self.assertFalse(uncertain)

    def test_rules_do_not_invent_missing_king_or_pawn(self):
        _, _, uncertain = decode_square({'a': .999, 'p': .001}, 4, 0, True)
        self.assertTrue(uncertain)
        self.assertEqual(decode_square({'-': .99, 'K': .01}, 8, 3, True)[0], '-')

    def test_marker_and_empty_are_same_semantic_class(self):
        self.assertEqual(decode_square({'.': .5, '-': .49, 'p': .01}, 4, 0, True), ('-', .99, False))

    def test_king_and_elephants_not_restricted_to_starting_squares(self):
        for r, c, piece in [(8, 3, 'K'), (7, 4, 'B'), (5, 6, 'B'), (2, 5, 'k')]:
            self.assertEqual(decode_square({piece: .99, '-': .01}, r, c, True), (piece, .99, False))

    def test_boundary_crop_preserves_center(self):
        image = np.zeros((40, 40, 3), np.uint8)
        image[2, 2] = 255
        cropped = centered_crop(image, 2, 2, 10)
        self.assertEqual(cropped.shape, (20, 20, 3))
        self.assertTrue((cropped[10, 10] == 255).all())

    def test_incomplete_grid_calibrates_without_fixed_pieces(self):
        image = np.full((890, 800, 3), 200, np.uint8)
        xs = list(range(45, 758, 89))
        ys = [47 + i * 89 for i in range(10)]
        for i, x in enumerate(xs):
            if i != 3:
                cv2.line(image, (x + 6, 47), (x + 6, 850), (20, 20, 20), 2)
        for i, y in enumerate(ys):
            if i != 6:
                cv2.line(image, (45, y - 5), (757, y - 5), (20, 20, 20), 2)
        xx, yy, supported = calibrate_grid(image, xs, ys)
        self.assertTrue(supported)
        self.assertLessEqual(abs(xx[4] - (xs[4] + 6)), 3)
        self.assertLessEqual(abs(yy[7] - (ys[7] - 5)), 3)

    def test_cached_uncertainty_is_preserved_and_periodically_recomputed(self):
        class Model:
            calls = 0
            def recognize_batch(self, crops):
                self.calls += 1
                return [{'class_name': 'r', 'confidence': .51,
                         'probabilities': {'r': .51, '-': .49}} for _ in crops]
        model, classifier = Model(), GridClassifier()
        image = np.full((890, 800, 3), 200, np.uint8)
        xs, ys = list(range(45, 758, 89)), [47 + i * 89 for i in range(10)]
        with patch('app.chess.grid_recognition.time.monotonic', return_value=1.):
            first = classifier.recognize(image, xs, ys, model, 'TT')[2]
            second = classifier.recognize(image, xs, ys, model, 'TT')[2]
        self.assertEqual(first, second)
        self.assertEqual(model.calls, 1)
        with patch('app.chess.grid_recognition.time.monotonic', return_value=3.):
            classifier.recognize(image, xs, ys, model, 'TT')
        self.assertEqual(model.calls, 2)
        classifier.reset()
        classifier.recognize(image, xs, ys, model, 'TT')
        self.assertEqual(model.calls, 3)


class EngineTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.engine = ChessEngine('unused')
        self.engine.process = SimpleNamespace(poll=lambda: 0)

    def tearDown(self):
        self.engine.process = None

    def test_silent_uci_handshake_has_real_deadline(self):
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            self.engine._wait_for_response('readyok', .04)
        self.assertLess(time.monotonic() - start, .5)

    def test_stale_waiter_never_sends_engine_commands(self):
        self.engine.is_initialized = True
        with patch.object(self.engine, '_send_command') as send:
            self.assertEqual(self.engine.get_bestmove('', True, is_current=lambda: False), ('', '', []))
            send.assert_not_called()


class WorkerTests(unittest.TestCase):
    def test_latest_frame_queue_never_builds_backlog(self):
        from app.chess.screenshot import ChessCaptureManager
        manager = object.__new__(ChessCaptureManager)
        manager.process_queue = queue.Queue(maxsize=1)
        for i in range(100):
            manager._enqueue_latest((i, object()))
        self.assertEqual(manager.process_queue.qsize(), 1)
        self.assertEqual(manager.process_queue.get_nowait()[0], 99)
        manager.process_queue.task_done()
        self.assertEqual(manager.process_queue.unfinished_tasks, 0)

    def test_nanosecond_cutoff_rejects_pre_refresh_frames(self):
        tasks, stop = queue.Queue(), threading.Event()
        previous_checker, previous_cutoff = context.checker, context.discard_before_timestamp
        context.set_checker(PositionChecker())
        context.discard_before_timestamp = time.time_ns()
        try:
            with patch('app.chess.processor.ChessProcess.from_context') as create:
                threads = start_process_worker(tasks, stop_event=stop)
                tasks.put((context.discard_before_timestamp - 1, object()))
                tasks.join()
                stop.set()
                threads[0].join(1)
                create.assert_not_called()
        finally:
            stop.set()
            context.set_checker(previous_checker)
            context.discard_before_timestamp = previous_cutoff

    def test_worker_survives_model_exception_and_stops_while_idle(self):
        tasks, stop, done = queue.Queue(), threading.Event(), threading.Event()
        fake = SimpleNamespace(_process_image=lambda *args: BoardAnalysisState(),
                               _handle_status=lambda state: done.set())
        previous = context.checker
        context.set_checker(PositionChecker())
        try:
            with patch('app.chess.processor.ChessProcess.from_context', side_effect=[ValueError('bad frame'), fake]), \
                    patch('app.chess.processor.logger.exception'):
                threads = start_process_worker(tasks, stop_event=stop)
                tasks.put((time.time_ns(), object()))
                tasks.put((time.time_ns(), object()))
                self.assertTrue(done.wait(3))
                stop.set()
                threads[0].join(1)
                self.assertFalse(threads[0].is_alive())
                self.assertEqual(tasks.unfinished_tasks, 0)
        finally:
            stop.set()
            context.set_checker(previous)


if __name__ == '__main__':
    unittest.main()
