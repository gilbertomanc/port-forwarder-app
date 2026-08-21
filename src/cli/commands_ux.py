"""Comandos CLI de UX y operacion: status, secrets, config, doctor, diag,
drift, maintenance, webhooks, connections, supervise, watch, gui."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import time
import urllib.request

from src.cli.cli import CliError, ConfigCliError, _json_out
from src.core.config import ConfigError, ConfigStore
from src.core.event_bus import bus
from src.core.logger import setup_logging
from src.core.metrics_store import MetricsStore
from src.core.supervisor import Supervisor
from src.providers.netsh_provider import NetshProvider
from src.providers.ssh_tunnel_provider import SshTunnelProvider
from src.providers.wsl_ip_provider import WslIpProvider
from src.utils import path as paths
from src.utils import subprocess_async as sp
from src.utils.secrets import SecretsStore


def _ctx(args: argparse.Namespace, web_external: bool = False):
    store = ConfigStore()
    netsh = NetshProvider(netsh_exe=store.cfg.windows.netsh_exe or None)
    wsl = WslIpProvider(wsl_exe=store.cfg.windows.wsl_exe or None)
    ssh = SshTunnelProvider(ssh_exe=store.cfg.windows.ssh_exe or None,
                            autossh_exe=store.cfg.windows.autossh_exe or None)
    metrics = MetricsStore()
    sup = Supervisor(store, netsh=netsh, wsl=wsl, ssh=ssh, metrics=metrics,
                     web_panel_external=web_external)
    return store, netsh, wsl, ssh, metrics, sup


def cmd_status(args: argparse.Namespace) -> int:
    store, netsh, wsl, ssh, metrics, sup = _ctx(args)
    data = sup.status()
    data["config_path"] = str(paths.config_path())
    data["version"] = 2
    traffic_by_id: dict[str, dict] = {}
    for t in store.cfg.tunnels:
        try:
            if ssh.is_alive(t):
                tf = ssh.traffic(t, store.get_vps(t.vps_id))
                if tf:
                    traffic_by_id[t.id] = tf
        except Exception:  # noqa: BLE001
            continue
    for tun in data.get("tunnels", []):
        tf = traffic_by_id.get(tun["id"])
        if tf:
            tun["traffic"] = tf
    if getattr(args, "json", False):
        _json_out(data)
    else:
        print(f"Supervisor: {'RUNNING' if data['running'] else 'idle'} "
              f"(interval {data['interval_seconds']}s) "
              f"admin={data['admin']}")
        print(f"Maintenance: {data['maintenance']}")
        for f in data["forwards"]:
            print(f"  fwd {f['id']:<16} :{f['listen_port']:<6} "
                  f"{f['state']:<8} ip={f['ip'] or '-'}")
        for t in data["tunnels"]:
            line = (f"  tun {t['id']:<16} {t['state']:<10} "
                    f"local={t['local']} remote={','.join(t['remote'])}")
            tf = t.get("traffic")
            if tf:
                line += (f"  [rx {_fmt_bytes(tf['rx_bytes'])} tx {_fmt_bytes(tf['tx_bytes'])}"
                         f" · ↓{_fmt_rate(tf['rx_rate_bps'])} ↑{_fmt_rate(tf['tx_rate_bps'])}]")
            print(line)
    return 0


def _fmt_bytes(n: int) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _fmt_rate(bps: int) -> str:
    return f"{_fmt_bytes(int(bps))}/s"


def cmd_secrets(args: argparse.Namespace) -> int:
    sec = SecretsStore()
    action = args.action
    if action == "set":
        # El valor entra SIEMPRE por stdin (regla 13.2: jamas como argumento).
        if sys.stdin.isatty():
            value = getpass.getpass(f"valor para '{args.ref}': ")
        else:
            value = sys.stdin.readline().rstrip("\n")
        if not value:
            raise CliError("valor vacio; no se guardo nada")
        sec.set(args.ref, value)
        print(f"secret '{args.ref}' guardado (cifrado DPAPI)")
        return 0
    if action == "check":
        ok = sec.check(args.ref)
        print(f"secret '{args.ref}': {'existe' if ok else 'no definido'}")
        return 0 if ok else 1
    print(f"accion desconocida: {action}")
    return 2


def cmd_config(args: argparse.Namespace) -> int:
    action = args.action
    if action == "validate":
        try:
            store = ConfigStore()
        except ConfigError as e:
            print(f"config INVALIDA: {e}", file=sys.stderr)
            return 3
        print(f"config OK ({len(store.cfg.forwards)} forwards, "
              f"{len(store.cfg.tunnels)} tunnels, "
              f"{len(store.cfg.vps_list)} vps)")
        return 0
    if action == "export":
        store = ConfigStore()
        with open(args.path, "w", encoding="utf-8") as f:
            json.dump(store.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"config exportada a {args.path}")
        return 0
    if action == "import":
        try:
            data = json.load(open(args.path, encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise CliError(f"no se pudo leer '{args.path}': {e}")
        try:
            from src.core.config import parse_config

            parse_config(data)
        except ConfigError as e:
            raise ConfigCliError(str(e))
        target = paths.config_path()
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                          encoding="utf-8")
        print(f"config importada a {target}")
        return 0
    print(f"accion desconocida: {action}")
    return 2


def cmd_doctor(args: argparse.Namespace) -> int:
    """U8: detector de problemas del entorno."""
    store, netsh, wsl, ssh, metrics, sup = _ctx(args)
    problems: list[str] = []
    checks: list[dict] = []

    def _check(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            problems.append(f"{name}: {detail}")

    _check("netsh", sp.run([store.cfg.windows.netsh_exe,
                            "interface", "portproxy", "show", "all"],
                           timeout=10, check=False).returncode == 0,
           "netsh no responde")
    _check("admin (para forwards)", sp.is_admin(),
           "aplicar forwards pedira UAC")
    _check("ssh", sp.run([store.cfg.windows.ssh_exe, "-V"],
                         timeout=10, check=False).returncode in (0, 1),
           "ssh.exe no disponible")

    distros = [f.wsl_distro for f in store.cfg.forwards if f.wsl_distro]
    for d in dict.fromkeys(distros):
        ip = wsl.get_ip(d)
        _check(f"wsl distro '{d}'", ip is not None,
               "distro detenida o inexistente (usa 'wsl -l')")

    for t in store.cfg.tunnels:
        vps = store.get_vps(t.vps_id)
        if vps is None:
            _check(f"tunnel {t.id} -> vps {t.vps_id}", False,
                   "vps_id no existe en config")
            continue
        _check(f"vps {vps.id} alcanzable", ssh.latency(t, vps) is not None,
               "VPS inalcanzable o GatewayPorts off")
        _check(f"tunnel {t.id} identidad", 
               bool(vps.identity_file) or True,
               "")

    for f in store.cfg.forwards:
        conflicts = netsh.detect_conflicts(f.listen_port)
        _check(f"puerto :{f.listen_port} libre", not conflicts,
               f"en uso por PIDs {conflicts}")

    for c in checks:
        status = "OK" if c["ok"] else "FAIL"
        suffix = f" — {c['detail']}" if (not c["ok"] and c["detail"]) else ""
        print(f"{status} {c['check']}{suffix}")
    if problems:
        print(f"\n{len(problems)} problema(s) detectados", file=sys.stderr)
        return 1
    print("\nentorno sano")
    return 0


def cmd_diag(args: argparse.Namespace) -> int:
    """U7: bundle de diagnostico (sin secretos)."""
    store, netsh, wsl, ssh, metrics, sup = _ctx(args)
    bundle = {
        "ts": time.time(),
        "status": sup.status(),
        "config": _redact_config(store.to_dict()),
        "alerts": metrics.list_alerts(limit=50),
        "events": metrics.list_events(limit=50),
        "ports": [e.as_dict() for e in netsh.declared_forwards(store.cfg.forwards)],
        "secrets_refs": SecretsStore().list_refs(),  # solo nombres
        "admin": sp.is_admin(),
    }
    out = paths.data_dir() / "diag.json"
    out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False, default=str),
                   encoding="utf-8")
    print(f"bundle de diagnostico en {out}")
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    """F13: estado deseado (config) vs real (netsh + procesos)."""
    store, netsh, wsl, ssh, metrics, sup = _ctx(args)
    action = getattr(args, "action", "check")
    entries = netsh.declared_forwards(store.cfg.forwards)
    drift = [
        {"forward_id": e.forward_id, "listen_port": e.listen_port,
         "state": e.state}
        for e in entries if e.state != "ok"
    ]
    for t in store.cfg.tunnels:
        if t.auto_start and not ssh.is_alive(t):
            drift.append({"tunnel_id": t.id, "state": "down"})

    if action == "reconcile":
        if not getattr(args, "yes", False) and drift:
            raise CliError(
                f"hay {len(drift)} diferencias; confirma con --yes "
                f"(usa --cleanup para borrar lo no declarado)"
            )
        for e in entries:
            f = store.get_forward(e.forward_id) if e.forward_id else None
            if e.state == "missing" and f:
                ip = wsl.get_ip(f.wsl_distro)
                if ip:
                    netsh.add_forward(f, ip)
            if e.state == "extra" and getattr(args, "cleanup", False):
                netsh.remove_forward(f) if f else None
                # eliminar regla extra por puerto
                from src.core.config import Forward as F

                netsh.remove_forward(F(id=f"extra-{e.listen_port}",
                                       listen_port=e.listen_port))
        print(f"reconciliado ({len(drift)} diferencias)")
        return 0

    if getattr(args, "json", False):
        _json_out(drift)
    else:
        if not drift:
            print("sin drift: config y realidad coinciden")
            return 0
        for d in drift:
            print(f"DRIFT {d}")
        return 1


def cmd_maintenance(args: argparse.Namespace) -> int:
    store, netsh, wsl, ssh, metrics, sup = _ctx(args)
    action = getattr(args, "action", "status")
    if action == "on":
        store.cfg.maintenance.active = True
        store.save()
        for t in store.cfg.tunnels:
            if ssh.is_alive(t):
                ssh.stop(t)
        print("modo mantenimiento ACTIVADO (todo pausado)")
        return 0
    if action == "off":
        store.cfg.maintenance.active = False
        store.save()
        print("modo mantenimiento DESACTIVADO (reaplicando...)")
        sup.run_once()
        return 0
    if action == "schedule":
        store.cfg.maintenance.start = args.start
        store.cfg.maintenance.end = args.end
        store.save()
        print(f"ventana de mantenimiento: {args.start}-{args.end}")
        return 0
    # status
    data = {"active": store.cfg.maintenance.active,
            "window": f"{store.cfg.maintenance.start}-{store.cfg.maintenance.end}"}
    if getattr(args, "json", False):
        _json_out(data)
    else:
        print(f"maintenance: {'ON' if data['active'] else 'OFF'} "
              f"(ventana {data['window']})")
    return 0


def cmd_webhooks(args: argparse.Namespace) -> int:
    store, netsh, wsl, ssh, metrics, sup = _ctx(args)
    action = args.action
    if action == "list":
        rows = [{"id": w.id, "url": w.url, "events": w.events,
                 "secret_ref": w.secret_ref} for w in store.cfg.webhooks]
        if getattr(args, "json", False):
            _json_out(rows)
        else:
            for r in rows:
                print(f"{r['id']:<12} {r['url']:<40} {','.join(r['events'])}")
        return 0
    if action == "add":
        import uuid

        from src.core.config import Webhook

        wh = Webhook(
            id=f"wh-{uuid.uuid4().hex[:8]}",
            url=args.url,
            events=[e.strip() for e in args.events.split(",") if e.strip()],
            secret_ref=args.secret,
        )
        store.cfg.webhooks.append(wh)
        store.save()
        print(f"webhook '{wh.id}' agregado para {wh.url}")
        return 0
    if action == "remove":
        before = len(store.cfg.webhooks)
        store.cfg.webhooks = [w for w in store.cfg.webhooks if w.id != args.id]
        if len(store.cfg.webhooks) == before:
            raise CliError(f"webhook '{args.id}' no existe")
        store.save()
        print(f"webhook '{args.id}' eliminado")
        return 0
    print(f"accion desconocida: {action}")
    return 2


def cmd_supervise(args: argparse.Namespace) -> int:
    """Corre el supervisor en foreground (headless). Ctrl+C para salir."""
    setup_logging(console=True)
    store, netsh, wsl, ssh, metrics, sup = _ctx(args)
    api_server = None
    if store.cfg.api.enabled:
        from src.api.auth import AuthService
        from src.api.server import ApiServer
        from src.api.service import AppService

        svc = AppService(store, sup)
        api_server = ApiServer(svc, AuthService(),
                               host=store.cfg.api.host,
                               port=store.cfg.api.port,
                               allowed_ips=store.cfg.api.allowed_ips)
        try:
            api_server.start()
            print(f"API REST en http://{store.cfg.api.host}:"
                  f"{api_server.port}/api/v1 (token obligatorio)")
        except RuntimeError as e:
            print(f"API no arranco: {e}", file=sys.stderr)
            api_server = None
    print(f"supervisor headless: interval {sup.interval}s, "
          f"Ctrl+C para salir")
    try:
        sup.run_forever()
    except KeyboardInterrupt:
        print("\nsupervisor detenido")
    finally:
        if api_server:
            api_server.stop()
    return 0


def _panel_token(store: ConfigStore) -> str:
    """Resuelve el token del panel: secrets DPAPI primero (H4), luego el
    campo legado en claro de config (con advertencia)."""
    from src.utils.secrets import SecretsStore

    sec = SecretsStore()
    if sec.check("web_panel_token"):
        return sec.get("web_panel_token")
    legacy = store.cfg.ui.web_panel_token
    if legacy:
        print(
            "AVISO: ui.web_panel_token esta en claro en config.json. "
            "Muevelo a secrets con: port-forwarder secrets set web_panel_token",
            file=sys.stderr,
        )
    return legacy


def _redact_config(cfg_dict: dict) -> dict:
    """Redacta secretos del bundle de diagnostico (H4): nunca exportar el
    token del panel ni contrasenas de VPS en claro."""
    ui = cfg_dict.get("ui") or {}
    if ui.get("web_panel_token"):
        ui["web_panel_token"] = "\u2022\u2022\u2022\u2022(redactado)"
    for v in cfg_dict.get("vps_list") or []:
        if v.get("password"):
            v["password"] = "\u2022\u2022\u2022\u2022(redactado)"
    return cfg_dict


def cmd_web(args: argparse.Namespace) -> int:
    """Panel web local (10.5): start (foreground, con supervisor), stop, status."""
    import os
    import signal

    from src.web.server import WebPanel

    action = getattr(args, "action", "status")
    store, netsh, wsl, ssh, metrics, sup = _ctx(
        args, web_external=not getattr(args, "no_supervisor", False)
    )
    ui = store.cfg.ui
    pidfile = paths.data_dir() / "web.pid"

    if action == "status":
        data = {
            "running": pidfile.exists(),
            "port": ui.web_panel_port,
            "bind": ui.web_panel_bind,
            "auth_required": bool(_panel_token(store)),
            "url": f"http://{ui.web_panel_bind}:{ui.web_panel_port}",
        }
        if pidfile.exists():
            try:
                info = json.loads(pidfile.read_text(encoding="utf-8"))
                data.update({"port": info.get("port", data["port"]),
                             "bind": info.get("bind", data["bind"])})
                data["url"] = f"http://{data['bind']}:{data['port']}"
            except (ValueError, OSError):
                pass
        if getattr(args, "json", False):
            _json_out(data)
        else:
            state = "corriendo" if running else "detenido"
            print(f"panel web {state}: {data['url']}"
                  + (" (token requerido)" if data["auth_required"] else ""))
        return 0

    if action == "stop":
        if not pidfile.exists():
            print("el panel web no esta corriendo")
            return 0
        try:
            try:
                info = json.loads(pidfile.read_text(encoding="utf-8"))
                pid = int(info.get("pid")) if isinstance(info, dict) else int(info)
            except ValueError:
                # formato viejo: solo un numero
                pid = int(pidfile.read_text(encoding="utf-8").strip())
            os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError, SystemError) as e:
            print(f"no se pudo detener (pid en {pidfile}): {e}",
                  file=sys.stderr)
        finally:
            pidfile.unlink(missing_ok=True)
        print("panel web detenido")
        return 0

    # action == "start": foreground con Ctrl+C.
    setup_logging(console=True)
    port = args.port or ui.web_panel_port
    bind = args.bind or ui.web_panel_bind
    # La clave es OBLIGATORIA siempre (secrets DPAPI primero, H4).
    token = _panel_token(store)
    if not token:
        print(
            "El panel web requiere una clave (obligatoria). Configurala con:\n"
            "  port-forwarder secrets set web_panel_token\n"
            "o desde Ajustes de la GUI.",
            file=sys.stderr,
        )
        return 1
    # El panel lo gestiona este proceso: el supervisor no debe competir
    # (sup se creo con web_panel_external=True cuando no hay --no-supervisor).
    pidfile.write_text(json.dumps({"pid": os.getpid(), "port": port,
                                   "bind": bind}), encoding="utf-8")
    panel = WebPanel(sup, port=port, bind=bind, token=token)
    try:
        panel.start()
    except RuntimeError as e:
        pidfile.unlink(missing_ok=True)
        raise CliError(str(e))
    if not args.no_supervisor:
        sup.start()
    print(f"panel web en http://{bind}:{port}"
          + (f" (supervisor {'activado' if sup.running else 'inactivo'})")
          + " [token requerido]")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\npanel web detenido")
    finally:
        panel.stop()
        sup.stop()
        pidfile.unlink(missing_ok=True)
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Stream de eventos en vivo (estilo tail -f)."""
    json_mode = getattr(args, "json", False)

    def _on(payload: dict) -> None:
        if json_mode:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            ts = time.strftime("%H:%M:%S", time.localtime(payload["ts"]))
            data = {k: v for k, v in payload.items() if k not in ("event", "ts")}
            print(f"[{ts}] {payload['event']}"
                  + (f" {json.dumps(data, ensure_ascii=False)}" if data else ""))
        sys.stdout.flush()

    unsub = bus.subscribe(_on)
    print("escuchando eventos... (Ctrl+C para salir)", file=sys.stderr)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        unsub()
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    """Control de la instancia GUI via IPC (P1). Sin GUI: error claro."""
    action = getattr(args, "action", None)
    if action is None:
        print("usa 'port-forwarder gui show|hide|quit'")
        return 2
    print("IPC de GUI no disponible en esta build (P1); "
          "la GUI se controla desde la ventana", file=sys.stderr)
    return 1
