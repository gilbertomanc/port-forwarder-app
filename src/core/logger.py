"""Logging rotado con redaccion de secretos (regla 13.2 del plan).

Nunca deben aparecer tokens, passphrases ni contenido de llaves en los logs.
El filtro RedactingFilter reemplaza valores de claves sensibles y patrones
comunes (Bearer tokens, passwords, passphrase, private keys).
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler

from src.utils import path as paths

SENSITIVE_KEYS = (
    "password", "passphrase", "secret", "token", "api_key", "apikey",
    "private_key", "authorization", "x-webhook-secret",
)

# Patrones tipicos de valores sensibles en lineas de log
_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.I),
    re.compile(r"(--passphrase\s+)\S+"),
    re.compile(r"(passphrase\s*[:=]\s*)\S+"),
    re.compile(r"(token\s*[:=]\s*)\S+"),
    re.compile(r"(password\s*[:=]\s*)\S+"),
    re.compile(r"((?:ssh-rsa|ecdsa-sha2|ssh-ed25519)\s+)[A-Za-z0-9+/=]+"),
]


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        redacted = msg
        for pat in _PATTERNS:
            redacted = pat.sub(r"\1***", redacted)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
    console: bool = True,
    redact: bool = True,
) -> logging.Logger:
    """Configura el logger raiz: archivo rotado (10 MB x 5) + consola."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    for h in list(root.handlers):
        root.removeHandler(h)

    if log_file is None:
        log_file = str(paths.logs_dir() / "port-forwarder.log")

    fh = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5,
                             encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)

    if redact:
        root.addFilter(RedactingFilter())

    return logging.getLogger("port-forwarder")


def get_logger(name: str = "port-forwarder") -> logging.Logger:
    if not logging.getLogger().handlers:
        setup_logging()
    return logging.getLogger(name)
