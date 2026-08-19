"""Utilidades de rutas: expansion de variables de entorno y directorios base.

Windows: %APPDATA%\\PortForwarder (datos) y %LOCALAPPDATA%\\PortForwarder\\logs.
Linux/macOS: XDG_CONFIG_HOME o ~/.config/PortForwarder (datos) y
XDG_DATA_HOME o ~/.local/share/PortForwarder/logs (logs).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_ENV_PATTERN = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")

_WINDOWS = sys.platform == "win32"


def expand_env(path: str) -> str:
    """Expande variables estilo Windows (%USERPROFILE%\\...) o $VAR en *nix."""

    def _sub(m: re.Match[str]) -> str:
        return os.environ.get(m.group(1), m.group(0))

    expanded = _ENV_PATTERN.sub(_sub, path)
    expanded = os.path.expandvars(expanded)
    expanded = os.path.expanduser(expanded)
    return expanded


def data_dir() -> Path:
    """Directorio base de datos de la app (APPDATA / XDG)."""
    if _WINDOWS:
        base = os.environ.get("APPDATA") or str(Path.home())
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    d = Path(base) / "PortForwarder"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    """Directorio de logs (LOCALAPPDATA / XDG_DATA_HOME)."""
    if _WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    d = Path(base) / "PortForwarder" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def backups_dir() -> Path:
    """Directorio de backups pre-edicion de config."""
    d = data_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return data_dir() / "config.json"


def secrets_path() -> Path:
    return data_dir() / "secrets.json"


def metrics_path() -> Path:
    return data_dir() / "metrics.db"
