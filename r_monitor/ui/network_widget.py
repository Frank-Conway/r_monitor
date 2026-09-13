"""网络流量标签页：全局速率 + 每进程上下行。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import SettingsStore
from . import theme
from .common import HistoryChart, fmt_rate

_COLS = ["进程名", "PID", "上行", "下行", "连接数", "服务 / 软件"]


class NetworkWidget(QWidget):
    def __init__(self, store: SettingsStore, history_points: int = 300, parent=None):
        super().__init__(parent)
        self._store = store
        root = QVBoxLayout(self)

        # 全局速率
        rates = QHBoxLayout()
        self.up_value = _RateLabel("上传", theme.ACCENT_RED)
        self.down_value = _RateLabel("下载", theme.ACCENT)
        rates.addWidget(self.up_value)
        rates.addWidget(self.down_value)
        rates.addStretch(1)
        root.addLayout(rates)

        # 全局速率历史
        self.chart = HistoryChart("全局网络速率", maxlen=history_points, ylabel="速率", legend=True)
        self.chart.add_series("up", theme.ACCENT_RED)
        self.chart.add_series("down", theme.ACCENT)
        # 压缩曲线区高度，把空间让给下方的进程榜，保证 TOP N 完整展示
        self.chart.setMinimumHeight(120)
        self.chart.setMaximumHeight(180)
        root.addWidget(self.chart, 2)

        # 每进程
        self.note = QLabel("")
        self.note.setStyleSheet(f"color:{theme.MUTED};")
        root.addWidget(self.note)
        top_n = store.get().top_process_count
        self.section_label = QLabel(f"进程流量榜（TOP {top_n}）")
        root.addWidget(self.section_label)
        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        # 纯展示表：禁用选中与焦点，避免出现意外的选中高亮色
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        # 完整展示全部进程行：关闭滚动条并按当前行数固定高度
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        root.addWidget(self.table)
        self._fit_table_height()

    # ------------------------------------------------------------------ #
    def update(self, sample) -> None:
        self.up_value.set_value(fmt_rate(sample.total_up_bps))
        self.down_value.set_value(fmt_rate(sample.total_down_bps))
        self.chart.push("up", sample.ts, sample.total_up_bps)
        self.chart.push("down", sample.ts, sample.total_down_bps)

        top_n = self._store.get().top_process_count
        source = getattr(sample, "source", "connections")
        if source == "sniffer":
            self.note.setText("每进程字节来源：npcap 抓包（覆盖 TCP + UDP）。")
            self.section_label.setText(f"进程流量榜 TOP {top_n}（按总速率排序）")
        elif source == "estats":
            self.note.setText("每进程字节来源：TCP ESTATS（需管理员，UDP 未覆盖）。")
            self.section_label.setText(f"进程流量榜 TOP {top_n}（按总速率排序）")
        else:
            self.note.setText(
                "⚠ 无每进程字节数据（未提权且未装 npcap），现按连接数排序；"
                "如需精确字节：在「设置」页点「以管理员身份重启」，或安装 npcap。"
            )
            self.section_label.setText(f"进程榜 TOP {top_n}（按连接数排序）")

        procs = sample.processes
        # 固定 TOP N 行：不足时用空行补齐，保持表格高度稳定，避免随活跃进程数上下抖动
        self.table.setRowCount(top_n)
        for r in range(top_n):
            p = procs[r] if r < len(procs) else None
            if p is not None:
                items = [
                    QTableWidgetItem(p.name),
                    QTableWidgetItem(str(p.pid)),
                    QTableWidgetItem(fmt_rate(p.up_bps)),
                    QTableWidgetItem(fmt_rate(p.down_bps)),
                    QTableWidgetItem(str(p.conn_count)),
                    QTableWidgetItem(p.service),
                ]
            else:
                items = [QTableWidgetItem("") for _ in _COLS]
            for c, it in enumerate(items):
                if c in (2, 3, 4):  # 上行 / 下行 / 连接数为数字列，右对齐
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, it)

        self._fit_table_height()

    def _fit_table_height(self) -> None:
        """按当前行数设置固定高度，让进程榜完整显示而不出现滚动条。"""
        rows = self.table.rowCount()
        hdr_h = self.table.horizontalHeader().sizeHint().height()
        row_h = self.table.verticalHeader().defaultSectionSize()
        frame = 2 * self.table.frameWidth()
        self.table.setFixedHeight(hdr_h + rows * row_h + frame)


class _RateLabel(QWidget):
    def __init__(self, title: str, color: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        self._value = QLabel("--")
        self._value.setStyleSheet(f"font-size:26px; font-weight:bold; color:{color};")
        self._value.setAlignment(Qt.AlignCenter)
        t = QLabel(title)
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet(f"color:{theme.MUTED};")
        layout.addWidget(self._value)
        layout.addWidget(t)

    def set_value(self, text: str) -> None:
        self._value.setText(text)
