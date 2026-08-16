"""Tests de AuthService, ApiServer (REST) y McpServer (seccion 21)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from unittest import mock

import pytest

from src.api.auth import SCOPE_ADMIN, SCOPE_READ, SCOPE_WRITE, AuthService
from src.api.server import ApiServer
from src.api.service import AppService
from src.core.config import Bind, ConfigStore, Tunnel, TunnelHealthGate, Vps
from src.core.metrics_store import MetricsStore
from src.core.supervisor import Supervisor
from src.mcp.server import McpServer
from src.utils.secrets import SecretsStore


# ------------------------------------------------------------------ Auth


@pytest.fixture
def auth(tmp_path):
    return AuthService(SecretsStore(str(tmp_path / "sec.json")),
                       rate_read=5, rate_write=3)


def test_token_lifecycle(auth):
    tid, plain = auth.create_token(SCOPE_READ, expires_days=30)
    result = auth.validate(plain)
    assert result == (tid, SCOPE_READ)
    assert auth.validate("otro-token") is None
    assert auth.revoke(tid)
    assert not auth.revoke(tid)
    assert auth.validate(plain) is None


def test_token_scope_rank(auth):
    _, write = auth.create_token(SCOPE_WRITE)
    assert auth.authorize(write, SCOPE_READ) is not None
    assert auth.authorize(write, SCOPE_WRITE) is not None
    assert auth.authorize(write, SCOPE_ADMIN) is None
    _, read = auth.create_token(SCOPE_READ)
    assert auth.authorize(read, SCOPE_WRITE) is None


def test_token_expiry(auth):
    tid, plain = auth.create_token(SCOPE_READ, expires_days=0)
    # expires_days=0 -> expira al instante
    assert auth.validate(plain) is None


def test_invalid_scope(auth):
    with pytest.raises(Exception):
        auth.create_token("superuser")


def test_rate_limit(auth):
    tid, plain = auth.create_token(SCOPE_READ)
    for _ in range(5):
        assert auth.check_rate(tid, SCOPE_READ)
    assert not auth.check_rate(tid, SCOPE_READ)
    # write tiene limite propio
    tid2, _ = auth.create_token(SCOPE_WRITE)
    for _ in range(3):
        assert auth.check_rate(tid2, SCOPE_WRITE)
    assert not auth.check_rate(tid2, SCOPE_WRITE)


def test_tokens_never_stored_plain(tmp_path):
    sec = SecretsStore(str(tmp_path / "sec.json"))
    a = AuthService(sec)
    _, plain = a.create_token(SCOPE_READ)
    raw = sec.get("api_tokens")
    assert plain not in raw


# ------------------------------------------------------------------ API server


@pytest.fixture
def api_env(tmp_path):
    store = ConfigStore(path=str(tmp_path / "config.json"))
    store.add_vps(Vps(id="v1", host="vps.example.com", user="tunnel"))
    store.cfg.tunnels.append(Tunnel(
        id="t1", vps_id="v1", local_bind=Bind(port=3000),
        remote_binds=[Bind(host="0.0.0.0", port=80)],
        health_gate=TunnelHealthGate(enabled=False),
    ))
    metrics = MetricsStore(str(tmp_path / "metrics.db"))
    sup = mock.Mock(spec=Supervisor)
    sup.metrics = metrics
    sup.store = store
    sup.netsh = mock.Mock()
    sup.netsh.clear_all.return_value = []
    sup.netsh.declared_forwards.return_value = []
    sup.wsl = mock.Mock()
    sup.ssh = mock.Mock()
    sup.running = True
    sup.interval = 10
    sup.last_cycle = 0
    sup.status.return_value = {"running": True, "maintenance": False,
                               "forwards": [], "tunnels": []}
    svc = AppService(store, supervisor=sup)
    auth = AuthService(SecretsStore(str(tmp_path / "sec.json")),
                       rate_read=50, rate_write=50)
    return store, sup, metrics, svc, auth


@pytest.fixture
def api_server(api_env, tmp_path):
    store, sup, metrics, svc, auth = api_env
    _, read_token = auth.create_token(SCOPE_READ)
    _, write_token = auth.create_token(SCOPE_WRITE)
    _, admin_token = auth.create_token(SCOPE_ADMIN)
    srv = ApiServer(svc, auth, port=0)
    srv.start()
    yield srv, read_token, write_token, admin_token
    srv.stop()


def _req(srv: ApiServer, method: str, path: str, token: str | None,
         body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{srv.port}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_api_401_without_token(api_server):
    srv, *_ = api_server
    status, data = _req(srv, "GET", "/api/v1/status", None)
    assert status == 401
    assert "token" in data["error"]


def test_api_401_bad_token(api_server):
    srv, *_ = api_server
    status, _ = _req(srv, "GET", "/api/v1/status", "token-malo")
    assert status == 401


def test_api_status_read(api_server):
    srv, _, write_token, _ = api_server
    status, data = _req(srv, "GET", "/api/v1/status", write_token)
    assert status == 200
    assert data["ok"] is True


def test_api_403_insufficient_scope(api_server):
    srv, read_token, *_ = api_server
    status, data = _req(srv, "POST", "/api/v1/forwards/apply", read_token)
    assert status == 403
    assert "scope" in data["error"]


def test_api_404_unknown_route(api_server):
    srv, _, write_token, _ = api_server
    status, _ = _req(srv, "GET", "/api/v1/no-existe", write_token)
    assert status == 404


def test_api_admin_requires_confirm(api_server):
    srv, _, write_token, admin_token = api_server
    # write no puede
    status, data = _req(srv, "POST", "/api/v1/forwards/clear?confirm=1",
                        write_token)
    assert status == 403
    # admin sin confirm
    status, data = _req(srv, "POST", "/api/v1/forwards/clear", admin_token)
    assert status == 400
    assert "confirm" in data["error"]
    # admin con confirm
    status, data = _req(srv, "POST", "/api/v1/forwards/clear?confirm=1",
                        admin_token)
    assert status == 200
    assert data["ok"] is True


def test_api_forwards_create_and_delete(api_server):
    srv, _, write_token, _ = api_server
    body = {"id": "f-api", "listen_port": 9090, "wsl_port": 9090,
            "distro": "ubuntu"}
    status, data = _req(srv, "POST", "/api/v1/forwards", write_token, body)
    assert status == 200 and data["ok"] is True
    status, data = _req(srv, "DELETE", "/api/v1/forwards/f-api",
                        write_token)
    assert status == 200 and data["ok"] is True
    status, data = _req(srv, "DELETE", "/api/v1/forwards/f-api",
                        write_token)
    assert status != 200 and data["ok"] is False


def test_api_tunnel_start(api_server):
    srv, _, write_token, _ = api_server
    status, data = _req(srv, "POST", "/api/v1/tunnels/t1/start", write_token)
    assert status == 200 and data["ok"] is True


def test_api_audit_recorded(api_server):
    srv, _, write_token, _ = api_server
    _req(srv, "GET", "/api/v1/status", write_token)
    events = srv.service.supervisor.metrics.list_events(limit=10)
    assert any(e["type"] == "api_call" and e["detail"]
               and '"status": 200' in e["detail"] for e in events)


def test_api_survives_concurrent_burst(api_env, tmp_path):
    """H3: con servidor acotado, una rafaga de conexiones no debe matarlo."""
    import threading
    from collections import Counter

    store, sup, metrics, svc, auth = api_env
    _, token = auth.create_token(SCOPE_READ)
    srv = ApiServer(svc, auth, port=0, max_connections=10)
    srv.start()
    try:
        lock = threading.Lock()
        results = []

        def hit():
            req = urllib.request.Request(f"http://127.0.0.1:{srv.port}/api/v1/status")
            req.add_header("Authorization", f"Bearer {token}")
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    code = r.status
            except urllib.error.HTTPError as e:
                code = e.code
            except Exception:
                code = 0
            with lock:
                results.append(code)

        for _ in range(8):
            threads = [threading.Thread(target=hit) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        counts = Counter(results)
        # el servidor debe seguir vivo y responder despues de la rafaga
        # (200 OK, o 429 si la rafaga consumio el rate limit del fixture)
        status, _ = _req(srv, "GET", "/api/v1/status", token)
        assert status in (200, 429), status
        assert srv.running is True
    finally:
        srv.stop()


# ------------------------------------------------------------------ MCP


@pytest.fixture
def mcp(api_env):
    store, sup, metrics, svc, auth = api_env
    return McpServer(svc)


def _call(mcp: McpServer, msg_id: int, method: str, params: dict | None = None):
    return mcp.handle({"jsonrpc": "2.0", "id": msg_id, "method": method,
                       "params": params or {}})


def test_mcp_initialize(mcp):
    r = _call(mcp, 1, "initialize", {"protocolVersion": "2024-11-05",
                                     "clientInfo": {"name": "test"}})
    assert r["id"] == 1
    assert r["result"]["protocolVersion"] == "2024-11-05"
    assert r["result"]["serverInfo"]["name"] == "port-forwarder"


def test_mcp_initialized_notification_no_response(mcp):
    assert _call(mcp, 1, "notifications/initialized") is None


def test_mcp_tools_list(mcp):
    r = _call(mcp, 2, "tools/list")
    names = [t["name"] for t in r["result"]["tools"]]
    assert "status" in names
    assert "forward_apply" in names
    assert "tunnel_start" in names
    assert "maintenance_on" in names
    assert "doctor" in names


def test_mcp_tools_call_status(mcp):
    r = _call(mcp, 3, "tools/call", {"name": "status", "arguments": {}})
    text = r["result"]["content"][0]["text"]
    assert '"ok": true' in text
    assert r["result"]["isError"] is False


def test_mcp_unknown_tool(mcp):
    r = _call(mcp, 4, "tools/call", {"name": "no-existe", "arguments": {}})
    assert "error" in r
    assert r["error"]["code"] == -32602


def test_mcp_unknown_method(mcp):
    r = _call(mcp, 5, "wat")
    assert r["error"]["code"] == -32601


def test_mcp_token_enforced():
    tools = [{"name": "echo", "description": "", "inputSchema": {},
              "handler": lambda a: {"ok": True}}]
    srv = McpServer(mock.Mock(), tools=tools, token="clave-mcp")
    r = _call(srv, 1, "tools/call", {"name": "echo", "arguments": {}})
    assert "error" in r and "token" in r["error"]["message"]
    r = _call(srv, 2, "tools/call",
              {"name": "echo", "arguments": {"token": "clave-mcp"}})
    assert "error" not in r
    assert r["result"]["isError"] is False


def test_mcp_missing_args(mcp):
    r = _call(mcp, 1, "tools/call", {"name": "forward_test",
                                     "arguments": {}})
    assert "error" in r


def test_mcp_selftest(mcp):
    results = mcp.selftest()
    assert all(r["ok"] for r in results)
