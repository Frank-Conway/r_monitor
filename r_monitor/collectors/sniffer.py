"""npcap 抓包采集器：通过 scapy 抓取 IP 包并按进程归因字节。

依赖：
- npcap（https://npcap.com/，需单独安装）
- scapy（pip install scapy）

说明：
- 抓包覆盖 TCP + UDP，可精确统计每进程上下行字节；
- 通常需要管理员权限抓包（或 npcap 配置为允许非管理员抓包）；
- 当前实现按 IPv4 归因（IPv6 后续可扩展，会直接跳过）。
"""
import logging
import os
import threading
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

# 无新数据包的 PID 条目保留时长：超过后从累计表中清理，避免长期运行无界增长
_PID_BYTES_TTL_S = 300.0

# 单进程远端地址集合上限：限制内存占用（浏览器 5 分钟内可能连接大量 CDN）
_MAX_REMOTE_PER_PID = 64


def _npcap_present() -> bool:
    """检测是否安装了 npcap（检查其 DLL）。"""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return any(
        os.path.exists(os.path.join(root, "System32", "Npcap", name))
        for name in ("wpcap.dll", "Packet.dll")
    )


class PacketSniffer:
    """后台线程用 scapy 抓包，累积每进程 [上行, 下行] 字节。"""

    def __init__(self):
        self._running = False
        self._sniffer = None  # scapy AsyncSniffer 实例（自带后台线程）
        self._lock = threading.Lock()
        self._tcp_map = {}   # (lip, lport, rip, rport) -> pid
        self._udp_map = {}   # (ip, port) -> pid
        # pid -> [up, down] 与 pid -> 最近一次归因时间（用于过期清理）
        self._pid_bytes: dict[int, list[int]] = defaultdict(lambda: [0, 0])
        self._pid_last_seen: dict[int, float] = {}
        # pid -> 远端地址集合（"ip:port"），与字节同生命周期清理
        self._pid_remote: dict[int, set[str]] = {}
        self.available = False

    # ------------------------------------------------------------------ #
    @staticmethod
    def check_available(timeout: float = 0.6) -> bool:
        """检测 scapy + npcap 是否可用（权限不足/未装 npcap 会返回 False）。"""
        if not _npcap_present():
            return False
        try:
            # 只导入抓包所需子模块（而非 scapy.all），便于 PyInstaller 精简打包体积。
            # Ether 仅为注册以太网层（conf.L2listen）这一副作用而导入。
            from scapy.config import conf
            from scapy.layers.l2 import Ether  # noqa: F401
            from scapy.sendrecv import sniff
        except ImportError:
            return False
        try:
            conf.verb = 0
            sniff(timeout=timeout, store=False)
            return True
        except Exception as exc:
            logger.debug("scapy 抓包探测失败: %s", exc)
            return False

    def start(self) -> bool:
        if self._running:
            return True
        try:
            # 只导入抓包/解析所需子模块（而非 scapy.all），便于 PyInstaller 精简打包体积。
            # IP/TCP/UDP/Ether 仅为“注册解析层”的副作用而导入，实际经 pkt.getlayer(...) 使用。
            from scapy.config import conf
            from scapy.layers.inet import IP, TCP, UDP  # noqa: F401
            from scapy.layers.l2 import Ether  # noqa: F401
            from scapy.sendrecv import AsyncSniffer
        except ImportError:
            self.available = False
            return False
        try:
            conf.verb = 0
            # 使用 AsyncSniffer：自带后台线程，stop() 会关闭 socket 使其可靠退出
            self._sniffer = AsyncSniffer(prn=self._on_packet, store=False)
            self._sniffer.start()
        except Exception:
            logger.exception("启动 scapy 抓包失败")
            self.available = False
            return False
        self._running = True
        self.available = True
        return True

    def stop(self) -> None:
        """停止抓包线程并释放资源（可安全重复调用）。"""
        self._running = False
        if self._sniffer is not None:
            try:
                self._sniffer.stop()
            except Exception:
                logger.exception("停止抓包线程失败")
            self._sniffer = None

    # ------------------------------------------------------------------ #
    def set_pid_maps(self, tcp_map: dict, udp_map: dict) -> None:
        with self._lock:
            self._tcp_map = tcp_map
            self._udp_map = udp_map

    def snapshot(self) -> dict:
        """返回当前每进程累计字节快照 {pid: [up, down]}（并清理过期条目）。"""
        with self._lock:
            cutoff = time.monotonic() - _PID_BYTES_TTL_S
            stale = [p for p, t in self._pid_last_seen.items() if t < cutoff]
            for pid in stale:
                self._pid_bytes.pop(pid, None)
                self._pid_last_seen.pop(pid, None)
                self._pid_remote.pop(pid, None)
            return {pid: list(v) for pid, v in self._pid_bytes.items()}

    def snapshot_remote(self) -> dict:
        """返回当前每进程远端地址快照 {pid: set("ip:port")}（并清理过期条目）。"""
        with self._lock:
            cutoff = time.monotonic() - _PID_BYTES_TTL_S
            stale = [p for p, t in self._pid_last_seen.items() if t < cutoff]
            for pid in stale:
                self._pid_remote.pop(pid, None)
            return {pid: set(v) for pid, v in self._pid_remote.items()}

    # ------------------------------------------------------------------ #
    def _on_packet(self, pkt) -> None:
        ip = pkt.getlayer("IP")
        if ip is None:
            return  # 仅 IPv4（IPv6 跳过）
        src, dst = ip.src, ip.dst
        length = int(getattr(ip, "len", 0) or 0)

        tcp = pkt.getlayer("TCP")
        if tcp is not None:
            self._attribute(src, tcp.sport, dst, tcp.dport, length, is_tcp=True)
            return
        udp = pkt.getlayer("UDP")
        if udp is not None:
            self._attribute(src, udp.sport, dst, udp.dport, length, is_tcp=False)

    def _attribute(self, src, sport, dst, dport, length, is_tcp: bool) -> None:
        with self._lock:
            now = time.monotonic()
            if is_tcp:
                m = self._tcp_map
                pid = m.get((src, sport, dst, dport))
                if pid is not None:
                    self._record(pid, 0, f"{dst}:{dport}", length, now)
                    return
                pid = m.get((dst, dport, src, sport))
                if pid is not None:
                    self._record(pid, 1, f"{src}:{sport}", length, now)
            else:
                m = self._udp_map
                pid = m.get((src, sport))
                if pid is not None:
                    self._record(pid, 0, f"{dst}:{dport}", length, now)
                    return
                pid = m.get((dst, dport))
                if pid is not None:
                    self._record(pid, 1, f"{src}:{sport}", length, now)

    def _record(self, pid: int, idx: int, remote: str, length: int, now: float) -> None:
        """把一次归因写入累计字节与远端地址（idx: 0=上行 1=下行）。"""
        self._pid_bytes[pid][idx] += length
        self._pid_last_seen[pid] = now
        remotes = self._pid_remote.setdefault(pid, set())
        if len(remotes) < _MAX_REMOTE_PER_PID:
            remotes.add(remote)
