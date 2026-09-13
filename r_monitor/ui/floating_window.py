"""置顶悬浮窗：无边框、始终在最前、可拖动、可吸附屏幕右下角，显示 CPU / 内存占用。

用法：在 MainWindow 中创建后，通过 ``update_stats(cpu, mem)`` 刷新数值；
信号 ``show_main_requested`` / ``quit_requested`` 用于右键菜单回调。
"""
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QWidget,
)

from . import theme

_SNAP_PX = 40   # 距右下角小于该距离时自动吸附
_EDGE_GAP = 8   # 吸附后与屏幕边缘的间距


class FloatingMonitorWindow(QWidget):
    show_main_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self._drag_offset = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(5)

        self.cpu_label = QLabel("CPU --%")
        self.cpu_label.setObjectName("floatCpu")
        self.sep_label = QLabel("｜")
        self.sep_label.setObjectName("floatSep")
        self.mem_label = QLabel("内存 --%")
        self.mem_label.setObjectName("floatMem")

        for w in (self.cpu_label, self.sep_label, self.mem_label):
            layout.addWidget(w)

        self.setStyleSheet(self._qss())
        self.adjustSize()
        self._move_to_corner()

    def _qss(self) -> str:
        return (
            f"#floatCpu {{ color: {theme.ACCENT}; font-size: 14px; font-weight: bold; }}"
            f"#floatSep {{ color: {theme.MUTED}; font-size: 14px; }}"
            f"#floatMem {{ color: {theme.ACCENT_GREEN}; font-size: 14px; font-weight: bold; }}"
        )

    def update_stats(self, cpu: int, mem: int) -> None:
        self.cpu_label.setText(f"CPU {cpu}%")
        self.mem_label.setText(f"内存 {mem}%")

    # ------------------------------------------------------------------ #
    # 圆角背景
    # ------------------------------------------------------------------ #
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(theme.PANEL))
        p.drawRoundedRect(r, 8, 8)

    # ------------------------------------------------------------------ #
    # 拖动 + 吸附
    # ------------------------------------------------------------------ #
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
            self._maybe_snap()
        super().mouseReleaseEvent(event)

    def _screen(self):
        return self.screen() or QApplication.primaryScreen()

    def _target_corner(self):
        """返回当前屏幕右下角（可用区域，避开任务栏）的目标坐标。"""
        geo = self._screen().availableGeometry()
        return QPoint(
            geo.right() - self.width() - _EDGE_GAP,
            geo.bottom() - self.height() - _EDGE_GAP,
        )

    def _move_to_corner(self) -> None:
        if self._screen() is not None:
            self.move(self._target_corner())

    def _maybe_snap(self) -> None:
        target = self._target_corner()
        if abs(self.x() - target.x()) <= _SNAP_PX and abs(self.y() - target.y()) <= _SNAP_PX:
            self.move(target)

    # ------------------------------------------------------------------ #
    # 右键菜单
    # ------------------------------------------------------------------ #
    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        show_action = menu.addAction("显示主窗口")
        quit_action = menu.addAction("退出程序")
        chosen = menu.exec(event.globalPos())
        if chosen is show_action:
            self.show_main_requested.emit()
        elif chosen is quit_action:
            self.quit_requested.emit()
