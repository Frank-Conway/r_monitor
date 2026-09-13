"""应用配置与设置持久化。

设置以强类型 dataclass（Settings）表示，并提供线程安全的 SettingsStore
供后台采样线程与 GUI 线程共享；读写磁盘时做类型/范围校验，避免手改
settings.json 或历史版本导致崩溃。
"""
import json
import logging
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "r_monitor"
# 单一版本源：pyproject.toml、version_info.txt 均由此派生；修改版本号只改这里。
# version_info.txt 由 tools/generate_version_info.py 再生成。
APP_VERSION = "1.0.0"

# 品牌主色（应用图标与托盘图标背景）；生成图标脚本与 UI 共用的单一来源。
BRAND_COLOR = "#1976d2"

# 数据与配置存放位置（用户主目录下，避免权限问题）
DATA_DIR = Path.home() / ".r_monitor"
DB_PATH = DATA_DIR / "r_monitor.db"
SETTINGS_PATH = DATA_DIR / "settings.json"

# settings.json 的结构版本；将来字段变更时递增并在此做迁移
SETTINGS_SCHEMA_VERSION = 1

_MB = 1024 * 1024


@dataclass(frozen=True)
class Settings:
    refresh_interval_ms: int = 1000          # 采样/刷新间隔（毫秒）
    history_points: int = 300                # 图表保留的采样点数
    upload_threshold_bps: int = _MB          # 上行告警阈值（字节/秒）
    download_threshold_bps: int = _MB        # 下行告警阈值（字节/秒）
    sustain_seconds: int = 10                # 高流量判定持续时间（秒）
    top_process_count: int = 10              # 进程流量榜展示条数
    close_action: str = "ask"                # ask=每次询问 / tray=最小化 / quit=退出
    theme: str = "dark"                      # dark=暗色 / light=亮色


# 字段取值范围（与设置页控件保持一致）
_RANGES = {
    "refresh_interval_ms": (200, 10000),
    "history_points": (30, 6000),
    "upload_threshold_bps": (0, 100000 * _MB),
    "download_threshold_bps": (0, 100000 * _MB),
    "sustain_seconds": (1, 300),
    "top_process_count": (3, 10),
}
_STR_CHOICES = {
    "close_action": ("ask", "tray", "quit"),
    "theme": ("dark", "light"),
}


def _coerce(raw: dict, f, default):
    """把 raw 里的单个字段转成合法值，非法时回退 default。"""
    key = f.name
    value = raw.get(key, default)
    if key in _RANGES:
        lo, hi = _RANGES[key]
        try:
            value = int(value)
        except (TypeError, ValueError):
            return default
        return max(lo, min(hi, value))
    if key in _STR_CHOICES:
        value = str(value)
        return value if value in _STR_CHOICES[key] else default
    return default


def load_settings() -> Settings:
    """读取设置；文件缺失/损坏/非法值时回退默认并做类型与范围钳制。"""
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {}
    except (OSError, ValueError) as exc:
        logger.warning("读取设置文件失败，回退默认设置: %s", exc)
        raw = {}
    if not isinstance(raw, dict):
        logger.warning("设置文件格式非法（非对象），回退默认设置")
        raw = {}

    kwargs = {f.name: _coerce(raw, f, f.default) for f in fields(Settings)}
    return Settings(**kwargs)


def save_settings(settings: Settings) -> None:
    """把设置写回磁盘（含 schema_version）。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SETTINGS_SCHEMA_VERSION}
    payload.update(asdict(settings))
    SETTINGS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class SettingsStore:
    """线程安全的设置快照容器。

    GUI 线程通过 update() 整体替换设置，采样线程通过 get() 读取最新快照；
    Settings 为 frozen dataclass（不可原地修改，用 replace/重建），
    通过整体替换避免跨线程数据竞争。
    """

    def __init__(self, settings: Settings):
        self._lock = threading.Lock()
        self._settings = settings

    def get(self) -> Settings:
        with self._lock:
            return self._settings

    def update(self, settings: Settings) -> None:
        with self._lock:
            self._settings = settings
