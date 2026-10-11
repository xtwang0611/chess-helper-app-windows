"""Temporal board/turn state. A static endgame does not reveal whose turn it is."""
from dataclasses import dataclass

from app.chess.checker import PositionChecker


@dataclass
class Observation:
    accepted: bool = False
    changed: bool = False
    recovered: bool = False
    reason: str = "正在确认棋子，请稍候"
    step: dict = None


class BoardSession:
    def __init__(self):
        self.board = None
        self.candidate = None
        self.frames = 0
        self.invalid_frames = 0
        self.ready = False
        self.our_turn = None
        self.anchor_fen = None
        self.anchor_red = None
        self.moves = []
        self.analysis_requested = False
        self.advice_suspended = False
        self.last_status = None

    def invalidate(self, reason):
        self.candidate = None
        self.frames = 0
        self.invalid_frames += 1
        self.ready = False
        self.analysis_requested = False
        return Observation(reason=reason)

    def observe(self, board, checker):
        if len(board) != 10 or any(len(row) != 9 for row in board):
            return self.invalidate("棋盘尺寸异常，正在重新识别")
        counts_ok, reason, _ = checker.check_pieces_count(board)
        # Detect orientation without mutating the live checker on rejected frames.
        validator = PositionChecker()
        validator.update_side_detection(board)
        position_ok, pos_reason = validator.check_pieces_position(board, validator.is_red)
        if not counts_ok or not position_ok:
            return self.invalidate("识别待确认：" + (reason if not counts_ok else pos_reason))
        kings = {piece: (r, c) for r, row in enumerate(board) for c, piece in enumerate(row)
                 if piece in ('k', 'K')}
        kr, kc = kings['k']
        rr, rc = kings['K']
        if kc == rc and all(board[r][kc] == '-' for r in range(min(kr, rr) + 1, max(kr, rr))):
            return self.invalidate("将帅之间的棋子待确认，正在重新识别")
        # Missing kings/low confidence are never treated as evidence of game over.
        if self.candidate == board:
            self.frames += 1
        else:
            self.candidate = [row[:] for row in board]
            self.frames = 1
        was_ready = self.ready
        if self.board != board or self.invalid_frames:
            self.ready = False
        if self.frames < 2:
            return Observation()

        step = {}
        changed = self.board != board
        if changed and self.board is not None:
            delta = checker.check_position_changes(self.board, board, checker.is_red)
            if delta.is_my_step or delta.is_opponent_step:
                moved_by_us = delta.is_my_step
                # Contradictory turns mean a discontinuity, not permission to advise.
                if self.our_turn is not None and self.our_turn != moved_by_us:
                    self.our_turn = None
                    self.anchor_fen = None
                    self.moves.clear()
                else:
                    if self.our_turn is None:
                        self.anchor_fen = None
                        self.moves.clear()
                    self.our_turn = not moved_by_us
                    step = delta.step_info
            else:
                changes = [(a, b) for old, new in zip(self.board, board)
                           for a, b in zip(old, new) if a != b]
                # A vanishing piece (or pair of elephants) is not a legal move.
                only_missing = changes and all(a != '-' and b == '-' for a, b in changes)
                if only_missing or len(changes) < 3:
                    return self.invalidate("棋子变化不完整，保留上一局面并重新识别")
                if self.frames < 3:
                    return Observation(reason="正在确认新局面")
                self.our_turn = (validator.is_red if board in
                                 (checker.START_RED, checker.START_BLACK) else None)
                self.anchor_fen = None
                self.moves.clear()
        elif self.board is None:
            # Only the standard start position determines the turn from pixels alone.
            self.our_turn = (validator.is_red if board in
                             (checker.START_RED, checker.START_BLACK) else None)

        recovered = not was_ready
        self.board = [row[:] for row in board]
        self.ready = True
        self.invalid_frames = 0
        checker.is_red = validator.is_red
        if changed:
            checker.force_sync_board(board)
        checker.in_settlement_screen = False
        if changed:
            self.analysis_requested = False
        return Observation(True, changed, recovered, self.turn_text(), step)

    def turn_text(self):
        if self.our_turn is None:
            return "棋盘已识别，请用「轮次」确认谁走"
        return "轮到我方走棋" if self.our_turn else "轮到对方走棋，等待对方落子"
