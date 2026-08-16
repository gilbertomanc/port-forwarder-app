"""E2E admin: netsh portproxy + firewall reales (sin distro WSL).

Usa 127.0.0.1 como destino para no depender de una distro: aplica el
portproxy, verifica con 'show all', prueba TCP y limpia.

Uso: pytest -m integration   (elevado; ver scripts/run_e2e_elevated.ps1)
"""

from __future__ import annotations

import socket
import time

import pytest

from src.core.config import ConfigStore, Forward
from src.providers.netsh_provider import NetshProvider
from src.utils import subprocess_async as sp


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.integration
def test_e2e_netsh_portproxy_apply_and_clean():
    if not sp.is_admin():
        pytest.skip("requiere admin para netsh/firewall")
    store = ConfigStore()
    netsh = NetshProvider(netsh_exe=store.cfg.windows.netsh_exe or None)

    port = _free_port()
    fwd = Forward(
        id="e2e-netsh", listen_port=port, listen_address="127.0.0.1",
        wsl_distro="", wsl_port=port, auto_apply=True,
    )
    try:
        result = netsh.add_forward(fwd, "127.0.0.1")
        assert result.ok, result.error
        time.sleep(0.5)
        found = [f for f in netsh.list_forwards()
                 if f.listen_port == port and f.listen_address == "127.0.0.1"]
        assert found, "forward no aparece en netsh"
        assert found[0].wsl_port == port
    finally:
        result = netsh.remove_forward(fwd)
        assert result.ok, result.error
        time.sleep(0.3)
        assert not [f for f in netsh.list_forwards()
                    if f.listen_port == port]
