"""Servidor REST /api/v1 (seccion 21.3) con AuthService.

- Desactivado por defecto; se activa con 'port-forwarder api enable'.
- Bind loopback por defecto (api.host); token Bearer obligatorio al activar.
- Scopes: read < write < admin; destructivos exigen admin + ?confirm=1.
- Rate limit por token (read 120/min, write 30/min).
- Auditoria de cada llamada en SQLite (events).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from src.api.auth import SCOPE_READ, SCOPE_WRITE, AuthService
from src.api.service import AppService
from src.core.event_bus import bus
from src.utils.http_server import BoundedThreadingHTTPServer

log = logging.getLogger("port-forwarder.api")

Handler = Callable[[AppService, dict[str, Any]], dict[str, Any]]

# Tabla de rutas: (metodo, regex, scope, handler)
ROUTES: list[tuple[str, str, str, Handler]] = [
    ("GET", r"^/api/v1/status$", SCOPE_READ, lambda s, m: s.status()),
    ("GET", r"^/api/v1/forwards$", SCOPE_READ, lambda s, m: s.forwards_list()),
    ("POST", r"^/api/v1/forwards$", SCOPE_WRITE,
     lambda s, m: s.forwards_add(
         forward_id=m.get("id", ""), listen_port=m.get("listen_port", 0),
         wsl_port=m.get("wsl_port", 0), distro=m.get("distro", ""),
         listen_address=m.get("listen_address", "0.0.0.0"),
         protocol=m.get("protocol", "tcp"),
         auto_apply=bool(m.get("auto_apply", False)),
         health_check=bool(m.get("health_check", True)))),
    ("DELETE", r"^/api/v1/forwards/([^/]+)$", SCOPE_WRITE,
     lambda s, m: s.forwards_remove(m["id"])),
    ("POST", r"^/api/v1/forwards/apply$", SCOPE_WRITE,
     lambda s, m: s.forwards_apply(all_=bool(m.get("all", False)))),
    ("POST", r"^/api/v1/forwards/clear$", "admin",
     lambda s, m: s.forwards_clear()),
    ("POST", r"^/api/v1/forwards/([^/]+)/test$", SCOPE_READ,
     lambda s, m: s.forwards_test(m["id"])),
    ("GET", r"^/api/v1/forwards/conflicts$", SCOPE_READ,
     lambda s, m: s.forwards_conflicts(m.get("port", 0))),
    ("GET", r"^/api/v1/portmap$", SCOPE_READ, lambda s, m: s.forwards_list()),
    ("GET", r"^/api/v1/tunnels$", SCOPE_READ, lambda s, m: s.tunnels_list()),
    ("POST", r"^/api/v1/tunnels$", SCOPE_WRITE,
     lambda s, m: s.tunnels_add(
         tunnel_id=m.get("id", ""), vps_id=m.get("vps_id", ""),
         local=m.get("local", ""), remote=m.get("remote") or [])),
    ("DELETE", r"^/api/v1/tunnels/([^/]+)$", SCOPE_WRITE,
     lambda s, m: s.tunnels_remove(m["id"])),
    ("POST", r"^/api/v1/tunnels/([^/]+)/start$", SCOPE_WRITE,
     lambda s, m: s.tunnels_start(m["id"])),
    ("POST", r"^/api/v1/tunnels/([^/]+)/stop$", SCOPE_WRITE,
     lambda s, m: s.tunnels_stop(m["id"])),
    ("POST", r"^/api/v1/tunnels/([^/]+)/restart$", SCOPE_WRITE,
     lambda s, m: s.tunnels_restart(m["id"])),
    ("POST", r"^/api/v1/tunnels/start-all$", "admin",
     lambda s, m: s.tunnels_start_all()),
    ("POST", r"^/api/v1/tunnels/stop-all$", "admin",
     lambda s, m: s.tunnels_stop_all()),
    ("GET", r"^/api/v1/vps$", SCOPE_READ, lambda s, m: s.vps_list()),
    ("POST", r"^/api/v1/vps$", SCOPE_WRITE,
     lambda s, m: s.vps_add(
         vps_id=m.get("id", ""), host=m.get("host", ""),
         user=m.get("user", ""), port=m.get("port", 22),
         identity_file=m.get("identity_file", ""))),
    ("DELETE", r"^/api/v1/vps/([^/]+)$", "admin",
     lambda s, m: s.vps_remove(m["id"])),
    ("GET", r"^/api/v1/health$", SCOPE_READ, lambda s, m: s.health()),
    ("GET", r"^/api/v1/alerts$", SCOPE_READ,
     lambda s, m: s.alerts_list(m.get("state"))),
    ("POST", r"^/api/v1/alerts/(\d+)/resolve$", SCOPE_WRITE,
     lambda s, m: s.alerts_resolve(m["id"])),
    ("GET", r"^/api/v1/schedule$", SCOPE_READ, lambda s, m: s.schedule_list()),
    ("POST", r"^/api/v1/schedule$", SCOPE_WRITE,
     lambda s, m: s.schedule_add(
         name=m.get("name", ""), action_type=m.get("type", ""),
         time_=m.get("time", ""), days=m.get("days", ""),
         tunnel=m.get("tunnel"), profile=m.get("profile"))),
    ("DELETE", r"^/api/v1/schedule/([^/]+)$", "admin",
     lambda s, m: s.schedule_remove(m["id"])),
    ("POST", r"^/api/v1/profiles/([^/]+)/apply$", SCOPE_WRITE,
     lambda s, m: s.profile_apply(m["name"])),
    ("POST", r"^/api/v1/profiles/([^/]+)/capture$", SCOPE_WRITE,
     lambda s, m: s.profile_capture(m["name"], m.get("description", ""))),
    ("GET", r"^/api/v1/profiles$", SCOPE_READ, lambda s, m: s.profile_list()),
    ("POST", r"^/api/v1/doctor$", SCOPE_READ, lambda s, m: s.doctor()),
    ("GET", r"^/api/v1/config/validate$", SCOPE_READ,
     lambda s, m: {"ok": True, "data": None, "message": "config OK"}),
    ("GET", r"^/api/v1/secrets/check/([^/]+)$", SCOPE_READ,
     lambda s, m: s.secrets_check(m["ref"])),
    ("POST", r"^/api/v1/maintenance/on$", "admin",
     lambda s, m: s.maintenance_on()),
    ("POST", r"^/api/v1/maintenance/off$", "admin",
     lambda s, m: s.maintenance_off()),
    ("GET", r"^/api/v1/maintenance/status$", SCOPE_READ,
     lambda s, m: s.maintenance_status()),
    ("GET", r"^/api/v1/drift$", SCOPE_READ, lambda s, m: s.drift_check()),
]


class ApiRequestHandler(BaseHTTPRequestHandler):
    api: "ApiServer"

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        log.debug(fmt, *args)

    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        remote = self.client_address[0]

        if self.api.allowed_ips and remote not in self.api.allowed_ips:
            self.api.audit("", method, path, 403, "ip no permitida")
            self._send_json({"ok": False, "error": "ip no permitida"}, 403)
            return

        # Auth: Bearer token obligatorio (21.2).
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self.api.audit("", method, path, 401, "sin token")
            self._send_json({"ok": False, "error": "token requerido"}, 401)
            return
        token = auth[len("Bearer "):]
        result = self.api.auth.authorize(token, SCOPE_READ)
        if result is None:
            self.api.audit("", method, path, 401, "token invalido")
            self._send_json({"ok": False, "error": "token invalido"}, 401)
            return
        token_id, token_scope = result

        for route_method, pattern, scope, handler in ROUTES:
            if route_method != method:
                continue
            m = re.match(pattern, path)
            if not m:
                continue
            # Scope suficiente?
            if self.api.auth.authorize(token, scope) is None:
                self.api.audit(token_id, method, path, 403,
                               f"scope insuficiente (necesita {scope})")
                self._send_json(
                    {"ok": False, "error": f"scope insuficiente: {scope}"},
                    403)
                return
            # Confirmacion para destructivos (admin).
            if scope == "admin" and "confirm" not in query and \
                    not path.endswith(("status",)):
                self.api.audit(token_id, method, path, 400, "falta confirm")
                self._send_json(
                    {"ok": False, "error": "parametro ?confirm=1 requerido"},
                    400)
                return
            # Rate limit.
            if not self.api.auth.check_rate(token_id, token_scope):
                self.api.audit(token_id, method, path, 429, "rate limit")
                self._send_json(
                    {"ok": False, "error": "rate limit excedido"}, 429)
                return
            # Cuerpo JSON (opcional).
            body_params: dict[str, Any] = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    try:
                        body_params = json.loads(
                            self.rfile.read(length).decode("utf-8")
                        )
                    except (ValueError, UnicodeDecodeError):
                        self.api.audit(token_id, method, path, 400,
                                       "json invalido")
                        self._send_json(
                            {"ok": False, "error": "cuerpo JSON invalido"},
                            400)
                        return
            params: dict[str, Any] = dict(query) if query else {}
            params.update(body_params)
            # Extraer grupos de captura de la regex (conversion a int si aplica).
            if m.groups():
                if len(m.groups()) == 1:
                    # alias generico: id/name/ref apuntan al mismo grupo
                    params["id"] = params["name"] = params["ref"] = m.group(1)
                else:
                    for g, gname in zip(m.groups(), ("id", "name", "ref")):
                        if gname not in params:
                            params[gname] = g
            for key in ("id", "port", "alert_id"):
                val = params.get(key)
                if isinstance(val, list):
                    val = val[0] if val else None
                    params[key] = val
                if isinstance(val, str):
                    try:
                        params[key] = int(val)
                    except ValueError:
                        pass
            if "state" in params and isinstance(params.get("state"), list):
                params["state"] = params["state"][0]

            try:
                result_data = handler(self.api.service, params)
            except Exception as e:
                log.exception("handler %s %s fallo", method, path)
                self.api.audit(token_id, method, path, 500, str(e))
                self._send_json({"ok": False, "error": str(e)}, 500)
                return
            status_code = 200
            if isinstance(result_data, dict) and result_data.get("ok") is False:
                status_code = 400 if "no existe" in result_data.get(
                    "message", "") or "invalido" in result_data.get(
                    "message", "") or "ya existe" in result_data.get(
                    "message", "") else 500
            self.api.audit(token_id, method, path, status_code, "")
            self._send_json(result_data, status_code)
            return

        self.api.audit(token_id, method, path, 404, "ruta desconocida")
        self._send_json({"ok": False, "error": "no encontrado"}, 404)

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_DELETE(self) -> None:
        self._handle("DELETE")


class ApiServer:
    def __init__(
        self,
        service: AppService,
        auth: AuthService,
        host: str = "127.0.0.1",
        port: int = 8791,
        allowed_ips: list[str] | None = None,
        max_connections: int = 50,
    ) -> None:
        self.service = service
        self.auth = auth
        self.host = host
        self.port = port
        self.allowed_ips = allowed_ips or ["127.0.0.1"]
        self.max_connections = max_connections
        self._httpd: BoundedThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.running = False

    def start(self) -> None:
        if self.running:
            return
        handler = type("ApiHandlerT", (ApiRequestHandler,), {"api": self})
        try:
            self._httpd = BoundedThreadingHTTPServer(
                (self.host, self.port), handler,
                max_connections=self.max_connections,
            )
        except OSError as e:
            raise RuntimeError(
                f"no se pudo abrir API en {self.host}:{self.port} ({e})"
            ) from e
        if self.port == 0:
            self.port = self._httpd.server_address[1]
        self.running = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="api-server", daemon=True
        )
        self._thread.start()
        log.info("API REST en http://%s:%s/api/v1", self.host, self.port)

    def stop(self) -> None:
        self.running = False
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "url": f"http://{self.host}:{self.port}/api/v1",
            "host": self.host,
            "port": self.port,
            "allowed_ips": self.allowed_ips,
            "tokens": len(self.auth.list_tokens()),
        }

    def audit(self, token_id: str, method: str, path: str,
              status: int, note: str) -> None:
        try:
            self.service.supervisor.metrics.record_event(
                "api_call", token_id=token_id or "-", method=method,
                path=path, status=status, note=note,
            )
        except Exception:  # la auditoria nunca rompe la peticion
            pass
