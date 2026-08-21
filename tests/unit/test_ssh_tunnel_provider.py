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
                             log_dir=tmp_path / "logs",
                             use_autossh=False)


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
    assert "TCPKeepAlive=yes" in cmd
    assert "ConnectTimeout=10" in cmd
    assert "-p" in cmd and "22" in cmd


def test_build_command_with_autossh(tmp_path):
    """Con autossh se usa 'autossh -M 0' + las mismas opciones de keepalive."""
    p = SshTunnelProvider(ssh_exe=r"C:\Windows\System32\OpenSSH\ssh.exe",
                          pid_dir=tmp_path / "pids",
                          log_dir=tmp_path / "logs",
                          autossh_exe=r"C:\tools\autossh.exe",
                          use_autossh=True)
    cmd = p.build_command(make_tunnel(), make_vps())
    assert cmd[0].endswith("autossh.exe")
    assert cmd[1:3] == ["-M", "0"]
    assert "-T" in cmd
    assert "TCPKeepAlive=yes" in cmd
    assert "ServerAliveInterval=30" in cmd
    assert "-R" in cmd


def test_cmd_matches_detects_r_forward(tmp_path):
    """Detecta procesos ssh del tunnel por la linea de comandos (-R)."""
    p = make_provider(tmp_path)
    tun = make_tunnel()  # local 3000, remote 80
    good = r"C:\Windows\System32\OpenSSH\ssh.exe -N -R 0.0.0.0:80:127.0.0.1:3000 debian@vps"
    other_port = r"C:\Windows\System32\OpenSSH\ssh.exe -N -R 0.0.0.0:8080:127.0.0.1:3000 debian@vps"
    other_local = r"C:\Windows\System32\OpenSSH\ssh.exe -N -R 0.0.0.0:80:127.0.0.1:9999 debian@vps"
    assert p._cmd_matches(tun, good)
    assert not p._cmd_matches(tun, other_port)
    assert not p._cmd_matches(tun, other_local)


def test_traffic_accumulates_via_vps(tmp_path, monkeypatch):
    """El trafico acumula bytes desde los contadores de la sesion SSH en el VPS."""
    import time

    p = make_provider(tmp_path)
    tun = make_tunnel()
    vps = make_vps()
    calls = iter([(1000, 500), (2100, 1050)])  # 2 muestras: delta 1100/550
    monkeypatch.setattr(p, "_vps_session_bytes", lambda v: next(calls))

    t1 = p.traffic(tun, vps)
    assert t1["rx_bytes"] == 1000
    assert t1["tx_bytes"] == 500
    assert t1["rx_rate_bps"] == 0  # primera muestra: sin dt
    time.sleep(1.0)
    t2 = p.traffic(tun, vps)
    assert 1900 <= t2["rx_bytes"] <= 2300   # acumulado ~2100
    assert 900 <= t2["tx_bytes"] <= 1200
    assert 900 <= t2["rx_rate_bps"] <= 1300
    assert p._traffic_file(tun.id).exists()


def test_traffic_sin_vps(tmp_path):
    p = make_provider(tmp_path)
    assert p.traffic(make_tunnel(), None) is None


def test_traffic_sin_sesiones(tmp_path, monkeypatch):
    p = make_provider(tmp_path)
    tun = make_tunnel()
    vps = make_vps()
    monkeypatch.setattr(p, "_vps_session_bytes", lambda v: None)
    tf = p.traffic(tun, vps)
    assert tf is not None
    assert tf["rx_bytes"] == 0
    assert tf["rx_rate_bps"] == 0
    assert tf["tx_rate_bps"] == 0


def test_vps_session_bytes_usa_la_sesion_mayor(tmp_path, monkeypatch):
    """Evita contar la sesion de medicion (la mayor es el tunnel real)."""
    from src.providers.ssh_tunnel_provider import sp

    p = make_provider(tmp_path)
    vps = make_vps()
    out = (
        "0 0 167.114.169.134:10000 1.2.3.4:5000\n"
        "\t cubic ... bytes_sent:100 bytes_received:50 ...\n"
        "0 0 167.114.169.134:10000 1.2.3.4:5001\n"
        "\t cubic ... bytes_sent:9000 bytes_received:3000 ...\n"
        "0 0 167.114.169.134:10000 1.2.3.4:5002\n"
        "\t cubic ... bytes_sent:500 bytes_received:100 ...\n"
    )
    proc = mock.Mock()
    proc.returncode = 0
    proc.stdout = out
    proc.stderr = ""
    monkeypatch.setattr(sp, "run", lambda *a, **k: proc)
    assert p._vps_session_bytes(vps) == (3000, 9000)


def test_traffic_snapshot_no_abre_ssh(tmp_path):
    """traffic_snapshot lee lo persistido sin tocar el VPS."""
    p = make_provider(tmp_path)
    tun = make_tunnel()
    assert p.traffic_snapshot(tun) is None
    p._traffic_file(tun.id).write_text(
        '{"rx_total": 100, "tx_total": 50, "rx_rate_bps": 10, "tx_rate_bps": 5}',
        encoding="utf-8",
    )
    snap = p.traffic_snapshot(tun)
    assert snap is not None
    assert snap["rx_bytes"] == 100
    assert snap["tx_bytes"] == 50
    assert snap["rx_rate_bps"] == 10


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
    assert "port-forwarder-askpass" in env["SSH_ASKPASS"]  # .cmd en Win, .sh en *nix
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
