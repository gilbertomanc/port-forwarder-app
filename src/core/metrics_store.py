"""MetricsStore: SQLite para eventos, alertas, uptime de tunnels y
eventos de forwards (seccion 10.4 del plan). Zero dependencias (sqlite3).

Tablas:
- events: journal de acciones (ts, tipo, detalle JSON)
- alerts: alertas (ts, tipo, severidad, mensaje, estado)
- tunnel_uptime: intervalos up/down por tunnel (ts_start, ts_end, estado)
- forward_events: aplicaciones/limpiezas/fallos por forward

Retencion configurable (default 30 dias) -> purge().
"""

from __future__ import annotations

import functools
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


def _locked(fn):
    """Serializa el acceso a la conexion SQLite (un solo hilo a la vez).

    La conexion sqlite NO es segura para uso concurrente (H3): todos los
    metodos publicos pasan por este lock.
    """

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)

    return wrapper


class MetricsStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        from src.utils import path as paths

        self.db_path = Path(db_path) if db_path else paths.metrics_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    @_locked
    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                type TEXT NOT NULL,
                detail TEXT
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                type TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'open',
                resolved_ts REAL
            );
            CREATE TABLE IF NOT EXISTS tunnel_uptime (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tunnel_id TEXT NOT NULL,
                ts_start REAL NOT NULL,
                ts_end REAL,
                state TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS forward_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                forward_id TEXT NOT NULL,
                action TEXT NOT NULL,
                ok INTEGER NOT NULL,
                detail TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
            CREATE INDEX IF NOT EXISTS idx_alerts_state ON alerts(state);
            CREATE INDEX IF NOT EXISTS idx_tun_uptime ON tunnel_uptime(tunnel_id);
            CREATE INDEX IF NOT EXISTS idx_fwd_events ON forward_events(forward_id);
            """
        )
        self._conn.commit()

    # -- escritura -----------------------------------------------------------

    @_locked
    def record_event(self, type_: str, **detail: Any) -> int:
        cur = self._conn.execute(
            "INSERT INTO events (ts, type, detail) VALUES (?, ?, ?)",
            (time.time(), type_, json.dumps(detail, default=str)),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    @_locked
    def record_alert(
        self, type_: str, message: str, severity: str = "warning"
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO alerts (ts, type, severity, message, state) "
            "VALUES (?, ?, ?, ?, 'open')",
            (time.time(), type_, severity, message),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    @_locked
    def resolve_alert(self, alert_id: int) -> bool:
        cur = self._conn.execute(
            "UPDATE alerts SET state='resolved', resolved_ts=? WHERE id=?",
            (time.time(), alert_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    @_locked
    def resolve_open_alerts(self, type_: str | None = None) -> int:
        if type_:
            cur = self._conn.execute(
                "UPDATE alerts SET state='resolved', resolved_ts=? "
                "WHERE state='open' AND type=?",
                (time.time(), type_),
            )
        else:
            cur = self._conn.execute(
                "UPDATE alerts SET state='resolved', resolved_ts=? "
                "WHERE state='open'",
                (time.time(),),
            )
        self._conn.commit()
        return cur.rowcount

    @_locked
    def record_forward_event(
        self, forward_id: str, action: str, ok: bool, detail: str = ""
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO forward_events (ts, forward_id, action, ok, detail) "
            "VALUES (?, ?, ?, ?, ?)",
            (time.time(), forward_id, action, 1 if ok else 0, detail),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    @_locked
    def tunnel_uptime_start(self, tunnel_id: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO tunnel_uptime (tunnel_id, ts_start, state) "
            "VALUES (?, ?, 'up')",
            (tunnel_id, time.time()),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    @_locked
    def tunnel_uptime_end(self, tunnel_id: str, state: str = "down") -> None:
        self._conn.execute(
            "UPDATE tunnel_uptime SET ts_end=?, state=? "
            "WHERE tunnel_id=? AND ts_end IS NULL",
            (time.time(), state, tunnel_id),
        )
        self._conn.commit()

    # -- lectura -------------------------------------------------------------

    @_locked
    def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    @_locked
    def list_alerts(
        self, state: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if state:
            rows = self._conn.execute(
                "SELECT * FROM alerts WHERE state=? ORDER BY ts DESC LIMIT ?",
                (state, limit),
            )
        else:
            rows = self._conn.execute(
                "SELECT * FROM alerts ORDER BY ts DESC LIMIT ?", (limit,)
            )
        return [dict(r) for r in rows.fetchall()]

    @_locked
    def tunnel_uptime_summary(self, tunnel_id: str) -> dict[str, Any]:
        """Total up/down en segundos + fraccion uptime para un tunnel."""
        rows = self._conn.execute(
            "SELECT state, SUM(COALESCE(ts_end, ?) - ts_start) AS secs "
            "FROM tunnel_uptime WHERE tunnel_id=? GROUP BY state",
            (time.time(), tunnel_id),
        ).fetchall()
        summary = {r["state"]: float(r["secs"] or 0) for r in rows}
        up = max(0.0, summary.get("up", 0.0))
        down = max(0.0, summary.get("down", 0.0))
        total = up + down
        fraction = up / total if total else 1.0
        return {
            "tunnel_id": tunnel_id,
            "up_seconds": up,
            "down_seconds": down,
            "uptime_fraction": round(fraction, 4),
        }

    @_locked
    def purge(self, retention_days: int = 30) -> dict[str, int]:
        """Borra metricas mas viejas que retention_days; devuelve conteos."""
        cutoff = time.time() - retention_days * 86400
        counts: dict[str, int] = {}
        ts_col = {
            "events": "ts",
            "alerts": "ts",
            "tunnel_uptime": "ts_start",
            "forward_events": "ts",
        }
        for table in ts_col:
            cur = self._conn.execute(
                f"DELETE FROM {table} WHERE {ts_col[table]} < ?", (cutoff,)
            )
            counts[table] = cur.rowcount
        self._conn.commit()
        return counts

    @_locked
    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
