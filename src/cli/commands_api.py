"""Comandos CLI de API REST y MCP (seccion 21.6 del plan)."""

from __future__ import annotations

import argparse
import sys
import time

from src.cli.cli import CliError, _json_out
from src.core.config import ConfigStore
from src.core.logger import setup_logging


def _parse_expires(text: str | None) -> int | None:
    if not text:
        return None
    t = text.strip().lower()
    if t.endswith("d"):
        return int(t[:-1])
    return int(t)


def cmd_api(args: argparse.Namespace) -> int:
    from src.api.auth import AuthService, SCOPES
    from src.api.server import ApiServer
    from src.api.service import AppService

    action = args.action
    store = ConfigStore()
    if action == "enable":
        port = getattr(args, "port", None) or store.cfg.api.port
        store.cfg.api.enabled = True
        store.cfg.api.port = port
        store.save()
        print(f"API REST habilitada en {store.cfg.api.host}:{port}/api/v1 "
              "(token obligatorio; crea uno con 'api tokens create')")
        return 0
    if action == "disable":
        store.cfg.api.enabled = False
        store.save()
        print("API REST deshabilitada")
        return 0
    if action == "status":
        from src.utils import path as paths

        data = {
            "enabled": store.cfg.api.enabled,
            "host": store.cfg.api.host,
            "port": store.cfg.api.port,
            "allowed_ips": store.cfg.api.allowed_ips,
            "rate_limit_per_minute": store.cfg.api.rate_limit_per_minute,
            "tokens": len(AuthService().list_tokens()),
            "running": (paths.data_dir() / "api.pid").exists(),
        }
        if getattr(args, "json", False):
            _json_out(data)
        else:
            state = "habilitada" if data["enabled"] else "deshabilitada"
            print(f"API REST {state} en {data['host']}:{data['port']}/api/v1 "
                  f"({data['tokens']} tokens)")
        return 0
    if action == "serve":
        if not store.cfg.api.enabled:
            raise CliError(
                "API deshabilitada en config. Usa 'api enable' primero."
            )
        setup_logging(console=True)
        import os
        import signal
        import time as _time

        from src.utils import path as paths

        service = AppService(store)
        service.supervisor.start()
        auth = AuthService()
        port = getattr(args, "port", None) or store.cfg.api.port
        server = ApiServer(service, auth, host=store.cfg.api.host,
                           port=port, allowed_ips=store.cfg.api.allowed_ips)
        pidfile = paths.data_dir() / "api.pid"
        pidfile.write_text(str(os.getpid()), encoding="utf-8")
        try:
            server.start()
        except RuntimeError as e:
            pidfile.unlink(missing_ok=True)
            raise CliError(str(e))
        print(f"API REST en http://{server.host}:{server.port}/api/v1 "
              f"(Ctrl+C para salir)")
        try:
            while True:
                _time.sleep(1)
        except KeyboardInterrupt:
            print("\nAPI detenida")
        finally:
            server.stop()
            service.supervisor.stop()
            pidfile.unlink(missing_ok=True)
        return 0
    if action == "tokens":
        taction = getattr(args, "taction", None)
        auth = AuthService()
        if taction == "create":
            tid, plain = auth.create_token(args.scope, _parse_expires(args.expires))
            print(f"token creado (id={tid}, scope={args.scope}, "
                  f"expira={args.expires or 'nunca'})")
            print(f"TOKEN (se muestra una sola vez): {plain}")
            print("Config en clientes: Authorization: Bearer <token>")
            return 0
        if taction == "list":
            rows = auth.list_tokens()
            if getattr(args, "json", False):
                _json_out(rows)
            else:
                for r in rows:
                    exp = r["expires_at"] and time.strftime(
                        "%Y-%m-%d", time.localtime(r["expires_at"]))
                    print(f"{r['id']:<14} {r['scope']:<7} expira={exp or 'nunca'}")
            return 0
        if taction == "revoke":
            if not auth.revoke(args.id):
                raise CliError(f"token '{args.id}' no existe")
            print(f"token '{args.id}' revocado")
            return 0
        print("usa 'api tokens create|list|revoke'")
        return 2
    print(f"accion desconocida: {action}")
    return 2


def cmd_mcp(args: argparse.Namespace) -> int:
    import os

    from src.api.service import AppService
    from src.core.config import ConfigStore
    from src.mcp.server import McpServer

    action = getattr(args, "action", "serve")
    store = ConfigStore()
    if not store.cfg.mcp.enabled:
        print(
            "MCP deshabilitado en config (mcp.enabled=false).\n"
            "Activalo desde Ajustes de la GUI (pestana Ajustes) o edita config.json.",
            file=sys.stderr,
        )
        return 3
    token = os.environ.get("PORT_FORWARDER_TOKEN")
    if not token and store.cfg.mcp.token_required:
        token = store.cfg.mcp.token or ""
    if action == "serve":
        setup_logging(console=True)
        service = AppService()
        service.supervisor.start()
        server = McpServer(service, token=token)
        print("servidor MCP stdio listo (token "
              + ("requerido" if server.token else "no configurado") + ")",
              file=sys.stderr)
        try:
            return server.serve()
        except KeyboardInterrupt:
            return 130
    if action == "test":
        service = AppService()
        server = McpServer(service, token=token)
        results = server.selftest()
        ok = all(r["ok"] for r in results)
        for r in results:
            extra = r.get("tools", "")
            print(f"{'PASS' if r['ok'] else 'FAIL'} {r['step']} {extra}")
        print("MCP OK" if ok else "MCP con fallos")
        return 0 if ok else 1
    print(f"accion desconocida: {action}")
    return 2
