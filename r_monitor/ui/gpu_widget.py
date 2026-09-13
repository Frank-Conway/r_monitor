"""GPU 标签页：跨厂商（NVIDIA / AMD / Intel）负载与显存。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .common import HistoryChart, fmt_bytes


class GpuWidget(QWidget):
    def __init__(self, history_points: int = 300, parent=None):
        super().__init__(parent)
        self.root = QVBoxLayout(self)

        # 在构造时读取当前主题配色（主题可能在启动时切换）
        self._colors = [
            theme.ACCENT_RED, theme.ACCENT_ORANGE, theme.ACCENT_GREEN,
            theme.ACCENT_PURPLE, theme.ACCENT, theme.MUTED,
        ]

        self.chart = HistoryChart("GPU 使用率历史", maxlen=history_points, ylabel="%", legend=True)
        self.root.addWidget(self.chart, 2)

        self._cards_root = QVBoxLayout()
        self.root.addLayout(self._cards_root, 3)

        self._adapter_seen = {}   # adapter index -> color
        self._cards = {}          # adapter index -> _GpuCard（复用，避免重建闪烁）
        self.placeholder = QLabel(
            "未检测到 GPU（或系统未提供 GPU 性能计数器）。"
        )
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet(f"color:{theme.MUTED};")
        self._cards_root.addWidget(self.placeholder)
        self._cards_root.setSpacing(8)

    # ------------------------------------------------------------------ #
    def update(self, sample) -> None:
        if not sample.adapters:
            # 无 GPU 时清空卡片并恢复占位提示
            self._clear_cards()
            self.placeholder.setVisible(True)
            return

        self.placeholder.setVisible(False)

        present = set()
        for ad in sample.adapters:
            idx = ad.index
            present.add(idx)

            # 为新增适配器分配颜色并确保曲线存在
            if idx not in self._adapter_seen:
                color = self._colors[len(self._adapter_seen) % len(self._colors)]
                self._adapter_seen[idx] = color
                self.chart.add_series(f"gpu{idx}", color)

            color = self._adapter_seen[idx]
            self.chart.push(f"gpu{idx}", sample.ts, ad.utilization)

            # 仅在适配器新增时创建卡片，其余原地更新
            card = self._cards.get(idx)
            if card is None:
                card = _GpuCard(ad, color)
                self._cards[idx] = card
                self._cards_root.addWidget(card)
            else:
                card.set_data(ad)

        # 移除已消失的适配器卡片
        for idx in list(self._cards):
            if idx not in present:
                card = self._cards.pop(idx)
                self._cards_root.removeWidget(card)
                card.deleteLater()

    def _clear_cards(self) -> None:
        """删除现有适配器卡片（保留占位提示）。"""
        for card in self._cards.values():
            self._cards_root.removeWidget(card)
            card.deleteLater()
        self._cards = {}


class _GpuCard(QWidget):
    def __init__(self, ad: dict, color: str, parent=None):
        super().__init__(parent)
        self._ad = ad
        # 卡片化：圆角边框 + 面板底色（随亮/暗主题变化）
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"background-color:{theme.PANEL}; "
            f"border:1px solid {theme.BORDER}; border-radius:8px;"
        )
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 10, 12, 10)

        self._name = QLabel()
        self._name.setStyleSheet("font-weight:bold; font-size:13px;")

        self._util = QLabel()
        self._util.setStyleSheet(f"font-size:26px; font-weight:bold; color:{color};")
        self._util.setAlignment(Qt.AlignCenter)

        grid.addWidget(self._name, 0, 0, 1, 4)
        grid.addWidget(QLabel("负载"), 1, 0)
        grid.addWidget(self._util, 1, 1, 1, 3)

        # 显存
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        grid.addWidget(QLabel("专用显存"), 2, 0)
        grid.addWidget(self._bar, 2, 1, 1, 3)

        self._shared = QLabel()
        grid.addWidget(QLabel("共享显存"), 3, 0)
        grid.addWidget(self._shared, 3, 1, 1, 3)

        # 主要引擎负载
        self._engines = QLabel()
        grid.addWidget(self._engines, 4, 0, 1, 4)

        self.set_data(ad)

    def set_data(self, ad) -> None:
        """原地更新卡片内容，避免销毁/重建带来的闪烁。"""
        self._ad = ad
        self._name.setText(ad.name)
        self._util.setText(f"{ad.utilization:.0f}%")

        vram = ad.vram_used
        total = ad.vram_total
        pct = round(vram / total * 100) if total > 0 else 0
        self._bar.setValue(pct)
        self._bar.setFormat(
            f"{fmt_bytes(vram)} / {fmt_bytes(total)} (%p%)" if total > 0
            else f"{fmt_bytes(vram)}"
        )
        self._shared.setText(fmt_bytes(ad.shared_used))

        engines = ad.engines or {}
        keys = [k for k in ("3D", "Copy", "VideoDecode", "VideoEncode", "Compute")
                if k in engines]
        if keys:
            self._engines.setText("  ".join(f"{k}: {engines[k]:.0f}%" for k in keys))
        else:
            self._engines.setText("")
