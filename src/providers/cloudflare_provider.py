"""CloudflareProvider: cloudflared tunnel (T8, P2; Anexo A).

Comando:
  quick tunnel:  cloudflared tunnel --url http://localhost:3000 run <id>
  named tunnel:  cloudflared tunnel run <id>   (requiere config/login previo)

is_alive via Popen (a diferencia de tailscale, cloudflared corre en
foreground). No testeado contra una instalacion real (requiere login).
"""

from __future__ import annotations

import subprocess
import time

from src.core.config import Tunnel
from src.utils import subprocess_async as sp
from src.utils import path as paths


class CloudflareError(Exception):
    pass


class CloudflareProvider:
    def __init__(self, exe: str = "cloudflared",
                 pid_dir: str | None = None) -> None:
        self.exe = exe
        self.pid_dir = paths.data_dir() / "tunnels" if pid_dir is None \
            else paths.Path(pid_dir)
        self.pid_dir.mkdir(parents=True, exist_ok=True)
        self._procs: dict[str, subprocess.Popen] = {}

    def _pidfile(self, tunnel_id: str):
        return self.pid_dir / f"cf-{tunnel_id}.pid"

    def build_command(self, tunnel: Tunnel) -> list[str]:
        if tunnel.local_url:
            return [self.exe, "tunnel", "--url", tunnel.local_url,
                    "run", tunnel.id]
        return [self.exe, "tunnel", "run", tunnel.id]

    def start(self, tunnel: Tunnel) -> subprocess.Popen:
        logf = open(self.pid_dir / f"cf-{tunnel.id}.log", "ab", buffering=0)
        try:
            proc = subprocess.Popen(
                self.build_command(tunnel),
                stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
                creationflags=sp.CREATE_NO_WINDOW,
            )
        except OSError as e:
            logf.close()
            raise CloudflareError(f"no se pudo lanzar cloudflared: {e}") from e
        self._procs[tunnel.id] = proc
        self._pidfile(tunnel.id).write_text(str(proc.pid), encoding="utf-8")
        return proc

    def stop(self, tunnel: Tunnel) -> None:
        proc = self._procs.pop(tunnel.id, None)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass
        self._pidfile(tunnel.id).unlink(missing_ok=True)

    def is_alive(self, tunnel: Tunnel) -> bool:
        proc = self._procs.get(tunnel.id)
        return proc is not None and proc.poll() is None

    def restart(self, tunnel: Tunnel) -> subprocess.Popen:
        self.stop(tunnel)
        time.sleep(0.5)
        return self.start(tunnel)
