"""r_monitor 入口。

用法：
    python main.py

启动逻辑位于 r_monitor/cli.py，供 `python main.py`、`python -m r_monitor.cli`
以及打包安装后的 `r-monitor` 命令共用，避免入口逻辑重复。
"""
import sys

from r_monitor.cli import main

if __name__ == "__main__":
    sys.exit(main())
