"""MonitorThread._record_sustained 的纯逻辑单测。

直接用哑 storage 注入，验证持续窗口 / 阈值 / 冷却逻辑，不依赖 GUI。
"""
from dataclasses import dataclass

from r_monitor.monitor import MonitorThread


@dataclass
class _P:
    pid: int
    name: str
    up_bps: float
    down_bps: float
    remote_addrs: str = ""


class _FakeStorage:
    def __init__(self):
        self.events = []        # (ts, pid, name, up, down, service, duration, remote_addrs)
        self._next_id = 1
        self._rows = {}         # row_id -> events 中的下标

    def record_traffic_event(self, ts, pid, name, up, down, service="",
                             duration=0.0, remote_addrs=""):
        row_id = self._next_id
        self._next_id += 1
        self._rows[row_id] = len(self.events)
        self.events.append((ts, pid, name, up, down, service, duration, remote_addrs))
        return row_id

    def update_traffic_event(self, row_id, up, down, service="",
                             duration=0.0, remote_addrs=""):
        idx = self._rows[row_id]
        ts, pid, name, _, _, _, _, _ = self.events[idx]
        self.events[idx] = (ts, pid, name, up, down, service, duration, remote_addrs)


def _thread():
    from r_monitor.config import Settings, SettingsStore
    return MonitorThread(SettingsStore(Settings()))


def test_no_event_before_sustain_window():
    t = _thread()
    st = _FakeStorage()
    # sustain=5s, interval=1s，进程持续高速 3 秒（尚未满 5 秒）
    for i in range(3):
        t._record_sustained(st, [_P(100, "x", 2_000_000, 0)], float(i),
                            1_000_000, 1_000_000, 5.0, 1.0)
    assert st.events == []


def test_event_fires_once_sustained_then_cools_down():
    t = _thread()
    st = _FakeStorage()
    p = _P(100, "x", 2_000_000, 0)
    # 持续 6 秒，平均速率 2MB/s > 阈值 1MB/s
    for i in range(6):
        t._record_sustained(st, [p], float(i), 1_000_000, 1_000_000, 5.0, 1.0)
    assert len(st.events) == 1
    # 冷却期内继续高速，不应重复记录
    for i in range(6, 10):
        t._record_sustained(st, [p], float(i), 1_000_000, 1_000_000, 5.0, 1.0)
    assert len(st.events) == 1


def test_avg_must_exceed_threshold():
    t = _thread()
    st = _FakeStorage()
    # 平均速率低于阈值（0.9MB/s < 1MB/s）不触发；实现用 >= 判定，恰好等于阈值会触发
    p = _P(200, "y", 900_000, 0)
    for i in range(6):
        t._record_sustained(st, [p], float(i), 1_000_000, 1_000_000, 5.0, 1.0)
    assert st.events == []


def test_downlink_triggers_too():
    t = _thread()
    st = _FakeStorage()
    p = _P(300, "z", 0, 3_000_000)
    for i in range(6):
        t._record_sustained(st, [p], float(i), 1_000_000, 1_000_000, 5.0, 1.0)
    assert len(st.events) == 1
    assert st.events[0][1] == 300


def test_duration_tracks_sustained_episode():
    t = _thread()
    st = _FakeStorage()
    # sustain=5s, interval=1s：窗口在 t=4 首次覆盖满 sustain-interval=4s，
    # 进程自 t=0 起持续超阈值，因此首次记录时持续时间应为 4 秒。
    p = _P(100, "x", 2_000_000, 0)
    for i in range(6):
        t._record_sustained(st, [p], float(i), 1_000_000, 1_000_000, 5.0, 1.0)
    assert len(st.events) == 1
    assert st.events[0][6] == 4.0


def test_duration_grows_across_cooldown():
    t = _thread()
    st = _FakeStorage()
    th = 1_000_000
    # 进程持续高速：t=4 首次触发插入一行（持续 4 秒），跨越 60 秒冷却后在 t=64
    # 仍在同一段 episode 内，应原地更新同一行而非新增，持续时间累计为 64 秒。
    p = _P(100, "x", 2_000_000, 0)
    for i in range(70):
        t._record_sustained(st, [p], float(i), th, th, 5.0, 1.0)
    assert len(st.events) == 1
    assert st.events[0][6] == 64.0


def test_new_episode_after_drop_creates_new_row():
    t = _thread()
    st = _FakeStorage()
    th = 1_000_000
    p_high = _P(100, "x", 2_000_000, 0)
    p_low = _P(100, "x", 0, 0)
    # 第一段高速：t=4 首次触发插入第一行
    for i in range(10):
        t._record_sustained(st, [p_high], float(i), th, th, 5.0, 1.0)
    assert len(st.events) == 1
    # 归零足够久：窗口平均回落结束第一段 episode，并跨过 60 秒冷却期
    for i in range(10, 76):
        t._record_sustained(st, [p_low], float(i), th, th, 5.0, 1.0)
    # 再次高速：应新插入一行，且第一行保持不变（不被覆盖）
    for i in range(76, 86):
        t._record_sustained(st, [p_high], float(i), th, th, 5.0, 1.0)
    assert len(st.events) == 2
    assert st.events[0][6] == 4.0


def test_duration_uses_windowed_average_not_instantaneous():
    t = _thread()
    st = _FakeStorage()
    th = 1_000_000
    # 瞬时速率在阈值上下抖动（2MB/s 与 0.5MB/s 交替，窗口平均 1.25MB/s 始终超阈值）。
    # 持续时间应按窗口平均稳定累计为 4 秒，而不是被瞬时抖动反复清零成 0。
    p_high = _P(100, "x", 2_000_000, 0)
    p_low = _P(100, "x", 500_000, 0)
    for i in range(6):
        t._record_sustained(st, [p_high if i % 2 == 0 else p_low],
                            float(i), th, th, 5.0, 1.0)
    assert len(st.events) == 1
    assert st.events[0][6] == 4.0
