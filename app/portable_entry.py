"""Frozen Windows entry point; report early import failures without a console."""
import json
import os
from pathlib import Path
import sys
import traceback


def prepare_output():
    directory = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'ChessHelper' / 'Logs'
    directory.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('CHESS_HELPER_LOG_DIR', str(directory))
    output = directory / 'startup.log'
    if output.exists() and output.stat().st_size > 2 * 1024 * 1024:
        output.replace(directory / 'startup.previous.log')
    if sys.stdout is None or sys.stderr is None:
        stream = output.open('a', encoding='utf-8', buffering=1)
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    return directory


def self_test(report_path):
    """Runs without desktop capture, clicking or an open UI; use an isolated profile."""
    import cv2
    import numpy as np
    import win32gui
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QPixmap
    from app.tools.utils import resource_path
    from app.chess.piece_recognizer import ChessPieceRecognizer
    from app.chess.engine import ChessEngine
    from app.chess.context import context
    from app.ui.main_window import MainWindow
    result = {'frozen': bool(getattr(sys, 'frozen', False)), 'checks': []}
    app = QApplication.instance() or QApplication([])
    for platform in ('TT', 'JJ'):
        prediction = ChessPieceRecognizer(platform).recognize_from_array(np.zeros((80, 80, 3), np.uint8))
        assert prediction is not None, platform + ' model failed'
        result['checks'].append(platform + ' ONNX model')
    for path in Path(resource_path('images')).rglob('*.png'):
        assert not QPixmap(str(path)).isNull(), str(path)
    result['checks'].append('Qt image assets')
    from app.themes.theme_manager import ThemeManager
    for theme in ('light', 'dark'):
        assert ThemeManager.load_stylesheet(theme), 'Missing theme: ' + theme
    result['checks'].append('Light/dark themes')
    window = MainWindow()
    assert not window.grab().isNull(), 'UI render failed'
    window.check_timer.stop()
    # Do not close via the user's close handler, which persists configuration.
    window.hide()
    result['checks'].append('MainWindow render')
    win32gui.EnumWindows(lambda hwnd, data: True, None)
    result['checks'].append('Win32 enumeration')
    engine = ChessEngine(threads=1, hash_size=32)
    try:
        assert engine.start(), 'Pikafish failed to start'
        context._engine_params = {'goParam': 'depth', 'depth': '2'}
        move, _, _ = engine.get_bestmove('', True, use_startpos=True)
        assert len(move) == 4, 'Pikafish returned no move'
        result['checks'].append('Pikafish NNUE search: ' + move)
    finally:
        engine.quit()
    result['ok'] = True
    Path(report_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    directory = prepare_output()
    testing = '--self-test' in sys.argv
    try:
        if testing:
            index = sys.argv.index('--self-test')
            self_test(sys.argv[index + 1])
        else:
            from app.main import main
            main()
    except Exception:
        detail = traceback.format_exc()
        (directory / 'startup-error.txt').write_text(detail, encoding='utf-8')
        if not testing:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,
                '启动失败。请完整解压 ZIP，不要单独移动 exe。\n错误详情：\n' + str(directory / 'startup-error.txt'),
                '象棋助手', 0x10)
        sys.exit(1)
