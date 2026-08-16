"""Comandos CLI de monitor: portmap (M6), health (M3), alertas (M4),
umbrales y conexiones activas (F16/M10)."""

from __future__ import annotations

import argparse
import socket
import sys

from src.cli.cli import CliError, _json_out
from src.core.config import ConfigStore
from src.core.metrics_store import MetricsStore
from src.providers.netsh_provider import NetshProvider
from src.utils import subprocess_async as sp


def _ctx(args: argparse.Namespace):
    store = ConfigStore()
    netsh = NetshProvider(netsh_exe=store.cfg.windows.netsh_exe or None)
    metrics = MetricsStore()
    return store, netsh, metrics


def cmd_portmap(args: argparse.Namespace) -> int:
    store, netsh, metrics = _ctx(args)
    entries = netsh.declared_forwards(store.cfg.forwards)
    rows = [e.as_dict() for e in entries]
    if getattr(args, "json", False):
        _json_out(rows)
    else:
        for e in entries:
            print(f":{e.listen_port:<6} -> :{e.wsl_port:<6} "
                  f"{e.state:<8} {e.forward_id or '(no declarado)'}")
    return 0


def cmd_health(args: argparse.Namespace) -> int:
    """Health check (M3): forwards funcionales + tunnels vivos + VPS."""
    store, netsh, metrics = _ctx(args)
    from src.providers.ssh_tunnel_provider import SshTunnelProvider

    ssh = SshTunnelProvider(ssh_exe=store.cfg.windows.ssh_exe or None)
    data: dict = {"forwards": [], "tunnels": [], "vps": []}

    for f in store.cfg.forwards:
        ok = netsh.test_connection(f.listen_port, timeout=2.0)
        data["forwards"].append({
            "id": f.id, "listen_port": f.listen_port,
            "reachable": ok, "state": "ok" if ok else "down",
        })
    for t in store.cfg.tunnels:
        alive = ssh.is_alive(t)
        data["tunnels"].append({
            "id": t.id, "alive": alive, "state": "running" if alive else "down",
        })
        vps = store.get_vps(t.vps_id)
        if vps:
            ms = ssh.latency(t, vps)
            data["vps"].append({
                "id": vps.id, "host": vps.host,
                "latency_ms": ms, "reachable": ms is not None,
            })

    if getattr(args, "json", False):
        _json_out(data)
    else:
        for f in data["forwards"]:
            print(f"forward {f['id']:<16} :{f['listen_port']:<6} "
                  f"{'OK' if f['reachable'] else 'DOWN'}")
        for t in data["tunnels"]:
            print(f"tunnel  {t['id']:<16} {'OK' if t['alive'] else 'DOWN'}")
        for v in data["vps"]:
            lat = f"{v['latency_ms']} ms" if v["latency_ms"] else "N/A"
            print(f"vps     {v['id']:<16} {lat}")
    unhealthy = [f for f in data["forwards"] if not f["reachable"]] + \
                [t for t in data["tunnels"] if not t["alive"]]
    return 1 if unhealthy else 0


def cmd_alerts(args: argparse.Namespace) -> int:
    store, netsh, metrics = _ctx(args)
    action = args.action
    if action == "list":
        rows = metrics.list_alerts(state=getattr(args, "state", None))
        if getattr(args, "json", False):
            _json_out(rows)
        else:
            for r in rows:
                print(f"#{r['id']:<4} {r['ts']:.0f} {r['severity']:<8} "
                      f"[{r['state']}] {r['message']}")
        return 0
    if action == "resolve":
        if not metrics.resolve_alert(args.id):
            raise CliError(f"alerta #{args.id} no existe")
        print(f"alerta #{args.id} resuelta")
        return 0
    print(f"accion desconocida: {action}")
    return 2


def cmd_alert_thresholds(args: argparse.Namespace) -> int:
    store, netsh, metrics = _ctx(args)
    a = store.cfg.alerts
    if args.action == "set":
        changed = False
        if args.tunnel_down_minutes is not None:
            a.tunnel_down_minutes = args.tunnel_down_minutes
            changed = True
        if args.forward_fail_count is not None:
            a.forward_fail_count = args.forward_fail_count
            changed = True
        if args.vps_latency_ms is not None:
            a.vps_latency_ms = args.vps_latency_ms
            changed = True
        if args.check_interval_seconds is not None:
            a.check_interval_seconds = args.check_interval_seconds
            changed = True
        if changed:
            store.save()
            print("umbrales actualizados")
        else:
            print("nada que cambiar")
        return 0
    # get (default)
    print(f"tunnel_down_minutes={a.tunnel_down_minutes}")
    print(f"forward_fail_count={a.forward_fail_count}")
    print(f"vps_latency_ms={a.vps_latency_ms}")
    print(f"check_interval_seconds={a.check_interval_seconds}")
    return 0


def cmd_connections(args: argparse.Namespace) -> int:
    """F16/M10: conexiones activas hacia el puerto del forward."""
    store, netsh, metrics = _ctx(args)
    fwd = store.get_forward(args.forward_id)
    if not fwd:
        raise CliError(f"forward '{args.forward_id}' no existe")
    try:
        proc = sp.run(["netstat", "-ano", "-p", "TCP"],
                      timeout=20.0, check=False)
    except OSError:
        raise CliError("netstat no disponible")
    rows = []
    for line in proc.stdout.splitlines():
        if f":{fwd.listen_port} " not in line:
            continue
        if "ESTABLISHED" not in line and "LISTENING" not in line:
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        rows.append({
            "local": parts[1],
            "remote": parts[2],
            "state": parts[3],
            "pid": parts[-1] if len(parts) > 4 else "",
        })
    if getattr(args, "json", False):
        _json_out(rows)
    else:
        for r in rows:
            print(f"{r['local']:<24} {r['remote']:<24} {r['state']:<12} pid={r['pid']}")
    return 0
