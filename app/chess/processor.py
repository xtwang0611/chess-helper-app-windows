"""Single-owner recognition pipeline with cancellable, versioned engine output."""
from dataclasses import dataclass
import queue
import threading

from app.chess.context import context
from app.chess.message import Message, MessageType
from app.chess.message_bus import message_bus
from app.chess.recognizer import ChessRecognizer, RecognitionErrorType
from app.chess.vision_guard import frame_quality, screenshot_to_bgr
from app.tools import utils
from app.tools.log_config import get_logger

logger = get_logger(__name__)


@dataclass
class BoardAnalysisState:
    observation: object = None
    timestamp: int = 0
    preview: object = None
    uncertain: object = None


class ChessProcess:
    @staticmethod
    def _is_fatal_recognition_error(error_type):
        return error_type not in (RecognitionErrorType.MARKER_MISSING,
                                  RecognitionErrorType.LOW_CONFIDENCE)

    @classmethod
    def from_context(cls, ctx):
        return cls(ctx.get_checker(), ctx.get_engine(), ctx.history, ctx)

    def __init__(self, checker, engine, history, context):
        self.checker, self.engine, self.history, self.context = checker, engine, history, context
        self.recognizer = context.get_recognizer()
        if self.recognizer is None:
            self.recognizer = ChessRecognizer(context)
            context.set_recognizer(self.recognizer)

    def publish(self, kind, content=None, **kwargs):
        message_bus.publish(Message(kind, content, analysis_token=self.context.analysis_token, **kwargs))

    def _process_image(self, img, capture_time=0):
        session = self.context.session
        preview, uncertain_positions = None, None
        try:
            quality, reason = frame_quality(screenshot_to_bgr(img))
        except (ValueError, TypeError, AttributeError):
            quality, reason = False, 'format'
        if not quality:
            observation = session.invalidate("截图暂不可用，正在重试（" + reason + "）")
        else:
            coords = self.context.board_coords
            board, _, _, details = self.recognizer.recognize_piece_from_grid(img, coords['x'], coords['y'])
            # Whole-grid detection is for location, not an occlusion classifier.
            unsure = [d for d in details if d.type != RecognitionErrorType.MARKER_MISSING]
            if unsure:
                local_errors = all(d.position[0] >= 0 and d.position[1] >= 0 for d in unsure)
                reason = (f"{len(unsure)}处棋子待确认，正在重新识别" if local_errors else
                          "截图局部信息不足，正在重试")
                observation = session.invalidate(reason)
                if (local_errors and session.board is None and len(unsure) <= 8 and
                        self.recognizer.grid_classifier.grid_supported):
                    # Preview is visibly provisional and never sent to the engine.
                    preview = [row[:] for row in board]
                    uncertain_positions = [d.position for d in unsure]
                    for row, col in uncertain_positions:
                        preview[row][col] = '-'
            else:
                observation = session.observe(board, self.checker)
        return BoardAnalysisState(observation, capture_time, preview, uncertain_positions)

    def _clear_advice(self):
        self.publish(MessageType.MOVE_TEXT, '')
        self.publish(MessageType.MOVE_CODE, '', is_red=self.checker.is_red)

    def _handle_status(self, state):
        observation, session = state.observation, self.context.session
        if not observation.accepted:
            if not getattr(session, 'advice_suspended', False):
                self.context.invalidate_analysis()
                self._clear_advice()
                session.advice_suspended = True
            if state.preview is not None:
                self.publish(MessageType.PIECES, array=state.preview, uncertain=state.uncertain)
            reason = observation.reason
            if getattr(session, 'last_status', None) != reason:
                session.last_status = reason
                self.publish(MessageType.STATUS, reason)
                logger.info(reason)
            return
        session.advice_suspended = False
        if observation.changed or observation.recovered:
            self.context.invalidate_analysis()
            self._clear_advice()
            self.publish(MessageType.CHANGE, observation.reason,
                         array=session.board, step_info=observation.step or {})
            session.last_status = observation.reason
            session.analysis_requested = False
        if observation.changed:
            fen, _ = utils.convert_array_to_fen(session.board, self.checker.is_red)
            if session.anchor_fen and observation.step:
                session.moves.append(utils.convert_coords_to_move(
                    observation.step['from_pos'], observation.step['to_pos'], self.checker.is_red))
            else:
                session.anchor_fen = fen
                session.anchor_red = (self.checker.is_red if session.our_turn else not self.checker.is_red)
                session.moves = []
        if session.our_turn is True and not session.analysis_requested:
            self._request_analysis()

    def confirm_turn(self, ours):
        with self.context.pipeline_lock:
            session = self.context.session
            if not session.ready or session.board is None:
                self.publish(MessageType.STATUS, "请等棋盘识别完成后再确认轮次")
                return
            self.context.invalidate_analysis()
            self._clear_advice()
            session.our_turn = bool(ours)
            session.anchor_fen, _ = utils.convert_array_to_fen(session.board, self.checker.is_red)
            session.anchor_red = self.checker.is_red if ours else not self.checker.is_red
            session.moves = []
            session.analysis_requested = False
            self.publish(MessageType.STATUS, session.turn_text())
            if ours:
                self._request_analysis()

    def _request_analysis(self, alternative=False):
        session = self.context.session
        if not session.ready or session.our_turn is not True or session.board is None:
            self.publish(MessageType.STATUS, "当前不是已确认的我方回合，暂不支招")
            return
        if not self.engine or not self.engine.is_initialized:
            self.publish(MessageType.STATUS, "棋盘已显示；引擎未启动，请停止后重试")
            session.analysis_requested = True
            return
        if alternative:
            self.context.invalidate_analysis()
            self._clear_advice()
        token = self.context.analysis_token
        session.analysis_requested = True
        board = [row[:] for row in session.board]
        is_red = self.checker.is_red
        current_fen, _ = utils.convert_array_to_fen(board, is_red)
        fen = session.anchor_fen or current_fen
        side = session.anchor_red if session.anchor_red is not None else is_red
        moves = ' '.join(session.moves)

        def current():
            return (token == self.context.analysis_token and self.context.session is session
                    and session.ready and session.our_turn is True)

        def callback(msg):
            with self.context.pipeline_lock:
                if current():
                    self.publish(msg.type, msg.content, **msg.kwargs)

        def analyze():
            try:
                move, _, pvs = self.engine.get_bestmove(
                    fen, side, callback, use_startpos=False, moves=moves,
                    multipv=2 if alternative else 1, is_current=current)
                with self.context.pipeline_lock:
                    if not current():
                        return
                    if alternative:
                        move = pvs[1] if len(pvs) > 1 else None
                    if not move or len(move) != 4:
                        self.publish(MessageType.STATUS, "没有可用变招" if alternative else
                                     "本次计算未得到着法，可点击变招重试")
                        return
                    text = utils.convert_move_to_chinese(move, board, is_red)
                    if text is None:
                        self.publish(MessageType.STATUS, "引擎着法与当前棋盘不符，请刷新识别")
                        return
                    self.publish(MessageType.MOVE_TEXT, text)
                    self.publish(MessageType.MOVE_CODE, move, is_red=is_red)
                    self.publish(MessageType.STATUS, "推荐走法：")
            except Exception as exc:
                logger.exception("引擎分析失败")
                with self.context.pipeline_lock:
                    if current():
                        self.publish(MessageType.ERROR, f"引擎计算失败：{exc}")

        self.analysis_thread = threading.Thread(target=analyze, name='chess-analysis', daemon=True)
        self.analysis_thread.start()

    def request_alternative_move(self):
        with self.context.pipeline_lock:
            self._request_analysis(alternative=True)


def start_process_worker(process_queue, result_queue=None, stop_event=None):
    """One ordered state owner; capture supplies a bounded latest-frame queue."""
    def worker():
        while not (stop_event and stop_event.is_set()):
            try:
                item = process_queue.get(timeout=.2)
            except queue.Empty:
                continue
            try:
                if item == 'STOP':
                    return
                capture_time, screenshot = item
                with context.pipeline_lock:
                    if (stop_event and stop_event.is_set()) or capture_time < context.discard_before_timestamp:
                        continue
                    if context.get_checker() is None:
                        continue
                    proc = ChessProcess.from_context(context)
                    state = proc._process_image(screenshot, capture_time)
                    if not (stop_event and stop_event.is_set()):
                        proc._handle_status(state)
            except Exception:
                logger.exception("当前帧处理失败，将继续识别后续帧")
                with context.pipeline_lock:
                    context.session.invalidate("识别暂时失败，正在重试")
                    context.invalidate_analysis()
                    token = context.analysis_token
                    message_bus.publish(Message(MessageType.MOVE_TEXT, '', analysis_token=token))
                    message_bus.publish(Message(MessageType.MOVE_CODE, '', is_red=True, analysis_token=token))
                    message_bus.publish(Message(MessageType.STATUS, "识别暂时失败，正在重试", analysis_token=token))
            finally:
                process_queue.task_done()

    thread = threading.Thread(target=worker, name='chess-recognition', daemon=True)
    thread.start()
    return [thread]
