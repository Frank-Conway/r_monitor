"""CPU / 内存采集器（基于 psutil）。"""
import psutil

from ..models import CpuProcess, CpuSample
from ..winsvc import service_or_software_for
from .base import Collector


class CpuCollector(Collector):
    def __init__(self):
        # psutil 的 cpu_percent(interval=None) 依赖“距上次调用”的差值，
        # 首次调用恒为 0，这里先触发一次以建立基线。
        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(interval=None, percpu=True)
        self._proc_cache = {}  # pid -> psutil.Process（保留对象以正确计算每进程 CPU）

    def sample(self, ts: float) -> CpuSample:
        overall = psutil.cpu_percent(interval=None)
        per_core = psutil.cpu_percent(interval=None, percpu=True)

        freq = psutil.cpu_freq()
        freq_mhz = freq.current if freq and freq.current else 0.0

        vm = psutil.virtual_memory()

        return CpuSample(
            ts=ts,
            overall=overall,
            per_core=list(per_core),
            freq_mhz=float(freq_mhz),
            mem_percent=vm.percent,
            mem_used_gb=vm.used / (1024 ** 3),
            mem_total_gb=vm.total / (1024 ** 3),
            top_processes=self._top_processes(5),
        )

    def _top_processes(self, n: int) -> list:
        """返回 CPU 占用前 n 的进程。

        一次 process_iter 同时完成「同步存活进程」与「取进程名」，避免重复枚举；
        新进程先做一次 cpu_percent 预热（首次调用恒为 0），本轮跳过、下一轮即准确。
        """
        # 同步当前存活进程，并顺带取出名称
        alive = {}
        infos = []
        for proc in psutil.process_iter(["pid", "name"]):
            pid = proc.info["pid"]
            alive[pid] = True
            infos.append((pid, proc.info["name"]))

        # 清理已退出进程
        for pid in list(self._proc_cache):
            if pid not in alive:
                self._proc_cache.pop(pid, None)

        rows = []
        for pid, raw_name in infos:
            if pid == 0:  # System Idle Process：无意义的空闲占位
                continue
            name = raw_name or f"PID {pid}"
            if pid not in self._proc_cache:
                try:
                    p = psutil.Process(pid)
                    p.cpu_percent(interval=None)  # 预热基线，避免首轮返回 0
                    self._proc_cache[pid] = p
                    continue  # 本轮无有效数据，下一轮再统计
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            p = self._proc_cache[pid]
            try:
                cpu = p.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                self._proc_cache.pop(pid, None)
                continue
            rows.append((pid, name, cpu))

        rows.sort(key=lambda r: r[2], reverse=True)
        # 服务/软件名解析可能触发 psutil.Process.exe() 与磁盘版本资源读取，
        # 属于每进程一次性的较重 IO；先选出 TOP N 再解析，避免每个采样周期
        # 都替全部进程做无用解析（服务名走 15s 缓存，软件名走 LRU 缓存）。
        return [
            CpuProcess(pid=pid, name=name, cpu=cpu,
                       service=service_or_software_for(pid))
            for pid, name, cpu in rows[:n]
        ]
