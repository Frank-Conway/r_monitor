"""ESTATS 诊断脚本：确认管理员权限与 SetPerTcpConnectionEStats 的失败原因。

复用 r_monitor.collectors.estats 的 ctypes 定义，避免与采集器重复维护。

用法（请在管理员 PowerShell 中运行）：
    python estats_diag.py
"""
import ctypes

from r_monitor.collectors import estats


def main():
    admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    print(f"== 是否管理员: {admin} ==")
    if not admin:
        print("!! 当前进程没有管理员权限，ESTATS 必然失败。请用管理员 PowerShell 运行。")
        print("   （若你是通过「以管理员身份重启」启动的却显示 False，说明提权重启没生效）")
        return

    rows = estats.get_tcp_table()
    est = [r for r in rows if r.dwState == estats.TCP_STATE_ESTABLISHED]
    print(f"== TCP 连接总数: {len(rows)}，其中 ESTABLISHED: {len(est)} ==")
    if not est:
        print("没有 ESTABLISHED 连接，无法探测（稍后再试）。")
        return

    for r in est[:5]:
        lport = estats.port_ntohs(r.dwLocalPort)
        rport = estats.port_ntohs(r.dwRemotePort)
        print(f"\n-- pid={r.dwOwningPid} localPort={lport} remotePort={rport} "
              f"(raw 0x{r.dwLocalPort:08X}/0x{r.dwRemotePort:08X})")

        row = estats.to_tcp_row(r)
        ret = estats.enable_estats(row)
        print(f"   SetPerTcpConnectionEStats -> {ret} ({estats.err_name(ret)})")

        code, stats = estats.read_connection_bytes(row)
        if code == 0:
            print(f"   GetPerTcpConnectionEStats -> {code} ({estats.err_name(code)}) "
                  f"BytesOut={stats[0]} BytesIn={stats[1]}")
        else:
            print(f"   GetPerTcpConnectionEStats -> {code} ({estats.err_name(code)})")


if __name__ == "__main__":
    main()
