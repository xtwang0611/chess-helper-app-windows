import mss
import time
import queue
import threading  
import app.chess.processor as processor
from app.chess.message import Message, MessageType
from app.chess.message_bus import message_bus
from app.chess.context import context
from app.tools.log_config import get_logger
from app.chess.board_locator import BoardLocator, LocationError, WindowError, PieceError, CombsError
from app.chess.hash_checker import StableFrameDetector
from app.chess.vision_guard import frame_quality, screenshot_to_bgr, validate_board_region

logger = get_logger(__name__)


class ChessCaptureManager:
    """象棋捕获管理器类，负责截图、发送识别"""

    def __init__(self):
        self.context = context
        self.detector = StableFrameDetector(hash_size=24, diff_threshold=2)
        self.last_emitted = 0.
        self.capture_key = None
        self.retry_requested = threading.Event()
        self.manual_trigger = False  # 手动触发标志
        self.stop_event = threading.Event() # 整个截图流程的停止事件
        self.process_queue = queue.Queue(maxsize=1)  # 存放识别任务的队列
        self.result_queue = queue.Queue()   # 存放识别和检查结果的队列
        self.worker_threads = processor.start_process_worker(
            self.process_queue, self.result_queue, self.stop_event
        )
        # 初始化棋盘定位器
        self.board_locator = BoardLocator(self.context)
        
        # 连续模式截图线程
        self.continuous_thread = None
        
        # 订阅重试截图消息
        message_bus.subscribe(MessageType.RETRY_CAPTURE, self._on_retry_capture)
        
        # 初始定位完成事件，用于通知截图主循环
        self._located_event = threading.Event()
        
        self.last_capture_time = time.time()

    def main_process_flow(self): 
        # 首先进行初始定位,循环尝试,直到成功
        while not self.stop_event.is_set(): 
            # 如果已有定位成功的事件（可能来自手动定位），直接跳出
            if self._located_event.is_set():
                break
            try:
                success = self.board_locator.handle_locating_board_tasks()
                if success:
                    print("初始定位成功")
                    break
            except WindowError as e:
                if self.stop_event.is_set():
                    return
                message_bus.publish_error(f"未检测到游戏窗口\n请确保游戏已打开")
                message_bus.publish(Message(MessageType.STOP))
                return
            except PieceError as e:
                if self.stop_event.is_set():
                    return
                message_bus.publish_status(str(e))
                self._located_event.wait(timeout=1.5)
            except CombsError as e:
                if self.stop_event.is_set():
                    return
                message_bus.publish_error(f"无法自动定位棋盘\n请确保已进入对局")
                self._located_event.wait(timeout=1.5)
            except LocationError as e:
                if self.stop_event.is_set():
                    return
                message_bus.publish_error(f"{e}")
                message_bus.publish(Message(MessageType.STOP))
                return
            except Exception as e:
                if self.stop_event.is_set():
                    return
                message_bus.publish_error(f"{e}")   
                message_bus.publish(Message(MessageType.STOP))
                return
        
        if self.stop_event.is_set():
            return
        
        # 重置事件，避免影响后续逻辑
        self._located_event.clear()
        
        # Invalidate old frames and caches without reloading the ONNX model.
        self.context.reset_pipeline()

        # 默认使用连续截图模式
        print("Debug - 启动连续截图模式")
        # 启动连续截图线程
        if self.continuous_thread is None or not self.continuous_thread.is_alive():
            self.continuous_thread = threading.Thread(
                target=self._continuous_capture_worker,
                daemon=True
            )
            self.continuous_thread.start()
        
        # 启动窗口移动监控
        try:
            self.board_locator.monitor_window_movement(self.stop_event)
        except WindowError as e:
            if self.board_locator.stop_event.is_set():
                return
            message_bus.publish_error(f"未检测到游戏窗口\n请确保游戏已打开")
            message_bus.publish(Message(MessageType.STOP))
        except PieceError as e:
            if self.board_locator.stop_event.is_set():
                return
            message_bus.publish_error(f"未检测到象棋棋局\n请确保已开始对局")
            message_bus.publish(Message(MessageType.STOP))
        except CombsError as e:
            if self.board_locator.stop_event.is_set():
                return
            message_bus.publish_error(f"无法自动定位棋盘位置\n请使用手动定位")
            message_bus.publish(Message(MessageType.STOP))
        except LocationError as e:
            if self.board_locator.stop_event.is_set():
                return
            message_bus.publish_error(f"{e}")
            message_bus.publish(Message(MessageType.STOP))
        except Exception as e:
            if self.board_locator.stop_event.is_set():
                return
            message_bus.publish_error(f"{e}")   
            message_bus.publish(Message(MessageType.STOP))

    def start_capture(self):
        """开始截图任务"""
        self.stop_event.clear()  # 重置停止事件
        self.last_capture_time = time.time()  # 重置截图时间
    
    def stop_capture(self):
        """停止截图任务"""
        self.stop_event.set()
        self._located_event.set()
        self.board_locator.stop()
        with self.context.pipeline_lock:
            self.context.invalidate_analysis()
        for t in self.worker_threads:
            t.join(timeout=2)

        # 停止棋盘定位器
        if hasattr(self, 'board_locator'):
            self.board_locator.stop()
        # 停止连续截图线程
        if self.continuous_thread is not None:
            self.continuous_thread.join(timeout=2)
            self.continuous_thread = None
        
        # 取消消息订阅
        message_bus.unsubscribe(MessageType.RETRY_CAPTURE, self._on_retry_capture)

    def _enqueue_latest(self, item):
        try:
            self.process_queue.put_nowait(item)
        except queue.Full:
            try:
                self.process_queue.get_nowait()
                self.process_queue.task_done()
            except queue.Empty:
                pass
            self.process_queue.put_nowait(item)

    def _capture_and_enqueue(self, region, force_output=False):
        valid, reason = validate_board_region(region)
        if not valid:
            self._enqueue_latest((time.time_ns(), None))
            return False
        key = (tuple(sorted(region.items())), self.context.platform, self.context.discard_before_timestamp)
        if key != self.capture_key:
            self.detector = StableFrameDetector(hash_size=24, diff_threshold=2)
            self.capture_key = key
            self.last_emitted = 0.
        capture_time = time.time_ns()
        with mss.mss() as sct:
            screenshot = sct.grab(region)
        quality, _ = frame_quality(screenshot_to_bgr(screenshot))
        now = time.monotonic()
        if not quality:
            # Invalid frames reach the state owner to cancel stale engine advice.
            self.detector.buffer.clear()
            if now - self.last_emitted >= .5:
                self._enqueue_latest((capture_time, screenshot))
                self.last_emitted = now
            return False
        stable, _ = self.detector.process_screenshot(
            screenshot, force_output=force_output or now - self.last_emitted >= .5)
        if stable is not None:
            self._enqueue_latest((capture_time, screenshot))
            self.last_emitted = now
            self.last_capture_time = time.time()
            return True
        return False

    def _continuous_capture_worker(self, interval=.18):
        while not self.stop_event.is_set():
            try:
                region = self.context.regions.get('board')
                if region:
                    force = self.retry_requested.is_set()
                    self.retry_requested.clear()
                    self._capture_and_enqueue(region, force)
            except Exception:
                logger.exception("截图失败，将继续重试")
                self._enqueue_latest((time.time_ns(), None))
            self.stop_event.wait(interval)

    def _on_retry_capture(self, message):
        # Coalesce requests; no retry-thread backlog and no concurrent frame cache.
        self.retry_requested.set()

    def manually_capture_once(self):
        self.context.reset_pipeline()
        self.retry_requested.set()
        return True
