"""Tests de SshTunnelProvider: build_command, start/stop/is_alive."""

from __future__ import annotations

import os
from unittest import mock

import pytest

from src.core.config import Bind, Tunnel, Vps
from src.providers.ssh_tunnel_provider import SshTunnelError, SshTunnelProvider


def make_tunnel(**kw):
    defaults = dict(
        id="t1",
        vps_id="v1",
        local_bind=Bind(host="127.0.0.1", port=3000),
        remote_binds=[Bind(host="0.0.0.0", port=80)],
        keepalive_interval=30,
        keepalive_count=3,
    )
    defaults.update(kw)
    return Tunnel(**defaults)


def make_vps():
    return Vps(id="v1", host="vps.example.com", user="tunnel",
               identity_file=r"C:\keys\wsl-manager")


def make_provider(tmp_path):
    return SshTunnelProvider(ssh_exe=r"C:\Windows\System32\OpenSSH\ssh.exe",
                             pid_dir=tmp_path / "pids",
                             log_dir=tmp_path / "logs")


def test_build_command_single_remote(tmp_path):
    p = make_provider(tmp_path)
    cmd = p.build_command(make_tunnel(), make_vps())
    assert cmd[0].endswith("ssh.exe")
    assert "-N" in cmd
    assert "-R" in cmd
    assert "0.0.0.0:80:127.0.0.1:3000" in cmd
    assert "tunnel@vps.example.com" in cmd
    assert "ServerAliveInterval=30" in cmd
    assert "ServerAliveCountMax=3" in cmd
    assert "-p" in cmd and "22" in cmd


def test_build_command_with_password(tmp_path):
    """Con contrasena se limita la autenticacion a password/keyboard."""
    p = make_provider(tmp_path)
    vps = make_vps()
    vps.password = "secreta123"
    cmd = p.build_command(make_tunnel(), vps)
    joined = " ".join(cmd)
    # con clave privada + contrasena: publickey primero, luego password
    assert "PreferredAuthentications=publickey,password,keyboard-interactive" in joined
    vps2 = make_vps()
    vps2.identity_file = ""
    vps2.password = "secreta123"
    cmd2 = p.build_command(make_tunnel(), vps2)
    joined2 = " ".join(cmd2)
    assert "PreferredAuthentications=password,keyboard-interactive" in joined2
    assert "publickey" not in joined2


def test_password_env_sets_askpass(tmp_path):
    p = make_provider(tmp_path)
    vps = make_vps()
    vps.password = "secreta123"
    env = p._password_env(vps)
    assert env is not None
    assert env["SSH_ASKPASS_REQUIRE"] == "force"
    assert env["PF_ASKPASS_PW"] == "secreta123"
    assert env["SSH_ASKPASS"].endswith("port-forwarder-askpass.cmd")
    # sin contrasena -> None
    assert p._password_env(make_vps()) is None


def test_start_passes_env(tmp_path):
    p = make_provider(tmp_path)
    vps = make_vps()
    vps.password = "secreta123"
    with mock.patch("src.providers.ssh_tunnel_provider.subprocess.Popen") as m:
        proc = mock.MagicMock()
        m.return_value = proc
        p.start(make_tunnel(), vps)
        _, kwargs = m.call_args
        env = kwargs.get("env") or {}
        assert env.get("PF_ASKPASS_PW") == "secreta123"
        assert "PATH" in env  # entorno completo, no solo las vars nuevas


def test_build_command_multi_port(tmp_path):
    p = make_provider(tmp_path)
    t = make_tunnel(remote_binds=[Bind(host="0.0.0.0", port=80),
                                  Bind(host="0.0.0.0", port=443)])
    cmd = p.build_command(t, make_vps())
    assert "0.0.0.0:80:127.0.0.1:3000" in cmd
    assert "0.0.0.0:443:127.0.0.1:3000" in cmd


def test_build_command_jump(tmp_path):
    p = make_provider(tmp_path)
    t = make_tunnel(jump="vps-a")
    cmd = p.build_command(t, make_vps())
    assert any("ProxyJump=vps-a" in c for c in cmd)


def test_build_command_rejects_non_ssh(tmp_path):
    p = make_provider(tmp_path)
    t = make_tunnel(type="tailscale")
    with pytest.raises(SshTunnelError):
        p.build_command(t, make_vps())


def test_start_writes_pidfile(tmp_path):
    p = make_provider(tmp_path)
    proc = mock.Mock(pid=4242)
    proc.poll.return_value = None
    with mock.patch("subprocess.Popen", return_value=proc) as popen, \
            mock.patch("socket.create_connection"):
        p.start(make_tunnel(), make_vps())
        assert popen.call_count == 1
        assert (tmp_path / "pids" / "t1.pid").read_text() == "4242"
        assert p.is_alive(make_tunnel())  # proc vivo + gate ok (mockeado)


def test_is_alive_checks_process(tmp_path):
    p = make_provider(tmp_path)
    t = make_tunnel()
    proc = mock.Mock(pid=1)
    proc.poll.return_value = None
    p._procs["t1"] = proc
    with mock.patch("socket.create_connection") as conn:
        conn.return_value.__enter__ = mock.Mock()
        conn.return_value.__exit__ = mock.Mock(return_value=False)
        assert p.is_alive(t) is True
    # proceso muerto -> no alive
    proc.poll.return_value = 1
    with mock.patch("socket.create_connection") as conn:
        conn.return_value.__enter__ = mock.Mock()
        conn.return_value.__exit__ = mock.Mock(return_value=False)
        assert p.is_alive(t) is False


def test_is_alive_health_gate_blocks(tmp_path):
    p = make_provider(tmp_path)
    t = make_tunnel(health_gate=mock.Mock(enabled=True))
    proc = mock.Mock(pid=1)
    proc.poll.return_value = None
    p._procs["t1"] = proc
    with mock.patch("socket.create_connection", side_effect=OSError):
        assert p.is_alive(t) is False
    # sin health gate -> vivo
    t2 = make_tunnel(health_gate=mock.Mock(enabled=False))
    p._procs["t1"] = proc
    assert p.is_alive(t2) is True


def test_stop_kills_process_and_removes_pidfile(tmp_path):
    p = make_provider(tmp_path)
    t = make_tunnel()
    proc = mock.Mock(pid=1)
    proc.poll.return_value = None
    p._procs["t1"] = proc
    p._pidfile("t1").write_text("1")
    with mock.patch.object(p, "_kill_by_pattern"):
        p.stop(t)
    proc.terminate.assert_called_once()
    assert not p._pidfile("t1").exists()


def test_latency_returns_ms(tmp_path):
    p = make_provider(tmp_path)
    with mock.patch("src.providers.ssh_tunnel_provider.sp.run") as run, \
            mock.patch("src.providers.ssh_tunnel_provider.time.monotonic",
                       side_effect=[1.0, 1.5]):
        run.return_value = mock.Mock(returncode=0)
        assert p.latency(make_tunnel(), make_vps()) == 500.0
