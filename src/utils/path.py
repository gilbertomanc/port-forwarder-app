"""Utilidades de rutas: expansion de variables de entorno y directorios base.

Todas las rutas persistentes viven bajo %APPDATA%\\PortForwarder y los logs
bajo %LOCALAPPDATA%\\PortForwarder\\logs (ver seccion 12.1 del plan).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_ENV_PATTERN = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")


def expand_env(path: str) -> str:
    """Expande variables estilo Windows (%USERPROFILE%\\...) o $VAR en *nix."""

    def _sub(m: re.Match[str]) -> str:
        return os.environ.get(m.group(1), m.group(0))

    expanded = _ENV_PATTERN.sub(_sub, path)
    expanded = os.path.expandvars(expanded)
    expanded = os.path.expanduser(expanded)
    return expanded


def data_dir() -> Path:
    """Directorio base de datos de la app (%APPDATA%\\PortForwarder)."""
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / "PortForwarder"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    """Directorio de logs (%LOCALAPPDATA%\\PortForwarder\\logs)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
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
