"""
统一日志配置模块
基于 loguru 提供项目级别的日志管理
"""
import sys
import os
import threading
import time
from collections import OrderedDict
from loguru import logger

# 移除默认的 handler
logger.remove()

class ConsoleRateLimit:
    """Bound recurring messages without hiding the first error or a new error."""
    def __init__(self, interval=10., clock=time.monotonic):
        self.interval, self.clock = interval, clock
        self.seen = OrderedDict()
        self.lock = threading.Lock()

    def __call__(self, record):
        extra = record['extra']
        key = (extra.get('name', record['name']), record['level'].name,
               extra.get('event') or record['message'])
        now = self.clock()
        with self.lock:
            previous = self.seen.get(key)
            if previous is not None and now - previous < self.interval:
                return False
            self.seen[key] = now
            self.seen.move_to_end(key)
            if len(self.seen) > 256:
                self.seen.popitem(last=False)
        return True


CONSOLE_LEVEL = os.environ.get('CHESS_LOG_LEVEL', 'INFO').upper()
if CONSOLE_LEVEL not in ('TRACE', 'DEBUG', 'INFO', 'SUCCESS', 'WARNING', 'ERROR', 'CRITICAL'):
    CONSOLE_LEVEL = 'INFO'
console_rate_limit = ConsoleRateLimit()

# 控制台输出配置
logger.add(
    sys.stderr,
    level=CONSOLE_LEVEL,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{extra[name]}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    filter=None if CONSOLE_LEVEL in ('TRACE', 'DEBUG') else console_rate_limit,
    colorize=True
)

# 文件输出配置（可选，按日期轮转）
def setup_file_logging(log_dir="logs"):
    """设置文件日志（可选调用）"""
    os.makedirs(log_dir, exist_ok=True)
    logger.add(
        os.path.join(log_dir, "chess_{time:YYYY-MM-DD}.log"),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="00:00",  # 每天午夜轮转
        retention="7 days",  # 保留7天
        encoding="utf-8"
    )

def get_logger(name: str = None):
    """
    获取带模块名的 logger
    
    Usage:
        from app.tools.log_config import get_logger
        logger = get_logger(__name__)
        logger.debug("调试信息")
    """
    if name:
        return logger.bind(name=name)
    return logger

# 导出
__all__ = ["logger", "get_logger", "setup_file_logging"]
