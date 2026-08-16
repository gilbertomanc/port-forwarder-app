"""Event bus simple pub/sub (patron clave del plan, seccion 4.2).

El Supervisor emite eventos ("state-changed", "tunnel-down", "forward-applied",
"alert") y la UI/CLI `watch` se suscriben. Thread-safe para el modelo de
threads del plan (un thread supervisor, threads de UI).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

Handler = Callable[[dict[str, Any]], None]


class EventBus:
    def __init__(self, max_history: int = 500) -> None:
        self._lock = threading.RLock()
        self._handlers: list[Handler] = []
        self._history: deque[dict[str, Any]] = deque(maxlen=max_history)

    def subscribe(self, handler: Handler) -> Callable[[], None]:
        """Registra un handler; devuelve funcion para desuscribirse."""
        with self._lock:
            self._handlers.append(handler)

        def _unsub() -> None:
            with self._lock:
                try:
                    self._handlers.remove(handler)
                except ValueError:
                    pass

        return _unsub

    def emit(self, event: str, **data: Any) -> None:
        """Publica un evento: {event, ts, **data}."""
        payload = {"event": event, "ts": time.time(), **data}
        with self._lock:
            self._history.append(payload)
            handlers = list(self._handlers)
        for h in handlers:
            try:
                h(payload)
            except Exception:
                # Un handler roto no debe tumbar el bus ni el supervisor.
                import logging

                logging.getLogger("event-bus").exception(
                    "handler failed for event %s", event
                )

    def history(self, since_ts: float | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._history)
        if since_ts is not None:
            items = [i for i in items if i["ts"] >= since_ts]
        return items


# Bus global de la aplicacion (un solo loop, seccion 12.3)
bus = EventBus()
