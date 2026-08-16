"""Notifier: toasts nativos via winotify (opcional) con fallback a log.

Dependencia opcional (seccion 5.1): si winotify no esta instalado, las
notificaciones se registran en el log y en el centro de alertas (SQLite),
sin romper nada.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("port-forwarder.notifier")

try:  # pragma: no cover - depende de winotify
    from winotify import Notification  # type: ignore

    _WINOTIFY = True
except ImportError:  # pragma: no cover
    _WINOTIFY = False


def notify(
    title: str,
    message: str,
    level: str = "info",
    app_id: str = "Port Forwarding Manager",
) -> None:
    """Muestra un toast nativo; si no hay winotify, lo registra en el log."""
    if _WINOTIFY:
        try:  # pragma: no cover
            icon = None
            n = Notification(
                app_id=app_id,
                title=title,
                msg=message,
                duration="short",
                icon=icon,
            )
            n.show()
            return
        except Exception as e:  # pragma: no cover
            log.warning("toast fallo (winotify): %s", e)
    getattr(log, level if level in ("info", "warning", "error") else "info")(
        "[notify %s] %s: %s", level, title, message
    )
