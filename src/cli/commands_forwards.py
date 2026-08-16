"""Comandos CLI de forwards (F1-F8, F14). Mismos providers que la GUI."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace

from src.cli.cli import CliError, _json_out
from src.core.config import ConfigStore, Forward, HealthCheck
from src.core.metrics_store import MetricsStore
from src.providers.netsh_provider import NetshProvider
from src.providers.wsl_ip_provider import WslIpProvider


def _ctx(args: argparse.Namespace):
    store = ConfigStore()
    netsh = NetshProvider(netsh_exe=store.cfg.windows.netsh_exe or None)
    wsl = WslIpProvider(wsl_exe=store.cfg.windows.wsl_exe or None)
    metrics = MetricsStore()
    return store, netsh, wsl, metrics


def dispatch(args: argparse.Namespace) -> int:
    action = args.action
    if action is None:
        print("usa 'port-forwarder forwards --help'")
        return 2
    store, netsh, wsl, metrics = _ctx(args)
    if action == "list":
        return _list(store, netsh, args)
    if action == "add":
        return _add(store, netsh, wsl, args)
    if action == "remove":
        return _remove(store, netsh, args)
    if action == "apply":
        return _apply(store, netsh, wsl, args)
    if action == "clear":
        return _clear(store, netsh, args)
    if action == "test":
        return _test(store, netsh, args)
    if action == "conflicts":
        return _conflicts(netsh, args)
    if action == "clone":
        return _clone(store, args)
    print(f"accion desconocida: {action}", file=sys.stderr)
    return 2


def _list(store: ConfigStore, netsh: NetshProvider,
          args: argparse.Namespace) -> int:
    rows = []
    for entry in netsh.declared_forwards(store.cfg.forwards):
        rows.append({
            "id": entry.forward_id,
            "listen_port": entry.listen_port,
            "wsl_port": entry.connect_port,
            "state": entry.state,
            "declared": entry.declared,
        })
    if getattr(args, "json", False):
        _json_out(rows)
    else:
        for r in rows:
            print(f"{str(r['id']):<20} :{r['listen_port']:<6} "
                  f"-> :{r['wsl_port']:<6} {r['state']}")
    return 0


def _add(store: ConfigStore, netsh: NetshProvider, wsl: WslIpProvider,
         args: argparse.Namespace) -> int:
    try:
        listen_port = int(args.listen_port)
        wsl_port = int(args.wsl_port)
    except ValueError as e:
        raise CliError("listen-port y wsl-port deben ser numeros") from e
    if not (0 < listen_port < 65536) or not (0 < wsl_port < 65536):
        raise CliError("puertos fuera de rango 1-65535")

    conflicts = netsh.detect_conflicts(listen_port)
    if conflicts:
        raise CliError(
            f"puerto {listen_port} en uso por PIDs {conflicts}. "
            "deten el servicio o usa otro puerto (F5)"
        )
    fwd = Forward(
        id=args.id,
        listen_port=listen_port,
        listen_address=args.listen_address,
        wsl_distro=args.distro,
        wsl_port=wsl_port,
        protocol=args.proto,
        auto_apply=args.auto_apply,
        health_check=HealthCheck(enabled=not args.no_health_check),
    )

    # Con --auto-apply, todo se valida ANTES de tocar la config: si algo
    # falla, no queda un forward huerfano en config.json.
    ip = None
    if args.auto_apply:
        if not args.distro:
            raise CliError("--distro es obligatorio con --auto-apply")
        ip = wsl.get_ip(args.distro)
        if not ip:
            raise CliError(
                f"no se encontro IP para la distro '{args.distro}' "
                "(verifica el nombre con 'wsl -l')"
            )
    store.add_forward(fwd)

    if args.auto_apply:
        result = netsh.add_forward(fwd, ip)
        if not result.ok:
            store.remove_forward(fwd.id)
            raise CliError(f"aplicacion fallo: {result.error}")
    applied = f" [aplicado ip {ip}]" if ip else " [no aplicado]"
    print(f"forward '{fwd.id}' agregado (listen :{listen_port} -> "
          f"{args.distro}:{wsl_port}){applied}")
    return 0


def _remove(store: ConfigStore, netsh: NetshProvider,
            args: argparse.Namespace) -> int:
    fwd = store.remove_forward(args.id)
    print(f"forward '{fwd.id}' eliminado de la config")
    return 0


def _apply(store: ConfigStore, netsh: NetshProvider, wsl: WslIpProvider,
           args: argparse.Namespace) -> int:
    targets = [f for f in store.cfg.forwards if args.all or f.auto_apply]
    if not targets:
        print("no hay forwards para aplicar (usa --all para todos)")
        return 0
    ips = wsl.get_all_ips(list({f.wsl_distro for f in targets if f.wsl_distro}))
    results = []
    for f in targets:
        ip = ips.get(f.wsl_distro)
        if not ip:
            results.append((f.id, False, "distro sin IP"))
            continue
        present = [x for x in netsh.list_forwards()
                   if x.listen_port == f.listen_port]
        if present:
            netsh.remove_forward(f)
        r = netsh.add_forward(f, ip)
        results.append((f.id, r.ok, r.error or "ok"))
    failed = [r for r in results if not r[1]]
    for fid, ok, msg in results:
        print(f"{fid:<20} {'OK' if ok else 'FALLO':<6} {msg}")
    return 1 if failed else 0


def _clear(store: ConfigStore, netsh: NetshProvider,
           args: argparse.Namespace) -> int:
    if not getattr(args, "yes", False):
        raise CliError("confirma con --yes (destructivo)")
    results = netsh.clear_all()
    failed = [r for r in results if not r.ok and r.error]
    for r in results:
        if not r.ok and r.error:
            print(f"fallo: {r.error}", file=sys.stderr)
    print(f"limpieza completa ({len(results)} operaciones, "
          f"{len(failed)} fallos)")
    return 1 if failed else 0


def _test(store: ConfigStore, netsh: NetshProvider,
          args: argparse.Namespace) -> int:
    fwd = store.get_forward(args.id)
    if not fwd:
        raise CliError(f"forward '{args.id}' no existe")
    ok = netsh.test_connection(fwd.listen_port, timeout=3.0)
    print(f"forward {fwd.id} (:{fwd.listen_port}): " +
          ("conexion OK" if ok else "sin respuesta"))
    return 0 if ok else 1


def _conflicts(netsh: NetshProvider, args: argparse.Namespace) -> int:
    pids = netsh.detect_conflicts(args.port)
    if not pids:
        print(f"puerto {args.port} libre")
        return 0
    print(f"puerto {args.port} en uso por PIDs: {', '.join(map(str, pids))}")
    return 1


def _clone(store: ConfigStore, args: argparse.Namespace) -> int:
    src = store.get_forward(args.id)
    if not src:
        raise CliError(f"forward '{args.id}' no existe")
    new = replace(src, id=args.new_id)
    if args.listen_port:
        new.listen_port = args.listen_port
    if args.wsl_port:
        new.wsl_port = args.wsl_port
    store.add_forward(new)
    print(f"forward clonado: '{args.id}' -> '{new.id}' "
          f"(:{new.listen_port} -> :{new.wsl_port})")
    return 0
