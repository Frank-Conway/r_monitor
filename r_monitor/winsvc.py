"""进程归属信息解析（无需管理员权限）。

- 服务名：通过 SCM（advapi32.dll）建立 PID -> 服务显示名 映射；
- 软件名：通过可执行文件版本资源（version.dll）读取 FileDescription / ProductName，
  作为「该进程不是服务」时的回退展示。
"""
import ctypes
import logging
import time
from collections import OrderedDict
from ctypes import wintypes

import psutil

logger = logging.getLogger(__name__)

_SC_MANAGER_ENUMERATE_SERVICE = 0x0004
_SC_MANAGER_CONNECT = 0x0001
_SC_ENUM_PROCESS_INFO = 0
_SERVICE_WIN32 = 0x00000030
_SERVICE_STATE_ALL = 0x00000003

# 服务列表刷新间隔：服务启停不频繁，避免每个采样周期都枚举一次 SCM
_REFRESH_INTERVAL_S = 15.0


class _SERVICE_STATUS_PROCESS(ctypes.Structure):
    _fields_ = [
        ("dwServiceType", wintypes.DWORD),
        ("dwCurrentState", wintypes.DWORD),
        ("dwControlsAccepted", wintypes.DWORD),
        ("dwWin32ExitCode", wintypes.DWORD),
        ("dwServiceSpecificExitCode", wintypes.DWORD),
        ("dwCheckPoint", wintypes.DWORD),
        ("dwWaitHint", wintypes.DWORD),
        ("dwProcessId", wintypes.DWORD),
        ("dwServiceFlags", wintypes.DWORD),
    ]


class _ENUM_SERVICE_STATUS_PROCESS(ctypes.Structure):
    _fields_ = [
        ("lpServiceName", ctypes.c_wchar_p),
        ("lpDisplayName", ctypes.c_wchar_p),
        ("ServiceStatusProcess", _SERVICE_STATUS_PROCESS),
    ]


_advapi32 = ctypes.WinDLL("advapi32.dll", use_last_error=True)
_advapi32.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
_advapi32.OpenSCManagerW.restype = wintypes.HANDLE
_advapi32.CloseServiceHandle.argtypes = [wintypes.HANDLE]
_advapi32.CloseServiceHandle.restype = wintypes.BOOL
_advapi32.EnumServicesStatusExW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.LPBYTE, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), wintypes.LPCWSTR,
]
_advapi32.EnumServicesStatusExW.restype = wintypes.BOOL


def _enum_pid_to_services() -> dict[int, list[str]]:
    """枚举运行中的 Win32 服务，返回 {pid: [显示名, ...]}。"""
    result: dict[int, list[str]] = {}
    scm = _advapi32.OpenSCManagerW(
        None, None, _SC_MANAGER_ENUMERATE_SERVICE | _SC_MANAGER_CONNECT
    )
    if not scm:
        return result
    try:
        needed = wintypes.DWORD(0)
        returned = wintypes.DWORD(0)
        resume = wintypes.DWORD(0)
        _advapi32.EnumServicesStatusExW(
            scm, _SC_ENUM_PROCESS_INFO, _SERVICE_WIN32, _SERVICE_STATE_ALL,
            None, 0, ctypes.byref(needed), ctypes.byref(returned),
            ctypes.byref(resume), None,
        )
        if needed.value == 0:
            return result
        buf = ctypes.create_string_buffer(needed.value)
        ok = _advapi32.EnumServicesStatusExW(
            scm, _SC_ENUM_PROCESS_INFO, _SERVICE_WIN32, _SERVICE_STATE_ALL,
            ctypes.cast(buf, wintypes.LPBYTE), needed.value,
            ctypes.byref(needed), ctypes.byref(returned), ctypes.byref(resume), None,
        )
        if not ok:
            return result

        arr = ctypes.cast(buf, ctypes.POINTER(_ENUM_SERVICE_STATUS_PROCESS))
        for i in range(returned.value):
            e = arr[i]
            pid = int(e.ServiceStatusProcess.dwProcessId)
            if pid <= 0:  # 未运行的服务 dwProcessId 为 0
                continue
            name = e.lpDisplayName or e.lpServiceName or f"PID {pid}"
            result.setdefault(pid, []).append(name)
    finally:
        _advapi32.CloseServiceHandle(scm)
    return result


_svc_cache_ts = 0.0
_svc_cache_map: dict[int, list[str]] = {}


def service_names_for(pid: int) -> str:
    """返回 pid 对应的服务名（显示名，多个用「、」连接）；无服务返回空串。"""
    global _svc_cache_ts, _svc_cache_map
    now = time.time()
    if now - _svc_cache_ts > _REFRESH_INTERVAL_S:
        try:
            _svc_cache_map = _enum_pid_to_services()
        except Exception:
            logger.exception("枚举服务列表失败，沿用旧缓存")
        _svc_cache_ts = now

    names = _svc_cache_map.get(int(pid))
    if not names:
        return ""
    if len(names) <= 3:
        return "、 ".join(names)
    return "、 ".join(names[:3]) + f" 等{len(names)}个服务"


# --------------------------------------------------------------------------- #
# 软件名（进程可执行文件的 FileDescription / ProductName）
# --------------------------------------------------------------------------- #

_version = ctypes.WinDLL("version.dll", use_last_error=True)
_version.GetFileVersionInfoSizeW.argtypes = [
    wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD),
]
_version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
_version.GetFileVersionInfoW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
]
_version.GetFileVersionInfoW.restype = wintypes.BOOL
_version.VerQueryValueW.argtypes = [
    ctypes.c_void_p, wintypes.LPCWSTR,
    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT),
]
_version.VerQueryValueW.restype = wintypes.BOOL

# 缓存上限（LRU 淘汰，避免长期运行无界增长）
_EXE_CACHE_MAX = 4096
_SOFTWARE_CACHE_MAX = 512

_exe_cache: OrderedDict[int, str] = OrderedDict()       # pid -> exe 路径
_software_cache: OrderedDict[str, str] = OrderedDict()  # exe 路径 -> 软件显示名


def _lru_get(cache: OrderedDict, key):
    """读取 LRU 缓存；命中时把 key 移到队尾（最近使用）。"""
    if key in cache:
        cache.move_to_end(key)
        return cache[key]
    return None


def _lru_put(cache: OrderedDict, key, value, maxsize: int) -> None:
    """写入 LRU 缓存并淘汰最久未使用的条目。"""
    cache[key] = value
    cache.move_to_end(key)
    if len(cache) > maxsize:
        cache.popitem(last=False)


def _read_file_description(path: str) -> str:
    """读取可执行文件版本资源里的 FileDescription（回退 ProductName）。"""
    size = _version.GetFileVersionInfoSizeW(path, None)
    if not size:
        return ""
    buf = ctypes.create_string_buffer(size)
    if not _version.GetFileVersionInfoW(path, 0, size, ctypes.cast(buf, ctypes.c_void_p)):
        return ""

    trans_ptr = ctypes.c_void_p()
    trans_len = wintypes.UINT(0)
    ok = _version.VerQueryValueW(
        ctypes.cast(buf, ctypes.c_void_p), "\\VarFileInfo\\Translation",
        ctypes.byref(trans_ptr), ctypes.byref(trans_len),
    )
    if not ok or not trans_ptr.value or trans_len.value < 4:
        return ""
    words = ctypes.cast(trans_ptr, ctypes.POINTER(ctypes.c_uint16))
    lang, codepage = words[0], words[1]

    for key in ("FileDescription", "ProductName"):
        sub = f"\\StringFileInfo\\{lang:04X}{codepage:04X}\\{key}"
        val_ptr = ctypes.c_void_p()
        val_len = wintypes.UINT(0)
        if _version.VerQueryValueW(
            ctypes.cast(buf, ctypes.c_void_p), sub,
            ctypes.byref(val_ptr), ctypes.byref(val_len),
        ) and val_ptr.value:
            text = ctypes.wstring_at(val_ptr.value).strip()
            if text:
                return text
    return ""


def software_name_for(pid: int) -> str:
    """返回进程所属软件的显示名（FileDescription/ProductName）；取不到返回空串。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return ""

    path = _lru_get(_exe_cache, pid)
    if path is None:
        try:
            path = psutil.Process(pid).exe() or ""
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            path = ""
        _lru_put(_exe_cache, pid, path, _EXE_CACHE_MAX)
    if not path:
        return ""

    name = _lru_get(_software_cache, path)
    if name is None:
        try:
            name = _read_file_description(path)
        except Exception:
            logger.exception("读取文件版本信息失败: %s", path)
            name = ""
        _lru_put(_software_cache, path, name, _SOFTWARE_CACHE_MAX)
    return name


def service_or_software_for(pid: int) -> str:
    """返回进程归属：优先服务名，找不到服务时回退到软件显示名。"""
    service = service_names_for(pid)
    if service:
        return service
    return software_name_for(pid)
