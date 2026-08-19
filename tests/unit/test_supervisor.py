"""Tests del Supervisor: maquina de estados, backoff, health gate."""

from __future__ import annotations

from unittest import mock

import pytest

from src.core.config import (
    Bind,
    ConfigStore,
    Forward,
    HealthCheck,
    Tunnel,
    TunnelHealthGate,
    Vps,
)
from src.core.metrics_store import MetricsStore
from src.providers.base import CommandResult
from src.core.supervisor import (
    STATE_DOWN,
    STATE_OK,
    STATE_PAUSED,
    STATE_RUNNING,
    STATE_WAITING,
    Supervisor,
)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t += secs


@pytest.fixture
def env(tmp_path, monkeypatch):
    # Aisla el SecretsStore (DPAPI) para que los tests no vean los secrets
    # reales del usuario en %APPDATA%.
    monkeypatch.setattr(
        "src.utils.path.secrets_path", lambda: tmp_path / "secrets.json"
    )
    store = ConfigStore(path=str(tmp_path / "config.json"))
    store.cfg.ui.supervisor_interval_seconds = 5
    store.cfg.forwards.append(Forward(
        id="f1", listen_port=8080, wsl_distro="ubuntu", wsl_port=3000,
        auto_apply=True,
        health_check=HealthCheck(enabled=False),
    ))
    store.add_vps(Vps(id="v1", host="vps.example.com", user="tunnel",
                      identity_file="id"))
    store.cfg.tunnels.append(Tunnel(
        id="t1", vps_id="v1", local_bind=Bind(port=3000),
        remote_binds=[Bind(host="0.0.0.0", port=80)], auto_start=True,
        health_gate=TunnelHealthGate(enabled=False),
    ))
    clock = FakeClock()
    netsh = mock.Mock()
    wsl = mock.Mock()
    ssh = mock.Mock()
    metrics = MetricsStore(str(tmp_path / "metrics.db"))
    sup = Supervisor(store, netsh=netsh, wsl=wsl, ssh=ssh, metrics=metrics,
                     interval=5, clock=clock)
    return store, netsh, wsl, ssh, metrics, clock, sup


def test_applies_forward_when_ip_available(env):
    store, netsh, wsl, ssh, metrics, clock, sup = env
    wsl.get_all_ips.return_value = {"ubuntu": "172.18.0.2"}
    netsh.list_forwards.return_value = []
    netsh.add_forward.return_value = CommandResult(ok=True)
    netsh.test_connection.return_value = True

    sup.run_once()
    netsh.add_forward.assert_called_once()
    assert sup.forward_state["f1"] == STATE_OK


def test_reload_config_when_file_changes(env):
    """La GUI/CLI pueden editar config.json desde otro proceso; el supervisor
    debe recargarlo cuando cambia el mtime en disco."""
    import os
    import time

    store, netsh, wsl, ssh, metrics, clock, sup = env
    called = []
    store.reload = lambda: called.append(1)  # type: ignore[assignment]
    before = sup._config_mtime()
    os.utime(store.path, (before + 10, before + 10))
    sup._maybe_reload_config()
    assert called == [1]
    # sin cambios de mtime no recarga
    sup._maybe_reload_config()
    assert called == [1]


def test_web_panel_lifecycle(env):
    """El panel web arranca/para segun config; sin clave NO arranca."""
    store, netsh, wsl, ssh, metrics, clock, sup = env
    store.cfg.ui.web_panel_port = 0  # puerto efimero (tests)
    # habilitado pero SIN clave: no arranca
    store.cfg.ui.web_panel_enabled = True
    store.save()
    sup._sync_web_panel()
    assert getattr(sup, "_web", None) is None
    # con clave: arranca
    store.cfg.ui.web_panel_token = "secreto"
    store.save()
    sup._sync_web_panel()
    assert sup._web is not None and sup._web.running
    assert sup._web.token == "secreto"
    # deshabilitado: se detiene
    store.cfg.ui.web_panel_enabled = False
    store.save()
    sup._sync_web_panel()
    assert getattr(sup, "_web", None) is None


def test_forward_not_reapplied_when_same(env):
    store, netsh, wsl, ssh, metrics, clock, sup = env
    wsl.get_all_ips.return_value = {"ubuntu": "172.18.0.2"}
    netsh.list_forwards.return_value = [
        Forward(id="x", listen_port=8080, wsl_distro="", wsl_port=3000,
                auto_apply=False)
    ]
    netsh.add_forward.return_value = CommandResult(ok=True)

    sup.run_once()
    netsh.add_forward.assert_not_called()
    assert sup.forward_state["f1"] == STATE_OK


def test_ip_change_triggers_reapply(env):
    store, netsh, wsl, ssh, metrics, clock, sup = env
    wsl.get_all_ips.return_value = {"ubuntu": "172.18.0.2"}
    netsh.list_forwards.return_value = []
    netsh.add_forward.return_value = CommandResult(ok=True)
    sup.run_once()
    netsh.add_forward.reset_mock()

    # La IP cambio (wsl --shutdown) -> reaplicar
    wsl.get_all_ips.return_value = {"ubuntu": "172.18.0.9"}
    sup.run_once()
    netsh.add_forward.assert_called_once()
    assert sup.known_ips["ubuntu"] == "172.18.0.9"


def test_forward_health_gate_pauses_and_retries(env):
    store, netsh, wsl, ssh, metrics, clock, sup = env
    f = store.get_forward("f1")
    f.health_check = HealthCheck(enabled=True, fail_count_before_pause=2)
    wsl.get_all_ips.return_value = {"ubuntu": "172.18.0.2"}
    netsh.list_forwards.return_value = []
    netsh.add_forward.return_value = CommandResult(ok=True)
    netsh.test_connection.return_value = True

    sup.run_once()
    assert sup.forward_state["f1"] == STATE_OK

    # el servicio muere: tras 2 fallos -> paused
    netsh.test_connection.return_value = False
    sup.run_once()
    assert sup.forward_state["f1"] == STATE_OK  # 1 fallo
    sup.run_once()
    assert sup.forward_state["f1"] == STATE_PAUSED

    # no reintenta antes de 60s
    clock.advance(10)
    sup.run_once()
    assert sup.forward_state["f1"] == STATE_PAUSED
    netsh.add_forward.reset_mock()

    # tras 60s + servicio recuperado -> vuelve a OK
    clock.advance(60)
    netsh.test_connection.return_value = True
    netsh.list_forwards.return_value = []
    sup.run_once()
    assert sup.forward_state["f1"] == STATE_OK


def test_tunnel_dead_restarts_with_backoff(env):
    store, netsh, wsl, ssh, metrics, clock, sup = env
    wsl.get_all_ips.return_value = {}
    ssh.is_alive.return_value = False
    ssh.start.side_effect = Exception("boom")

    sup.run_once()
    assert sup.tunnel_state["t1"] == STATE_DOWN
    # backoff: no reintenta de inmediato
    ssh.start.reset_mock()
    sup.run_once()
    ssh.start.assert_not_called()

    # avanza el reloj: reintento fallido -> backoff mayor
    clock.advance(20)
    sup.run_once()
    assert ssh.start.call_count >= 1


def test_tunnel_up_clears_backoff(env):
    store, netsh, wsl, ssh, metrics, clock, sup = env
    wsl.get_all_ips.return_value = {}
    ssh.is_alive.side_effect = [False, False, True]
    ssh.start.side_effect = Exception("boom")

    sup.run_once()
    sup.run_once()
    assert sup.tunnel_state["t1"] == STATE_DOWN

    clock.advance(20)
    sup.run_once()  # ahora is_alive=True -> up
    assert sup.tunnel_state["t1"] == STATE_RUNNING
    assert "t1" not in sup.tunnel_backoff


def test_tunnel_waiting_when_health_gate_fails(env):
    store, netsh, wsl, ssh, metrics, clock, sup = env
    wsl.get_all_ips.return_value = {}
    ssh.is_alive.return_value = False
    ssh._gate_ok.return_value = False
    ssh.start.side_effect = Exception("no")
    store.get_tunnel("t1").health_gate.enabled = True

    sup.run_once()
    assert sup.tunnel_state["t1"] == STATE_WAITING
    ssh.start.assert_not_called()


def test_maintenance_stops_everything(env):
    store, netsh, wsl, ssh, metrics, clock, sup = env
    sup.maintenance = True
    ssh.is_alive.return_value = True
    summary = sup.run_once()
    ssh.stop.assert_called_once()
    assert summary["maintenance"] is True


def test_status_shape(env):
    store, netsh, wsl, ssh, metrics, clock, sup = env
    wsl.get_all_ips.return_value = {"ubuntu": "172.18.0.2"}
    netsh.list_forwards.return_value = []
    netsh.add_forward.return_value = CommandResult(ok=True)
    netsh.test_connection.return_value = True
    ssh.is_alive.return_value = False
    sup.run_once()
    st = sup.status()
    assert "forwards" in st and "tunnels" in st
    assert st["forwards"][0]["id"] == "f1"
    assert st["tunnels"][0]["id"] == "t1"
