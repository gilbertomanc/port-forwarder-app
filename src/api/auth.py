"""AuthService: tokens con scopes (seccion 21.2 del plan).

- Generacion: secrets.token_urlsafe(32); el valor se muestra UNA sola vez.
- Almacen: solo hash sha256 + metadatos (scope, expiracion), cifrado DPAPI
  via SecretsStore (ref 'api_tokens').
- Rate limiting por token: ventana deslizante por minuto (read 120, write 30).
- Auditoria: cada llamada la registra el servidor (events de SQLite).
"""

from __future__ import annotations

import hashlib
import json
import secrets as pysecrets
import time
import uuid
from typing import Any

from src.utils.secrets import SecretsStore

SCOPE_READ = "read"
SCOPE_WRITE = "write"
SCOPE_ADMIN = "admin"
SCOPES = (SCOPE_READ, SCOPE_WRITE, SCOPE_ADMIN)

# Orden de privilegios: admin incluye write incluye read.
_SCOPE_RANK = {SCOPE_READ: 1, SCOPE_WRITE: 2, SCOPE_ADMIN: 3}

RATE_READ_PER_MIN = 120
RATE_WRITE_PER_MIN = 30


class AuthError(Exception):
    pass


class AuthService:
    def __init__(
        self,
        secrets: SecretsStore | None = None,
        rate_read: int = RATE_READ_PER_MIN,
        rate_write: int = RATE_WRITE_PER_MIN,
    ) -> None:
        self.secrets = secrets or SecretsStore()
        self.rate_read = rate_read
        self.rate_write = rate_write
        self._calls: dict[str, list[float]] = {}

    # -- almacen ---------------------------------------------------------------

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.secrets.check("api_tokens"):
            return {}
        try:
            raw = self.secrets.get("api_tokens")
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (KeyError, ValueError):
            return {}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self.secrets.set("api_tokens", json.dumps(data))

    # -- ciclo de vida de tokens -------------------------------------------------

    def create_token(
        self, scope: str, expires_days: int | None = None
    ) -> tuple[str, str]:
        """Devuelve (token_id, token_plano). El plano solo se muestra una vez."""
        if scope not in SCOPES:
            raise AuthError(f"scope invalido: {scope} (usa {', '.join(SCOPES)})")
        token_id = uuid.uuid4().hex[:12]
        token_plain = pysecrets.token_urlsafe(32)
        data = self._load()
        data[token_id] = {
            "hash": hashlib.sha256(token_plain.encode()).hexdigest(),
            "scope": scope,
            "created_at": time.time(),
            # expires_days <= 0 => token ya expirado (semantica util en tests/CLI)
            "expires_at": (time.time() + expires_days * 86400)
            if (expires_days or 0) > 0 else (
                time.time() - 1 if expires_days is not None else None
            ),
        }
        self._save(data)
        return token_id, token_plain

    def validate(self, token_plain: str) -> tuple[str, str] | None:
        """Devuelve (token_id, scope) o None si invalido/expirado."""
        digest = hashlib.sha256(token_plain.encode()).hexdigest()
        for tid, meta in self._load().items():
            if meta.get("hash") == digest:
                exp = meta.get("expires_at")
                if exp and time.time() > exp:
                    return None
                return tid, meta["scope"]
        return None

    def revoke(self, token_id: str) -> bool:
        data = self._load()
        if token_id not in data:
            return False
        del data[token_id]
        self._save(data)
        self._calls.pop(token_id, None)
        return True

    def list_tokens(self) -> list[dict[str, Any]]:
        rows = []
        for tid, meta in self._load().items():
            rows.append({
                "id": tid,
                "scope": meta["scope"],
                "created_at": meta.get("created_at"),
                "expires_at": meta.get("expires_at"),
            })
        return sorted(rows, key=lambda r: r["created_at"] or 0)

    # -- autorizacion ---------------------------------------------------------------

    def authorize(self, token_plain: str, required_scope: str) -> tuple[str, str] | None:
        """Valida token + scope; None si falla."""
        result = self.validate(token_plain)
        if result is None:
            return None
        tid, scope = result
        if _SCOPE_RANK[scope] < _SCOPE_RANK[required_scope]:
            return None
        return tid, scope

    def check_rate(self, token_id: str, scope: str) -> bool:
        """True si la llamada entra dentro del limite por minuto."""
        limit = self.rate_write if scope != SCOPE_READ else self.rate_read
        now = time.time()
        window = self._calls.setdefault(token_id, [])
        window = [t for t in window if now - t < 60]
        self._calls[token_id] = window
        if len(window) >= limit:
            return False
        window.append(now)
        return True
