"""Tests de TailscaleProvider/CloudflareProvider y dispatch del supervisor."""

from __future__ import annotations

from unittest import mock

import pytest

from src.core.config import Bind, ConfigStore, Tunnel, TunnelHealthGate, Vps
from src.core.metrics_store import MetricsStore
from src.core.supervisor import STATE_DOWN, STATE_RUNNING, Supervisor
from src.providers.cloudflare_provider import CloudflareError, CloudflareProvider
from src.providers.tailscale_provider import TailscaleError, TailscaleProvider


def make_tunnel(ttype: str = "tailscale", **kw) -> Tunnel:
    defaults = dict(id="t1", type=ttype, local_url="http://127.0.0.1:3000",
                    auto_start=True, health_gate=TunnelHealthGate(enabled=False))
    defaults.update(kw)
    return Tunnel(**defaults)


# ------------------------------------------------------------- Tailscale


def test_tailscale_build_serve_command():
    p = TailscaleProvider(exe="tailscale")
    t = make_tunnel()
    assert p.build_command(t) == ["tailscale", "serve", "--bg",
                                  "http://127.0.0.1:3000"]


def test_tailscale_build_funnel_command():
    p = TailscaleProvider(exe="tailscale")
    t = make_tunnel(funnel=True)
    assert p.build_command(t) == ["tailscale", "funnel", "--bg", "443",
                                  "http://127.0.0.1:3000"]


def test_tailscale_start_failure_raises():
    p = TailscaleProvider(exe="tailscale")
    with mock.patch("src.providers.tailscale_provider.sp.run") as run:
        run.return_value = mock.Mock(returncode=1, stderr="boom")
        with pytest.raises(TailscaleError):
            p.start(make_tunnel())


def test_tailscale_is_alive():
    p = TailscaleProvider(exe="tailscale")
    with mock.patch("src.providers.tailscale_provider.sp.run") as run:
        run.return_value = mock.Mock(returncode=0, stdout="active serve")
        assert p.is_alive(make_tunnel()) is True
        run.return_value = mock.Mock(returncode=1, stdout="")
        assert p.is_alive(make_tunnel()) is False


def test_tailscale_stop_uses_off():
    p = TailscaleProvider(exe="tailscale")
    with mock.patch("src.providers.tailscale_provider.sp.run") as run:
        p.stop(make_tunnel(funnel=True))
        assert run.call_args.args[0] == ["tailscale", "funnel", "--bg", "off"]


# ------------------------------------------------------------- Cloudflare


def test_cloudflare_build_quick_tunnel():
    p = CloudflareProvider(exe="cloudflared", pid_dir="tmp")
    t = make_tunnel("cloudflare")
    assert p.build_command(t) == ["cloudflared", "tunnel", "--url",
                                  "http://127.0.0.1:3000", "run", "t1"]


def test_cloudflare_start_writes_pidfile(tmp_path):
    p = CloudflareProvider(exe="cloudflared", pid_dir=str(tmp_path))
    proc = mock.Mock(pid=99)
    proc.poll.return_value = None
    with mock.patch("subprocess.Popen", return_value=proc):
        p.start(make_tunnel("cloudflare"))
    assert (tmp_path / "cf-t1.pid").read_text() == "99"
    assert p.is_alive(make_tunnel("cloudflare")) is True


def test_cloudflare_stop_kills(tmp_path):
    p = CloudflareProvider(exe="cloudflared", pid_dir=str(tmp_path))
    proc = mock.Mock(pid=99)
    proc.poll.return_value = None
    p._procs["t1"] = proc
    p.stop(make_tunnel("cloudflare"))
    proc.terminate.assert_called_once()


# ------------------------------------------------------------- Supervisor dispatch


class FakeProvider:
    def __init__(self, alive=False, error=None):
        self.alive = alive
        self.error = error
        self.started = 0
        self.stopped = 0

    def is_alive(self, tunnel):
        return self.alive

    def start(self, tunnel):
        self.started += 1
        if self.error:
            raise self.error

    def stop(self, tunnel):
        self.stopped += 1


@pytest.fixture
def env(tmp_path):
    store = ConfigStore(path=str(tmp_path / "config.json"))
    store.cfg.forwards = []
    metrics = MetricsStore(str(tmp_path / "metrics.db"))
    netsh = mock.Mock()
    wsl = mock.Mock()
    ssh = mock.Mock()
    wsl.get_all_ips.return_value = {}
    sup = Supervisor(store, netsh=netsh, wsl=wsl, ssh=ssh, metrics=metrics,
                     interval=5, clock=lambda: 1000.0)
    return store, metrics, sup


def test_supervisor_tailscale_dispatch(env):
    store, metrics, sup = env
    store.cfg.tunnels.append(make_tunnel("tailscale"))
    ts = FakeProvider(alive=False)
    sup.tailscale = ts
    sup.run_once()
    assert ts.started == 1
    assert sup.tunnel_state["t1"] == STATE_RUNNING


def test_supervisor_tailscale_alive_no_restart(env):
    store, metrics, sup = env
    store.cfg.tunnels.append(make_tunnel("tailscale"))
    ts = FakeProvider(alive=True)
    sup.tailscale = ts
    sup.run_once()
    assert ts.started == 0
    assert sup.tunnel_state["t1"] == STATE_RUNNING


def test_supervisor_cloudflare_backoff(env):
    store, metrics, sup = env
    store.cfg.tunnels.append(make_tunnel("cloudflare"))
    cf = FakeProvider(alive=False, error=CloudflareError("boom"))
    sup.cloudflare = cf
    sup.run_once()
    assert sup.tunnel_state["t1"] == STATE_DOWN
    assert cf.started == 1
    # backoff: no reintenta de inmediato
    cf.started = 0
    sup.run_once()
    assert cf.started == 0


def test_supervisor_unknown_type(env):
    store, metrics, sup = env
    store.cfg.tunnels.append(make_tunnel("weird"))
    sup.run_once()
    assert sup.tunnel_state["t1"] == STATE_DOWN


def test_supervisor_maintenance_stops_all_types(env):
    store, metrics, sup = env
    store.cfg.tunnels.append(make_tunnel("tailscale"))
    store.cfg.tunnels.append(make_tunnel("cloudflare"))
    ts = FakeProvider(alive=True)
    cf = FakeProvider(alive=True)
    sup.tailscale = ts
    sup.cloudflare = cf
    sup.maintenance = True
    sup.run_once()
    assert ts.stopped == 1
    assert cf.stopped == 1
