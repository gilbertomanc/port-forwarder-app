"""ConfigStore: carga/valida/persiste config.json (pydantic-less).

Decision de la fase 0 (docs/decisions.md): el core es stdlib puro para
garantizar funcionamiento sin instalaciones en cualquier Windows con Python.
La validacion replica el schema del Anexo B con dataclasses + checks.

Reglas:
- Backups antes de cada escritura (seccion 13.2).
- Paths con %ENV% se expanden al cargar.
- Config invalida -> ConfigError (el CLI sale con codigo 3).
"""

from __future__ import annotations

import copy
import json
import shutil
import time
from dataclasses import asdict, dataclass, field, fields
from typing import Any, TypeVar

from src.utils import path as paths

CONFIG_VERSION = 2


class ConfigError(Exception):
    """Config invalida o ilegible."""


@dataclass
class HealthCheck:
    enabled: bool = True
    fail_count_before_pause: int = 3


@dataclass
class ForwardSchedule:
    days: list[str] = field(default_factory=list)
    start: str | None = None
    end: str | None = None


@dataclass
class Forward:
    id: str
    listen_port: int
    listen_address: str = "0.0.0.0"
    wsl_distro: str = ""
    wsl_port: int = 0
    protocol: str = "tcp"
    auto_apply: bool = True
    health_check: HealthCheck = field(default_factory=HealthCheck)
    schedule: ForwardSchedule | None = None

    @property
    def firewall_name(self) -> str:
        return f"WSL-Fwd-{self.listen_port}"


@dataclass
class Vps:
    id: str
    host: str = ""
    user: str = ""
    port: int = 22
    identity_file: str = ""
    password: str = ""
    secret_ref: str | None = None


@dataclass
class Bind:
    host: str = "127.0.0.1"
    port: int = 0


@dataclass
class TunnelHealthGate:
    enabled: bool = True


@dataclass
class Tunnel:
    id: str
    type: str = "ssh"  # ssh | tailscale | cloudflare
    enabled: bool = True
    vps_id: str = ""
    local_bind: Bind = field(default_factory=Bind)
    remote_binds: list[Bind] = field(default_factory=list)
    keepalive_interval: int = 30
    keepalive_count: int = 3
    auto_start: bool = True
    health_gate: TunnelHealthGate = field(default_factory=TunnelHealthGate)
    jump: str | None = None  # multi-hop T10 (P2)
    local_url: str = ""  # tailscale/cloudflare: URL del servicio local
    funnel: bool = False  # tailscale funnel (T7)

    @property
    def ssh_dest(self) -> str:
        """Destino local del tunnel: host:port del servicio (9.2)."""
        return f"{self.local_bind.host}:{self.local_bind.port}"


@dataclass
class Alerts:
    tunnel_down_minutes: int = 2
    forward_fail_count: int = 3
    vps_latency_ms: int = 500
    check_interval_seconds: int = 15


@dataclass
class ScheduleAction:
    type: str = "tunnel_start"  # tunnel_start|tunnel_stop|forwards_apply|forwards_clear|apply_profile|snapshot_state
    tunnel: str | None = None
    profile: str | None = None


@dataclass
class ScheduleItem:
    id: str
    name: str = ""
    action: ScheduleAction = field(default_factory=ScheduleAction)
    schedule: dict = field(default_factory=lambda: {"days": [], "time": "09:00"})
    enabled: bool = True


@dataclass
class Profile:
    name: str
    description: str = ""
    forwards: list[str] = field(default_factory=list)
    tunnels: list[str] = field(default_factory=list)


@dataclass
class Ui:
    start_minimized: bool = True
    close_to_tray: bool = True
    theme: str = "dark"
    language: str = "es"
    log_level: str = "INFO"
    logs_dir: str = ""
    supervisor_interval_seconds: int = 10
    metrics_retention_days: int = 30
    web_panel_enabled: bool = False
    # Puertos propios (8794/8795/8796): no chocan con wsl-manager-gui (8790/8791/8792)
    web_panel_port: int = 8794
    web_panel_bind: str = "127.0.0.1"
    web_panel_token: str = ""  # opcional; recomendado si bind != loopback
    auto_assign_port_range: str = "8000-9000"  # F17


@dataclass
class Api:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8795
    auth_mode: str = "token"
    rate_limit_per_minute: int = 120
    allowed_ips: list[str] = field(default_factory=lambda: ["127.0.0.1"])


@dataclass
class Mcp:
    enabled: bool = False
    transport: str = "stdio"
    port: int = 8796
    token_required: bool = True
    token: str = ""


@dataclass
class OnClose:
    keep_tunnels_alive: bool = True
    clear_forwards: bool = False


@dataclass
class Webhook:
    id: str
    url: str
    events: list[str] = field(default_factory=list)
    secret_ref: str | None = None


@dataclass
class WindowsCfg:
    ssh_exe: str = ""
    autossh_exe: str = ""  # opcional: ruta a autossh (si vacio, se auto-detecta)
    netsh_exe: str = ""
    wsl_exe: str = ""


@dataclass
class Maintenance:
    active: bool = False
    start: str | None = None
    end: str | None = None


@dataclass
class AppConfig:
    version: int = CONFIG_VERSION
    windows: WindowsCfg = field(default_factory=WindowsCfg)
    vps_list: list[Vps] = field(default_factory=list)
    forwards: list[Forward] = field(default_factory=list)
    tunnels: list[Tunnel] = field(default_factory=list)
    alerts: Alerts = field(default_factory=Alerts)
    scheduler: list[ScheduleItem] = field(default_factory=list)
    profiles: list[Profile] = field(default_factory=list)
    ui: Ui = field(default_factory=Ui)
    api: Api = field(default_factory=Api)
    mcp: Mcp = field(default_factory=Mcp)
    on_close: OnClose = field(default_factory=OnClose)
    webhooks: list[Webhook] = field(default_factory=list)
    maintenance: Maintenance = field(default_factory=Maintenance)


T = TypeVar("T")


def _from_dict(dc_type: type[T], data: dict[str, Any]) -> T:
    """Construye un dataclass desde dict ignorando claves desconocidas."""
    if data is None:
        data = {}
    known = {f.name for f in fields(dc_type)}
    kwargs = {k: v for k, v in data.items() if k in known}
    return dc_type(**kwargs)


def _fwd_from_dict(d: dict) -> Forward:
    d = dict(d)
    d["health_check"] = _from_dict(HealthCheck, d.get("health_check") or {})
    d["schedule"] = (
        _from_dict(ForwardSchedule, d["schedule"]) if d.get("schedule") else None
    )
    return _from_dict(Forward, d)


def _tun_from_dict(d: dict) -> Tunnel:
    d = dict(d)
    d["local_bind"] = _from_dict(Bind, d.get("local_bind") or {})
    d["remote_binds"] = [
        _from_dict(Bind, b) if isinstance(b, dict) else b
        for b in (d.get("remote_binds") or [])
    ]
    d["health_gate"] = _from_dict(TunnelHealthGate, d.get("health_gate") or {})
    return _from_dict(Tunnel, d)


def _vps_from_dict(d: dict) -> Vps:
    return _from_dict(Vps, d)


def _sch_from_dict(d: dict) -> ScheduleItem:
    d = dict(d)
    d["action"] = _from_dict(ScheduleAction, d.get("action") or {})
    return _from_dict(ScheduleItem, d)


def _webhook_from_dict(d: dict) -> Webhook:
    return _from_dict(Webhook, d)


def _to_dict(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    if isinstance(obj, (list, tuple)):
        return [_to_dict(x) for x in obj]
    return obj


def parse_config(data: dict[str, Any]) -> AppConfig:
    """Valida y convierte un dict (JSON) en AppConfig. Lanza ConfigError."""
    if not isinstance(data, dict):
        raise ConfigError("la config raiz debe ser un objeto JSON")

    try:
        cfg = AppConfig(
            version=int(data.get("version", CONFIG_VERSION)),
            windows=_from_dict(WindowsCfg, data.get("windows") or {}),
            vps_list=[_vps_from_dict(v) for v in data.get("vps_list") or []],
            forwards=[_fwd_from_dict(f) for f in data.get("forwards") or []],
            tunnels=[_tun_from_dict(t) for t in data.get("tunnels") or []],
            alerts=_from_dict(Alerts, data.get("alerts") or {}),
            scheduler=[_sch_from_dict(s) for s in data.get("scheduler") or []],
            profiles=[_from_dict(Profile, p) for p in data.get("profiles") or []],
            ui=_from_dict(Ui, data.get("ui") or {}),
            api=_from_dict(Api, data.get("api") or {}),
            mcp=_from_dict(Mcp, data.get("mcp") or {}),
            on_close=_from_dict(OnClose, data.get("on_close") or {}),
            webhooks=[_webhook_from_dict(w) for w in data.get("webhooks") or []],
            maintenance=_from_dict(Maintenance, data.get("maintenance") or {}),
        )
    except (TypeError, ValueError) as e:
        raise ConfigError(f"schema invalido: {e}") from e

    cfg.windows.ssh_exe = paths.expand_env(cfg.windows.ssh_exe) or _default_ssh()
    cfg.windows.netsh_exe = paths.expand_env(cfg.windows.netsh_exe) or _default_netsh()
    cfg.windows.wsl_exe = paths.expand_env(cfg.windows.wsl_exe) or _default_wsl()

    _validate(cfg)
    return cfg


def _default_ssh() -> str:
    return r"C:\Windows\System32\OpenSSH\ssh.exe"


def _default_netsh() -> str:
    return r"C:\Windows\System32\netsh.exe"


def _default_wsl() -> str:
    return r"C:\Windows\System32\wsl.exe"


def _validate(cfg: AppConfig) -> None:
    seen: set[str] = set()

    def _check_unique(items: list, kind: str) -> None:
        ids = [getattr(i, "id") for i in items]
        dupes = {i for i in ids if i in seen or ids.count(i) > 1}
        if dupes:
            raise ConfigError(f"ids duplicados en {kind}: {sorted(dupes)}")
        seen.update(ids)

    _check_unique(cfg.forwards, "forwards")
    _check_unique(cfg.tunnels, "tunnels")
    _check_unique(cfg.vps_list, "vps_list")
    _check_unique(cfg.scheduler, "scheduler")
    _check_unique(cfg.webhooks, "webhooks")

    vps_ids = {v.id for v in cfg.vps_list}
    for f in cfg.forwards:
        if not (0 < f.listen_port < 65536):
            raise ConfigError(f"forward '{f.id}': listen_port fuera de rango")
        if not (0 < f.wsl_port < 65536):
            raise ConfigError(f"forward '{f.id}': wsl_port fuera de rango")
        if f.protocol not in ("tcp", "udp"):
            raise ConfigError(f"forward '{f.id}': protocol debe ser tcp|udp")
        if f.health_check.fail_count_before_pause < 1:
            raise ConfigError(
                f"forward '{f.id}': fail_count_before_pause >= 1"
            )

    for t in cfg.tunnels:
        if t.type not in ("ssh", "tailscale", "cloudflare"):
            raise ConfigError(f"tunnel '{t.id}': tipo desconocido '{t.type}'")
        if t.type == "ssh":
            if not t.vps_id:
                raise ConfigError(f"tunnel '{t.id}': falta vps_id")
            if t.vps_id not in vps_ids:
                raise ConfigError(
                    f"tunnel '{t.id}': vps_id '{t.vps_id}' no existe en vps_list"
                )
            if not t.remote_binds:
                raise ConfigError(f"tunnel '{t.id}': falta remote_binds")
            for b in t.remote_binds:
                if not (0 < b.port < 65536):
                    raise ConfigError(
                        f"tunnel '{t.id}': puerto remoto fuera de rango"
                    )
        if t.local_bind.port and not (0 < t.local_bind.port < 65536):
            raise ConfigError(f"tunnel '{t.id}': local_bind.port fuera de rango")

    if cfg.ui.supervisor_interval_seconds < 2:
        raise ConfigError("ui.supervisor_interval_seconds >= 2")

    names = {p.name for p in cfg.profiles}
    if len(names) != len(cfg.profiles):
        raise ConfigError("profiles: nombres duplicados")


class ConfigStore:
    """Carga, valida y persiste config.json con backups."""

    def __init__(
        self,
        path: str | None = None,
        backup_dir: str | None = None,
    ) -> None:
        self.path = paths.config_path() if path is None else paths.Path(path)
        self.backup_dir = (
            paths.backups_dir() if backup_dir is None else paths.Path(backup_dir)
        )
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.cfg = self.load()

    # -- carga / persistencia ------------------------------------------------

    def load(self) -> AppConfig:
        if not self.path.exists():
            cfg = AppConfig()
            self._write(cfg, backup=False)
            # Aplica defaults (paths de exe) y validacion como si viniera de disco.
            return parse_config(_to_dict(cfg))
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ConfigError(
                f"config.json corrupto ({e}). "
                "Usa 'config import <archivo>' para restaurar un backup "
                "(backups\\ ) o config/config.example.json."
            ) from e
        return parse_config(data)

    def save(self) -> None:
        # Nunca persistir config invalida (12.1: modo seguro ante config rota).
        _validate(self.cfg)
        self._write(self.cfg, backup=True)

    def _write(self, cfg: AppConfig, backup: bool) -> None:
        if backup and self.path.exists():
            stamp = time.strftime("%Y%m%d-%H%M%S")
            shutil.copy2(
                self.path, self.backup_dir / f"config-{stamp}.json"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(_to_dict(cfg), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def reload(self) -> AppConfig:
        self.cfg = self.load()
        return self.cfg

    # -- helpers -------------------------------------------------------------

    def get_forward(self, fwd_id: str) -> Forward | None:
        return next((f for f in self.cfg.forwards if f.id == fwd_id), None)

    def get_tunnel(self, tun_id: str) -> Tunnel | None:
        return next((t for t in self.cfg.tunnels if t.id == tun_id), None)

    def get_vps(self, vps_id: str) -> Vps | None:
        return next((v for v in self.cfg.vps_list if v.id == vps_id), None)

    def add_forward(self, fwd: Forward) -> None:
        if self.get_forward(fwd.id):
            raise ConfigError(f"forward '{fwd.id}' ya existe")
        self.cfg.forwards.append(fwd)
        self.save()

    def remove_forward(self, fwd_id: str) -> Forward:
        fwd = self.get_forward(fwd_id)
        if not fwd:
            raise ConfigError(f"forward '{fwd_id}' no existe")
        self.cfg.forwards.remove(fwd)
        self.save()
        return fwd

    def add_tunnel(self, tun: Tunnel) -> None:
        if self.get_tunnel(tun.id):
            raise ConfigError(f"tunnel '{tun.id}' ya existe")
        self.cfg.tunnels.append(tun)
        self.save()

    def remove_tunnel(self, tun_id: str) -> Tunnel:
        tun = self.get_tunnel(tun_id)
        if not tun:
            raise ConfigError(f"tunnel '{tun_id}' no existe")
        self.cfg.tunnels.remove(tun)
        self.save()
        return tun

    def add_vps(self, vps: Vps) -> None:
        if self.get_vps(vps.id):
            raise ConfigError(f"vps '{vps.id}' ya existe")
        self.cfg.vps_list.append(vps)
        self.save()

    def remove_vps(self, vps_id: str) -> Vps:
        vps = self.get_vps(vps_id)
        if not vps:
            raise ConfigError(f"vps '{vps_id}' no existe")
        if any(t.vps_id == vps_id for t in self.cfg.tunnels):
            raise ConfigError(
                f"vps '{vps_id}' esta en uso por tunnels; remuevelos primero"
            )
        self.cfg.vps_list.remove(vps)
        self.save()
        return vps

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self.cfg)

    def as_yaml_safe_json(self) -> str:
        return json.dumps(_to_dict(self.cfg), indent=2, ensure_ascii=False)
