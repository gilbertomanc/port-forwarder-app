"""Smoke tests del CLI: cada comando principal con exit code y JSON."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(*args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # Aislamos la config en un dir temporal para no tocar la del usuario.
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "src.cli", *args],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
        timeout=60,
    )


@pytest.mark.smoke
def test_help_exits_zero():
    r = run_cli("--help")
    assert r.returncode == 0
    assert "forwards" in r.stdout


@pytest.mark.smoke
def test_version():
    r = run_cli("--version")
    assert r.returncode == 0
    assert "port-forwarder" in r.stdout


@pytest.mark.smoke
def test_status_json():
    r = run_cli("status", "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "forwards" in data
    assert "tunnels" in data


@pytest.mark.smoke
def test_config_validate():
    r = run_cli("config", "validate")
    assert r.returncode == 0, r.stderr
    assert "config OK" in r.stdout


@pytest.mark.smoke
def test_forwards_list_json():
    r = run_cli("forwards", "list", "--json")
    assert r.returncode == 0, r.stderr
    assert isinstance(json.loads(r.stdout), list)


@pytest.mark.smoke
def test_tunnels_list_json():
    r = run_cli("tunnels", "list", "--json")
    assert r.returncode == 0, r.stderr
    assert isinstance(json.loads(r.stdout), list)


@pytest.mark.smoke
def test_portmap_json():
    r = run_cli("portmap", "--json")
    assert r.returncode == 0, r.stderr
    assert isinstance(json.loads(r.stdout), list)


@pytest.mark.smoke
def test_alerts_list():
    r = run_cli("alerts", "list")
    assert r.returncode == 0, r.stderr


@pytest.mark.smoke
def test_unknown_command_exit_2():
    r = run_cli("no-existe")
    assert r.returncode == 2


@pytest.mark.smoke
def test_unknown_action_exit_2():
    r = run_cli("forwards", "no-existe")
    assert r.returncode == 2


@pytest.mark.smoke
def test_destructive_requires_confirm():
    r = run_cli("forwards", "clear")
    assert r.returncode == 1
    assert "--yes" in r.stderr


@pytest.mark.smoke
def test_web_status_json():
    r = run_cli("web", "status", "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "running" in data
    assert "url" in data and "http://" in data["url"]
    assert data["port"] > 0


@pytest.mark.smoke
def test_redact_config_hides_panel_token():
    """H4: el bundle diag nunca incluye el token del panel en claro."""
    from src.cli.commands_ux import _redact_config

    cfg = {"ui": {"web_panel_token": "clave-plana-123", "port": 8794}}
    redacted = _redact_config(cfg)
    assert redacted["ui"]["web_panel_token"] != "clave-plana-123"
    assert "clave-plana-123" not in str(redacted)
    assert "redactado" in redacted["ui"]["web_panel_token"]


def _mcp_env(tmp_path) -> dict:
    """Entorno aislado con MCP habilitado (no toca la config del usuario)."""
    appdata = tmp_path / "appdata"
    cfg_dir = appdata / "PortForwarder"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(
        json.dumps({"version": 2, "mcp": {"enabled": True,
                                          "token_required": False}}),
        encoding="utf-8",
    )
    return dict(os.environ, APPDATA=str(appdata), XDG_CONFIG_HOME=str(appdata))


@pytest.mark.smoke
def test_mcp_selftest_cli(tmp_path):
    r = run_cli("mcp", "test", env_extra=_mcp_env(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "MCP OK" in r.stdout


@pytest.mark.smoke
def test_mcp_stdio_handshake(tmp_path):
    """Handshake JSON-RPC real por stdio: initialize + tools/list + call."""
    payload = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "2024-11-05",
                                 "clientInfo": {"name": "smoke"}}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": "status", "arguments": {}}}),
        "",
    ])
    r = subprocess.run(
        [sys.executable, "-m", "src.cli", "mcp", "serve"],
        input=payload, capture_output=True, text=True, cwd=REPO,
        env=_mcp_env(tmp_path), timeout=60,
    )
    assert r.returncode == 0, r.stderr
    lines = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
    by_id = {l["id"]: l for l in lines}
    assert "result" in by_id[1]  # initialize
    names = [t["name"] for t in by_id[2]["result"]["tools"]]
    assert "status" in names and "tunnel_start" in names
    assert '"ok": true' in by_id[3]["result"]["content"][0]["text"]


@pytest.mark.smoke
def test_api_status_cli():
    r = run_cli("api", "status", "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "enabled" in data and "tokens" in data


@pytest.mark.smoke
def test_schedule_add_remove_roundtrip():
    r = run_cli("schedule", "add", "--name", "test-x", "--type", "tunnel_start",
                "--tunnel", "t", "--time", "09:00", "--days", "mon,fri")
    assert r.returncode == 0, r.stderr
    # parsear el id generado y eliminarlo para dejar limpio
    r2 = run_cli("schedule", "list", "--json")
    rows = json.loads(r2.stdout)
    mine = [x for x in rows if x["name"] == "test-x"]
    assert len(mine) == 1
    r3 = run_cli("schedule", "remove", mine[0]["id"])
    assert r3.returncode == 0, r3.stderr
