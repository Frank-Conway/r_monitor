"""GPU 采集器（跨厂商：NVIDIA / AMD / Intel）。

实现思路（全部使用 Windows 系统 DLL，无需安装任何厂商 SDK）：
1. DXGI（dxgi.dll）枚举适配器，拿到显卡名称 + LUID + 显存总量；
2. PDH（pdh.dll）性能计数器：
   - ``\\GPU Engine(*)\\Utilization Percentage``    各引擎利用率（按 LUID 归并到适配器）
   - ``\\GPU Adapter Memory(*)\\Dedicated Usage``   专用显存占用
   - ``\\GPU Adapter Memory(*)\\Shared Usage``      共享显存占用

LUID 的两个 32 位字段在计数器实例名中的先后顺序在不同系统上可能不同，
因此匹配时对两种顺序都做尝试，保证稳健。
"""
import ctypes
import logging
import re
import time
from ctypes import wintypes

from ..models import GpuAdapter, GpuSample
from .base import Collector

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# DXGI 适配器枚举
# --------------------------------------------------------------------------- #

class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _LUID(ctypes.Structure):
    _fields_ = [
        ("LowPart", ctypes.c_uint32),
        ("HighPart", ctypes.c_uint32),
    ]


class _DXGI_ADAPTER_DESC(ctypes.Structure):
    # DXGI_ADAPTER_DESC（GetDesc 返回值）已包含 AdapterLuid，
    # 因此无需使用 IDXGIAdapter1::GetDesc1（其虚表在部分系统上存在偏移问题）。
    _fields_ = [
        ("Description", ctypes.c_wchar * 128),
        ("VendorId", wintypes.UINT),
        ("DeviceId", wintypes.UINT),
        ("SubSysId", wintypes.UINT),
        ("Revision", wintypes.UINT),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", _LUID),
    ]


_IID_IDXGIFactory1 = _GUID(
    0x770AAE78, 0xF26F, 0x4DBA,
    (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87),
)

_dxgi = ctypes.WinDLL("dxgi.dll")

# DXGI 枚举时会一并列出 Windows 的软件回退适配器：
#   - "Microsoft Basic Render Driver"：WARP 软件光栅化器，非物理 GPU；
#   - "Microsoft Basic Display Adapter"：未安装显卡驱动时的 BASIC 显示回退。
# 这些不是真实硬件，采集时直接跳过。
_SOFTWARE_GPU_NAMES = (
    "Microsoft Basic Render Driver",
    "Microsoft Basic Display Adapter",
)


def _com_method(this, index, restype, *argtypes):
    """取得 COM 接口虚表里第 index 个方法（带好签名）。"""
    vtbl = ctypes.cast(this, ctypes.POINTER(ctypes.c_void_p))[0]
    fn_addr = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[index]
    # fn_addr 可能是 int 或 c_void_p，统一转成整数地址
    addr = fn_addr.value if hasattr(fn_addr, "value") else fn_addr
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(int(addr) if addr is not None else 0)


def _enum_adapters_dxgi():
    """返回 [{index, name, luid_lo, luid_hi, luid, vram_total, shared_total}, ...]。"""
    _dxgi.CreateDXGIFactory1.argtypes = [
        ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)
    ]
    _dxgi.CreateDXGIFactory1.restype = ctypes.c_long

    factory = ctypes.c_void_p()
    hr = _dxgi.CreateDXGIFactory1(ctypes.byref(_IID_IDXGIFactory1), ctypes.byref(factory))
    if hr != 0 or not factory.value:
        raise OSError(f"CreateDXGIFactory1 失败: 0x{hr & 0xFFFFFFFF:08X}")

    adapters = []
    try:
        # 使用基础接口 IDXGIFactory::EnumAdapters（vtable index 7）
        # 与 IDXGIAdapter::GetDesc（vtable index 8），两者已实证可用。
        enum_adapters = _com_method(
            factory, 7, ctypes.c_long, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)
        )
        index = 0
        while True:
            adapter = ctypes.c_void_p()
            hr = enum_adapters(factory, index, ctypes.byref(adapter))
            if hr != 0:  # DXGI_ERROR_NOT_FOUND 等，表示枚举结束
                break
            if adapter.value:
                desc = _DXGI_ADAPTER_DESC()
                get_desc = _com_method(
                    adapter, 8, ctypes.c_long, ctypes.POINTER(_DXGI_ADAPTER_DESC)
                )
                if get_desc(adapter, ctypes.byref(desc)) == 0:
                    name = desc.Description
                    if not any(s in name for s in _SOFTWARE_GPU_NAMES):
                        lo = int(desc.AdapterLuid.LowPart)
                        hi = int(desc.AdapterLuid.HighPart)
                        adapters.append({
                            "index": index,
                            "name": name,
                            "luid_lo": lo,
                            "luid_hi": hi,
                            "luid": (hi << 32) | lo,
                            "vram_total": int(desc.DedicatedVideoMemory),
                            "shared_total": int(desc.SharedSystemMemory),
                        })
                release = _com_method(adapter, 2, ctypes.c_ulong)
                release(adapter)
            index += 1
    finally:
        release = _com_method(factory, 2, ctypes.c_ulong)
        release(factory)
    return adapters


# --------------------------------------------------------------------------- #
# PDH 计数器
# --------------------------------------------------------------------------- #

_pdh = ctypes.WinDLL("pdh.dll")
_pdh.PdhRemoveCounter.argtypes = [ctypes.c_void_p]
_pdh.PdhRemoveCounter.restype = ctypes.c_long

PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_LARGE = 0x00000400
_PDH_MORE_DATA = 0x800007D2
_PDH_CSTATUS_VALID_DATA = 0x00000000


class _PDH_COUNTER_VALUE_UNION(ctypes.Union):
    _fields_ = [
        ("longValue", ctypes.c_long),
        ("doubleValue", ctypes.c_double),
        ("largeValue", ctypes.c_longlong),
        ("AnsiStringValue", ctypes.c_char_p),
        ("WideStringValue", ctypes.c_wchar_p),
    ]


class _PDH_FMT_COUNTERVALUE(ctypes.Structure):
    _fields_ = [
        ("CStatus", wintypes.DWORD),
        ("value", _PDH_COUNTER_VALUE_UNION),
    ]


_LUID_RE = re.compile(r"luid_0x([0-9a-fA-F]{8})_0x([0-9a-fA-F]{8})")
_ENG_RE = re.compile(r"engtype_([A-Za-z0-9_]+)")


def _expand_wildcard(wildcard_path: str):
    """展开形如 ``\\Object(*)\\Counter`` 的通配路径，返回计数器路径列表。"""
    size = wintypes.DWORD(0)
    _pdh.PdhExpandWildCardPathW(
        None, wildcard_path, None, ctypes.byref(size)
    )
    if size.value == 0:
        return []
    buf = ctypes.create_unicode_buffer(size.value)
    ret = _pdh.PdhExpandWildCardPathW(
        None, wildcard_path, buf, ctypes.byref(size)
    )
    if ret != 0:
        return []
    # ctypes 切片类型在 typeshed 里不精确，这里显式还原为 str
    text = "".join(buf[: size.value])
    return [p for p in text.split("\x00") if p]


class GpuCollector(Collector):
    # 引擎计数器实例名会随进程启停动态增删（实例名含 pid），因此不能只枚举一次，
    # 需要每次采样前重新枚举并同步计数器句柄，否则监控启动后才打开的 GPU 进程
    # （游戏/浏览器硬件加速等）负载始终读不到，表现为“负载一直是 0”。
    # 同步间隔（秒）：新进程最多延迟该时间被纳入统计。
    _SYNC_INTERVAL_S = 2.0

    def __init__(self):
        self._adapters = []
        self._query = ctypes.c_void_p()
        self._engine_counters = {}   # path -> {"idx":, "eng":, "h":}
        self._mem_counters = {}      # path -> {"idx":, "kind":, "h":}
        self._ok = False
        self._last_sync = 0.0
        self._init()

    # -- 初始化 ------------------------------------------------------------ #
    def _init(self):
        try:
            self._adapters = _enum_adapters_dxgi()
        except Exception:
            logger.exception("枚举 DXGI 适配器失败")
            self._adapters = []

        _pdh.PdhOpenQueryW(
            None, 0, ctypes.byref(self._query)
        )
        if not self._query.value:
            return

        try:
            self._sync_engine_counters()
            self._sync_memory_counters()
            # 第一次 collect 建立基线（利用率是区间型计数器）
            _pdh.PdhCollectQueryData(self._query)
            self._ok = True
        except Exception:
            logger.exception("初始化 PDH GPU 计数器失败")
            self._ok = False

    def _match_adapter(self, a: int, b: int):
        for i, ad in enumerate(self._adapters):
            lo, hi = ad["luid_lo"], ad["luid_hi"]
            if (a == lo and b == hi) or (a == hi and b == lo):
                return i
        return None

    def _add_counter(self, path: str):
        h = ctypes.c_void_p()
        ret = _pdh.PdhAddEnglishCounterW(
            self._query, path, 0, ctypes.byref(h)
        )
        return h if ret == 0 else None

    @staticmethod
    def _parse_engine_path(p: str):
        """解析引擎计数器路径 -> (luid_a, luid_b, eng) 或 None。

        a/b 为路径中先后出现的两个 LUID 字段，顺序不固定；lo/hi 的判定交由
        ``_match_adapter`` 双向匹配完成。
        """
        m = _LUID_RE.search(p)
        if not m:
            return None
        a = int(m.group(1), 16)
        b = int(m.group(2), 16)
        eng = "3D"
        em = _ENG_RE.search(p)
        if em:
            eng = em.group(1)
        return (a, b, eng)

    def _sync_engine_counters(self):
        """重新枚举引擎计数器，新增/移除实例句柄，与系统当前进程对齐。"""
        paths = _expand_wildcard(r"\GPU Engine(*)\Utilization Percentage")
        wanted = {p: None for p in paths}
        for p in paths:
            parsed = self._parse_engine_path(p)
            if parsed is None:
                continue
            a, b, eng = parsed
            idx = self._match_adapter(a, b)
            if idx is None:
                continue
            wanted[p] = (idx, eng)

        # 移除已消失的实例
        for p in list(self._engine_counters):
            if p not in wanted:
                info = self._engine_counters.pop(p)
                _pdh.PdhRemoveCounter(info["h"])

        # 添加新出现的实例
        for p, meta in wanted.items():
            if meta is None or p in self._engine_counters:
                continue
            idx, eng = meta
            h = self._add_counter(p)
            if h:
                self._engine_counters[p] = {"idx": idx, "eng": eng, "h": h}

    def _sync_memory_counters(self):
        """同步显存计数器（实例按 LUID 归并，同样可能随适配器变化）。"""
        wanted: dict = {}
        for kind, counter in (
            ("dedicated", r"\GPU Adapter Memory(*)\Dedicated Usage"),
            ("shared", r"\GPU Adapter Memory(*)\Shared Usage"),
        ):
            for p in _expand_wildcard(counter):
                m = _LUID_RE.search(p)
                if not m:
                    continue
                a = int(m.group(1), 16)
                b = int(m.group(2), 16)
                idx = self._match_adapter(a, b)
                if idx is None:
                    continue
                wanted[p] = (idx, kind)

        for p in list(self._mem_counters):
            if p not in wanted:
                info = self._mem_counters.pop(p)
                _pdh.PdhRemoveCounter(info["h"])

        for p, (idx, kind) in wanted.items():
            if p in self._mem_counters:
                continue
            h = self._add_counter(p)
            if h:
                self._mem_counters[p] = {"idx": idx, "kind": kind, "h": h}

    def _sync_if_due(self):
        """按节流间隔同步引擎/显存计数器实例。"""
        now = time.monotonic()
        if self._last_sync + self._SYNC_INTERVAL_S > now:
            return
        self._sync_engine_counters()
        self._sync_memory_counters()
        self._last_sync = now

    # -- 采样 -------------------------------------------------------------- #
    def _read_double(self, h):
        val = _PDH_FMT_COUNTERVALUE()
        dtype = wintypes.DWORD(0)
        ret = _pdh.PdhGetFormattedCounterValue(
            h, PDH_FMT_DOUBLE, ctypes.byref(dtype), ctypes.byref(val)
        )
        if ret == 0 and val.CStatus == _PDH_CSTATUS_VALID_DATA:
            return float(val.value.doubleValue)
        return 0.0

    def _read_large(self, h):
        val = _PDH_FMT_COUNTERVALUE()
        dtype = wintypes.DWORD(0)
        ret = _pdh.PdhGetFormattedCounterValue(
            h, PDH_FMT_LARGE, ctypes.byref(dtype), ctypes.byref(val)
        )
        if ret == 0 and val.CStatus == _PDH_CSTATUS_VALID_DATA:
            return int(val.value.largeValue)
        return 0

    def sample(self, ts: float) -> GpuSample:
        if not self._ok:
            return GpuSample(ts=ts, adapters=[])

        # 先同步实例集，把监控启动后才出现的 GPU 进程纳入统计
        self._sync_if_due()
        _pdh.PdhCollectQueryData(self._query)

        # 初始化每适配器结果
        result = {}
        for ad in self._adapters:
            result[ad["index"]] = GpuAdapter(
                index=ad["index"],
                name=ad["name"],
                vram_total=ad["vram_total"],
            )

        # 利用率：同一引擎名有多个进程实例（实例名含 pid），
        # 同名引擎的各实例占用应累加，再取各引擎最大值作为该适配器“负载”。
        for c in self._engine_counters.values():
            idx = c["idx"]
            val = self._read_double(c["h"])
            ad = result.get(idx)
            if ad is None:
                continue
            eng = c["eng"]
            ad.engines[eng] = round(ad.engines.get(eng, 0.0) + val, 1)
        for ad in result.values():
            if ad.engines:
                ad.utilization = max(ad.engines.values())

        # 显存
        for c in self._mem_counters.values():
            ad = result.get(c["idx"])
            if ad is None:
                continue
            v = self._read_large(c["h"])
            if c["kind"] == "dedicated":
                ad.vram_used = v
            else:
                ad.shared_used = v

        # 只返回在 PDH 中有对应计数器的适配器，过滤掉无数据的“幽灵/重复”适配器
        mapped = {c["idx"] for c in self._engine_counters.values()}
        mapped |= {c["idx"] for c in self._mem_counters.values()}
        adapters = [result[i] for i in result if i in mapped] or list(result.values())
        return GpuSample(ts=ts, adapters=adapters)

    @property
    def adapters(self) -> list:
        """枚举到的适配器元数据（只读副本）。"""
        return list(self._adapters)

    @property
    def engine_counter_count(self) -> int:
        return len(self._engine_counters)

    @property
    def memory_counter_count(self) -> int:
        return len(self._mem_counters)

    def close(self):
        if self._query.value:
            _pdh.PdhCloseQuery(self._query)
            self._query = ctypes.c_void_p()
