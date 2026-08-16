"""Smoke en vivo del panel web con componentes REALES (no mocks).

Uso: python scripts/smoke_web_live.py
Crea config aislada en %TEMP%, arranca supervisor + panel, hace peticiones
HTTP reales y verifica respuestas.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.core.config import Bind, ConfigStore, Forward, Tunnel, Vps  # noqa: E402
from src.core.metrics_store import MetricsStore  # noqa: E402
from src.core.supervisor import Supervisor  # noqa: E402
from src.web.server import WebPanel  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="pf-web-live-"))
print(f"config aislada en {tmp}")

store = ConfigStore(path=str(tmp / "config.json"), backup_dir=str(tmp / "bk"))
store.cfg.forwards.append(Forward(
    id="fwd-web", listen_port=8080, wsl_distro="ubuntu-dev",
    wsl_port=8080, auto_apply=True,
))
store.add_vps(Vps(id="vps-main", host="vps.example.com", user="tunnel"))
store.cfg.tunnels.append(Tunnel(
    id="tunnel-web", vps_id="vps-main", local_bind=Bind(port=3000),
    remote_binds=[Bind(host="0.0.0.0", port=80)],
))
store.save()

metrics = MetricsStore(str(tmp / "metrics.db"))
sup = Supervisor(store, metrics=metrics, interval=2)
sup.start()

panel = WebPanel(sup, port=0, bind="127.0.0.1")
panel.start()
base = f"http://127.0.0.1:{panel.port}"
print(f"panel en {base}")


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'} {name} {extra}")
    if not cond:
        raise SystemExit(1)


def get(path: str) -> tuple[int, str]:
    with urllib.request.urlopen(base + path, timeout=10) as r:
        return r.status, r.read().decode("utf-8")


def post(path: str) -> tuple[int, dict]:
    req = urllib.request.Request(base + path, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


status, html = get("/")
check("GET / (dashboard)", status == 200 and "Port Forwarding Manager" in html)

status, body = get("/api/v1/state")
data = json.loads(body)
check("GET /api/v1/state", status == 200 and data["ok"], f"forwards={len(data['status']['forwards'])}")
check("state incluye forward", data["status"]["forwards"][0]["id"] == "fwd-web")
check("state incluye tunnel", data["status"]["tunnels"][0]["id"] == "tunnel-web")

status, body = get("/api/v1/events")
check("GET /api/v1/events", status == 200 and "events" in json.loads(body))

status, body = get("/api/v1/alerts")
check("GET /api/v1/alerts", status == 200 and "alerts" in json.loads(body))

status, data = post("/api/v1/forwards/apply")
check("POST /forwards/apply", status == 200 and data["ok"])

status, data = post("/api/v1/maintenance/on")
check("POST /maintenance/on", status == 200 and data["ok"])
status, data = post("/api/v1/maintenance/off")
check("POST /maintenance/off", status == 200 and data["ok"])

# panel con token: 401 sin token, 200 con token
panel2 = WebPanel(sup, port=0, bind="127.0.0.1", token="clave-live")
panel2.start()
base2 = f"http://127.0.0.1:{panel2.port}"
try:
    req = urllib.request.Request(base2 + "/api/v1/state")
    try:
        urllib.request.urlopen(req, timeout=10)
        check("auth: sin token -> 401", False)
    except urllib.error.HTTPError as e:
        check("auth: sin token -> 401", e.code == 401)
    req = urllib.request.Request(base2 + "/api/v1/state")
    req.add_header("Authorization", "Bearer clave-live")
    with urllib.request.urlopen(req, timeout=10) as r:
        check("auth: con token -> 200", r.status == 200)
finally:
    panel2.stop()

# supervisor termina limpio y el panel con el
panel.stop()
sup.stop()
print("\nTODO OK — panel web en vivo validado")
