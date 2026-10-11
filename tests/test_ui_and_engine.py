"""Headless Qt rendering and optional installed Pikafish smoke tests."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import queue
from pathlib import Path
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from app.chess.context import context
from app.chess.engine import ChessEngine
from app.chess.checker import PositionChecker
from app.chess.message import Message, MessageType
from app.tools.utils import convert_array_to_fen
from app.ui.board_display import BoardDisplay
from app.ui.main_window import MainWindow


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # Offscreen Qt lacks the Windows platform's normal font fallback.
        font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))

    def test_preview_proxy_and_arrow_clear_repaint(self):
        display = BoardDisplay()
        display.resize(430, 550)
        display.update_pieces(PositionChecker.START_RED, uncertain=[(8, 4)])
        self.assertEqual(len(display.board_canvas.pieces), 32)
        self.assertEqual(display.board_canvas.uncertain, [(8, 4)])
        display.update_arrow('a3a4', True)
        self.assertIsNotNone(display.board_canvas.move_arrow)
        display.update_arrow('', True)
        self.assertIsNone(display.board_canvas.move_arrow)
        display.update_board(PositionChecker.START_RED)
        self.assertEqual(display.board_canvas.uncertain, [])
        self.assertFalse(display.grab().isNull())
        display.close()

    def test_full_window_renders_endgame_without_starting_capture(self):
        with patch.object(MainWindow, 'check_platform_change'), patch.object(context, 'save_config'):
            window = MainWindow()
            try:
                self.assertIsNone(window.capture_manager)
                window.is_running = True
                board = [list(row) for row in
                         '---a-k---/-N-----R-/---abc---/--N------/---------/---------/---------/-n--B----/--p-p----/c--K--B--'.split('/')]
                window.ui_message_queue.put(Message(MessageType.CHANGE,
                    '棋盘已识别，请用「轮次」确认谁走', array=board, analysis_token=context.analysis_token))
                window.check_queue()
                self.assertEqual(len(window.board_display.board_canvas.pieces), 15)
                self.assertFalse(window.grab().isNull())
                output = os.environ.get('CHESS_HELPER_UI_PREVIEW')
                if output:
                    self.assertTrue(window.grab().save(output))
            finally:
                window.check_timer.stop()
                window.is_running = False
                window.close()
                from app.chess.message_bus import message_bus
                message_bus.set_ui_queue(None)

    def test_ui_drains_batch_and_rejects_stale_messages(self):
        # Exercise the actual queue handler without starting window detection or capture.
        class Receiver:
            check_queue = MainWindow.check_queue
            def __init__(self):
                self.ui_message_queue = queue.Queue()
                self.is_running = True
                self.board_display = BoardDisplay()
                self.texts = []
            def update_text(self, *args):
                self.texts.append(args[0])
        receiver = Receiver()
        receiver.ui_message_queue.put(Message(MessageType.STATUS, 'stale', analysis_token=-1))
        for i in range(15):
            receiver.ui_message_queue.put(Message(MessageType.STATUS, str(i), analysis_token=context.analysis_token))
        receiver.ui_message_queue.put(Message(MessageType.PIECES, array=PositionChecker.START_RED))
        receiver.check_queue()
        self.assertTrue(receiver.ui_message_queue.empty())
        self.assertNotIn('stale', receiver.texts)
        self.assertEqual(len(receiver.texts), 15)
        self.assertEqual(len(receiver.board_display.board_canvas.pieces), 32)
        receiver.board_display.close()


class InstalledEngineTests(unittest.TestCase):
    def test_real_pikafish_startpos_endgame_and_alternative(self):
        root = Path(__file__).resolve().parents[1]
        executable = root / 'app/Pikafish/src' / ('pikafish.exe' if os.name == 'nt' else 'pikafish')
        if not executable.exists():
            self.skipTest('Pikafish is not installed locally')
        engine = ChessEngine(str(executable), threads=1, hash_size=32)
        try:
            self.assertTrue(engine.start())
            with patch.object(context, 'get_engine_params', return_value={'goParam': 'depth', 'depth': '6'}):
                fen, _ = convert_array_to_fen(PositionChecker.START_RED, True)
                move, _, pvs = engine.get_bestmove(fen, True, use_startpos=False, multipv=2)
                self.assertRegex(move, r'^[a-i][0-9][a-i][0-9]$')
                self.assertGreaterEqual(len(pvs), 2)
                # Real screenshot 309, including both elephants and off-center king.
                endgame = '3a1k3/1N5R1/3abc3/2N6/9/9/9/1n2B4/2p1p4/c2K2B2'
                move, fen_string, _ = engine.get_bestmove(endgame, True, use_startpos=False)
                self.assertRegex(move, r'^[a-i][0-9][a-i][0-9]$')
                self.assertTrue(fen_string.endswith(' w - - 0 1'))
        finally:
            engine.quit()


if __name__ == '__main__':
    unittest.main()
