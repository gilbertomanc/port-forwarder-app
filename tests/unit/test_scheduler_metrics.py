"""Tests del Scheduler con reloj falso y del MetricsStore."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from unittest import mock

import pytest

from src.core.config import Bind, ConfigStore, ScheduleAction, ScheduleItem, Tunnel, TunnelHealthGate, Vps
from src.core.metrics_store import MetricsStore
from src.core.scheduler import Scheduler
from src.core.supervisor import Supervisor


class FakeNow:
    def __init__(self, dt: datetime):
        self.dt = dt

    def __call__(self) -> datetime:
        return self.dt

    def advance(self, minutes: int = 1):
        self.dt += timedelta(minutes=minutes)


@pytest.fixture
def sched_env(tmp_path):
    store = ConfigStore(path=str(tmp_path / "config.json"))
    store.add_vps(Vps(id="v1", host="vps.example.com", user="tunnel"))
    store.cfg.tunnels.append(Tunnel(
        id="tunnel-web", vps_id="v1", local_bind=Bind(port=3000),
        remote_binds=[Bind(host="0.0.0.0", port=80)],
        health_gate=TunnelHealthGate(enabled=False),
    ))
    metrics = MetricsStore(str(tmp_path / "metrics.db"))
    sup = mock.Mock()
    sup.metrics = metrics
    sup.ssh = mock.Mock()
    fake_now = FakeNow(datetime(2026, 8, 14, 9, 0))  # viernes
    s = Scheduler(store, sup, metrics=metrics, now=fake_now)
    return store, sup, metrics, fake_now, s


def test_fires_on_matching_day_and_time(sched_env):
    store, sup, metrics, fake_now, s = sched_env
    store.cfg.scheduler.append(ScheduleItem(
        id="t1", name="web",
        action=ScheduleAction(type="tunnel_start", tunnel="tunnel-web"),
        schedule={"days": ["fri"], "time": "09:00"},
    ))
    s.tick()  # 09:00 viernes -> dispara
    sup.ssh.start.assert_called_once()


def test_does_not_fire_wrong_minute(sched_env):
    store, sup, metrics, fake_now, s = sched_env
    store.cfg.scheduler.append(ScheduleItem(
        id="t1", name="web",
        action=ScheduleAction(type="tunnel_start", tunnel="tunnel-web"),
        schedule={"days": ["fri"], "time": "09:00"},
    ))
    fake_now.advance(1)  # 09:01
    s.tick()
    sup.ssh.start.assert_not_called()


def test_does_not_fire_wrong_day(sched_env):
    store, sup, metrics, fake_now, s = sched_env
    store.cfg.scheduler.append(ScheduleItem(
        id="t1", name="web",
        action=ScheduleAction(type="tunnel_start", tunnel="tunnel-web"),
        schedule={"days": ["mon"], "time": "09:00"},
    ))
    s.tick()
    sup.ssh.start.assert_not_called()


def test_disabled_task_skipped(sched_env):
    store, sup, metrics, fake_now, s = sched_env
    store.cfg.scheduler.append(ScheduleItem(
        id="t1", name="web", enabled=False,
        action=ScheduleAction(type="tunnel_start", tunnel="tunnel-web"),
        schedule={"days": ["fri"], "time": "09:00"},
    ))
    s.tick()
    sup.ssh.start.assert_not_called()


def test_fires_only_once_per_minute(sched_env):
    store, sup, metrics, fake_now, s = sched_env
    store.cfg.scheduler.append(ScheduleItem(
        id="t1", name="web",
        action=ScheduleAction(type="tunnel_start", tunnel="tunnel-web"),
        schedule={"days": ["fri"], "time": "09:00"},
    ))
    s.tick()
    s.tick()
    sup.ssh.start.assert_called_once()


# ---------------------------------------------------------------- Metrics


@pytest.fixture
def mstore(tmp_path):
    return MetricsStore(str(tmp_path / "m.db"))


def test_record_and_list_events(mstore):
    mstore.record_event("forward_applied", forward_id="f1", port=80)
    mstore.record_event("tunnel_down_event", tunnel_id="t1")
    events = mstore.list_events()
    assert len(events) == 2
    assert events[0]["type"] == "tunnel_down_event"


def test_alerts_lifecycle(mstore):
    aid = mstore.record_alert("tunnel_down", "algo paso", severity="error")
    assert mstore.resolve_alert(aid)
    assert not mstore.resolve_alert(99999)
    rows = mstore.list_alerts(state="open")
    assert rows == []
    rows = mstore.list_alerts(state="resolved")
    assert len(rows) == 1


def test_forward_events(mstore):
    id1 = mstore.record_forward_event("f1", "apply", True)
    id2 = mstore.record_forward_event("f1", "apply", False, "boom")
    assert isinstance(id1, int) and isinstance(id2, int)
    rows = mstore._conn.execute(
        "SELECT * FROM forward_events WHERE forward_id='f1'"
    ).fetchall()
    assert len(rows) == 2
    assert rows[1]["ok"] == 0
    assert rows[1]["detail"] == "boom"


def test_tunnel_uptime_summary(mstore):
    mstore.tunnel_uptime_start("t1")
    time.sleep(0.1)  # > granularidad del reloj de Windows (~15ms)
    mstore.tunnel_uptime_end("t1", state="down")
    mstore.tunnel_uptime_start("t1")
    # dormir antes del summary: si el reloj esta cuantizado (mismo tick que
    # el INSERT), now == ts_start y up_seconds daria 0.0 (test flaky)
    time.sleep(0.1)
    summary = mstore.tunnel_uptime_summary("t1")
    assert summary["up_seconds"] > 0
    assert summary["down_seconds"] > 0
    assert 0 < summary["uptime_fraction"] < 1


def test_purge(mstore):
    old = time.time() - 100 * 86400
    mstore._conn.execute(
        "INSERT INTO events (ts, type) VALUES (?, 'viejo')", (old,)
    )
    mstore._conn.commit()
    mstore.record_event("nuevo")
    counts = mstore.purge(retention_days=30)
    assert counts["events"] == 1
    types = [e["type"] for e in mstore.list_events()]
    assert "viejo" not in types


def test_concurrent_access_no_crash(mstore):
    """H3: la conexion SQLite compartida debe soportar acceso concurrente
    (lock interno) sin corromperse ni crashear."""
    import threading

    errors = []

    def worker(n: int) -> None:
        try:
            for i in range(25):
                mstore.record_event(f"worker_{n}", i=i)
                mstore.record_alert("tunnel_down", f"alerta {n}-{i}")
                mstore.record_forward_event(f"f{n}", "apply", True)
                mstore.list_events(limit=5)
                mstore.list_alerts(state="open")
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(mstore.list_events(limit=1000)) == 20 * 25
    assert len(mstore.list_alerts(state="open", limit=1000)) == 20 * 25
