"""冒烟测试：验证 CPU / GPU / 网络采集器（不启动 GUI）。"""
import threading
import time
import urllib.request

from r_monitor.collectors import (
    CpuCollector,
    GpuCollector,
    NetworkCollector,
    estats,
)


def test_cpu():
    print("=" * 60)
    print("[CPU]")
    c = CpuCollector()
    time.sleep(1.0)
    s = c.sample(time.time())
    print(f"  overall={s.overall:.1f}%  cores={len(s.per_core)}  "
          f"freq={s.freq_mhz:.0f}MHz  mem={s.mem_percent:.1f}%")
    print(f"  per_core={[round(x) for x in s.per_core[:8]]}...")
    print(f"  top_proc={[(p.name, round(p.cpu,1)) for p in s.top_processes[:5]]}")


def test_gpu():
    print("=" * 60)
    print("[GPU]")
    g = GpuCollector()
    print(f"  adapters(enum)={[(a.name, a.vram_total) for a in g.adapters]}")
    print(f"  engine_counters={g.engine_counter_count}  "
          f"mem_counters={g.memory_counter_count}")
    time.sleep(1.0)
    g.sample(time.time())
    time.sleep(1.0)
    s2 = g.sample(time.time())
    for ad in s2.adapters:
        print(f"  {ad.name}: util={ad.utilization}%  "
              f"vram={ad.vram_used}/{ad.vram_total}  "
              f"shared={ad.shared_used}  engines={ad.engines}")
    if not s2.adapters:
        print("  (无适配器数据)")


def test_network():
    print("=" * 60)
    print("[NET]")
    n = NetworkCollector()

    rows = estats.get_tcp_table()
    print(f"  tcp_connections={len(rows)}")

    ok = 0
    nonzero = 0
    for r in rows:
        code, stats = estats.read_connection_bytes(estats.to_tcp_row(r))
        if code == 0:
            ok += 1
            if stats[0] > 0 or stats[1] > 0:
                nonzero += 1
    print(f"  estats_ok={ok}/{len(rows)}  nonzero={nonzero}")

    # 本进程实测：开一条下载连接，验证能否统计到自己的字节
    def _download():
        try:
            with urllib.request.urlopen(
                "https://speed.cloudflare.com/__down?bytes=8000000", timeout=15
            ) as resp:
                total = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
        except Exception as exc:
            print(f"  download_err={exc}")

    th = threading.Thread(target=_download, daemon=True)
    th.start()
    time.sleep(0.5)
    s = n.sample(time.time())
    th.join(timeout=20)

    mine = [p for p in s.processes if p.name and "python" in p.name.lower()]
    print(f"  self_process_bytes: {[(p.pid, p.name, round(p.down_bps/1024,1)) for p in mine]}")
    print(f"  global down={s.total_down_bps/1024/1024:.2f} MB/s  "
          f"up={s.total_up_bps/1024/1024:.2f} MB/s")
    top = [(p.name, round((p.up_bps + p.down_bps) / 1024, 1)) for p in s.processes[:8]]
    print(f"  top_processes={top}")


if __name__ == "__main__":
    test_cpu()
    test_gpu()
    test_network()
    print("=" * 60)
    print("DONE")
