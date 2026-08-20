"""Comandos CLI de tunnels (T1-T6, T10). Mismos providers que la GUI."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace

from src.cli.cli import CliError, _json_out
from src.core.config import Bind, ConfigStore, Tunnel, TunnelHealthGate
from src.core.metrics_store import MetricsStore
from src.providers.ssh_tunnel_provider import SshTunnelError, SshTunnelProvider


def _ctx(args: argparse.Namespace):
    store = ConfigStore()
    ssh = SshTunnelProvider(ssh_exe=store.cfg.windows.ssh_exe or None,
                            autossh_exe=store.cfg.windows.autossh_exe or None)
    metrics = MetricsStore()
    return store, ssh, metrics


def _parse_bind(text: str, what: str) -> Bind:
    try:
        host, port = text.rsplit(":", 1)
    except ValueError:
        raise CliError(f"{what} debe ser host:puerto (ej. 0.0.0.0:80)")
    try:
        port = int(port)
    except ValueError:
        raise CliError(f"{what}: puerto invalido '{port}'")
    return Bind(host=host, port=port)


def dispatch(args: argparse.Namespace) -> int:
    action = args.action
    if action is None:
        print("usa 'port-forwarder tunnels --help'")
        return 2
    store, ssh, metrics = _ctx(args)
    if action == "list":
        return _list(store, ssh, args)
    if action == "add":
        return _add(store, args)
    if action == "remove":
        return _remove(store, ssh, args)
    if action == "start":
        return _start(store, ssh, args)
    if action == "stop":
        return _stop(store, ssh, args)
    if action == "restart":
        return _restart(store, ssh, args)
    if action == "start-all":
        return _start_all(store, ssh)
    if action == "stop-all":
        return _stop_all(store, ssh, args)
    if action == "status":
        return _status(store, ssh, args)
    if action == "latency":
        return _latency(store, ssh, args)
    if action == "clone":
        return _clone(store, args)
    print(f"accion desconocida: {action}", file=sys.stderr)
    return 2


def _list(store: ConfigStore, ssh: SshTunnelProvider,
          args: argparse.Namespace) -> int:
    rows = []
    for t in store.cfg.tunnels:
        rows.append({
            "id": t.id,
            "type": t.type,
            "vps_id": t.vps_id,
            "local": t.ssh_dest,
            "remote": [f"{b.host}:{b.port}" for b in t.remote_binds],
            "auto_start": t.auto_start,
            "state": "running" if ssh.is_alive(t) else "stopped",
        })
    if getattr(args, "json", False):
        _json_out(rows)
    else:
        for r in rows:
            print(f"{r['id']:<20} {r['type']:<10} {r['vps_id']:<12} "
                  f"{r['local']:<16} -> {', '.join(r['remote']):<20} "
                  f"{r['state']}")
    return 0


def _add(store: ConfigStore, args: argparse.Namespace) -> int:
    if args.type == "ssh":
        if not args.vps or not args.local or not args.remote:
            raise CliError(
                "tunnel ssh requiere --vps, --local y --remote (host:puerto)"
            )
        local = _parse_bind(args.local, "--local")
        remotes = [_parse_bind(r, "--remote") for r in args.remote]
        tun = Tunnel(
            id=args.id,
            vps_id=args.vps,
            local_bind=local,
            remote_binds=remotes,
            keepalive_interval=args.keepalive_interval,
            keepalive_count=args.keepalive_count,
            auto_start=not args.no_auto_start,
            health_gate=TunnelHealthGate(enabled=not args.no_health_gate),
            jump=args.jump,
        )
        store.add_tunnel(tun)
        desc = f"{local.host}:{local.port} -> " \
               f"{', '.join(f'{b.host}:{b.port}' for b in remotes)} via {args.vps}"
    else:
        # tailscale / cloudflare (T7/T8, P2)
        tun = Tunnel(
            id=args.id,
            type=args.type,
            local_url=args.local_url,
            funnel=args.funnel,
            auto_start=not args.no_auto_start,
            health_gate=TunnelHealthGate(enabled=False),
        )
        store.add_tunnel(tun)
        kind = "funnel" if (args.type == "tailscale" and args.funnel) else args.type
        desc = f"{kind} -> {args.local_url or '(URL por defecto)'}"
    print(f"tunnel '{tun.id}' agregado ({desc})")
    return 0


def _remove(store: ConfigStore, ssh: SshTunnelProvider,
            args: argparse.Namespace) -> int:
    tun = store.get_tunnel(args.id)
    if not tun:
        raise CliError(f"tunnel '{args.id}' no existe")
    if ssh.is_alive(tun):
        ssh.stop(tun)
    store.remove_tunnel(args.id)
    print(f"tunnel '{args.id}' eliminado (y detenido)")
    return 0


def _start(store: ConfigStore, ssh: SshTunnelProvider,
           args: argparse.Namespace) -> int:
    tun = store.get_tunnel(args.id)
    if not tun:
        raise CliError(f"tunnel '{args.id}' no existe")
    vps = store.get_vps(tun.vps_id)
    if ssh.is_alive(tun):
        print(f"tunnel '{args.id}' ya esta corriendo")
        return 0
    try:
        ssh.start(tun, vps)
    except SshTunnelError as e:
        raise CliError(str(e))
    print(f"tunnel '{args.id}' iniciado (pid {ssh._procs[args.id].pid})")
    return 0


def _stop(store: ConfigStore, ssh: SshTunnelProvider,
          args: argparse.Namespace) -> int:
    tun = store.get_tunnel(args.id)
    if not tun:
        raise CliError(f"tunnel '{args.id}' no existe")
    ssh.stop(tun)
    print(f"tunnel '{args.id}' detenido")
    return 0


def _restart(store: ConfigStore, ssh: SshTunnelProvider,
             args: argparse.Namespace) -> int:
    tun = store.get_tunnel(args.id)
    if not tun:
        raise CliError(f"tunnel '{args.id}' no existe")
    vps = store.get_vps(tun.vps_id)
    ssh.restart(tun, vps)
    print(f"tunnel '{args.id}' reiniciado")
    return 0


def _start_all(store: ConfigStore, ssh: SshTunnelProvider) -> int:
    for t in store.cfg.tunnels:
        if not t.auto_start or t.type != "ssh":
            continue
        if ssh.is_alive(t):
            continue
        vps = store.get_vps(t.vps_id)
        try:
            ssh.start(t, vps)
            print(f"{t.id}: iniciado")
        except SshTunnelError as e:
            print(f"{t.id}: FALLO {e}", file=sys.stderr)
    return 0


def _stop_all(store: ConfigStore, ssh: SshTunnelProvider,
              args: argparse.Namespace) -> int:
    if not getattr(args, "yes", False):
        raise CliError("confirma con --yes (destructivo)")
    for t in store.cfg.tunnels:
        if ssh.is_alive(t):
            ssh.stop(t)
            print(f"{t.id}: detenido")
    return 0


def _status(store: ConfigStore, ssh: SshTunnelProvider,
            args: argparse.Namespace) -> int:
    tun = store.get_tunnel(args.id)
    if not tun:
        raise CliError(f"tunnel '{args.id}' no existe")
    alive = ssh.is_alive(tun)
    data = {
        "id": tun.id,
        "type": tun.type,
        "vps_id": tun.vps_id,
        "local": tun.ssh_dest,
        "remote": [f"{b.host}:{b.port}" for b in tun.remote_binds],
        "alive": alive,
        "state": "running" if alive else "stopped",
    }
    if getattr(args, "json", False):
        _json_out(data)
    else:
        print(f"tunnel {tun.id}: {'CORRIENDO' if alive else 'detenido'}")
        print(f"  vps:   {tun.vps_id}  local: {tun.ssh_dest}")
        print(f"  bind:  {', '.join(data['remote'])}")
    return 0 if alive else 1


def _latency(store: ConfigStore, ssh: SshTunnelProvider,
             args: argparse.Namespace) -> int:
    tun = store.get_tunnel(args.id)
    if not tun:
        raise CliError(f"tunnel '{args.id}' no existe")
    vps = store.get_vps(tun.vps_id)
    ms = ssh.latency(tun, vps)
    if ms is None:
        raise CliError(f"VPS {vps.host} inalcanzable")
    print(f"latencia a {vps.host}: {ms} ms")
    return 0


def _clone(store: ConfigStore, args: argparse.Namespace) -> int:
    src = store.get_tunnel(args.id)
    if not src:
        raise CliError(f"tunnel '{args.id}' no existe")
    new = replace(src, id=args.new_id)
    store.add_tunnel(new)
    print(f"tunnel clonado: '{args.id}' -> '{new.id}'")
    return 0
