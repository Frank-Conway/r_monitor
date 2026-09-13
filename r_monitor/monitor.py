"""采样编排：后台线程周期采样，通过 Qt 信号推送结果。"""
import logging
import threading
import time
from collections import deque

from PySide6.QtCore import QThread, Signal

from .collectors import CpuCollector, GpuCollector, NetworkCollector
from .config import SettingsStore
from .models import SampleBundle
from .storage import Storage
from .winsvc import service_or_software_for

logger = logging.getLogger(__name__)

# 同一进程的高流量事件冷却时间：避免持续超阈值时每个采样周期都重复写库
_EVENT_COOLDOWN_S = 60.0


class MonitorThread(QThread):
    """在独立线程里周期采样 CPU/GPU/网络，并记录高流量事件。"""

    sample_ready = Signal(object)   # 携带一次完整采样快照（SampleBundle）
    error = Signal(str)

    def __init__(self, store: SettingsStore, parent=None):
        super().__init__(parent)
        self._store = store
        self._stop_event = threading.Event()
        self._last_event_ts: dict[int, float] = {}   # pid -> 上次记录高流量事件的时间
        self._rate_history: dict[int, deque] = {}    # pid -> deque[(ts, up_bps, down_bps)]
        self._episode_start: dict[int, float] = {}   # pid -> 本次持续超阈值起始时刻
        self._episode_row: dict[int, int] = {}       # pid -> 本次 episode 对应的 DB 行 id

    def run(self) -> None:
        storage = Storage()
        cpu = gpu = net = None
        try:
            cpu = CpuCollector()
            gpu = GpuCollector()
            net = NetworkCollector()
        except Exception as exc:  # 初始化阶段失败
            logger.exception("采集器初始化失败")
            self.error.emit(f"采集器初始化失败: {exc}")
            if gpu is not None:
                gpu.close()
            storage.close()
            return

        try:
            while not self._stop_event.is_set():
                ts = time.time()
                settings = self._store.get()
                try:
                    cpu_sample = cpu.sample(ts)
                    gpu_sample = gpu.sample(ts)
                    net_sample = net.sample(ts, top_n=settings.top_process_count)
                except Exception as exc:
                    logger.exception("采样异常")
                    self.error.emit(f"采样异常: {exc}")
                    self._stop_event.wait(1.0)
                    continue

                # 记录高流量进程：持续一段时间内平均速率超阈值才记录
                try:
                    self._record_sustained(
                        storage, net_sample.processes, ts,
                        settings.upload_threshold_bps,
                        settings.download_threshold_bps,
                        settings.sustain_seconds,
                        settings.refresh_interval_ms / 1000.0,
                    )
                except Exception:
                    logger.exception("高流量记录失败")

                self.sample_ready.emit(SampleBundle(
                    ts=ts, cpu=cpu_sample, gpu=gpu_sample, net=net_sample,
                ))

                # 依据当前设置计算睡眠，尽量维持固定采样周期
                interval = settings.refresh_interval_ms / 1000.0
                elapsed = time.time() - ts
                self._stop_event.wait(max(0.0, interval - elapsed))
        finally:
            for collector in (cpu, gpu, net):
                if collector is not None:
                    collector.close()
            storage.close()

    def _record_sustained(self, storage, processes, ts, up_th, down_th,
                          sustain, interval) -> None:
        """按「持续 sustain 秒内的平均速率」判定并记录高流量事件。

        每个采样周期把进程瞬时速率追加到其滚动窗口；当窗口覆盖满 sustain 秒后，
        用窗口内平均上行/下行速率与阈值比较，超阈值且超过冷却时间才写库。
        记录中的「持续时间」按窗口平均速率（与判定一致）跟踪：进程平均速率首次
        超阈值时，以窗口内最早样本作为 episode 起始时刻（而非超阈值那一瞬间），
        回落到阈值以下后重新计时，写库时用「当前时刻 - 起始时刻」。用窗口平均而
        非瞬时速率判定，可避免真实流量的瞬时抖动反复重置计时，导致持续时间被
        错误地缩到接近 0。

        同一进程的同一段持续超阈值期间只保留一条记录：首次触发时插入新行（时间
        记为 episode 起点），跨冷却期仍超阈值则原地更新该行的速率与持续时间，
        避免长时间下载在历史里产生大量重复行。
        """
        # 1) 追加当前样本
        for p in processes:
            hist = self._rate_history.get(p.pid)
            if hist is None:
                hist = self._rate_history[p.pid] = deque()
            hist.append((ts, p.up_bps, p.down_bps))

        # 2) 清理过期样本（保留最近 sustain + 一个采样周期的数据，避免内存增长）
        cutoff = ts - sustain - interval
        for pid in list(self._rate_history):
            hist = self._rate_history[pid]
            while hist and hist[0][0] < cutoff:
                hist.popleft()
            if not hist:
                del self._rate_history[pid]
                self._episode_start.pop(pid, None)
                self._episode_row.pop(pid, None)

        # 3) 清理早已过冷却期的 PID 事件时间戳，避免长期运行无界增长
        for pid in list(self._last_event_ts):
            if ts - self._last_event_ts[pid] > _EVENT_COOLDOWN_S:
                del self._last_event_ts[pid]

        # 4) 基于窗口平均速率判定并记录
        for p in processes:
            hist = self._rate_history.get(p.pid)
            if not hist:
                continue
            avg_up = sum(h[1] for h in hist) / len(hist)
            avg_down = sum(h[2] for h in hist) / len(hist)
            over = avg_up >= up_th or avg_down >= down_th
            if over:
                if p.pid not in self._episode_start:
                    # 首次判定为超阈值：以窗口内最早样本作为 episode 起点
                    self._episode_start[p.pid] = hist[0][0]
            else:
                self._episode_start.pop(p.pid, None)
                self._episode_row.pop(p.pid, None)
                continue

            if ts - hist[0][0] < sustain - interval:
                continue  # 尚未持续满 sustain 秒

            last = self._last_event_ts.get(p.pid)
            if last is not None and (ts - last) < _EVENT_COOLDOWN_S:
                continue
            duration = max(0.0, ts - self._episode_start[p.pid])
            service = service_or_software_for(p.pid)
            row_id = self._episode_row.get(p.pid)
            if row_id is None:
                # 本次 episode 的第一条记录：插入新行，时间记为 episode 起点
                row_id = storage.record_traffic_event(
                    self._episode_start[p.pid], p.pid, p.name,
                    avg_up, avg_down, service=service, duration=duration,
                    remote_addrs=p.remote_addrs,
                )
                self._episode_row[p.pid] = row_id
            else:
                # 同一段持续 episode：原地刷新速率与持续时间，避免产生重复行
                storage.update_traffic_event(
                    row_id, avg_up, avg_down, service, duration,
                    remote_addrs=p.remote_addrs,
                )
            self._last_event_ts[p.pid] = ts

    def stop(self) -> None:
        """请求停止采样线程；会立即唤醒正在 sleep/wait 的循环。"""
        self._stop_event.set()
