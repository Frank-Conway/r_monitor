"""r_monitor — Windows 桌面系统监控工具。

读取 CPU / GPU 负载，并记录高流量的上传、下载进程。
"""

from .config import APP_NAME, APP_VERSION

__version__ = APP_VERSION
__all__ = ["APP_NAME", "APP_VERSION"]
