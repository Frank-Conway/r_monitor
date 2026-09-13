"""UI 通用工具：格式化与实时曲线组件。"""
from collections import deque

import pyqtgraph as pg

from . import theme


def fmt_rate(bps: float) -> str:
    """把 字节/秒 格式化为易读字符串。"""
    bps = max(0.0, bps)
    if bps >= 1024 ** 3:
        return f"{bps / 1024 ** 3:.2f} GB/s"
    if bps >= 1024 ** 2:
        return f"{bps / 1024 ** 2:.2f} MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps:.0f} B/s"


def fmt_duration(seconds: float) -> str:
    """把秒数格式化为紧凑可读字符串（如 45s / 3m25s / 1h02m）。"""
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def fmt_bytes(n: int) -> str:
    """把字节数格式化为易读字符串（1024 进制：B / KB / MB / GB）。"""
    n = max(0, int(n))
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def fmt_gb(n: float) -> str:
    return f"{n:.2f} GB"


class HistoryChart(pg.PlotWidget):
    """带固定长度历史缓冲的实时曲线。"""

    def __init__(self, title="", maxlen=300, ylabel="%", legend=False):
        super().__init__()
        pg.setConfigOptions(antialias=True)
        self._maxlen = maxlen
        self._t0 = None
        self._series = {}
        self.setBackground(theme.CHART_BG)
        self.setTitle(title, color=theme.TEXT, size="11pt")
        self.showGrid(x=True, y=True, alpha=0.22)
        self.setLabel("left", ylabel)
        self.setLabel("bottom", "经过时间（秒，自监控启动）")
        for axis in ("left", "bottom"):
            self.getAxis(axis).setTextPen(theme.MUTED)
            self.getAxis(axis).setPen(theme.BORDER)
        if legend:
            self._legend = self.addLegend(offset=(10, 10))
            self._legend.setLabelTextColor(theme.TEXT)
            self._legend.setBrush(pg.mkBrush(theme.PANEL_2))
            self._legend.setPen(pg.mkPen(theme.BORDER))
        else:
            self._legend = None

    def add_series(self, name: str, color: str):
        curve = self.plot(
            [], [], pen=pg.mkPen(color, width=2), name=name
        )
        self._series[name] = {
            "curve": curve,
            "x": deque(maxlen=self._maxlen),
            "y": deque(maxlen=self._maxlen),
        }
        return name

    def push(self, name: str, ts: float, value: float) -> None:
        series = self._series.get(name)
        if series is None:
            return
        if self._t0 is None:
            self._t0 = ts
        series["x"].append(ts - self._t0)
        series["y"].append(float(value))
        series["curve"].setData(list(series["x"]), list(series["y"]))
