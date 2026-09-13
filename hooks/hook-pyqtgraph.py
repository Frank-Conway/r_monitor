# -*- coding: utf-8 -*-
"""项目级 pyqtgraph hook：覆盖 PyInstaller 自带的 hook。

自带 hook 会 `collect_submodules("pyqtgraph")` 递归进入 `pyqtgraph.opengl`、
`pyqtgraph.jupyter` 等子模块，而这些模块依赖未安装的 PyOpenGL / jupyter_rfb，
导致打包时打印 "Failed to collect submodules for 'pyqtgraph.xxx'"。

本程序只用 2D 绘图（PlotWidget），不创建任何 GL 上下文，用不到这些模块，
故这里在收集子模块时用 on_error="ignore" 静默跳过导入失败，保持打包日志干净。
其余行为与自带 hook 一致。
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# pyqtgraph 数据文件（色标、图标等），排除 examples 示例数据
datas = collect_data_files("pyqtgraph", excludes=["**/examples/*"])

# 收集 Qt 版本相关的模板子模块；跳过 pyqtgraph.examples（避免误实例化 QApplication）。
# on_error="ignore"：opengl、jupyter 等子模块依赖未安装的 PyOpenGL/jupyter_rfb，
# 导入会失败，但本程序只用 2D 绘图，用不到它们，直接跳过且不告警。
all_imports = collect_submodules(
    "pyqtgraph",
    filter=lambda name: name != "pyqtgraph.examples",
    on_error="ignore",
)
hiddenimports = [name for name in all_imports if "Template" in name]

# pyqtgraph.multiprocess 的引导模块（其 multiprocessing 运行时需要）
hiddenimports += ["pyqtgraph.multiprocess.bootstrap"]

# 排除多余的 Qt 绑定（只保留 PySide6）
try:
    from PyInstaller.utils.hooks.qt import exclude_extraneous_qt_bindings
except ImportError:
    pass
else:
    excludedimports = exclude_extraneous_qt_bindings(
        hook_name="hook-pyqtgraph",
        qt_bindings_order=None,
    )
