"""Comandos CLI de schedule (A3) y perfiles (A2)."""

from __future__ import annotations

import argparse
import uuid

from src.cli.cli import CliError, _json_out
from src.core.config import ConfigStore, ScheduleAction, ScheduleItem
from src.core.metrics_store import MetricsStore
from src.core.profiles import Profiles
from src.core.scheduler import Scheduler, WEEKDAYS
from src.core.supervisor import Supervisor


def _ctx(args: argparse.Namespace):
    store = ConfigStore()
    sup = Supervisor(store)
    return store, sup


def cmd_schedule(args: argparse.Namespace) -> int:
    store, sup = _ctx(args)
    action = args.action
    if action == "list":
        rows = [
            {"id": s.id, "name": s.name, "type": s.action.type,
             "time": (s.schedule or {}).get("time"),
             "days": (s.schedule or {}).get("days"),
             "enabled": s.enabled}
            for s in store.cfg.scheduler
        ]
        if getattr(args, "json", False):
            _json_out(rows)
        else:
            for r in rows:
                print(f"{r['id']:<10} {r['name']:<24} {r['type']:<16} "
                      f"{r['time']} {','.join(r['days'] or []):<20} "
                      f"{'on' if r['enabled'] else 'off'}")
        return 0
    if action == "add":
        days = [d.strip() for d in args.days.split(",") if d.strip()]
        bad = [d for d in days if d not in WEEKDAYS]
        if bad:
            raise CliError(f"dias invalidos: {bad} (usa {','.join(WEEKDAYS)})")
        item = ScheduleItem(
            id=f"tarea-{uuid.uuid4().hex[:8]}",
            name=args.name,
            action=ScheduleAction(type=args.type, tunnel=args.tunnel,
                                  profile=args.profile),
            schedule={"days": days, "time": args.time},
        )
        store.cfg.scheduler.append(item)
        store.save()
        print(f"tarea '{item.name}' programada (id={item.id}, "
              f"{args.time} {','.join(days) or 'todos los dias'})")
        return 0
    if action == "remove":
        before = len(store.cfg.scheduler)
        store.cfg.scheduler = [s for s in store.cfg.scheduler
                               if s.id != args.id]
        if len(store.cfg.scheduler) == before:
            raise CliError(f"tarea '{args.id}' no existe")
        store.save()
        print(f"tarea '{args.id}' eliminada")
        return 0
    print(f"accion desconocida: {action}")
    return 2


def cmd_profile(args: argparse.Namespace) -> int:
    store, sup = _ctx(args)
    profiles = Profiles(store, sup)
    action = args.action
    if action == "list":
        rows = [{"name": p.name, "description": p.description,
                 "forwards": p.forwards, "tunnels": p.tunnels}
                for p in profiles.list()]
        if getattr(args, "json", False):
            _json_out(rows)
        else:
            for r in rows:
                print(f"{r['name']:<12} {r['description']:<28} "
                      f"fwd={len(r['forwards'])} tun={len(r['tunnels'])}")
        return 0
    if action == "apply":
        try:
            profiles.apply(args.name)
        except ValueError as e:
            raise CliError(str(e))
        print(f"perfil '{args.name}' aplicado")
        return 0
    if action == "capture":
        p = profiles.capture(args.name, args.desc)
        print(f"perfil '{p.name}' capturado "
              f"({len(p.forwards)} forwards, {len(p.tunnels)} tunnels)")
        return 0
    print(f"accion desconocida: {action}")
    return 2
