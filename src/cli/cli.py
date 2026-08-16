"""Entrada del CLI: port-forwarder (seccion 19 del plan).

Diseno:
- argparse estandar (cero dependencias; decision fase 0).
- Salida humana por defecto; --json para scripting.
- Exit codes: 0 OK, 1 error funcional, 2 argumentos invalidos,
  3 config invalida.
- Los comandos invocan los MISMOS providers que la GUI (paridad).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from src import __version__
from src.core.config import ConfigError


class CliError(Exception):
    """Error funcional -> exit 1."""


class ConfigCliError(CliError):
    """Config invalida -> exit 3."""


def _json_out(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="salida JSON")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="port-forwarder",
        description="Port Forwarding Manager: forwards Windows-WSL y tunnels "
                    "hacia VPS. Paridad completa con la GUI.",
    )
    p.add_argument("--version", action="version",
                   version=f"port-forwarder {__version__}")
    sub = p.add_subparsers(dest="command", metavar="COMANDO")

    # -- status ---------------------------------------------------------------
    sp_ = sub.add_parser("status", help="estado global")
    add_json_flag(sp_)

    # -- forwards -------------------------------------------------------------
    fw = sub.add_parser("forwards", help="gestion de forwards Windows-WSL")
    fsub = fw.add_subparsers(dest="action", metavar="ACCION")

    f_list = fsub.add_parser("list", help="F1/F4: listar forwards")
    add_json_flag(f_list)

    f_add = fsub.add_parser("add", help="F1: agregar forward")
    f_add.add_argument("--id", required=True)
    f_add.add_argument("--listen-port", required=True)
    f_add.add_argument("--listen-address", default="0.0.0.0")
    f_add.add_argument("--distro", default="")
    f_add.add_argument("--wsl-port", required=True)
    f_add.add_argument("--proto", choices=["tcp", "udp"], default="tcp")
    f_add.add_argument("--auto-apply", action="store_true")
    f_add.add_argument("--no-health-check", action="store_true")

    f_rm = fsub.add_parser("remove", help="F1: eliminar forward de la config")
    f_rm.add_argument("id")

    f_apply = fsub.add_parser("apply", help="F2: aplicar forwards (netsh+firewall)")
    f_apply.add_argument("--all", action="store_true", help="aplicar todos los auto_apply")

    f_clear = fsub.add_parser("clear", help="F3: limpiar TODOS los portproxies")
    f_clear.add_argument("--yes", action="store_true", help="sin confirmacion")

    f_test = fsub.add_parser("test", help="F6: probar conexion TCP al forward")
    f_test.add_argument("id")

    f_conf = fsub.add_parser("conflicts", help="F5: detectar conflictos de puerto")
    f_conf.add_argument("port", type=int)

    f_clone = fsub.add_parser("clone", help="F14: clonar forward")
    f_clone.add_argument("id")
    f_clone.add_argument("--new-id", required=True)
    f_clone.add_argument("--listen-port", type=int)
    f_clone.add_argument("--wsl-port", type=int)

    # -- tunnels --------------------------------------------------------------
    tn = sub.add_parser("tunnels", help="gestion de tunnels hacia VPS")
    tsub = tn.add_subparsers(dest="action", metavar="ACCION")

    t_list = tsub.add_parser("list", help="T1: listar tunnels")
    add_json_flag(t_list)

    t_add = tsub.add_parser("add", help="T1/T4: agregar tunnel")
    t_add.add_argument("--id", required=True)
    t_add.add_argument("--type", choices=["ssh", "tailscale", "cloudflare"],
                       default="ssh")
    t_add.add_argument("--vps", default=None, help="solo ssh")
    t_add.add_argument("--local", default=None,
                       help="host:port del servicio local (solo ssh)")
    t_add.add_argument("--remote", action="append",
                       help="bind remoto host:port (solo ssh, repetible)")
    t_add.add_argument("--local-url", default="",
                       help="URL del servicio (tailscale/cloudflare)")
    t_add.add_argument("--funnel", action="store_true",
                       help="tailscale funnel (T7)")
    t_add.add_argument("--keepalive-interval", type=int, default=30)
    t_add.add_argument("--keepalive-count", type=int, default=3)
    t_add.add_argument("--no-auto-start", action="store_true")
    t_add.add_argument("--no-health-gate", action="store_true")
    t_add.add_argument("--jump", default=None, help="VPS intermedio (T10)")

    t_rm = tsub.add_parser("remove", help="T1: eliminar tunnel de la config")
    t_rm.add_argument("id")

    t_start = tsub.add_parser("start", help="T1: iniciar tunnel")
    t_start.add_argument("id")
    t_stop = tsub.add_parser("stop", help="T2: detener tunnel")
    t_stop.add_argument("id")
    t_restart = tsub.add_parser("restart", help="T2: reiniciar tunnel")
    t_restart.add_argument("id")
    t_sa = tsub.add_parser("start-all", help="T1: iniciar todos los auto_start")
    t_so = tsub.add_parser("stop-all", help="T2: detener todos")
    t_so.add_argument("--yes", action="store_true")
    t_stat = tsub.add_parser("status", help="T1: estado de un tunnel")
    t_stat.add_argument("id")
    add_json_flag(t_stat)
    t_lat = tsub.add_parser("latency", help="T6 (P2): latencia al VPS")
    t_lat.add_argument("id")

    t_clone = tsub.add_parser("clone", help="F14/T: clonar tunnel")
    t_clone.add_argument("id")
    t_clone.add_argument("--new-id", required=True)

    # -- vps ------------------------------------------------------------------
    vp = sub.add_parser("vps", help="T3: gestion de VPS")
    vsub = vp.add_subparsers(dest="action", metavar="ACCION")
    v_list = vsub.add_parser("list", help="listar VPS")
    add_json_flag(v_list)
    v_add = vsub.add_parser("add", help="agregar VPS")
    v_add.add_argument("--id", required=True)
    v_add.add_argument("--host", required=True)
    v_add.add_argument("--user", required=True)
    v_add.add_argument("--port", type=int, default=22)
    v_add.add_argument("--identity", default="")
    v_add.add_argument("--password", default="",
                       help="contrasena SSH (alternativa a --identity)")
    v_rm = vsub.add_parser("remove", help="eliminar VPS")
    v_rm.add_argument("id")

    # -- portmap --------------------------------------------------------------
    pm = sub.add_parser("portmap", help="M6: mapa de puertos real vs config")
    add_json_flag(pm)

    # -- health / alerts ------------------------------------------------------
    h = sub.add_parser("health", help="M3: health checks")
    hsub = h.add_subparsers(dest="action", metavar="ACCION")
    h_check = hsub.add_parser("check", help="ejecutar health checks")
    add_json_flag(h_check)

    al = sub.add_parser("alerts", help="M4: centro de alertas")
    asub = al.add_subparsers(dest="action", metavar="ACCION")
    a_list = asub.add_parser("list", help="listar alertas")
    a_list.add_argument("--state", choices=["open", "resolved"], default=None)
    add_json_flag(a_list)
    a_res = asub.add_parser("resolve", help="resolver alerta")
    a_res.add_argument("id", type=int)

    ath = sub.add_parser("alert", help="umbrales de alertas")
    athsub = ath.add_subparsers(dest="action", metavar="ACCION")
    ath_get = athsub.add_parser("thresholds", help="get/set")
    ath_get.add_argument("get", nargs="?", default="get")
    ath_set = athsub.add_parser("set", help="set")
    ath_set.add_argument("--tunnel-down-minutes", type=int)
    ath_set.add_argument("--forward-fail-count", type=int)
    ath_set.add_argument("--vps-latency-ms", type=int)
    ath_set.add_argument("--check-interval-seconds", type=int)

    # -- schedule / profiles ---------------------------------------------------
    sch = sub.add_parser("schedule", help="A3: tareas programadas")
    ssub = sch.add_subparsers(dest="action", metavar="ACCION")
    s_list = ssub.add_parser("list", help="listar")
    add_json_flag(s_list)
    s_add = ssub.add_parser("add", help="agregar")
    s_add.add_argument("--name", required=True)
    s_add.add_argument("--type", required=True,
                       choices=["tunnel_start", "tunnel_stop",
                                "forwards_apply", "forwards_clear",
                                "apply_profile", "snapshot_state"])
    s_add.add_argument("--tunnel", default=None)
    s_add.add_argument("--profile", default=None)
    s_add.add_argument("--time", required=True, help="HH:MM")
    s_add.add_argument("--days", default="",
                       help="mon,tue,wed,thu,fri,sat,sun")
    s_rm = ssub.add_parser("remove", help="eliminar")
    s_rm.add_argument("id")

    pr = sub.add_parser("profile", help="A2: perfiles de exposicion")
    prsub = pr.add_subparsers(dest="action", metavar="ACCION")
    p_list = prsub.add_parser("list", help="listar")
    add_json_flag(p_list)
    p_apply = prsub.add_parser("apply", help="aplicar")
    p_apply.add_argument("name")
    p_cap = prsub.add_parser("capture", help="capturar estado actual")
    p_cap.add_argument("name")
    p_cap.add_argument("--desc", default="")

    # -- secrets / config ------------------------------------------------------
    sec = sub.add_parser("secrets", help="13.1: secrets (nunca se imprimen)")
    secsub = sec.add_subparsers(dest="action", metavar="ACCION")
    s_set = secsub.add_parser("set", help="guardar (valor por stdin)")
    s_set.add_argument("ref")
    s_check = secsub.add_parser("check", help="verificar existencia")
    s_check.add_argument("ref")

    cf = sub.add_parser("config", help="U5: gestion de config")
    cfsub = cf.add_subparsers(dest="action", metavar="ACCION")
    c_val = cfsub.add_parser("validate", help="validar config.json")
    c_exp = cfsub.add_parser("export", help="exportar config")
    c_exp.add_argument("path")
    c_imp = cfsub.add_parser("import", help="importar config")
    c_imp.add_argument("path")

    # -- diagnostico ------------------------------------------------------------
    sub.add_parser("doctor", help="U8: detector de problemas del entorno")
    sub.add_parser("diag", help="U7: bundle de diagnostico")

    dr = sub.add_parser("drift", help="F13: drift check + reconcile")
    drsub = dr.add_subparsers(dest="action", metavar="ACCION")
    dr_check = drsub.add_parser("check", help="comparar config vs realidad")
    add_json_flag(dr_check)
    dr_rec = drsub.add_parser("reconcile", help="reconciliar (aplica lo que falta)")
    dr_rec.add_argument("--cleanup", action="store_true",
                        help="ademas limpiar reglas no declaradas")
    dr_rec.add_argument("--yes", action="store_true")

    mt = sub.add_parser("maintenance", help="F15/A8: modo mantenimiento")
    mtsub = mt.add_subparsers(dest="action", metavar="ACCION")
    mtsub.add_parser("on", help="pausar todo")
    mtsub.add_parser("off", help="reanudar todo")
    mt_stat = mtsub.add_parser("status", help="estado")
    add_json_flag(mt_stat)
    mt_sch = mtsub.add_parser("schedule", help="ventana horaria")
    mt_sch.add_argument("--start", required=True, help="HH:MM")
    mt_sch.add_argument("--end", required=True, help="HH:MM")

    conn = sub.add_parser("connections", help="F16/M10: conexiones activas")
    conn.add_argument("forward_id")
    add_json_flag(conn)

    wh = sub.add_parser("webhooks", help="M11: webhooks de eventos")
    whsub = wh.add_subparsers(dest="action", metavar="ACCION")
    wh_list = whsub.add_parser("list", help="listar webhooks")
    add_json_flag(wh_list)
    wh_add = whsub.add_parser("add", help="agregar webhook")
    wh_add.add_argument("--url", required=True)
    wh_add.add_argument("--events", required=True,
                        help="lista separada por comas")
    wh_add.add_argument("--secret", default=None, help="ref a secrets")
    wh_rm = whsub.add_parser("remove", help="eliminar webhook")
    wh_rm.add_argument("id")

    sub.add_parser("supervise", help="correr el supervisor en foreground")
    sub.add_parser("watch", help="stream de eventos en vivo")
    we = sub.add_parser("web", help="panel web local (seccion 10.5)")
    wesub = we.add_subparsers(dest="action", metavar="ACCION")
    we_start = wesub.add_parser("start", help="iniciar panel + supervisor")
    we_start.add_argument("--port", type=int, default=None)
    we_start.add_argument("--bind", default=None)
    we_start.add_argument("--no-supervisor", action="store_true",
                          help="no arrancar el supervisor (solo servidor)")
    we_stop = wesub.add_parser("stop", help="detener panel iniciado con 'start'")
    we_stat = wesub.add_parser("status", help="estado del panel")
    add_json_flag(we_stat)

    # -- API REST (21) ------------------------------------------------------------
    ap = sub.add_parser("api", help="gestion de la API REST (21)")
    apsub = ap.add_subparsers(dest="action", metavar="ACCION")
    ap_en = apsub.add_parser("enable", help="habilitar API (token obligatorio)")
    ap_en.add_argument("--port", type=int, default=None)
    apsub.add_parser("disable", help="deshabilitar API")
    ap_stat = apsub.add_parser("status", help="estado")
    add_json_flag(ap_stat)
    ap_serve = apsub.add_parser("serve", help="correr la API en foreground")
    ap_serve.add_argument("--port", type=int, default=None)
    ap_tok = apsub.add_parser("tokens", help="gestion de tokens")
    apsub_tok = ap_tok.add_subparsers(dest="taction", metavar="ACCION")
    tok_create = apsub_tok.add_parser("create", help="crear token (se muestra 1 vez)")
    tok_create.add_argument("--scope", required=True,
                            choices=["read", "write", "admin"])
    tok_create.add_argument("--expires", default=None,
                            help="duracion, ej. 30d")
    tok_list = apsub_tok.add_parser("list", help="listar tokens")
    add_json_flag(tok_list)
    tok_revoke = apsub_tok.add_parser("revoke", help="revocar token")
    tok_revoke.add_argument("id")

    # -- MCP (21.4) ------------------------------------------------------------------
    mc = sub.add_parser("mcp", help="servidor MCP para agentes LLM (21.4)")
    mcsub = mc.add_subparsers(dest="action", metavar="ACCION")
    mcsub.add_parser("serve", help="servidor stdio (para agentes)")
    mcsub.add_parser("test", help="self-test del handshake MCP")

    gu = sub.add_parser("gui", help="control de la instancia GUI (P1, IPC)")
    gusub = gu.add_subparsers(dest="action", metavar="ACCION")
    gusub.add_parser("show", help="mostrar ventana")
    gusub.add_parser("hide", help="ocultar ventana")
    gusub.add_parser("quit", help="cerrar la GUI")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        code = dispatch(args)
    except ConfigError as e:
        print(f"error de config: {e}", file=sys.stderr)
        return 3
    except ConfigCliError as e:
        print(f"error de config: {e}", file=sys.stderr)
        return 3
    except CliError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return code if code is not None else 0


def dispatch(args: argparse.Namespace) -> int:
    """Ruta los subcomandos a los handlers. Cada handler vive en
    commands_*.py y usa los mismos providers que la GUI."""
    from src.cli import commands_forwards, commands_monitor, commands_schedule, \
        commands_tunnels, commands_ux, commands_vps

    cmd = args.command
    if cmd is None:
        print("usa --help para ver los comandos")
        return 2
    if cmd == "status":
        return commands_ux.cmd_status(args)
    if cmd == "forwards":
        return commands_forwards.dispatch(args)
    if cmd == "tunnels":
        return commands_tunnels.dispatch(args)
    if cmd == "vps":
        return commands_vps.dispatch(args)
    if cmd == "portmap":
        return commands_monitor.cmd_portmap(args)
    if cmd == "health":
        return commands_monitor.cmd_health(args)
    if cmd == "alerts":
        return commands_monitor.cmd_alerts(args)
    if cmd == "alert":
        return commands_monitor.cmd_alert_thresholds(args)
    if cmd == "schedule":
        return commands_schedule.cmd_schedule(args)
    if cmd == "profile":
        return commands_schedule.cmd_profile(args)
    if cmd == "secrets":
        return commands_ux.cmd_secrets(args)
    if cmd == "config":
        return commands_ux.cmd_config(args)
    if cmd == "doctor":
        return commands_ux.cmd_doctor(args)
    if cmd == "diag":
        return commands_ux.cmd_diag(args)
    if cmd == "drift":
        return commands_ux.cmd_drift(args)
    if cmd == "maintenance":
        return commands_ux.cmd_maintenance(args)
    if cmd == "connections":
        return commands_ux.cmd_connections(args)
    if cmd == "webhooks":
        return commands_ux.cmd_webhooks(args)
    if cmd == "supervise":
        return commands_ux.cmd_supervise(args)
    if cmd == "watch":
        return commands_ux.cmd_watch(args)
    if cmd == "web":
        return commands_ux.cmd_web(args)
    if cmd == "api":
        from src.cli import commands_api

        return commands_api.cmd_api(args)
    if cmd == "mcp":
        from src.cli import commands_api

        return commands_api.cmd_mcp(args)
    if cmd == "gui":
        return commands_ux.cmd_gui(args)
    print(f"comando desconocido: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
