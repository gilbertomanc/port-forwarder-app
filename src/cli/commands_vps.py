"""Comandos CLI de VPS (T3). Mismos providers que la GUI."""

from __future__ import annotations

import argparse

from src.cli.cli import CliError, _json_out
from src.core.config import ConfigStore, Vps


def dispatch(args: argparse.Namespace) -> int:
    action = args.action
    if action is None:
        print("usa 'port-forwarder vps --help'")
        return 2
    store = ConfigStore()
    if action == "list":
        rows = [
            {"id": v.id, "host": v.host, "user": v.user, "port": v.port,
             "identity_file": v.identity_file}
            for v in store.cfg.vps_list
        ]
        if getattr(args, "json", False):
            _json_out(rows)
        else:
            for r in rows:
                print(f"{r['id']:<14} {r['user']}@{r['host']}:{r['port']} "
                      f"id={r['identity_file'] or '-'}")
        return 0
    if action == "add":
        if store.get_vps(args.id):
            raise CliError(f"vps '{args.id}' ya existe")
        store.add_vps(Vps(
            id=args.id,
            host=args.host,
            user=args.user,
            port=args.port,
            identity_file=args.identity,
            password=args.password,
        ))
        print(f"vps '{args.id}' agregado ({args.user}@{args.host}:{args.port})")
        return 0
    if action == "remove":
        store.remove_vps(args.id)
        print(f"vps '{args.id}' eliminado")
        return 0
    print(f"accion desconocida: {action}")
    return 2
