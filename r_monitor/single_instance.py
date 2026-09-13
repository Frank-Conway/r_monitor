"""单实例限制：确保同一时刻只运行一个 r_monitor 实例。

用 QtCore 的 QLockFile 实现：进程正常退出时由析构释放，进程被强杀后靠写入锁
文件的 PID 存活检测清理陈旧锁。不依赖 QtNetwork，与 PyInstaller 打包时裁剪
QtNetwork 的配置兼容（见 r_monitor.spec）。
"""
import logging
import os

from PySide6.QtCore import QDir, QLockFile

logger = logging.getLogger(__name__)

# 锁文件放在系统临时目录：同一用户跨提权级别可见且始终可写
_LOCK_FILENAME = "r_monitor.lock"

_lock: QLockFile | None = None


def acquire() -> bool:
    """尝试获取单实例锁。

    返回 True 表示本实例是唯一实例；False 表示已有其它实例在运行。
    幂等：已持有锁时直接返回 True。
    """
    global _lock
    if _lock is None:
        path = os.path.join(QDir.tempPath(), _LOCK_FILENAME)
        _lock = QLockFile(path)
    if _lock.isLocked():
        return True
    ok = _lock.tryLock(0)
    if not ok:
        logger.info("检测到已有 r_monitor 实例在运行")
    return ok


def release() -> None:
    """释放单实例锁（提权重启时，旧实例在拉起新进程前调用）。"""
    if _lock is not None and _lock.isLocked():
        _lock.unlock()
