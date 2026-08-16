"""Tests de SecretsStore (DPAPI real en Windows) y del logger redactor."""

from __future__ import annotations

import pytest

from src.core.logger import RedactingFilter
from src.utils.secrets import SecretsStore


@pytest.fixture
def sec(tmp_path):
    return SecretsStore(str(tmp_path / "secrets.json"))


def test_set_get_roundtrip(sec):
    sec.set("ssh_key_main", "valor-super-secreto")
    assert sec.get("ssh_key_main") == "valor-super-secreto"


def test_check_and_delete(sec):
    assert not sec.check("nope")
    sec.set("x", "y")
    assert sec.check("x")
    assert sec.delete("x")
    assert not sec.delete("x")


def test_get_missing_raises(sec):
    with pytest.raises(KeyError):
        sec.get("no-existe")


def test_list_refs(sec):
    sec.set("b", "1")
    sec.set("a", "2")
    assert sec.list_refs() == ["a", "b"]


def test_persistence_across_instances(tmp_path):
    p = tmp_path / "secrets.json"
    SecretsStore(str(p)).set("k", "v")
    assert SecretsStore(str(p)).get("k") == "v"


def test_stored_file_does_not_contain_plaintext(tmp_path):
    p = tmp_path / "secrets.json"
    SecretsStore(str(p)).set("k", "texto-plano-123")
    raw = p.read_text(encoding="utf-8")
    assert "texto-plano-123" not in raw


# ---------------------------------------------------------------- Logger


def test_redacting_filter_removes_tokens():
    import logging

    f = RedactingFilter()
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname="", lineno=1, msg="token=abc123 valor",
        args=(), exc_info=None,
    )
    assert f.filter(record)
    assert "abc123" not in record.getMessage()
    assert "token=***" in record.getMessage()


def test_redacting_filter_removes_bearer():
    import logging

    f = RedactingFilter()
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname="", lineno=1,
        msg="Authorization: Bearer xy.zz.qq", args=(), exc_info=None,
    )
    assert f.filter(record)
    assert "xy.zz.qq" not in record.getMessage()


def test_redacting_filter_removes_ssh_key_body():
    import logging

    f = RedactingFilter()
    body = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI test@pc"
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname="", lineno=1,
        msg=f"llave: {body}", args=(), exc_info=None,
    )
    assert f.filter(record)
    assert "AAAAC3NzaC1lZDI1NTE5AAAAI" not in record.getMessage()
