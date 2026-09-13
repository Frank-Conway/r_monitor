"""IP Helper 表枚举与 TCP ESTATS（Windows）。

集中定义 GetExtendedTcpTable / GetExtendedUdpTable 与
SetPerTcpConnectionEStats / GetPerTcpConnectionEStats 的 ctypes 绑定、结构体
与常量，供 NetworkCollector 与 estats_diag.py 诊断脚本复用，避免两处重复维护。
"""
import ctypes
import socket
import struct
from ctypes import wintypes

AF_INET = 2
TCP_TABLE_OWNER_PID_ALL = 5
UDP_TABLE_OWNER_PID = 1
# TCP_ESTATS_TYPE 枚举（tcpestats.h）：SynOpts=0, Data=1, SndCong=2, ...
TcpConnectionEstatsData = 1

# TCP 连接状态（MIB_TCP_STATE 中本程序关注的几个）
TCP_STATE_FIN_WAIT1 = 4
TCP_STATE_ESTABLISHED = 5
TCP_STATE_CLOSE_WAIT = 8
TCP_STATE_TIME_WAIT = 11


class MIB_TCPROW(ctypes.Structure):
    _fields_ = [
        ("dwState", wintypes.DWORD),
        ("dwLocalAddr", wintypes.DWORD),
        ("dwLocalPort", wintypes.DWORD),
        ("dwRemoteAddr", wintypes.DWORD),
        ("dwRemotePort", wintypes.DWORD),
    ]


class MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("dwState", wintypes.DWORD),
        ("dwLocalAddr", wintypes.DWORD),
        ("dwLocalPort", wintypes.DWORD),
        ("dwRemoteAddr", wintypes.DWORD),
        ("dwRemotePort", wintypes.DWORD),
        ("dwOwningPid", wintypes.DWORD),
    ]


class MIB_UDPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("dwLocalAddr", wintypes.DWORD),
        ("dwLocalPort", wintypes.DWORD),
        ("dwOwningPid", wintypes.DWORD),
    ]


class TCP_ESTATS_DATA_ROD_v0(ctypes.Structure):
    # 结构必须与 SDK tcpestats.h 完全一致（96 字节），否则 GetPerTcpConnectionEStats
    # 会因缓冲区过小返回 ERROR_INSUFFICIENT_BUFFER，导致永远读不到字节。
    _fields_ = [
        ("DataBytesOut", ctypes.c_ulonglong),
        ("DataSegsOut", ctypes.c_ulonglong),
        ("DataBytesIn", ctypes.c_ulonglong),
        ("DataSegsIn", ctypes.c_ulonglong),
        ("SegsOut", ctypes.c_ulonglong),
        ("SegsIn", ctypes.c_ulonglong),
        ("SoftErrors", wintypes.ULONG),
        ("SoftErrorReason", wintypes.ULONG),
        ("SndUna", wintypes.ULONG),
        ("SndNxt", wintypes.ULONG),
        ("SndMax", wintypes.ULONG),
        ("ThruBytesAcked", ctypes.c_ulonglong),
        ("RcvNxt", wintypes.ULONG),
        ("ThruBytesReceived", ctypes.c_ulonglong),
    ]


class TCP_ESTATS_DATA_RW_v0(ctypes.Structure):
    _fields_ = [("EnableCollection", ctypes.c_ubyte)]


_iphlpapi = ctypes.WinDLL("iphlpapi")

_iphlpapi.GetExtendedTcpTable.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
    wintypes.BOOL, wintypes.ULONG, wintypes.ULONG, wintypes.ULONG,
]
_iphlpapi.GetExtendedTcpTable.restype = wintypes.ULONG

_iphlpapi.GetExtendedUdpTable.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
    wintypes.BOOL, wintypes.ULONG, wintypes.ULONG, wintypes.ULONG,
]
_iphlpapi.GetExtendedUdpTable.restype = wintypes.ULONG

_iphlpapi.SetPerTcpConnectionEStats.argtypes = [
    ctypes.POINTER(MIB_TCPROW), wintypes.ULONG,
    ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG, wintypes.ULONG,
]
_iphlpapi.SetPerTcpConnectionEStats.restype = wintypes.ULONG

_iphlpapi.GetPerTcpConnectionEStats.argtypes = [
    ctypes.POINTER(MIB_TCPROW), wintypes.ULONG,
    ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG,
    ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG,
    ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG,
]
_iphlpapi.GetPerTcpConnectionEStats.restype = wintypes.ULONG


def err_name(code: int) -> str:
    """把 Win32 错误码转成可读名称。"""
    return {
        0: "SUCCESS", 5: "ERROR_ACCESS_DENIED", 50: "ERROR_NOT_SUPPORTED",
        87: "ERROR_INVALID_PARAMETER", 122: "ERROR_INSUFFICIENT_BUFFER",
        1168: "ERROR_NOT_FOUND", 258: "ERROR_WAIT_TIMEOUT",
    }.get(code, f"0x{code:08X}")


def get_tcp_table():
    """返回 IPv4 TCP 表（含 PID），元素为 MIB_TCPROW_OWNER_PID。"""
    size = wintypes.DWORD(0)
    _iphlpapi.GetExtendedTcpTable(
        None, ctypes.byref(size), False, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0
    )
    if size.value == 0:
        return []
    buf = ctypes.create_string_buffer(size.value)
    ret = _iphlpapi.GetExtendedTcpTable(
        buf, ctypes.byref(size), False, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0
    )
    if ret != 0:
        return []
    n = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD)).contents.value
    rows = (MIB_TCPROW_OWNER_PID * n).from_buffer(
        buf, ctypes.sizeof(wintypes.DWORD)
    )
    return list(rows)


def get_udp_table():
    """返回 IPv4 UDP 表（含 PID），元素为 MIB_UDPROW_OWNER_PID。"""
    size = wintypes.DWORD(0)
    _iphlpapi.GetExtendedUdpTable(
        None, ctypes.byref(size), False, AF_INET, UDP_TABLE_OWNER_PID, 0
    )
    if size.value == 0:
        return []
    buf = ctypes.create_string_buffer(size.value)
    ret = _iphlpapi.GetExtendedUdpTable(
        buf, ctypes.byref(size), False, AF_INET, UDP_TABLE_OWNER_PID, 0
    )
    if ret != 0:
        return []
    n = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD)).contents.value
    rows = (MIB_UDPROW_OWNER_PID * n).from_buffer(
        buf, ctypes.sizeof(wintypes.DWORD)
    )
    return list(rows)


def to_tcp_row(owner_row) -> MIB_TCPROW:
    """把 MIB_TCPROW_OWNER_PID 裁剪成 ESTATS 接口所需的 MIB_TCPROW。"""
    return MIB_TCPROW(
        owner_row.dwState, owner_row.dwLocalAddr, owner_row.dwLocalPort,
        owner_row.dwRemoteAddr, owner_row.dwRemotePort,
    )


def enable_estats(row: MIB_TCPROW) -> int:
    """开启该连接的 ESTATS 采集，返回 Win32 错误码（0=成功）。"""
    rw = TCP_ESTATS_DATA_RW_v0(1)
    return int(_iphlpapi.SetPerTcpConnectionEStats(
        ctypes.byref(row), TcpConnectionEstatsData,
        ctypes.byref(rw), 0, ctypes.sizeof(TCP_ESTATS_DATA_RW_v0), 0,
    ))


def read_connection_bytes(row: MIB_TCPROW):
    """读取该连接的 ESTATS 字节，返回 (错误码, (bytes_out, bytes_in) 或 None)。"""
    rod = TCP_ESTATS_DATA_ROD_v0()
    ret = int(_iphlpapi.GetPerTcpConnectionEStats(
        ctypes.byref(row), TcpConnectionEstatsData,
        None, 0, 0, None, 0, 0,
        ctypes.byref(rod), 0, ctypes.sizeof(TCP_ESTATS_DATA_ROD_v0),
    ))
    if ret != 0:
        return ret, None
    return 0, (int(rod.DataBytesOut), int(rod.DataBytesIn))


def dw_to_ip(dw: int) -> str:
    """把 IP Helper 表中的 IPv4 地址（网络字节序 DWORD）转成点分字符串。"""
    try:
        # dw 由 ctypes 按主机字节序（x86/x64 为小端）读出，其值已是网络序字节的
        # 反转；再用 "<I" 小端打包即还原网络序字节，恰好是 inet_ntoa 所需。勿改成
        # "!I"：那会得到字节反转后的错误 IP。
        return socket.inet_ntoa(struct.pack("<I", dw))
    except Exception:
        return "0.0.0.0"


def port_ntohs(raw: int) -> int:
    return socket.ntohs(raw & 0xFFFF)
