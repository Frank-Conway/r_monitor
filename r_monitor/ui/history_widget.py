"""高流量记录标签页（读取 SQLite）。"""
import time

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..storage import Storage
from .common import fmt_duration, fmt_rate

_COLS = ["时间", "进程名", "PID", "上行", "下行", "方向", "持续时间", "服务 / 软件", "远端地址"]

# 可变长文本列：用 Stretch 弹性伸缩填满剩余宽度，避免长文本把列撑得过宽、使表格超出页面
_STRETCH_COLS = {1, 7, 8}  # 进程名 / 服务 / 远端地址


class _ElideTipDelegate(QStyledItemDelegate):
    """文本被省略号截断时，鼠标悬停以气泡展示完整内容。

    省略号的绘制交给默认委托（配合 ``QTableWidget.setTextElideMode``），
    这里只负责在文本确实放不下的情况下弹出气泡提示。
    """

    def helpEvent(self, event, view, option, index):
        if event.type() != QEvent.Type.ToolTip:
            return super().helpEvent(event, view, option, index)
        text = str(index.data(Qt.DisplayRole) or "")
        if not text:
            return False
        if option.fontMetrics.horizontalAdvance(text) > option.rect.width():
            QToolTip.showText(event.globalPos(), text, view)
            return True
        return super().helpEvent(event, view, option, index)


class HistoryWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._storage = Storage()
        root = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("超过阈值的高流量进程记录"))
        toolbar.addStretch(1)
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.reload)
        clear_btn = QPushButton("清空记录")
        clear_btn.clicked.connect(self.clear)
        toolbar.addWidget(refresh_btn)
        toolbar.addWidget(clear_btn)
        root.addLayout(toolbar)

        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        # 文本列弹性伸缩占满剩余宽度，短列按内容自适应，共同保证表格不超出页面
        for c in _STRETCH_COLS:
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        for c in range(len(_COLS)):
            if c not in _STRETCH_COLS:
                header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        # 文本在列尾显示省略号，配合 _ElideTipDelegate 悬停展示全文
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setItemDelegate(_ElideTipDelegate(self.table))
        root.addWidget(self.table)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.reload)
        self._timer.start(5000)
        self.reload()

    def reload(self) -> None:
        # 仅加载最近 300 条记录，避免表格行数过多导致卡顿（如需更多可调大）
        rows = self._storage.recent_events(300)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            ts, pid, name, up, down, direction, service, duration, remote_addrs = row
            t = time.strftime("%H:%M:%S", time.localtime(ts))
            vals = [
                t, name, str(pid), fmt_rate(up), fmt_rate(down),
                "▲ 上传" if direction == "up" else "▼ 下载",
                fmt_duration(duration),
                service or "",
                remote_addrs or "",
            ]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))

    def clear(self) -> None:
        self._storage.clear()
        self.reload()

    def shutdown(self) -> None:
        """关闭存储连接（由 MainWindow 退出时调用）。"""
        self._timer.stop()
        self._storage.close()