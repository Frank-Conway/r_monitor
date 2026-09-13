"""系统集成：管理员权限检测、提权重启、开机自启。"""
import ctypes
import logging
import os
import subprocess
import sys
import winreg
from ctypes import wintypes

from . import single_instance

logger = logging.getLogger(__name__)

APP_KEY_NAME = "r_monitor"


def is_admin() -> bool:
    """当前进程是否以管理员权限运行。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _app_dir() -> str:
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def _is_frozen() -> bool:
    """是否以 PyInstaller 等打包后的方式运行。"""
    return bool(getattr(sys, "frozen", False))


def _launch_exe() -> str:
    """返回用于启动本程序的解释器/exe。

    源码运行：优先 pythonw.exe（无控制台窗口），不存在则回退 python.exe；
    打包运行：sys.executable 即打包出的 exe 自身。
    """
    if _is_frozen():
        return sys.executable
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return exe if os.path.exists(exe) else sys.executable


def _launch_args() -> list:
    """返回启动本程序所需的命令行参数。

    源码运行：需把脚本路径作为第一个参数传给 python(w)；
    打包运行：exe 自身即入口，透传用户参数即可。
    """
    if _is_frozen():
        return sys.argv[1:]
    return [os.path.abspath(sys.argv[0])] + sys.argv[1:]


def restart_as_admin() -> bool:
    """以管理员身份重启本程序；返回 True 表示已发起（当前实例应退出）。

    通过 ShellExecute 的 ``runas`` 触发 UAC 提权。
    """
    try:
        exe = _launch_exe()
        # list2cmdline 会正确处理引号与反斜杠转义，避免路径含引号时出错
        params = subprocess.list2cmdline(_launch_args())
        # 提权后是新进程：先释放单实例锁，让新实例能够获取；若提权被取消/失败
        # 则重新拿回锁，避免本实例继续运行时失去单实例保护。
        single_instance.release()
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe, params, _app_dir(), 1
        )
        ok = int(ret) > 32  # ShellExecute 返回值 >32 表示成功
        if not ok:
            single_instance.acquire()
        return ok
    except Exception:
        logger.exception("以管理员身份重启失败")
        single_instance.acquire()
        return False


def _run_key():
    return winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
    )


def get_autostart() -> bool:
    """是否已设置开机自启（HKCU Run 键）。"""
    try:
        with _run_key() as key:
            value, _ = winreg.QueryValueEx(key, APP_KEY_NAME)
            return bool(value)
    except (FileNotFoundError, OSError):
        return False


def set_autostart(enabled: bool) -> bool:
    """设置/取消开机自启（当前用户，无需管理员）。"""
    try:
        with _run_key() as key:
            if enabled:
                cmd = subprocess.list2cmdline([_launch_exe()] + _launch_args())
                winreg.SetValueEx(key, APP_KEY_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, APP_KEY_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        logger.exception("设置开机自启失败")
        return False


# --------------------------------------------------------------------------- #
# 原生标题栏上色（DWM）
# --------------------------------------------------------------------------- #
# DwmSetWindowAttribute 的属性 ID（dwmapi.h）：
#   - 沉浸式深色标题栏：1809(17763) 起为 19，20H1(18985) 起改为 20；
#   - 标题栏/边框/文字精确配色：Windows 11(22000) 起分别为 35/34/36。
_DWMWA_USE_IMMERSIVE_DARK_MODE_1809 = 19
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_BORDER_COLOR = 34
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36

_dwmapi = ctypes.WinDLL("dwmapi")
_dwmapi.DwmSetWindowAttribute.argtypes = [
    wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
]
_dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long


def _set_dwm_dword(hwnd: int, attr: int, value: int) -> bool:
    """给指定窗口设置一个 DWORD 型 DWM 属性，返回是否成功。"""
    v = wintypes.DWORD(value)
    ret = _dwmapi.DwmSetWindowAttribute(
        wintypes.HWND(hwnd), wintypes.DWORD(attr),
        ctypes.byref(v), ctypes.sizeof(v),
    )
    return ret == 0


def _hex_to_colorref(hex_color: str) -> int:
    """把 "#RRGGBB" 转成 COLORREF（0x00BBGGRR）。"""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return (b << 16) | (g << 8) | r


def apply_title_bar(window, caption: str, border: str, text: str, dark: bool) -> None:
    """给原生标题栏（带关闭按钮的那一栏）上色，使其与页面配色一致。

    - Windows 11（build >= 22000）：用 DWMWA_CAPTION_COLOR / BORDER_COLOR /
      TEXT_COLOR 精确设置标题栏背景、边框与标题文字颜色；
    - Windows 10（build >= 17763）：仅支持「沉浸式深色标题栏」，深色主题用深色、
      浅色主题保持系统默认；
    - 更老系统不做处理。
    """
    try:
        hwnd = int(window.winId())
        build = int(sys.getwindowsversion().build)
    except Exception:
        return
    try:
        if build >= 22000:
            _set_dwm_dword(hwnd, _DWMWA_CAPTION_COLOR, _hex_to_colorref(caption))
            _set_dwm_dword(hwnd, _DWMWA_BORDER_COLOR, _hex_to_colorref(border))
            _set_dwm_dword(hwnd, _DWMWA_TEXT_COLOR, _hex_to_colorref(text))
        elif build >= 17763:
            attr = (
                _DWMWA_USE_IMMERSIVE_DARK_MODE
                if build >= 18985
                else _DWMWA_USE_IMMERSIVE_DARK_MODE_1809
            )
            _set_dwm_dword(hwnd, attr, 1 if dark else 0)
    except Exception:
        logger.exception("设置标题栏颜色失败")
