# Schema de config.json (Anexo B implementado)

Ubicación: `%APPDATA%\PortForwarder\config.json` (auto-creada con defaults).
Los paths con `%VAR%` se expanden al cargar. Se valida en cada carga
(`config validate`); config inválida → exit 3.

```jsonc
{
  "version": 2,
  "windows": {
    "ssh_exe": "C:\\Windows\\System32\\OpenSSH\\ssh.exe",
    "netsh_exe": "C:\\Windows\\System32\\netsh.exe",
    "wsl_exe": "C:\\Windows\\System32\\wsl.exe"
  },
  "vps_list": [ { "id", "host", "user", "port", "identity_file", "secret_ref" } ],
  "forwards": [ {
    "id", "listen_port", "listen_address", "wsl_distro", "wsl_port",
    "protocol": "tcp|udp", "auto_apply": true,
    "health_check": { "enabled": true, "fail_count_before_pause": 3 },
    "schedule": null | { "days": ["mon"], "start": "09:00", "end": "18:00" }
  } ],
  "tunnels": [ {
    "id", "type": "ssh", "enabled": true, "vps_id",
    "local_bind": { "host": "127.0.0.1", "port": 3000 },
    "remote_binds": [ { "host": "0.0.0.0", "port": 80 } ],
    "keepalive_interval": 30, "keepalive_count": 3,
    "auto_start": true, "health_gate": { "enabled": true },
    "jump": null
  } ],
  "alerts": {
    "tunnel_down_minutes": 2, "forward_fail_count": 3,
    "vps_latency_ms": 500, "check_interval_seconds": 15
  },
  "scheduler": [ {
    "id", "name",
    "action": { "type": "tunnel_start|tunnel_stop|forwards_apply|forwards_clear|apply_profile|snapshot_state", "tunnel": "...", "profile": "..." },
    "schedule": { "days": ["mon","tue"], "time": "09:00" },
    "enabled": true
  } ],
  "profiles": [ { "name", "description", "forwards": [], "tunnels": [] } ],
  "ui": {
    "start_minimized": true, "close_to_tray": true, "theme": "dark",
    "language": "es", "log_level": "INFO",
    "logs_dir": "%LOCALAPPDATA%\\PortForwarder\\logs",
    "supervisor_interval_seconds": 10, "metrics_retention_days": 30,
    "web_panel_enabled": false,
    "web_panel_port": 8790, "web_panel_bind": "127.0.0.1",
    "web_panel_token": ""
  },
  "api":   { "enabled": false, "host": "127.0.0.1", "port": 8791,
             "auth": { "mode": "token", "rate_limit_per_minute": 120 },
             "allowed_ips": ["127.0.0.1"] },
  "mcp":   { "enabled": false, "transport": "stdio", "port": 8792,
             "token_required": true },
  "on_close": { "keep_tunnels_alive": true, "clear_forwards": false },
  "webhooks": [ { "id", "url", "events": [], "secret_ref": null } ],
  "maintenance": { "active": false, "start": null, "end": null }
}
```

## Reglas de validación

- IDs únicos dentro de cada lista (y entre listas).
- Puertos 1-65535; `protocol` ∈ {tcp, udp}; `type` ∈ {ssh, tailscale, cloudflare}.
- `tunnels[].vps_id` debe existir en `vps_list`.
- `ui.supervisor_interval_seconds >= 2`.
- Backups automáticos en `%APPDATA%\PortForwarder\backups\` antes de cada escritura.

## Campos nuevos respecto al plan (v2.1)

| Campo | Motivo |
|-------|--------|
| `ui.web_panel_port` / `web_panel_bind` | Panel web stdlib (10.5) |
| `ui.web_panel_token` | **Deprecado (v0.2.1)**: guardar con `secrets set web_panel_token` (DPAPI); el campo legado solo se usa como respaldo con aviso y se redacta en `diag` |
| `webhooks` | M11 (P1, ya operativo en CLI) |
| `maintenance` | F15/A8 (P1, ya operativo) |
| `ui.auto_assign_port_range` | F17 (P1) |
