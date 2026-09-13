"""设置标签页。"""
import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import config, system
from ..config import Settings, SettingsStore
from . import theme

logger = logging.getLogger(__name__)

_MB = 1024 * 1024


class SettingsWidget(QWidget):
    settings_changed = Signal(object)   # 携带新的 Settings 快照
    restart_as_admin_requested = Signal()

    def __init__(self, store: SettingsStore, parent=None):
        super().__init__(parent)
        self._store = store
        settings = store.get()
        root = QVBoxLayout(self)

        form = QFormLayout()

        self.refresh = QSpinBox()
        self.refresh.setRange(200, 10000)
        self.refresh.setSuffix(" ms")
        self.refresh.setValue(settings.refresh_interval_ms)
        form.addRow("采样/刷新间隔", self.refresh)

        self.history = QSpinBox()
        self.history.setRange(30, 6000)
        self.history.setValue(settings.history_points)
        form.addRow("图表保留点数", self.history)

        self.up_th = QDoubleSpinBox()
        self.up_th.setRange(0, 100000)
        self.up_th.setDecimals(3)
        self.up_th.setSuffix(" MB/s")
        self.up_th.setValue(settings.upload_threshold_bps / _MB)
        form.addRow("上传告警阈值", self.up_th)

        self.down_th = QDoubleSpinBox()
        self.down_th.setRange(0, 100000)
        self.down_th.setDecimals(3)
        self.down_th.setSuffix(" MB/s")
        self.down_th.setValue(settings.download_threshold_bps / _MB)
        form.addRow("下载告警阈值", self.down_th)

        self.top_n = QSpinBox()
        self.top_n.setRange(3, 10)
        self.top_n.setValue(settings.top_process_count)
        form.addRow("进程流量榜条数", self.top_n)

        self.sustain = QSpinBox()
        self.sustain.setRange(1, 300)
        self.sustain.setSuffix(" s")
        self.sustain.setValue(settings.sustain_seconds)
        form.addRow("高流量持续时间", self.sustain)

        sustain_hint = QLabel(
            "高流量判定：进程在「高流量持续时间」内的平均上传/下载速率"
            "超过对应阈值时才记入高流量记录。"
        )
        sustain_hint.setStyleSheet(f"color:{theme.MUTED};")
        sustain_hint.setWordWrap(True)
        form.addRow(sustain_hint)

        self.close_action = QComboBox()
        self.close_action.addItem("每次询问", "ask")
        self.close_action.addItem("最小化到托盘", "tray")
        self.close_action.addItem("退出程序", "quit")
        for i in range(self.close_action.count()):
            if self.close_action.itemData(i) == settings.close_action:
                self.close_action.setCurrentIndex(i)
                break
        form.addRow("关闭窗口时", self.close_action)

        self.theme = QComboBox()
        self.theme.addItem("暗色", "dark")
        self.theme.addItem("亮色", "light")
        for i in range(self.theme.count()):
            if self.theme.itemData(i) == settings.theme:
                self.theme.setCurrentIndex(i)
                break
        form.addRow("主题", self.theme)

        group = QGroupBox("参数")
        group.setLayout(form)
        root.addWidget(group)

        # 系统权限
        sys_group = QGroupBox("系统权限")
        sys_form = QFormLayout()
        self.admin_status = QLabel("")
        sys_form.addRow("当前权限", self.admin_status)
        self.restart_btn = QPushButton("以管理员身份重启")
        self.restart_btn.clicked.connect(self.restart_as_admin_requested.emit)
        sys_form.addRow(self.restart_btn)
        self.autostart_cb = QCheckBox("开机自启")
        self.autostart_cb.setChecked(system.get_autostart())
        self.autostart_cb.toggled.connect(self._toggle_autostart)
        sys_form.addRow(self.autostart_cb)
        self.admin_hint = QLabel(
            "精确的每进程字节需要管理员权限（TCP ESTATS）或安装 npcap 抓包（TCP+UDP）。"
        )
        self.admin_hint.setWordWrap(True)
        self.admin_hint.setStyleSheet(f"color:{theme.MUTED};")
        sys_form.addRow(self.admin_hint)
        sys_group.setLayout(sys_form)
        root.addWidget(sys_group)

        self._refresh_admin_status()

        row = QHBoxLayout()
        self.hint = QLabel("阈值/间隔/持续时间/进程榜条数立即生效；主题、图表点数重启后生效。")
        self.hint.setStyleSheet(f"color:{theme.MUTED};")
        save = QPushButton("保存")
        save.clicked.connect(self._save)
        row.addWidget(self.hint, 1)
        row.addWidget(save)
        root.addLayout(row)
        root.addStretch(1)

    # ------------------------------------------------------------------ #
    def _refresh_admin_status(self) -> None:
        if system.is_admin():
            self.admin_status.setText("✅ 管理员（每进程 TCP 字节可用）")
            self.restart_btn.setEnabled(False)
            self.restart_btn.setText("已以管理员身份运行")
        else:
            self.admin_status.setText("⚠ 普通用户（每进程字节受限）")
            self.restart_btn.setEnabled(True)

    def _toggle_autostart(self, enabled: bool) -> None:
        if not system.set_autostart(enabled):
            self.autostart_cb.blockSignals(True)
            self.autostart_cb.setChecked(not enabled)
            self.autostart_cb.blockSignals(False)
            self.admin_status.setText("⚠ 开机自启设置失败")

    def _save(self) -> None:
        new = Settings(
            refresh_interval_ms=self.refresh.value(),
            history_points=self.history.value(),
            upload_threshold_bps=int(self.up_th.value() * _MB),
            download_threshold_bps=int(self.down_th.value() * _MB),
            top_process_count=self.top_n.value(),
            sustain_seconds=self.sustain.value(),
            close_action=self.close_action.currentData(),
            theme=self.theme.currentData(),
        )
        # 先更新内存快照：即使写盘失败，本次会话内的设置也应立即生效
        self._store.update(new)
        try:
            config.save_settings(new)
            self.hint.setText("已保存。")
        except OSError as exc:
            logger.exception("保存设置到磁盘失败")
            self.hint.setText(f"⚠ 设置已在本会话生效，但写入磁盘失败：{exc}")
        self.settings_changed.emit(new)
