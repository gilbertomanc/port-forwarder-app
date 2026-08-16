"""Scheduler: tareas programadas por dias + hora (A3, seccion 11.1).

Acciones soportadas: tunnel_start, tunnel_stop, forwards_apply,
forwards_clear, apply_profile, snapshot_state.

El reloj es inyectable (tests con reloj falso). Se evalua cada minuto.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any, Callable

from src.core.config import ConfigStore, ScheduleItem
from src.core.event_bus import bus
from src.core.metrics_store import MetricsStore
from src.core.supervisor import Supervisor

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Scheduler:
    def __init__(
        self,
        store: ConfigStore,
        supervisor: Supervisor,
        metrics: MetricsStore | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.supervisor = supervisor
        self.metrics = metrics or supervisor.metrics
        self._now = now or datetime.now
        self._last_minute: str | None = None
        self._stop_ev = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_ev.clear()
        self._thread = threading.Thread(target=self._loop, name="scheduler",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_ev.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop_ev.is_set():
            self.tick()
            self._stop_ev.wait(30)

    def tick(self) -> None:
        """Evalua tareas cuyo horario coincide con el minuto actual."""
        now = self._now()
        minute = now.strftime("%Y-%m-%d %H:%M")
        if minute == self._last_minute:
            return
        self._last_minute = minute
        for item in self.store.cfg.scheduler:
            if not item.enabled:
                continue
            if self._matches(item, now):
                self._run(item)

    def _matches(self, item: ScheduleItem, now: datetime) -> bool:
        sched = item.schedule or {}
        days = [d.lower() for d in (sched.get("days") or [])]
        t = (sched.get("time") or "00:00").strip()
        try:
            hour, minute = (int(x) for x in t.split(":"))
        except ValueError:
            return False
        if now.hour != hour or now.minute != minute:
            return False
        if days:
            return WEEKDAYS[now.weekday()] in days
        return True

    def _run(self, item: ScheduleItem) -> None:
        action = item.action
        a_type = action.type
        self.metrics.record_event("schedule_fire", task=item.id, action=a_type)
        bus.emit("schedule-fired", task=item.id, action=a_type)
        try:
            if a_type == "tunnel_start" and action.tunnel:
                self.supervisor.ssh.start(
                    self.store.get_tunnel(action.tunnel),
                    self.store.get_vps(
                        self.store.get_tunnel(action.tunnel).vps_id
                    ),
                )
            elif a_type == "tunnel_stop" and action.tunnel:
                self.supervisor.ssh.stop(self.store.get_tunnel(action.tunnel))
            elif a_type == "forwards_apply":
                self.supervisor.run_once()
            elif a_type == "forwards_clear":
                self.supervisor.netsh.clear_all()
            elif a_type == "apply_profile" and action.profile:
                self._apply_profile(action.profile)
            elif a_type == "snapshot_state":
                self.supervisor.metrics.record_event(
                    "snapshot",
                    **self.supervisor.status(),
                )
        except Exception:
            import logging

            logging.getLogger("port-forwarder.scheduler").exception(
                "tarea %s fallo", item.id
            )
            self.metrics.record_alert(
                "schedule_error",
                f"Tarea '{item.name}' fallo (tipo {a_type})",
                severity="error",
            )

    def _apply_profile(self, name: str) -> None:
        from src.core.profiles import Profiles

        Profiles(self.store, self.supervisor).apply(name)
