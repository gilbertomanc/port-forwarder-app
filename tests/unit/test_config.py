"""Tests de ConfigStore: carga, validacion, backups y CRUD."""

from __future__ import annotations

import json

import pytest

from src.core.config import (
    ConfigError,
    ConfigStore,
    Forward,
    Tunnel,
    Bind,
    Vps,
    parse_config,
    _to_dict,
)


@pytest.fixture
def store(tmp_path):
    store = ConfigStore(path=str(tmp_path / "config.json"),
                        backup_dir=str(tmp_path / "backups"))
    return store


def test_default_config_created(store):
    assert store.cfg.version == 2
    assert store.cfg.forwards == []
    assert store.cfg.windows.ssh_exe.endswith("ssh.exe")


def test_invalid_json_raises(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        ConfigStore(path=str(p))


def test_duplicate_ids_rejected(tmp_path):
    p = tmp_path / "config.json"
    data = {
        "forwards": [
            {"id": "a", "listen_port": 1000, "wsl_port": 1000},
            {"id": "a", "listen_port": 1001, "wsl_port": 1001},
        ]
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="duplicados"):
        ConfigStore(path=str(p))


def test_tunnel_requires_existing_vps(tmp_path):
    p = tmp_path / "config.json"
    data = {"tunnels": [
        {"id": "t1", "vps_id": "nope",
         "remote_binds": [{"host": "0.0.0.0", "port": 80}]}
    ]}
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="vps_id"):
        ConfigStore(path=str(p))


def test_bad_protocol_rejected(tmp_path):
    p = tmp_path / "config.json"
    data = {"forwards": [
        {"id": "a", "listen_port": 1000, "wsl_port": 1000,
         "protocol": "sctp"}
    ]}
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="protocol"):
        ConfigStore(path=str(p))


def test_crud_forward(store):
    f = Forward(id="f1", listen_port=8080, wsl_distro="ubuntu",
                wsl_port=8080)
    store.add_forward(f)
    assert store.get_forward("f1") is f
    with pytest.raises(ConfigError):
        store.add_forward(f)
    store.remove_forward("f1")
    assert store.get_forward("f1") is None
    with pytest.raises(ConfigError):
        store.remove_forward("f1")


def test_crud_tunnel_and_vps(store):
    store.add_vps(Vps(id="v1", host="h", user="u"))
    tun = Tunnel(id="t1", vps_id="v1",
                 local_bind=Bind(port=3000),
                 remote_binds=[Bind(host="0.0.0.0", port=80)])
    store.add_tunnel(tun)
    assert store.get_tunnel("t1") is tun
    # vps en uso no se puede borrar
    with pytest.raises(ConfigError):
        store.remove_vps("v1")
    store.remove_tunnel("t1")
    store.remove_vps("v1")


def test_backup_created_on_save(store):
    f = Forward(id="f1", listen_port=8080, wsl_distro="ubuntu",
                wsl_port=8080)
    store.add_forward(f)
    store.add_forward(Forward(id="f2", listen_port=8081, wsl_distro="ubuntu",
                              wsl_port=8081))
    backups = list((store.backup_dir).glob("*.json"))
    assert len(backups) >= 1


def test_env_expansion(tmp_path):
    import os

    p = tmp_path / "config.json"
    fake = str(tmp_path / "fake-ssh.exe")
    open(fake, "w").close()
    data = {"windows": {"ssh_exe": fake}}
    p.write_text(json.dumps(data), encoding="utf-8")
    cfg = parse_config(json.loads(p.read_text()))
    assert cfg.windows.ssh_exe == fake


def test_to_dict_roundtrip(store):
    store.add_forward(Forward(id="f1", listen_port=8080, wsl_distro="ubuntu",
                              wsl_port=8080))
    d = _to_dict(store.cfg)
    assert d["forwards"][0]["listen_port"] == 8080
    parsed = parse_config(d)
    assert parsed.forwards[0].id == "f1"
