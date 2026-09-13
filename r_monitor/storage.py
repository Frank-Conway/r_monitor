"""SQLite 存储：记录高流量事件。"""
import logging
import os
import sqlite3

from .config import DB_PATH

logger = logging.getLogger(__name__)


class Storage:
    def __init__(self, path=None):
        path = str(path or DB_PATH)
        dirname = os.path.dirname(path)
        if dirname:  # 相对路径（如 "foo.db"）的 dirname 为空，无需建目录
            os.makedirs(dirname, exist_ok=True)
        self._conn = sqlite3.connect(path)
        # busy_timeout 3s：写锁被占用时等待而非立即抛 "database is locked"
        self._conn.execute("PRAGMA busy_timeout = 3000")
        # WAL：写线程与读线程（高流量记录页）并发时减少锁竞争
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS traffic_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                pid INTEGER,
                name TEXT,
                up_bps REAL,
                down_bps REAL,
                direction TEXT,
                service TEXT,
                duration REAL,
                remote_addrs TEXT
            )
            """
        )
        # 旧库迁移：补充 service / duration / remote_addrs 列
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(traffic_events)")}
        if "service" not in cols:
            self._conn.execute("ALTER TABLE traffic_events ADD COLUMN service TEXT")
        if "duration" not in cols:
            self._conn.execute(
                "ALTER TABLE traffic_events ADD COLUMN duration REAL NOT NULL DEFAULT 0"
            )
        if "remote_addrs" not in cols:
            self._conn.execute("ALTER TABLE traffic_events ADD COLUMN remote_addrs TEXT")
        self._conn.commit()

    def record_traffic_event(self, ts: float, pid: int, name: str,
                             up_bps: float, down_bps: float,
                             service: str = "", duration: float = 0.0,
                             remote_addrs: str = "") -> int:
        """记录一次高流量事件，返回新行的 id（供持续期间刷新复用）。"""
        direction = "up" if up_bps >= down_bps else "down"
        cur = self._conn.execute(
            "INSERT INTO traffic_events "
            "(ts, pid, name, up_bps, down_bps, direction, service, duration, remote_addrs) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, pid, name, up_bps, down_bps, direction, service, duration, remote_addrs),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_traffic_event(self, row_id: int, up_bps: float, down_bps: float,
                             service: str = "", duration: float = 0.0,
                             remote_addrs: str = "") -> None:
        """刷新一次仍处于持续中的高流量记录（速率 / 方向 / 持续时间 / 远端地址）。

        同一进程的同一段持续超阈值期间只保留一条记录，跨冷却期仅原地更新，
        避免长时间下载在历史里产生大量重复行。
        """
        direction = "up" if up_bps >= down_bps else "down"
        self._conn.execute(
            "UPDATE traffic_events "
            "SET up_bps=?, down_bps=?, direction=?, service=?, duration=?, remote_addrs=? "
            "WHERE id=?",
            (up_bps, down_bps, direction, service, duration, remote_addrs, row_id),
        )
        self._conn.commit()

    def recent_events(self, limit: int = 300):
        cur = self._conn.execute(
            "SELECT ts, pid, name, up_bps, down_bps, direction, service, duration, remote_addrs "
            "FROM traffic_events ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()

    def clear(self) -> None:
        self._conn.execute("DELETE FROM traffic_events")
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            logger.exception("关闭数据库连接失败")
