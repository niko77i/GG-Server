"""日志持久化：控制台 + 轮转文件。

背景：原先只有 main.py 的一行 logging.basicConfig，日志全部打到控制台。
服务以 waitress 常驻运行时，控制台内容随会话结束一起消失 —— Sheets 写表
失败、掉包检测异常这类 warning/error 不留任何痕迹（2026-10-07 排查表同步
问题时，全盘找不到任何 429/quota 记录，数据库成了唯一证据源）。

路径规则与 database._db_path() 保持一致：打包模式取 EXE 所在目录，开发模式
取项目根。刻意不 import main，避免导入期循环依赖。
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

# 单文件 10 MB，保留 5 个历史文件 → 磁盘占用硬上限约 60 MB。
# 选按大小而非按天轮转：异常刷屏时磁盘不会被写爆；代价是排查「昨天」时
# 若那段时间日志量大，可能已被轮转掉。
MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5

# 这些库在 INFO 级会逐次调用刷屏，压到 WARNING 只留真问题
_NOISY_LOGGERS = (
    "googleapiclient",
    "google_auth_httplib2",
    "httplib2",
    "urllib3",
    "requests",
)

_configured = False
_file_enabled = False


def _data_root() -> str:
    """与 main._DATA_ROOT 同一套规则：打包取 EXE 目录，开发取项目根。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # 本文件在 py/ 下，上一级是项目根
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def log_dir() -> str:
    return os.path.join(_data_root(), "temp", "logs")


def log_file_path() -> str:
    return os.path.join(log_dir(), "gg-server.log")


def setup_logging(level: int = logging.INFO, enable_file: bool = True):
    """给 root logger 挂上「控制台 [+ 轮转文件]」handler。

    enable_file=True  → 返回日志文件路径（生产用法，main.py 顶层调用）
    enable_file=False → 只留控制台，返回 None（测试用法）

    幂等：重复调用直接返回，不会叠加 handler。**首次调用的 enable_file 决定
    本进程是否写文件**，后调用者无法再打开 —— 测试正是靠这一点抢在
    `from main import app` 之前关掉文件写入（见 tests/conftest.py）。
    """
    global _configured, _file_enabled
    if _configured:
        return log_file_path() if _file_enabled else None

    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT)

    # 控制台：保留改动前的行为（basicConfig 默认也是 stderr）
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    if enable_file:
        # encoding 必须显式给 utf-8。Windows 下 FileHandler 不指定时跟随
        # locale(GBK)，中文日志会乱码；遇到 GBK 表达不了的字符还会抛
        # UnicodeEncodeError，让「记日志」这个动作本身变成异常源。
        os.makedirs(log_dir(), exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file_path(),
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        _file_enabled = True

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    _configured = True
    return log_file_path() if _file_enabled else None
