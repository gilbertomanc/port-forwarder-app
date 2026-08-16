"""Tests de NetshProvider: construccion de comandos, parseo, conflictos."""

from __future__ import annotations

from unittest import mock

import pytest

from src.core.config import Forward
from src.providers.netsh_provider import NetshProvider

SHOW_ALL_SAMPLE = """
Listen on ipv4:             Connect to ipv4:

Address         Port        Address         Port
--------------- ----------  --------------- ----------
0.0.0.0         8080        172.18.0.2      3000
0.0.0.0         5432        172.18.0.2      5432
"""


def make_provider():
    return NetshProvider(
        netsh_exe="netsh.exe",
        powershell_exe="powershell.exe",
        elevate=False,
    )


def test_list_forwards_parses_show_all():
    p = make_provider()
    with mock.patch("src.providers.netsh_provider.sp.run") as run:
        run.return_value = mock.Mock(returncode=0, stdout=SHOW_ALL_SAMPLE,
                                     stderr="")
        forwards = p.list_forwards()
    assert len(forwards) == 2
    assert forwards[0].listen_port == 8080
    assert forwards[0].wsl_port == 3000


def test_add_forward_builds_netsh_and_firewall():
    p = make_provider()
    f = Forward(id="f1", listen_port=8080, wsl_distro="ubuntu",
                wsl_port=3000)
    with mock.patch("src.providers.netsh_provider.sp.run") as run, \
            mock.patch("src.providers.netsh_provider.sp.is_admin",
                       return_value=True):
        run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
        result = p.add_forward(f, "172.18.0.2")
    assert result.ok
    calls = [c.args[0] for c in run.call_args_list]
    assert ["netsh.exe", "interface", "portproxy", "add", "v4tov4",
            "listenport=8080", "listenaddress=0.0.0.0", "connectport=3000",
            "connectaddress=172.18.0.2"] in calls
    ps_call = next(c for c in calls if c[0].endswith("powershell.exe"))
    assert "New-NetFirewallRule" in ps_call[-1]
    assert "WSL-Fwd-8080" in ps_call[-1]


def test_add_forward_without_ip_fails():
    p = make_provider()
    f = Forward(id="f1", listen_port=8080, wsl_distro="ubuntu",
                wsl_port=3000)
    result = p.add_forward(f, "")
    assert not result.ok


def test_remove_forward_reverts_on_firewall_failure():
    p = make_provider()
    f = Forward(id="f1", listen_port=8080, wsl_distro="ubuntu",
                wsl_port=3000)
    with mock.patch("src.providers.netsh_provider.sp.run") as run, \
            mock.patch("src.providers.netsh_provider.sp.is_admin",
                       return_value=True):
        # firewall falla
        def fake_run(args, **kw):
            if args[0] == "netsh.exe":
                return mock.Mock(returncode=0, stdout="", stderr="")
            return mock.Mock(returncode=1, stdout="", stderr="boom")

        run.side_effect = fake_run
        result = p.add_forward(f, "172.18.0.2")
    assert not result.ok
    # se intento revertir el portproxy
    delete_calls = [c for c in run.call_args_list
                    if c.args[0][:4] == ["netsh.exe", "interface",
                                         "portproxy", "delete"]]
    assert delete_calls


def test_detect_conflicts_parses_netstat():
    p = make_provider()
    netstat_out = """
  TCP    0.0.0.0:8080           0.0.0.0:0              LISTENING       1234
  TCP    127.0.0.1:8080         127.0.0.1:5555         ESTABLISHED     9999
  TCP    0.0.0.0:9090           0.0.0.0:0              LISTENING       5678
"""
    with mock.patch("src.providers.netsh_provider.sp.run") as run:
        run.return_value = mock.Mock(returncode=0, stdout=netstat_out)
        pids = p.detect_conflicts(8080)
    assert pids == [1234]
    with mock.patch("src.providers.netsh_provider.sp.run") as run:
        run.return_value = mock.Mock(returncode=0, stdout=netstat_out)
        assert p.detect_conflicts(9090) == [5678]
    with mock.patch("src.providers.netsh_provider.sp.run") as run:
        run.return_value = mock.Mock(returncode=0, stdout=netstat_out)
        assert p.detect_conflicts(7000) == []


def test_test_connection():
    p = make_provider()
    with mock.patch("socket.create_connection") as conn:
        conn.return_value.__enter__ = mock.Mock()
        conn.return_value.__exit__ = mock.Mock(return_value=False)
        assert p.test_connection(8080) is True
    with mock.patch("socket.create_connection", side_effect=OSError):
        assert p.test_connection(8080) is False


def test_declared_forwards_drift():
    p = make_provider()
    declared = [Forward(id="f1", listen_port=8080, wsl_distro="ubuntu",
                        wsl_port=3000)]
    with mock.patch.object(p, "list_forwards", return_value=[
        Forward(id="x", listen_port=8080, wsl_distro="", wsl_port=3000),
        Forward(id="y", listen_port=9090, wsl_distro="", wsl_port=9999),
    ]):
        entries = p.declared_forwards(declared)
    states = {e.listen_port: e.state for e in entries}
    assert states[8080] == "ok"
    assert states[9090] == "extra"
    assert len(entries) == 2


def test_declared_forwards_missing():
    p = make_provider()
    declared = [Forward(id="f1", listen_port=8080, wsl_distro="ubuntu",
                        wsl_port=3000)]
    with mock.patch.object(p, "list_forwards", return_value=[]):
        entries = p.declared_forwards(declared)
    assert entries[0].state == "missing"
    assert entries[0].forward_id == "f1"
