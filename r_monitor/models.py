"""采样结果的数据模型（dataclass）。"""
from dataclasses import dataclass, field


@dataclass
class CpuProcess:
    pid: int
    name: str
    cpu: float = 0.0            # 该进程占用 CPU 比例 %
    service: str = ""           # 进程所属服务或软件显示名


@dataclass
class CpuSample:
    ts: float
    overall: float = 0.0                    # 整体 CPU 使用率 %
    per_core: list[float] = field(default_factory=list)  # 每核使用率 %
    freq_mhz: float = 0.0                   # 当前主频 MHz
    mem_percent: float = 0.0                # 内存使用率 %
    mem_used_gb: float = 0.0
    mem_total_gb: float = 0.0
    top_processes: list[CpuProcess] = field(default_factory=list)


@dataclass
class GpuAdapter:
    index: int
    name: str
    utilization: float = 0.0    # 负载 %
    vram_used: int = 0          # 专用显存占用（字节）
    vram_total: int = 0         # 专用显存总量（字节）
    shared_used: int = 0        # 共享显存占用（字节）
    engines: dict[str, float] = field(default_factory=dict)  # 引擎名 -> 利用率 %


@dataclass
class GpuSample:
    ts: float
    adapters: list[GpuAdapter] = field(default_factory=list)


@dataclass
class ProcessNetRate:
    pid: int
    name: str
    up_bps: float = 0.0      # 上行字节/秒
    down_bps: float = 0.0    # 下行字节/秒
    conn_count: int = 0      # 活跃 TCP 连接数
    service: str = ""        # 进程所属服务或软件（服务优先，找不到服务时回退到软件显示名）
    remote_addrs: str = ""   # 远端地址（去重，逗号分隔，如 "1.2.3.4:443, 5.6.7.8:80"）


@dataclass
class NetSample:
    ts: float
    total_up_bps: float = 0.0        # 全局上行速率
    total_down_bps: float = 0.0      # 全局下行速率
    total_up_bytes: int = 0          # 累计上行字节
    total_down_bytes: int = 0        # 累计下行字节
    bytes_available: bool = False    # 每进程字节是否可用
    source: str = "connections"      # sniffer | estats | connections
    processes: list[ProcessNetRate] = field(default_factory=list)


@dataclass
class SampleBundle:
    """一次完整采样周期的快照：由采样线程通过信号推送给 GUI。"""
    ts: float
    cpu: CpuSample
    gpu: GpuSample
    net: NetSample
