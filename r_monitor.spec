# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir + 精简 scapy + UPX 压缩 + 裁剪未用 Qt 模块）。

用法：python -m PyInstaller --noconfirm --clean r_monitor.spec
"""
import os

from PyInstaller.utils.hooks import collect_submodules

# 应用图标；exe 版本资源来自 version_info.txt（由 tools/generate_version_info.py
# 从 r_monitor.config.APP_VERSION 生成，请勿手改版本号）。
APP_ICON = "assets/app.ico"

# 只打包抓包/解析 IP/TCP/UDP 所需的 scapy 子模块，而非全量（全量含几百个协议层、
# contrib/asn1/tools 等，约多 10~20MB）。sniffer.py 已改为定向 import（不再 import
# scapy.all），故这里只保留核心包 + l2/inet 协议层。
# on_error="ignore"：scapy 含 arch.linux 等平台特定子包，在打包机导入会失败
# （缺 fcntl 等），本程序用不到，直接跳过且不告警，保持打包日志干净。
def _scapy_needed(name: str) -> bool:
    if name.startswith("scapy.layers."):
        return name.startswith(("scapy.layers.l2", "scapy.layers.inet"))
    return not name.startswith(("scapy.contrib", "scapy.asn1", "scapy.tools", "scapy.modules"))


scapy_hiddenimports = collect_submodules("scapy", filter=_scapy_needed, on_error="ignore")

# 本程序只用 QtCore/QtGui/QtWidgets；pyqtgraph 会硬导入 QtOpenGL/QtOpenGLWidgets
# （见 OpenGLHelpers.py），故这两者不能排除；其余为 hook 误带、可安全排除。
excluded_modules = [
    "tkinter",
    "PySide6.QtNetwork",
    "PySide6.QtSvg",
    "PySide6.QtTest",
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=scapy_hiddenimports,
    # 项目级 hooks 目录：覆盖 pyqtgraph hook，跳过无用的 pyqtgraph.opengl
    hookspath=[os.path.join(SPECPATH, "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)

# PyInstaller 的 PySide6 hook 会通过 collect_extra_binaries() 把 Qt 全部 DLL 一并收集，
# 这里把未使用的 Qt6 DLL 与软渲染器 opengl32sw.dll 剔除。
_DROP_PREFIXES = (
    "opengl32sw",          # 软件 OpenGL 渲染器：本程序不创建 GL 上下文，可安全剔除
    "Qt6Quick",           # Qt6Quick.dll
    "Qt6Qml",             # Qt6Qml*.dll
    "Qt6Pdf",             # Qt6Pdf.dll
    "Qt6VirtualKeyboard",
    "Qt6Network",
    "Qt6Svg",
    "Qt6Test",
)
_DROP_SUBPATHS = (
    "plugins/tls/",                # QtNetwork 的 OpenSSL 后端
    "plugins/networkinformation/",  # QtNetwork 的网卡信息后端
    "translations/",               # Qt 自带多语言翻译（界面为中文且未用 QTranslator）
)

# 这些插件目录只保留最小集，其余剔除（应用仅用 ico/png/jpeg 图标，平台仅 Windows）
_KEEP_ONLY = {
    "platforms/": {"qwindows.dll"},
    "imageformats/": {"qico.dll", "qjpeg.dll", "qpng.dll"},
}


def _keep_binary(entry):
    name = entry[0].replace("\\", "/")
    base = name.rsplit("/", 1)[-1]
    for prefix in _DROP_PREFIXES:
        if base.startswith(prefix):
            return False
    for sub in _DROP_SUBPATHS:
        if sub in name:
            return False
    for sub, keep in _KEEP_ONLY.items():
        if sub in name and base not in keep:
            return False
    return True


a.binaries = [b for b in a.binaries if _keep_binary(b)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='r_monitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=APP_ICON,
    version="version_info.txt",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    # api-ms-win-*.dll 与 python3.dll 是 Windows API 集 / 稳定 ABI 转发桩，
    # UPX 会报 NotCompressibleException，且压缩无收益，直接排除以避免打包日志刷屏。
    upx_exclude=["api-ms-win-*", "python3.dll"],
    name='r_monitor',
)
