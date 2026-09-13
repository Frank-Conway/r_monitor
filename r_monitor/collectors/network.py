"""网络采集器：全局速率 + 每进程上下行字节。

每进程字节按优先级选择数据源：
1. npcap 抓包（scapy）—— 覆盖 TCP + UDP，最准确；
2. TCP ESTATS（IP Helper）—— 仅 TCP，需管理员权限；
3. 连接数 —— 无字节数据时的降级。

全局速率始终由 psutil.net_io_counters() 提供（无需提权）。
"""
import logging
import time
from collections import OrderedDict

import psutil

from ..models import NetSample, ProcessNetRate
from ..winsvc import service_or_software_for
from .base import Collector
from .estats import (
    TCP_STATE_ESTABLISHED,
    dw_to_ip,
    enable_estats,
    get_tcp_table,
    get_udp_table,
    port_ntohs,
    read_connection_bytes,
    to_tcp_row,
)
from .sniffer import PacketSniffer

logger = logging.getLogger(__name__)

# pid -> 进程名 缓存上限（LRU 淘汰，避免长期运行无界增长）
_PID_NAME_CACHE_MAX = 4096

# 单连接瞬时速率上限（字节/秒）：超过视为 ESTATS 读到脏数据（例如已释放/复用的
# 连接 TCB），在按 pid 聚合前对每条 ESTABLISHED 连接分别校验并丢弃，避免在记录里
# 出现 GB/s 级的天文数字。任何真实网卡/连接都远达不到 1 TiB/s，此上限足够宽松。
_MAX_PLAUSIBLE_BPS = 1024 ** 4  # 1 TiB/s

# 展示在高流量记录里的单进程远端地址条数上限（超出用「等 N 个」表示）
_MAX_REMOTE_SHOWN = 8


class NetworkCollector(Collector):
    def __init__(self):
        io = psutil.net_io_counters()
        self._last_ts = time.time()
        self._last_sent = io.bytes_sent
        self._last_recv = io.bytes_recv

        self._prev_conn = {}        # conn_key -> {"out","in","ts"}（ESTATS）
        self._prev_sniff = {}       # pid -> {"up","down","ts"}（sniffer）
        self._pid_names = OrderedDict()  # pid -> name（LRU）
        self._enabled_keys = set()  # 已开启 ESTATS 的连接

        self._bytes_capable = None  # ESTATS 是否可用（None=未探测）
        self._sniffer = PacketSniffer()
        self._sniffer_started = False
        self._source = None         # 当前每进程字节数据源

    # ------------------------------------------------------------------ #
    # ESTATS（TCP，需管理员）
    # ------------------------------------------------------------------ #
    def _probe_bytes_capable(self, owner_row) -> bool:
        self._bytes_capable = enable_estats(to_tcp_row(owner_row)) == 0
        return self._bytes_capable

    def _probe_estats(self, rows) -> bool:
        for r in rows:
            if r.dwState == TCP_STATE_ESTABLISHED:
                return self._probe_bytes_capable(r)
        # 当前没有 ESTABLISHED 连接，保留未探测状态（_bytes_capable 仍为 None），
        # 下次采样再探测，避免管理员用户因启动瞬间无连接而误判为「不可用」。
        return False

    def _ensure_enabled(self, owner_row, key) -> bool:
        if key in self._enabled_keys:
            return True
        if enable_estats(to_tcp_row(owner_row)) == 0:
            self._enabled_keys.add(key)
            return True
        return False

    def _connection_bytes(self, owner_row) -> tuple[int, int] | None:
        code, stats = read_connection_bytes(to_tcp_row(owner_row))
        return stats if code == 0 else None

    # ------------------------------------------------------------------ #
    # 数据源选择
    # ------------------------------------------------------------------ #
    def _detect_source(self, tcp_rows) -> str:
        # 已确定「有字节」的数据源后保持不变
        if self._source in ("sniffer", "estats"):
            return self._source

        # 1) npcap 抓包（每次运行仅尝试一次）
        if not self._sniffer_started:
            self._sniffer_started = True
            if PacketSniffer.check_available():
                if self._sniffer.start():
                    self._source = "sniffer"
                    logger.info("每进程字节数据源：npcap 抓包")
                    return self._source

        # 2) TCP ESTATS（需管理员）
        if self._bytes_capable is None:
            self._probe_estats(tcp_rows)
        if self._bytes_capable:
            self._source = "estats"
            logger.info("每进程字节数据源：TCP ESTATS")
            return self._source

        # 3) 降级：仅连接数
        #    仅在确认「无字节能力」后固定；若尚未探测到 ESTABLISHED 连接则保持待定，
        #    下次采样重新探测，避免误判。
        if self._bytes_capable is False:
            if self._source != "connections":
                logger.info("每进程字节不可用，降级为连接数排序")
            self._source = "connections"
        return "connections"

    # ------------------------------------------------------------------ #
    # 采样
    # ------------------------------------------------------------------ #
    def sample(self, ts: float, top_n: int = 40) -> NetSample:
        io = psutil.net_io_counters()
        dt = max(1e-6, ts - self._last_ts)
        total_up = max(0.0, (io.bytes_sent - self._last_sent) / dt)
        total_down = max(0.0, (io.bytes_recv - self._last_recv) / dt)
        self._last_ts = ts
        self._last_sent = io.bytes_sent
        self._last_recv = io.bytes_recv

        tcp_rows = get_tcp_table()
        source = self._detect_source(tcp_rows)
        processes = self._per_process(ts, source, tcp_rows, top_n)

        return NetSample(
            ts=ts,
            total_up_bps=total_up,
            total_down_bps=total_down,
            total_up_bytes=io.bytes_sent,
            total_down_bytes=io.bytes_recv,
            bytes_available=source in ("sniffer", "estats"),
            source=source,
            processes=processes,
        )

    def _per_process(self, ts, source, tcp_rows, top_n):
        if source == "sniffer":
            return self._per_process_sniffer(ts, tcp_rows, top_n)
        if source == "estats":
            return self._per_process_estats(ts, tcp_rows, top_n)
        return self._per_process_connections(tcp_rows, top_n)

    # -- sniffer -------------------------------------------------------- #
    def _per_process_sniffer(self, ts, tcp_rows, top_n):
        udp_rows = get_udp_table()
        tcp_map, udp_map, conn_counts = self._build_sniffer_maps(tcp_rows, udp_rows)
        self._sniffer.set_pid_maps(tcp_map, udp_map)

        snapshot = self._sniffer.snapshot()
        prev = self._prev_sniff
        agg: dict[int, list[float]] = {}
        for pid, (up, down) in snapshot.items():
            p = prev.get(pid)
            if p is not None and ts > p["ts"]:
                d = ts - p["ts"]
                up_rate = max(0.0, (up - p["up"]) / d)
                down_rate = max(0.0, (down - p["down"]) / d)
            else:
                up_rate = down_rate = 0.0
            agg[pid] = [up_rate, down_rate, conn_counts.get(pid, 0)]

        self._prev_sniff = {
            pid: {"up": up, "down": down, "ts": ts}
            for pid, (up, down) in snapshot.items()
        }
        return self._rank(agg, self._remote_map(tcp_rows), by_bytes=True, top_n=top_n)

    def _build_sniffer_maps(self, tcp_rows, udp_rows):
        tcp_map = {}
        udp_map = {}
        conn_counts: dict[int, int] = {}
        for r in tcp_rows:
            pid = int(r.dwOwningPid)
            lip = dw_to_ip(r.dwLocalAddr)
            rip = dw_to_ip(r.dwRemoteAddr)
            lport = port_ntohs(r.dwLocalPort)
            rport = port_ntohs(r.dwRemotePort)
            tcp_map[(lip, lport, rip, rport)] = pid
            conn_counts[pid] = conn_counts.get(pid, 0) + 1
        for r in udp_rows:
            pid = int(r.dwOwningPid)
            ip = dw_to_ip(r.dwLocalAddr)
            port = port_ntohs(r.dwLocalPort)
            udp_map[(ip, port)] = pid
            conn_counts[pid] = conn_counts.get(pid, 0) + 1
        return tcp_map, udp_map, conn_counts

    # -- estats --------------------------------------------------------- #
    def _per_process_estats(self, ts, tcp_rows, top_n):
        conns = []  # [(pid, key, out, in), ...] 仅保留本次成功读到的连接
        for r in tcp_rows:
            # 仅统计 ESTABLISHED 连接的字节：TIME_WAIT / CLOSE_WAIT / FIN_WAIT1
            # 等关闭中的连接，其 TCB 可能已被释放或复用，读到的累计字节不可靠，
            # 会产生天文数字的瞬时速率。连接的流量在 ESTABLISHED 阶段已被统计，
            # 这里跳过不会漏计。
            if r.dwState != TCP_STATE_ESTABLISHED:
                continue
            pid = int(r.dwOwningPid)
            key = (r.dwLocalAddr, r.dwLocalPort, r.dwRemoteAddr, r.dwRemotePort)
            if not self._ensure_enabled(r, key):
                continue
            stats = self._connection_bytes(r)
            if stats is None:
                # 读取失败：跳过而不是把失败当成 0 基线。否则下一次成功读取会
                # 把该连接自建立以来的累计字节误当成一个采样周期内的增量，
                # 产生 GB/s 级的假速率。
                continue
            conns.append((pid, key, stats[0], stats[1]))

        # 仅保留本采样仍 ESTABLISHED 且成功读取的连接为「已启用」。四元组被新
        # 连接复用时，旧 key 已不在此集合中，会重新开启 ESTATS，避免读到未启用
        # 连接的脏数据。
        present = {key for _pid, key, _out, _inn in conns}
        self._enabled_keys.intersection_update(present)

        prev = self._prev_conn
        agg: dict[int, list[float]] = {}
        for pid, key, out, inn in conns:
            p = prev.get(key)
            if p is not None and ts > p["ts"]:
                d = ts - p["ts"]
                up = max(0.0, (out - p["out"]) / d)
                down = max(0.0, (inn - p["in"]) / d)
            else:
                up = down = 0.0
            if up > _MAX_PLAUSIBLE_BPS or down > _MAX_PLAUSIBLE_BPS:
                continue  # 丢弃物理上不可能的瞬时速率（脏数据）
            entry = agg.setdefault(pid, [0.0, 0.0, 0])
            entry[0] += up
            entry[1] += down
            entry[2] += 1

        self._prev_conn = {
            key: {"out": out, "in": inn, "ts": ts}
            for _pid, key, out, inn in conns
        }
        return self._rank(agg, self._remote_map(tcp_rows), by_bytes=True, top_n=top_n)

    # -- 降级：仅连接数 -------------------------------------------------- #
    def _per_process_connections(self, tcp_rows, top_n):
        agg: dict[int, list[float]] = {}
        for r in tcp_rows:
            entry = agg.setdefault(int(r.dwOwningPid), [0.0, 0.0, 0])
            entry[2] += 1
        return self._rank(agg, self._remote_map(tcp_rows), by_bytes=False, top_n=top_n)

    # ------------------------------------------------------------------ #
    # 远端地址归集
    # ------------------------------------------------------------------ #
    def _build_tcp_remote_map(self, tcp_rows) -> dict[int, set[str]]:
        """从 TCP 连接表构建 pid -> 远端地址集合（"ip:port"）。"""
        remote: dict[int, set[str]] = {}
        for r in tcp_rows:
            pid = int(r.dwOwningPid)
            if pid == 0:
                continue
            ip = dw_to_ip(r.dwRemoteAddr)
            if ip == "0.0.0.0":
                continue
            remote.setdefault(pid, set()).add(f"{ip}:{port_ntohs(r.dwRemotePort)}")
        return remote

    def _remote_map(self, tcp_rows) -> dict[int, set[str]]:
        """pid -> 远端地址集合；sniffer 源时额外并入抓包观测到的 UDP/TCP 端点。"""
        remote_map = self._build_tcp_remote_map(tcp_rows)
        if self._source == "sniffer":
            for pid, remotes in self._sniffer.snapshot_remote().items():
                remote_map.setdefault(pid, set()).update(remotes)
        return remote_map

    def _fmt_remote(self, remotes: set[str]) -> str:
        if not remotes:
            return ""
        items = sorted(remotes)
        if len(items) > _MAX_REMOTE_SHOWN:
            return ", ".join(items[:_MAX_REMOTE_SHOWN]) + f" 等{len(items)}个"
        return ", ".join(items)

    # ------------------------------------------------------------------ #
    def _rank(self, agg: dict[int, list[float]], remote_map: dict[int, set[str]],
              by_bytes: bool, top_n: int) -> list[ProcessNetRate]:
        agg = {pid: v for pid, v in agg.items() if pid != 0}  # 过滤 System Idle Process

        def key_fn(kv):
            up, down, cnt = kv[1]
            return up + down if by_bytes else cnt

        ranked = sorted(agg.items(), key=key_fn, reverse=True)[:top_n]
        result = []
        for pid, (up, down, cnt) in ranked:
            result.append(ProcessNetRate(
                pid=pid,
                name=self._resolve_name(pid),
                up_bps=up,
                down_bps=down,
                conn_count=int(cnt),
                service=service_or_software_for(pid),
                remote_addrs=self._fmt_remote(remote_map.get(pid, set())),
            ))
        return result

    def _resolve_name(self, pid: int) -> str:
        if pid in self._pid_names:
            self._pid_names.move_to_end(pid)
            return self._pid_names[pid]
        try:
            name = psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            name = f"PID {pid}"
        self._pid_names[pid] = name
        self._pid_names.move_to_end(pid)
        if len(self._pid_names) > _PID_NAME_CACHE_MAX:
            self._pid_names.popitem(last=False)
        return name

    def close(self) -> None:
        """退出前释放资源（停止抓包线程）。"""
        self._sniffer.stop()

    @property
    def bytes_available(self) -> bool:
        return self._source in ("sniffer", "estats")

    @property
    def source(self) -> str:
        return self._source or "connections"
