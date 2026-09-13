"""CPU / 内存标签页。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .common import HistoryChart, fmt_gb

_TABLE_COLS = ["进程名", "PID", "CPU %", "服务 / 软件"]
_TOP_N = 5


class CpuWidget(QWidget):
    def __init__(self, history_points: int = 300, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # 顶部概览区：CPU 使用率与内存占用分成两个卡片，互不拥挤
        top = QHBoxLayout()
        top.setSpacing(12)

        cpu_box = QGroupBox("CPU 使用率")
        cpu_layout = QVBoxLayout(cpu_box)
        self.overall = _BigNumber()
        self.freq_label = QLabel("主频: -- MHz")
        self.freq_label.setStyleSheet(f"color:{theme.MUTED};")
        self.freq_label.setAlignment(Qt.AlignCenter)
        cpu_layout.addWidget(self.overall)
        cpu_layout.addWidget(self.freq_label)
        top.addWidget(cpu_box, 1)

        mem_box = QGroupBox("内存占用")
        mem_layout = QVBoxLayout(mem_box)
        self.mem_label = QLabel("内存: --")
        self.mem_bar = QProgressBar()
        self.mem_bar.setRange(0, 100)
        self.mem_bar.setTextVisible(True)
        mem_layout.addWidget(self.mem_label)
        mem_layout.addWidget(self.mem_bar)
        mem_layout.addStretch(1)
        top.addWidget(mem_box, 1)

        root.addLayout(top)

        # CPU 历史曲线（横轴为自监控启动起经过的秒数）
        self.chart = HistoryChart("CPU 使用率历史", maxlen=history_points, ylabel="%")
        self.chart.add_series("cpu", theme.ACCENT)
        self.chart.setMinimumHeight(160)
        self.chart.setMaximumHeight(220)
        root.addWidget(self.chart, 1)

        # 各核心
        self.cores_group = QGroupBox("各核心负载")
        self.cores_layout = QGridLayout(self.cores_group)
        self._core_bars = []  # 复用进度条，避免每秒销毁重建
        # 限制高度，把垂直空间让给下方的进程表，避免核心数多时挤压 TOP 进程表
        self.cores_group.setMaximumHeight(140)
        root.addWidget(self.cores_group)

        # 进程表
        root.addWidget(QLabel(f"CPU 占用 TOP {_TOP_N} 进程"))
        cpu_hint = QLabel(
            "CPU% 表示该进程占用的 CPU 比例；多核系统下可能超过 100%"
            "（100% 约等于一个核心满载）。"
        )
        cpu_hint.setStyleSheet(f"color:{theme.MUTED};")
        cpu_hint.setWordWrap(True)
        root.addWidget(cpu_hint)
        self.proc_table = QTableWidget(_TOP_N, len(_TABLE_COLS))
        self.proc_table.setHorizontalHeaderLabels(_TABLE_COLS)
        self.proc_table.horizontalHeader().setStretchLastSection(True)
        self.proc_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.proc_table.verticalHeader().setVisible(False)
        # 纯展示表：禁用选中与焦点，避免出现意外的选中高亮色
        self.proc_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.proc_table.setFocusPolicy(Qt.NoFocus)
        # 完整展示 TOP N 行：关闭滚动条并按固定 _TOP_N 行高度布局，避免启动瞬间被压缩
        self.proc_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.proc_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.proc_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        root.addWidget(self.proc_table)
        self._fit_proc_table_height()

    # ------------------------------------------------------------------ #
    def update(self, sample) -> None:
        self.overall.set_value(f"{sample.overall:.0f}%")
        self.freq_label.setText(f"主频: {sample.freq_mhz:.0f} MHz")
        self.mem_label.setText(
            f"内存 {fmt_gb(sample.mem_used_gb)} / {fmt_gb(sample.mem_total_gb)}"
        )
        self.mem_bar.setValue(int(round(sample.mem_percent)))
        self.chart.push("cpu", sample.ts, sample.overall)
        self._update_cores(sample.per_core)
        self._update_table(sample.top_processes[:_TOP_N])

    def _update_cores(self, per_core) -> None:
        cols = 4
        # 核心数变化时才重建进度条（罕见），否则原地 setValue
        if len(per_core) != len(self._core_bars):
            self._build_core_bars(len(per_core), cols)
        for i, val in enumerate(per_core):
            self._core_bars[i].setValue(int(round(val)))

    def _build_core_bars(self, n: int, cols: int) -> None:
        """按核心数一次性创建进度条，避免每个采样周期销毁重建。"""
        while self.cores_layout.count():
            item = self.cores_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._core_bars = []
        for i in range(n):
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setFormat(f"核 {i}: %p%")
            bar.setTextVisible(True)
            bar.setFixedHeight(20)
            self._core_bars.append(bar)
            self.cores_layout.addWidget(bar, i // cols, i % cols)

    def _update_table(self, procs) -> None:
        # 始终维持固定 TOP N 行：数据不足时用占位行补齐，保证高度恒定、不随采样抖动
        self.proc_table.setRowCount(_TOP_N)
        for r in range(_TOP_N):
            p = procs[r] if r < len(procs) else None
            self.proc_table.setItem(r, 0, QTableWidgetItem(p.name if p else "—"))
            self.proc_table.setItem(r, 1, QTableWidgetItem(str(p.pid) if p else ""))
            self.proc_table.setItem(r, 2, QTableWidgetItem(f"{p.cpu:.1f}" if p else ""))
            self.proc_table.setItem(r, 3, QTableWidgetItem(p.service if p else ""))
        self._fit_proc_table_height()

    def _fit_proc_table_height(self) -> None:
        """按固定 TOP N 行设置高度，让进程表完整显示且启动瞬间不被压缩。"""
        hdr_h = self.proc_table.horizontalHeader().sizeHint().height()
        row_h = self.proc_table.verticalHeader().defaultSectionSize()
        frame = 2 * self.proc_table.frameWidth()
        self.proc_table.setFixedHeight(hdr_h + _TOP_N * row_h + frame)


class _BigNumber(QWidget):
    """大号数值展示块。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._value = QLabel("--")
        self._value.setStyleSheet(
            f"font-size:44px; font-weight:bold; color:{theme.ACCENT};"
        )
        self._value.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._value)

    def set_value(self, text: str) -> None:
        self._value.setText(text)
