"""E2E de forward real (marcado integration): aplica un forward a un puerto
efimero, lo prueba y lo limpia. Requiere admin + una distro WSL.

Uso: pytest -m integration
"""

from __future__ import annotations

import socket
import time

import pytest

from src.core.config import ConfigStore, Forward
from src.providers.netsh_provider import NetshProvider
from src.providers.wsl_ip_provider import WslIpProvider
from src.utils import subprocess_async as sp


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.integration
def test_e2e_forward_apply_and_clean():
    if not sp.is_admin():
        pytest.skip("requiere admin para netsh/firewall")
    store = ConfigStore()
    netsh = NetshProvider(netsh_exe=store.cfg.windows.netsh_exe or None)
    wsl = WslIpProvider(wsl_exe=store.cfg.windows.wsl_exe or None)

    distros = wsl.list_distros()
    assert distros, "no hay distros WSL"
    distro = next((d for d in distros if "docker" not in d.lower()), distros[0])
    ip = wsl.get_ip(distro)
    if not ip:
        pytest.skip(f"distro '{distro}' no responde hostname -I")

    port = _free_port()
    fwd = Forward(
        id="e2e-test", listen_port=port, wsl_distro=distro, wsl_port=port,
        auto_apply=True,
    )
    try:
        result = netsh.add_forward(fwd, ip)
        assert result.ok, result.error
        time.sleep(0.5)
        found = [f for f in netsh.list_forwards()
                 if f.listen_port == port]
        assert found, "forward no aparece en netsh"
        assert found[0].connect_port == port
    finally:
        result = netsh.remove_forward(fwd)
        assert result.ok, result.error
        time.sleep(0.3)
        assert not [f for f in netsh.list_forwards()
                    if f.listen_port == port]
