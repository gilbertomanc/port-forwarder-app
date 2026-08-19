"""NetshProvider: portproxy + firewall + conflictos + port map (F1-F8, M6).

Comandos subyacentes (seccion 8.2 del plan):
  netsh interface portproxy add v4tov4 listenport=X listenaddress=0.0.0.0 \\
      connectport=Y connectaddress=<IP-WSL>
  New-NetFirewallRule -DisplayName "WSL-Fwd-X" ...
  netsh interface portproxy delete v4tov4 listenport=X listenaddress=0.0.0.0
  Remove-NetFirewallRule -DisplayName "WSL-Fwd-X"

- Los comandos netsh se ejecutan sin ventana.
- Las reglas de firewall se gestionan via PowerShell (idempotente: borra y
  recrea para evitar duplicados).
- add/remove requieren admin: se lanza UAC selectivo si el proceso no esta
  elevado (seccion 13.2).
"""

from __future__ import annotations

import re
import socket
import subprocess
import time
from dataclasses import asdict
from typing import Iterable

from src.core.config import Forward
from src.providers.base import CommandResult, PortEntry
from src.utils import subprocess_async as sp

_PORT_LINE = re.compile(r"^\s*(\S+)\s+(\d+)\s+(\S+)\s+(\d+)\s*$")


class NetshError(Exception):
    pass


class NetshProvider:
    def __init__(
        self,
        netsh_exe: str | None = None,
        powershell_exe: str | None = None,
        elevate: bool = True,
    ) -> None:
        import sys as _sys

        if netsh_exe is None:
            netsh_exe = (r"C:\Windows\System32\netsh.exe"
                         if _sys.platform == "win32" else "netsh")
        self.netsh_exe = netsh_exe
        self.powershell_exe = powershell_exe or sp.POWERSHELL_EXE
        self.elevate = elevate  # UAC selectivo para add/remove

    # -- helpers -------------------------------------------------------------

    def _netsh(self, args: list[str], timeout: float = 30.0) -> CommandResult:
        try:
            proc = sp.run([self.netsh_exe, *args], timeout=timeout, check=False)
            return CommandResult(
                ok=proc.returncode == 0,
                output=(proc.stdout or "").strip(),
                error=(proc.stderr or "").strip(),
                exit_code=proc.returncode,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return CommandResult(ok=False, error=str(e), exit_code=-1)

    def _elevated_or_plain(self, script: str, timeout: float = 90.0) -> CommandResult:
        """Corre un script PS; si hace falta admin y no lo somos, pide UAC."""
        try:
            if self.elevate and not sp.is_admin():
                proc = sp.run_powershell(script, timeout=timeout, elevate=True)
            else:
                proc = sp.run_powershell(script, timeout=timeout, check=False)
            return CommandResult(
                ok=proc.returncode == 0,
                output=(proc.stdout or "").strip(),
                error=(proc.stderr or "").strip(),
                exit_code=proc.returncode,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return CommandResult(ok=False, error=str(e), exit_code=-1)

    @staticmethod
    def _firewall_script(
        name: str, port: int, protocol: str, action: str = "Add"
    ) -> str:
        if action == "Add":
            return (
                f"Remove-NetFirewallRule -DisplayName '{name}' -ErrorAction SilentlyContinue; "
                f"New-NetFirewallRule -DisplayName '{name}' -Direction Inbound "
                f"-LocalPort {port} -Action Allow -Protocol {protocol.upper()} | Out-Null; "
                f"Write-Output 'ok'"
            )
        return (
            f"Remove-NetFirewallRule -DisplayName '{name}' -ErrorAction SilentlyContinue; "
            f"Write-Output 'ok'"
        )

    # -- operaciones ---------------------------------------------------------

    def add_forward(self, forward: Forward, ip: str) -> CommandResult:
        """Aplica portproxy + firewall. Ip se obtiene AL MOMENTO (8.2)."""
        if not ip:
            return CommandResult(
                ok=False,
                error=f"IP de WSL vacia para distro '{forward.wsl_distro}'",
            )
        add = self._netsh([
            "interface", "portproxy", "add", "v4tov4",
            f"listenport={forward.listen_port}",
            f"listenaddress={forward.listen_address}",
            f"connectport={forward.wsl_port}",
            f"connectaddress={ip}",
        ])
        fw = self._elevated_or_plain(
            self._firewall_script(
                forward.firewall_name, forward.listen_port, forward.protocol
            )
        )
        if not add.ok:
            return add
        if not fw.ok:
            # El portproxy quedo pero la regla fallo: intentar limpiar.
            self.remove_forward(forward)
            return CommandResult(
                ok=False,
                error=f"regla de firewall fallo: {fw.error or fw.output} "
                      "(portproxy revertido)",
                exit_code=fw.exit_code,
            )
        return CommandResult(ok=True, output=f"forward {forward.id} aplicado -> {ip}")

    def remove_forward(self, forward: Forward) -> CommandResult:
        del_ = self._netsh([
            "interface", "portproxy", "delete", "v4tov4",
            f"listenport={forward.listen_port}",
            f"listenaddress={forward.listen_address}",
        ])
        fw = self._elevated_or_plain(
            self._firewall_script(
                forward.firewall_name, forward.listen_port, forward.protocol,
                action="Remove",
            )
        )
        ok = del_.ok or "no se encontro" in (del_.output + del_.error).lower()
        # netsh delete falla con error si no existe; lo tratamos como exito.
        errors = []
        if not ok:
            errors.append(del_.error or del_.output)
        if not fw.ok:
            errors.append(fw.error or fw.output)
        return CommandResult(
            ok=not errors,
            output=f"forward {forward.id} limpiado" if not errors else "",
            error="; ".join(errors),
            exit_code=0 if not errors else 1,
        )

    def list_forwards(self) -> list[Forward]:
        """Parse de 'netsh interface portproxy show all' -> lista de Forward
        (sin wsl_distro conocida; el caller la cruza con la config)."""
        result = self._netsh(["interface", "portproxy", "show", "all"])
        forwards: list[Forward] = []
        if not result.ok:
            return forwards
        for line in result.output.splitlines():
            m = _PORT_LINE.match(line)
            if not m:
                continue
            addr, port, conn_addr, conn_port = m.groups()
            try:
                forwards.append(
                    Forward(
                        id=f"{addr}:{port}",
                        listen_address=addr,
                        listen_port=int(port),
                        wsl_distro="",
                        wsl_port=int(conn_port),
                        auto_apply=False,
                    )
                )
            except ValueError:
                continue
        return forwards

    def clear_all(self) -> list[CommandResult]:
        """Elimina todos los portproxies y reglas WSL-Fwd-*."""
        results: list[CommandResult] = []
        for f in self.list_forwards():
            results.append(self.remove_forward(f))
        fw = self._elevated_or_plain(
            "Remove-NetFirewallRule -DisplayName 'WSL-Fwd-*' "
            "-ErrorAction SilentlyContinue; Write-Output 'ok'"
        )
        results.append(fw)
        return results

    def detect_conflicts(self, port: int) -> list[int]:
        """PIDs con listeners activos en :port (F5), via netstat."""
        try:
            proc = sp.run(
                ["netstat", "-ano", "-p", "TCP"],
                timeout=20.0,
                check=False,
            )
        except OSError:
            return []
        pids: set[int] = set()
        for line in proc.stdout.splitlines():
            if f":{port} " not in line and f":{port}\t" not in line:
                continue
            if "LISTENING" not in line:
                continue
            m = re.search(r"(\d+)\s*$", line.strip())
            if m:
                try:
                    pids.add(int(m.group(1)))
                except ValueError:
                    pass
        return sorted(pids)

    def test_connection(self, port: int, timeout: float = 3.0) -> bool:
        """Test TCP a 127.0.0.1:port (F6/M3) — no requiere admin."""
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                return True
        except OSError:
            return False

    def port_map(self) -> list[PortEntry]:
        """Mapa de puertos real (M6): lo que netsh declara hoy."""
        return [PortEntry(
            listen_address=f.listen_address,
            listen_port=f.listen_port,
            connect_address="",  # netsh show no trae la IP conectada
            connect_port=f.wsl_port,
        ) for f in self.list_forwards()]

    # -- utilidades de estado -------------------------------------------------

    def declared_forwards(self, declared: Iterable[Forward]) -> list[PortEntry]:
        """Cruza el estado real (netsh) con la config deseada (drift, M6)."""
        real = {f.listen_port: f for f in self.list_forwards()}
        declared_by_port = {f.listen_port: f for f in declared}
        entries: list[PortEntry] = []

        for port, rf in real.items():
            df = declared_by_port.get(port)
            ok = df is not None and df.wsl_port == rf.wsl_port
            entries.append(PortEntry(
                listen_address=rf.listen_address,
                listen_port=port,
                connect_address="",
                connect_port=rf.wsl_port,
                declared=df is not None,
                forward_id=df.id if df else None,
                state="ok" if ok else ("extra" if df is None else "broken"),
            ))
        for port, df in declared_by_port.items():
            if port not in real:
                entries.append(PortEntry(
                    listen_address=df.listen_address,
                    listen_port=port,
                    connect_address="",
                    connect_port=df.wsl_port,
                    declared=True,
                    forward_id=df.id,
                    state="missing",
                ))
        entries.sort(key=lambda e: e.listen_port)
        return entries
