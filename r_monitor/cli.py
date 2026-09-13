"""命令行入口：供 `python -m r_monitor.cli` 与安装后的 `r-monitor` 命令使用。

根目录的 `main.py` 只是转发到这里的薄壳，保证源码运行、`python -m` 运行、
以及打包安装后的 console script 三者共用同一套启动逻辑。
"""
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from . import config, logging_setup, single_instance
from .ui import theme
from .ui.main_window import MainWindow


def main() -> int:
    logging_setup.setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)

    # 单实例限制：避免重复采样、重复写库、多个托盘图标与日志文件竞争
    if not single_instance.acquire():
        QMessageBox.information(
            None,
            config.APP_NAME,
            "r_monitor 已经在运行，请从系统托盘打开已有实例。",
        )
        return 0

    store = config.SettingsStore(config.load_settings())
    theme.apply_theme(app, store.get().theme)

    window = MainWindow(store)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
