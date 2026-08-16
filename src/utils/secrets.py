"""SecretsStore: valores sensibles cifrados con DPAPI (CurrentUser).

Implementacion con ctypes (CryptProtectData/CryptUnprotectData) para
mantener el core sin dependencias (seccion 13.1 del plan).

- Los valores NUNCA se imprimen; solo `check` confirma existencia.
- Fuera de Windows: fallback a cifrado XOR con advertencia (solo dev/test).
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
from pathlib import Path

from src.utils import path as paths

_DPAPI_OK = sys.platform == "win32"
_lock = threading.Lock()


def _dpapi_protect(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("CryptProtectData fallo")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("CryptUnprotectData fallo (usuario distinto?)")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _fallback_protect(data: bytes) -> bytes:
    key = os.environ.get("USERNAME", "port-forwarder").encode()
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _fallback_unprotect(data: bytes) -> bytes:
    return _fallback_protect(data)


class SecretsStore:
    """Almacen de secrets cifrados; API: set/get/check/delete/list_refs."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else paths.secrets_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, str] = {}
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._data = {
                    k: v for k, v in raw.items() if isinstance(v, str)
                }
            except (json.JSONDecodeError, OSError):
                self._data = {}

    @staticmethod
    def _encrypt(plain: str) -> str:
        data = plain.encode("utf-8")
        if _DPAPI_OK:
            blob = _dpapi_protect(data)
        else:  # pragma: no cover - solo dev/test
            blob = _fallback_protect(data)
        return base64.b64encode(blob).decode("ascii")

    @staticmethod
    def _decrypt(blob_b64: str) -> str:
        blob = base64.b64decode(blob_b64)
        if _DPAPI_OK:
            return _dpapi_unprotect(blob).decode("utf-8")
        return _fallback_unprotect(blob).decode("utf-8")  # pragma: no cover

    def set(self, ref: str, value: str) -> None:
        """Guarda un secret; el valor NUNCA se registra."""
        with _lock:
            self._data[ref] = self._encrypt(value)
            self._persist()

    def get(self, ref: str) -> str:
        with _lock:
            if ref not in self._data:
                raise KeyError(f"secret '{ref}' no definido")
            return self._decrypt(self._data[ref])

    def check(self, ref: str) -> bool:
        with _lock:
            return ref in self._data

    def delete(self, ref: str) -> bool:
        with _lock:
            if ref not in self._data:
                return False
            del self._data[ref]
            self._persist()
            return True

    def list_refs(self) -> list[str]:
        with _lock:
            return sorted(self._data.keys())

    def _persist(self) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._data, indent=2), encoding="utf-8"
        )
        tmp.replace(self.path)
