"""主窗口：承载各标签页、系统托盘，并启动采样线程。"""
import logging
import time
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStatusBar,
    QSystemTrayIcon,
    QTabWidget,
)

from .. import APP_NAME, config, system
from ..config import SettingsStore
from ..models import SampleBundle
from ..monitor import MonitorThread
from . import theme
from .cpu_widget import CpuWidget
from .floating_window import FloatingMonitorWindow
from .gpu_widget import GpuWidget
from .history_widget import HistoryWidget
from .network_widget import NetworkWidget
from .settings_widget import SettingsWidget

logger = logging.getLogger(__name__)

# 相同错误消息在状态栏的去重窗口（秒），避免持续失败时每秒刷屏
_ERROR_DEDUP_S = 3.0


def _make_app_icon() -> QIcon:
    """程序化生成一个简易图标（蓝色圆角底 + 三根柱状条）。"""
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(config.BRAND_COLOR))
    p.drawRoundedRect(0, 0, 64, 64, 14, 14)
    p.setBrush(QColor("white"))
    p.drawRect(14, 34, 8, 16)
    p.drawRect(28, 22, 8, 28)
    p.drawRect(42, 12, 8, 38)
    p.end()
    return QIcon(pix)


def _make_status_icon(cpu: float, mem: float) -> QIcon:
    """生成带实时负载的托盘图标：三根柱=CPU 使用率，底部绿条=内存占用。

    具体百分比数字由置顶悬浮窗显示（见 FloatingMonitorWindow）。
    """
    cpu = max(0.0, min(100.0, cpu))
    mem = max(0.0, min(100.0, mem))
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    # 背景
    p.setBrush(QColor(config.BRAND_COLOR))
    p.drawRoundedRect(0, 0, 64, 64, 14, 14)
    # CPU：三根柱，高度随 CPU 使用率变化
    p.setBrush(QColor("white"))
    h = max(2, int(round(cpu / 100.0 * 44)))
    for x in (14, 28, 42):
        p.drawRect(x, 52 - h, 8, h)
    # 内存：底部横向进度条
    p.setBrush(QColor(255, 255, 255, 60))
    p.drawRect(10, 56, 44, 3)
    p.setBrush(QColor("#34d399"))
    p.drawRect(10, 56, max(0, int(round(mem / 100.0 * 44))), 3)
    p.end()
    return QIcon(pix)


class MainWindow(QMainWindow):
    def __init__(self, store: SettingsStore, parent=None):
        super().__init__(parent)
        self._store = store
        settings = store.get()
        self._really_quit = False
        self._centered = False
        self._tray_notified = False
        self._tray_cpu = None
        self._tray_mem = None
        self._last_error_msg = ""
        self._last_error_ts = 0.0

        icon = _make_app_icon()
        self.setWindowIcon(icon)
        self.setWindowTitle(APP_NAME)
        self.resize(1120, 760)

        # 原生标题栏（带关闭按钮的那一栏）与页面同色系，并加边框色
        system.apply_title_bar(
            self,
            caption=theme.CHART_BG,
            border=theme.BORDER,
            text=theme.TEXT,
            dark=settings.theme == "dark",
        )

        history_points = settings.history_points

        tabs = QTabWidget()
        self.cpu_widget = CpuWidget(history_points=history_points)
        self.gpu_widget = GpuWidget(history_points=history_points)
        self.net_widget = NetworkWidget(store, history_points=history_points)
        self.history_widget = HistoryWidget()
        self.settings_widget = SettingsWidget(store)

        tabs.addTab(self.cpu_widget, "CPU / 内存")
        tabs.addTab(self.gpu_widget, "GPU")
        tabs.addTab(self.net_widget, "网络流量")
        tabs.addTab(self.history_widget, "高流量记录")
        tabs.addTab(self.settings_widget, "设置")
        self.setCentralWidget(tabs)

        self.status = QStatusBar()
        self.setStatusBar(self.status)

        self.settings_widget.settings_changed.connect(self._on_settings_changed)
        self.settings_widget.restart_as_admin_requested.connect(self._on_restart_as_admin)

        self._setup_tray(icon)

        # 置顶悬浮窗：最小化到托盘后显示 CPU / 内存占用
        self.floating = FloatingMonitorWindow()
        self.floating.show_main_requested.connect(self._show_from_tray)
        self.floating.quit_requested.connect(self._quit_app)

        # 采样线程
        self.monitor = MonitorThread(store, parent=self)
        self.monitor.sample_ready.connect(self._on_sample)
        self.monitor.error.connect(self._on_error)
        self.monitor.start()

    # ------------------------------------------------------------------ #
    # 托盘
    # ------------------------------------------------------------------ #
    def _setup_tray(self, icon: QIcon) -> None:
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        show_action = menu.addAction("显示主窗口")
        show_action.triggered.connect(self._show_from_tray)
        menu.addSeparator()
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self._quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self.floating.hide()

    def _quit_app(self) -> None:
        self._really_quit = True
        self._shutdown()
        self.tray.hide()
        QApplication.instance().quit()

    # ------------------------------------------------------------------ #
    def _on_sample(self, snap: SampleBundle) -> None:
        # 各标签页独立刷新：单个页面出错不应阻断其他页面
        for name, widget, sample in (
            ("cpu", self.cpu_widget, snap.cpu),
            ("gpu", self.gpu_widget, snap.gpu),
            ("net", self.net_widget, snap.net),
        ):
            try:
                widget.update(sample)
            except Exception as exc:
                self._on_error(f"{name} 界面刷新异常: {exc}")

        # 托盘图标 + 提示实时展示 CPU / 内存占用
        try:
            self._update_tray_stats(snap.cpu)
        except Exception:
            pass

    def _update_tray_stats(self, cpu_sample) -> None:
        """把 CPU / 内存占用刷新到托盘图标、悬停提示与置顶悬浮窗。"""
        cpu = int(round(cpu_sample.overall))
        mem = int(round(cpu_sample.mem_percent))
        if cpu == self._tray_cpu and mem == self._tray_mem:
            return  # 数值未变化，避免每秒无谓重绘托盘图标
        self._tray_cpu = cpu
        self._tray_mem = mem
        self.tray.setToolTip(
            f"{APP_NAME}\nCPU: {cpu}%  内存: {mem}%"
        )
        self.tray.setIcon(_make_status_icon(cpu, mem))
        self.floating.update_stats(cpu, mem)

    def _on_error(self, msg: str) -> None:
        now = time.monotonic()
        if msg == self._last_error_msg and now - self._last_error_ts < _ERROR_DEDUP_S:
            return
        self._last_error_msg = msg
        self._last_error_ts = now
        self.status.showMessage(f"⚠ {msg}")

    def _on_settings_changed(self, settings) -> None:
        self.status.showMessage("设置已保存。", 3000)

    def _on_restart_as_admin(self) -> None:
        if system.restart_as_admin():
            self._really_quit = True
            self._shutdown()
            QApplication.instance().quit()
        else:
            self.status.showMessage("⚠ 提权被取消或启动失败。", 5000)

    # ------------------------------------------------------------------ #
    def _shutdown(self) -> None:
        """停止采样线程（等待最多 3 秒），并关闭悬浮窗与历史记录存储。"""
        self.monitor.stop()
        self.monitor.wait(3000)
        if self.monitor.isRunning():
            logger.warning("采样线程未在 3 秒内退出，可能仍有资源未释放")
        self.floating.close()
        self.history_widget.shutdown()

    def _ask_close_action(self):
        """弹出关闭方式对话框，返回 (action, remember)。"""
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Question)
        box.setText("关闭程序")
        box.setInformativeText("请选择关闭方式：")
        tray_btn = box.addButton("最小化到托盘", QMessageBox.AcceptRole)
        quit_btn = box.addButton("退出程序", QMessageBox.DestructiveRole)
        box.setDefaultButton(tray_btn)
        remember_cb = QCheckBox("记住我的选择，不再询问")
        box.setCheckBox(remember_cb)
        box.exec()
        action = "quit" if box.clickedButton() is quit_btn else "tray"
        return action, remember_cb.isChecked()

    def showEvent(self, event) -> None:
        """首次显示时把窗口居中到主屏可用区域中央（后续恢复不再移动）。"""
        super().showEvent(event)
        if not self._centered:
            self._centered = True
            self._center_on_screen()

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        frame = self.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())

    def closeEvent(self, event) -> None:
        if self._really_quit:
            self._shutdown()
            super().closeEvent(event)
            return

        action = self._store.get().close_action
        if action not in ("tray", "quit", "ask"):
            action = "ask"

        if action == "ask":
            action, remember = self._ask_close_action()
            if remember:
                self._store.update(replace(self._store.get(), close_action=action))
                try:
                    config.save_settings(self._store.get())
                except OSError:
                    logger.exception("保存关闭方式到磁盘失败")

        if action == "quit":
            self._really_quit = True
            self._shutdown()
            super().closeEvent(event)
            return

        # 最小化到托盘
        event.ignore()
        self.hide()
        self.floating.show()
        if not self._tray_notified:
            self._tray_notified = True
            self.tray.showMessage(
                APP_NAME, "已最小化到系统托盘，双击图标可恢复窗口。"
            )
