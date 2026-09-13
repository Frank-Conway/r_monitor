"""日志初始化：控制台 + 按大小轮转的文件日志。

作为常驻托盘程序，运行期错误不应只显示在会瞬时覆盖的状态栏里；
统一通过 logging 落到用户目录下的日志文件，便于事后排查。
"""
import logging
import logging.handlers

from .config import APP_NAME, DATA_DIR

LOG_PATH = DATA_DIR / f"{APP_NAME}.log"
_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_MAX_BYTES = 2 * 1024 * 1024   # 单文件 2 MB
_BACKUP_COUNT = 3              # 保留 3 个历史文件


def setup_logging(level: int = logging.INFO) -> None:
    """初始化根日志器（幂等：重复调用不会叠加 handler）。"""
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(level)

    formatter = logging.Formatter(_LOG_FORMAT)

    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setFormatter(formatter)
        root.addHandler(fh)
    except OSError:
        # 目录不可写时降级为仅控制台，不能让日志初始化反过来把程序搞崩。
        pass

    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    root.addHandler(ch)
