# Changelog

## v0.2.4 (2026-08-19) — keepalive SSH para tuneles estables

- Configuracion del VPS (sshd): **ClientAliveInterval 60**,
  **ClientAliveCountMax 3**, **TCPKeepAlive yes** anadidos a
  `vps/sshd_config.snippet` y aplicados automaticamente por `vps/install.sh`.
- Complementa el keepalive del cliente (`ServerAliveInterval=30`) que ya usaba
  `ssh_tunnel_provider.py`, evitando cortes por NAT/firewall.
- Para aplicar en un VPS existente: `sudo bash install.sh` o anade el bloque
  del snippet a `/etc/ssh/sshd_config` y reinicia sshd.

## v0.2.3 (2026-08-19) — puertos propios (independencia de wsl-manager-gui)

- Los puertos por defecto dejan de chocar con wsl-manager-gui: **panel web
  8790 → 8794**, **API REST 8791 → 8795**, **MCP 8792 → 8796**.
- Aplicado en `config.py`, `web/server.py`, `web/__init__.py`, `gui/window.py`,
  `config/config.example.json`, `docker-compose.yml` y documentación.
- Las configs existentes conservan sus valores; esta instalación ya usaba 8794.
- Ambas apps pueden ejecutarse a la vez en la misma máquina sin colisiones.

## v0.2.2 (2026-08-19) — supervisor honra el token DPAPI del panel web

- `src/core/supervisor.py`: `_web_panel_token()` resuelve el token del panel
  primero desde SecretsStore (DPAPI) con fallback a `ui.web_panel_token`
  (legacy). `_sync_web_panel` usa el token resuelto, de modo que el panel
  arrancado por la GUI/supervisor respeta `secrets set web_panel_token`.

## v0.2.1 (2026-08-14) — Remediación de seguridad (High)

- **H1 CSRF**: el panel web exige `Origin`/`Referer` del mismo host en todos
  los POST; scripts deben enviar `Origin: http://<host>:<puerto>`.
- **H2 XSS**: escape `esc()` en todos los sinks `innerHTML` del dashboard;
  headers de seguridad (nosniff, `X-Frame-Options: DENY`, CSP con
  `frame-ancestors 'none'`, `Referrer-Policy`).
- **H3 Concurrencia**: `BoundedThreadingHTTPServer` (máx. 50 conexiones) en
  API y panel; `MetricsStore` con lock que serializa la conexión SQLite.
  Verificado: 200 conexiones paralelas ya no tumban el servidor.
- **H4 Token del panel**: se guarda con `port-forwarder secrets set
  web_panel_token` (DPAPI); `diag` redacta el campo legado en claro;
  advertencia al usar `ui.web_panel_token`.

---

## v0.2.0 (2026-08-14)

### API REST (seccion 21)
- `api enable|disable|status|serve` + `api tokens create|list|revoke` (el token se
  muestra una sola vez; almacen solo hash sha256 en secrets DPAPI).
- `/api/v1/*` completo: status, forwards (CRUD/apply/clear/test/conflicts),
  tunnels (CRUD/start/stop/restart/start-all/stop-all), vps, health, alerts,
  schedule, profiles, maintenance, drift, secrets/check, doctor.
- Scopes read/write/admin (destructivos exigen `?confirm=1`), rate limit por
  token (120 read / 30 write por min), bind loopback, auditoria de cada llamada
  en SQLite. Desactivada por defecto.
- Arranca sola dentro de `supervise` o la GUI si `api.enabled`.

### MCP (seccion 21.4)
- `mcp serve` (stdio, JSON-RPC 2.0) + `mcp test`. 29 tools mapeadas 1:1 al CLI
  (`forward_*`, `tunnel_*`, `vps_*`, `health_*`, `alert_*`, `schedule_*`,
  `profile_*`, `maintenance_*`, `drift_check`, `doctor`, `status`).
- Auth opcional via env `PORT_FORWARDER_TOKEN`.

### Providers P2
- `TailscaleProvider` (serve/funnel T7) y `CloudflareProvider` (T8) con
  dispatch por tipo en el supervisor; `tunnels add --type tailscale|cloudflare
  --local-url [--funnel]`.

### Packaging (seccion 15)
- `scripts/build.ps1` + `scripts/port-forwarder.spec` (PyInstaller one-dir) +
  `scripts/installer.iss` (Inno Setup, instalador por usuario).
- Build verificado: `dist/port-forwarder/port-forwarder.exe` con CLI/API/MCP/web.

### Fixes
- `secrets/check/{ref}` de la API (alias de grupo de ruta).
- Auth: tokens con `expires_days<=0` expiran al instante.

---

## v0.1.0 (2026-08-14)

Primera entrega operativa del plan (fases P0 del `PLAN-PORTFORWARD.md`).

### Core
- `ConfigStore` (config.json validada, backups automáticos, CRUD completo) — Anexo B.
- `Supervisor` de un solo loop: reaplica forwards al cambiar IP de WSL, reinicia
  tunnels muertos con backoff exponencial, health gates (F7/T5), maintenance (F15/A8).
- `Scheduler` (A3) con reloj inyectable: tunnel_start/stop, forwards_apply/clear,
  apply_profile, snapshot_state.
- `Profiles` (A2): capture/apply con transición (abre lo que falta, cierra lo que sobra).
- `MetricsStore` (SQLite): events, alerts, tunnel_uptime, forward_events + purge 30d.
- `SecretsStore` con DPAPI (ctypes), sin dependencias; redactor de secretos en logs.
- `Notifier` (winotify opcional con fallback a log).

### Providers (paridad GUI/CLI/web)
- `NetshProvider`: portproxy + firewall, parse de `show all`, conflictos (netstat),
  port map con drift (ok/missing/extra).
- `WslIpProvider`: `hostname -I` con cache TTL; manejo de distros BusyBox (None).
- `SshTunnelProvider`: `ssh -R` multi-puerto, pidfiles, kill de huerfanos por patrón
  de línea de comandos, health gate T5, latency (T6).

### CLI (`port-forwarder`)
- status, forwards (list/add/remove/apply/clear/test/conflicts/clone),
  tunnels (list/add/remove/start/stop/restart/start-all/stop-all/status/latency/clone),
  vps, portmap, health, alerts, alert thresholds, schedule, profile, secrets,
  config (validate/export/import), doctor, diag, drift, maintenance, connections,
  webhooks, supervise, watch, web (start/stop/status).
- Exit codes 0/1/2/3; `--json` en consultas; destructivos exigen `--yes`.

### Panel web (10.5)
- Dashboard HTML oscuro (forwards, tunnels, uptime, alertas, journal) + API JSON
  `/api/v1` (state/events/alerts/health + acciones) con token Bearer opcional.

### GUI (esqueleto P0)
- Tray + ventana con pestañas Forwards/Tunnels/Logs (extras opcionales).

### Tests
- 74 unit/smoke verdes (config, netsh, wsl_ip, ssh_tunnel, supervisor, scheduler,
  metrics, secrets, logger, web, CLI smoke) + E2E de forward marcado `integration`
  (requiere admin).

### Conocidos / pendientes (P1-P2)
- API REST FastAPI + MCP (sección 21), wizard, autoarranque, packaging,
  Tailscale/Cloudflare, webhooks con reintento, i18n — ver `PLAN-PORTFORWARD.md`.
