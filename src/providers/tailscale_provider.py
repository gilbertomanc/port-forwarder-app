"""TailscaleProvider: tailscale serve / funnel (T7, P2; Anexo A).

Comandos (mejor esfuerzo, dependen de la version de tailscale):
  serve:   tailscale serve --bg http://localhost:3000
  funnel:  tailscale funnel --bg 443 http://localhost:3000
  stop:    tailscale serve --bg off  |  tailscale funnel --bg off
  is_alive: tailscale serve status  (contiene la URL/estado activo)

No testeado contra una instalacion real (requiere tailscale up).
"""

from __future__ import annotations

import subprocess

from src.utils import subprocess_async as sp


class TailscaleError(Exception):
    pass


class TailscaleProvider:
    def __init__(self, exe: str = "tailscale") -> None:
        self.exe = exe

    def build_command(self, tunnel) -> list[str]:
        url = tunnel.local_url or f"http://localhost:{tunnel.local_bind.port}"
        if tunnel.funnel:
            return [self.exe, "funnel", "--bg", "443", url]
        return [self.exe, "serve", "--bg", url]

    def start(self, tunnel) -> subprocess.Popen | None:
        result = sp.run(self.build_command(tunnel), timeout=30.0, check=False)
        if result.returncode != 0:
            raise TailscaleError(result.stderr or result.stdout or
                                 "tailscale fallo")
        return None  # serve --bg es daemon: no hay Popen que vigilar

    def stop(self, tunnel) -> None:
        cmd = [self.exe, "funnel", "--bg", "off"] if tunnel.funnel \
            else [self.exe, "serve", "--bg", "off"]
        sp.run(cmd, timeout=30.0, check=False)

    def is_alive(self, tunnel) -> bool:
        try:
            proc = sp.run([self.exe, "serve", "status"], timeout=20.0,
                          check=False)
        except OSError:
            return False
        out = str(proc.stdout or "") + str(proc.stderr or "")
        return proc.returncode == 0 and "active" in out.lower()
