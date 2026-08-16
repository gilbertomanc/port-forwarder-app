"""Panel web local (seccion 10.5 del plan): dashboard + API JSON.

Servidor stdlib (http.server) en 127.0.0.1:8790 por defecto, cero
dependencias. Muestra estado de forwards/tunnels, alertas, uptime y
permite acciones desde el navegador. Auth opcional con token Bearer
(necesario si el bind no es loopback).
"""

from .server import WebPanel, start_panel

__all__ = ["WebPanel", "start_panel"]
