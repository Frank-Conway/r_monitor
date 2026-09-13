"""全局主题：亮色 / 暗色两套配色 + QPalette + QSS。

通过 ``apply_theme(app, mode)`` 一次性应用；``mode`` 为 ``"dark"``（默认）或 ``"light"``。
应用后本模块的配色常量（``ACCENT`` / ``MUTED`` / ``PANEL`` …）会随之更新，
因此各控件在构造时读取这些常量即可拿到当前主题的配色。
"""
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# ---- 两套配色表 ----------------------------------------------------------- #
_DARK = {
    "BG": "#0f1216", "PANEL": "#171b22", "PANEL_2": "#1d222b",
    "BORDER": "#2a3038", "TEXT": "#e7ebf0", "MUTED": "#8b94a1",
    "ACCENT": "#38bdf8", "ACCENT_RED": "#f87171", "ACCENT_GREEN": "#34d399",
    "ACCENT_ORANGE": "#fbbf24", "ACCENT_PURPLE": "#a78bfa",
    "CHART_BG": "#13171d", "HIGHLIGHT": "#1e3a5f",
    "HIGHLIGHT_TEXT": "#ffffff", "DISABLED": "#5b6570",
}

_LIGHT = {
    "BG": "#f3f5f7", "PANEL": "#ffffff", "PANEL_2": "#e9edf2",
    "BORDER": "#d6dce3", "TEXT": "#1f242b", "MUTED": "#6b7280",
    "ACCENT": "#0284c7", "ACCENT_RED": "#dc2626", "ACCENT_GREEN": "#059669",
    "ACCENT_ORANGE": "#d97706", "ACCENT_PURPLE": "#7c3aed",
    "CHART_BG": "#ffffff", "HIGHLIGHT": "#0078d7",
    "HIGHLIGHT_TEXT": "#ffffff", "DISABLED": "#9aa3ad",
}

# 当前生效的配色常量（默认暗色；apply_theme 会更新这些值）
BG = _DARK["BG"]
PANEL = _DARK["PANEL"]
PANEL_2 = _DARK["PANEL_2"]
BORDER = _DARK["BORDER"]
TEXT = _DARK["TEXT"]
MUTED = _DARK["MUTED"]
ACCENT = _DARK["ACCENT"]
ACCENT_RED = _DARK["ACCENT_RED"]
ACCENT_GREEN = _DARK["ACCENT_GREEN"]
ACCENT_ORANGE = _DARK["ACCENT_ORANGE"]
ACCENT_PURPLE = _DARK["ACCENT_PURPLE"]
CHART_BG = _DARK["CHART_BG"]


def _make_palette(c: dict) -> QPalette:
    p = QPalette()
    p.setColor(QPalette.Window, QColor(c["BG"]))
    p.setColor(QPalette.WindowText, QColor(c["TEXT"]))
    p.setColor(QPalette.Base, QColor(c["PANEL_2"]))
    p.setColor(QPalette.AlternateBase, QColor(c["PANEL"]))
    p.setColor(QPalette.Text, QColor(c["TEXT"]))
    p.setColor(QPalette.Button, QColor(c["PANEL_2"]))
    p.setColor(QPalette.ButtonText, QColor(c["TEXT"]))
    p.setColor(QPalette.Highlight, QColor(c["HIGHLIGHT"]))
    p.setColor(QPalette.HighlightedText, QColor(c["HIGHLIGHT_TEXT"]))
    p.setColor(QPalette.ToolTipBase, QColor(c["PANEL_2"]))
    p.setColor(QPalette.ToolTipText, QColor(c["TEXT"]))
    p.setColor(QPalette.PlaceholderText, QColor(c["MUTED"]))
    p.setColor(QPalette.Link, QColor(c["ACCENT"]))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        p.setColor(QPalette.Disabled, role, QColor(c["DISABLED"]))
    return p


DARK_STYLESHEET = """
QWidget {
    color: #e7ebf0;
    font-size: 13px;
    font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
}
QMainWindow, QDialog { background-color: #0f1216; }

QTabWidget::pane {
    border: 1px solid #2a3038;
    border-radius: 8px;
    background-color: #13171d;
    top: -1px;
}
QTabBar::tab {
    background-color: #171b22;
    color: #8b94a1;
    padding: 8px 20px;
    border: 1px solid #2a3038;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}
QTabBar::tab:hover:!selected { background-color: #1d222b; color: #e7ebf0; }
QTabBar::tab:selected {
    background-color: #1d222b;
    color: #38bdf8;
    border-top: 2px solid #38bdf8;
}
QTabBar {
    background-color: #13171d;
    border-bottom: 1px solid #2a3038;
}

QGroupBox {
    background-color: #171b22;
    border: 1px solid #2a3038;
    border-radius: 8px;
    margin-top: 12px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: #38bdf8;
}
QLabel { background: transparent; }

QProgressBar {
    background-color: #232a33;
    border: 1px solid #2a3038;
    border-radius: 5px;
    text-align: center;
    color: #e7ebf0;
    min-height: 16px;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0ea5e9, stop:1 #38bdf8);
    border-radius: 4px;
}

QTableWidget {
    background-color: #13171d;
    alternate-background-color: #171b22;
    gridline-color: #232a33;
    border: 1px solid #2a3038;
    border-radius: 6px;
    selection-background-color: #1e3a5f;
    selection-color: #ffffff;
}
QHeaderView::section {
    background-color: #1d222b;
    color: #9aa6b2;
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid #2a3038;
    border-right: 1px solid #232a33;
    font-weight: bold;
}
QTableCornerButton::section { background-color: #1d222b; border: none; }

QPushButton {
    background-color: #1d222b;
    color: #e7ebf0;
    border: 1px solid #2a3038;
    border-radius: 6px;
    padding: 6px 16px;
}
QPushButton:hover { background-color: #232a33; border-color: #38bdf8; }
QPushButton:pressed { background-color: #2b3542; }
QPushButton:disabled { color: #5b6570; background-color: #171b22; }

QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #1d222b;
    color: #e7ebf0;
    border: 1px solid #2a3038;
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: #1e3a5f;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: #1d222b;
    color: #e7ebf0;
    border: 1px solid #2a3038;
    selection-background-color: #1e3a5f;
}

QCheckBox { background: transparent; spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #2a3038;
    border-radius: 4px;
    background-color: #1d222b;
}
QCheckBox::indicator:checked { background-color: #38bdf8; border-color: #38bdf8; }

QStatusBar {
    background-color: #171b22;
    border-top: 1px solid #2a3038;
    color: #8b94a1;
}
QMenu { background-color: #1d222b; color: #e7ebf0; border: 1px solid #2a3038; }
QMenu::item { padding: 6px 24px; }
QMenu::item:selected { background-color: #1e3a5f; }
QToolTip { background-color: #1d222b; color: #e7ebf0; border: 1px solid #2a3038; padding: 4px; }

QScrollBar:vertical { background: #171b22; width: 10px; border-radius: 5px; }
QScrollBar::handle:vertical { background: #2f3742; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #3a4552; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #171b22; height: 10px; border-radius: 5px; }
QScrollBar::handle:horizontal { background: #2f3742; border-radius: 5px; min-width: 24px; }
QScrollBar::handle:horizontal:hover { background: #3a4552; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""

LIGHT_STYLESHEET = """
QWidget {
    color: #1f242b;
    font-size: 13px;
    font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
}
QMainWindow, QDialog { background-color: #f3f5f7; }

QTabWidget::pane {
    border: 1px solid #d6dce3;
    border-radius: 8px;
    background-color: #ffffff;
    top: -1px;
}
QTabBar::tab {
    background-color: #e9edf2;
    color: #6b7280;
    padding: 8px 20px;
    border: 1px solid #d6dce3;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}
QTabBar::tab:hover:!selected { background-color: #ffffff; color: #1f242b; }
QTabBar::tab:selected {
    background-color: #ffffff;
    color: #0284c7;
    border-top: 2px solid #0284c7;
}
QTabBar {
    background-color: #ffffff;
    border-bottom: 1px solid #d6dce3;
}

QGroupBox {
    background-color: #ffffff;
    border: 1px solid #d6dce3;
    border-radius: 8px;
    margin-top: 12px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: #0284c7;
}
QLabel { background: transparent; }

QProgressBar {
    background-color: #e3e8ee;
    border: 1px solid #d6dce3;
    border-radius: 5px;
    text-align: center;
    color: #1f242b;
    min-height: 16px;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #0ea5e9, stop:1 #38bdf8);
    border-radius: 4px;
}

QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #f5f7fa;
    gridline-color: #e3e8ee;
    border: 1px solid #d6dce3;
    border-radius: 6px;
    selection-background-color: #cfe3f7;
    selection-color: #1f242b;
}
QHeaderView::section {
    background-color: #eef1f5;
    color: #4b5563;
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid #d6dce3;
    border-right: 1px solid #e3e8ee;
    font-weight: bold;
}
QTableCornerButton::section { background-color: #eef1f5; border: none; }

QPushButton {
    background-color: #ffffff;
    color: #1f242b;
    border: 1px solid #d6dce3;
    border-radius: 6px;
    padding: 6px 16px;
}
QPushButton:hover { background-color: #eef1f5; border-color: #0284c7; }
QPushButton:pressed { background-color: #e3e8ee; }
QPushButton:disabled { color: #9aa3ad; background-color: #f0f2f5; }

QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #ffffff;
    color: #1f242b;
    border: 1px solid #d6dce3;
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: #cfe3f7;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #1f242b;
    border: 1px solid #d6dce3;
    selection-background-color: #cfe3f7;
}

QCheckBox { background: transparent; spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #c3cad2;
    border-radius: 4px;
    background-color: #ffffff;
}
QCheckBox::indicator:checked { background-color: #0284c7; border-color: #0284c7; }

QStatusBar {
    background-color: #ffffff;
    border-top: 1px solid #d6dce3;
    color: #6b7280;
}
QMenu { background-color: #ffffff; color: #1f242b; border: 1px solid #d6dce3; }
QMenu::item { padding: 6px 24px; }
QMenu::item:selected { background-color: #cfe3f7; }
QToolTip { background-color: #ffffff; color: #1f242b; border: 1px solid #d6dce3; padding: 4px; }

QScrollBar:vertical { background: #e9edf2; width: 10px; border-radius: 5px; }
QScrollBar::handle:vertical { background: #c3cad2; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #aeb7c2; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #e9edf2; height: 10px; border-radius: 5px; }
QScrollBar::handle:horizontal { background: #c3cad2; border-radius: 5px; min-width: 24px; }
QScrollBar::handle:horizontal:hover { background: #aeb7c2; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""


def apply_theme(app: QApplication, mode: str = "dark") -> None:
    """应用主题。mode 为 "dark"（默认）或 "light"。

    同时更新本模块暴露的配色常量，供后续构造的控件/图表读取。
    """
    global BG, PANEL, PANEL_2, BORDER, TEXT, MUTED, \
        ACCENT, ACCENT_RED, ACCENT_GREEN, ACCENT_ORANGE, ACCENT_PURPLE, CHART_BG
    c = _LIGHT if mode == "light" else _DARK
    BG, PANEL, PANEL_2, BORDER, TEXT, MUTED = (
        c["BG"], c["PANEL"], c["PANEL_2"], c["BORDER"], c["TEXT"], c["MUTED"],
    )
    ACCENT, ACCENT_RED, ACCENT_GREEN, ACCENT_ORANGE, ACCENT_PURPLE, CHART_BG = (
        c["ACCENT"], c["ACCENT_RED"], c["ACCENT_GREEN"],
        c["ACCENT_ORANGE"], c["ACCENT_PURPLE"], c["CHART_BG"],
    )
    app.setPalette(_make_palette(c))
    app.setStyleSheet(LIGHT_STYLESHEET if mode == "light" else DARK_STYLESHEET)
