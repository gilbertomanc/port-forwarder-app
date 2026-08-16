"""PowerEvents: recuperacion por suspension (A4, seccion 11.3).

Suscribirse a eventos de energia de Windows (WM_POWERBROADCAST) requiere
un message loop de la GUI; en headless se usa el approach por polling del
Supervisor (los forwards se reaplican cuando la IP cambia y los tunnels
muertos se reinician con backoff).

Este modulo expone el hook para la GUI y un helper de arranque que el
Supervisor llama en cada ciclo; el plan lo marca P1.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

log = logging.getLogger("port-forwarder.power")


class PowerEvents:
    """Registra timestamps de suspension/reanudacion detectadas por la GUI.

    La GUI (gui/tray.py) llama on_resume() cuando recibe WM_POWERBROADCAST
    con PBT_APMRESUMEAUTOMATIC. El Supervisor consulta was_resumed().
    """

    def __init__(self) -> None:
        self._resumed_at: float | None = None
        self._suspend_ts: float | None = None

    def on_suspend(self) -> None:
        self._suspend_ts = time.time()
        log.info("suspension detectada")

    def on_resume(self) -> None:
        self._resumed_at = time.time()
        log.info("reanudacion detectada: se reaplicara todo")
        if self._suspend_ts:
            from src.core.event_bus import bus

            bus.emit("power-resumed", suspended_seconds=round(
                self._resumed_at - self._suspend_ts, 1
            ))
            self._suspend_ts = None

    def was_resumed(self) -> bool:
        return self._resumed_at is not None

    def consume_resume(self) -> float | None:
        ts = self._resumed_at
        self._resumed_at = None
        return ts


power_events = PowerEvents()


def resume_hook(callback: Callable[[], None]) -> None:
    """Helper: registra un callback que se ejecuta al reanudar (P1)."""
    from src.core.event_bus import bus

    def _on(payload: dict) -> None:
        try:
            callback()
        except Exception:
            log.exception("resume_hook fallo")

    bus.subscribe(_on)
