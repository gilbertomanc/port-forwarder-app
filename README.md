# Port Forwarding Manager

Gestión de **redirección de puertos Windows → WSL** (netsh portproxy + firewall) y **túneles SSH hacia VPS**, con supervisor automático, health checks, alertas, programador, perfiles, panel web y CLI completo con **paridad garantizada** con la GUI.

> Implementación de las fases P0 del plan `PLAN-PORTFORWARD.md` (docs: `docs/decisions.md`).

## Características

| Área | Funcionalidad |
|------|---------------|
| Forwards (F1-F8, F14) | CRUD, aplicar/limpiar (netsh + firewall), test TCP, detector de conflictos, clone |
| Tunnels (T1-T6) | SSH reverse multi-puerto, start/stop/restart, health gate, latency, clone |
| Supervisor (12.3) | Loop único: IPs WSL cambian → reaplica; tunnel muerto → backoff + restart; health gate pausa forwards sin servicio |
| Monitoring (M3-M6) | Health checks, alertas (SQLite), portmap, conexiones activas |
| Automatización (A2-A3) | Scheduler por días/hora, perfiles de exposición (capture/apply) |
| Seguridad (13) | Secrets cifrados con DPAPI, redactor de secretos en logs, backups de config, journal en SQLite |
| Diagnóstico (U7-U8) | `doctor` (detector de problemas), `diag` (bundle sin secretos), `drift` (config vs realidad) |
| **Panel web (10.5)** | Dashboard HTML en `127.0.0.1:8794` + API JSON `/api/v1`, token opcional, uptime de túneles |
| **API REST (21)** | `/api/v1` completa (forwards, tunnels, vps, health, alerts, schedule, profiles, maintenance, drift) con tokens Bearer + scopes read/write/admin, rate limit y auditoría |
| **MCP (21.4)** | Servidor stdio JSON-RPC (`mcp serve`) con 29 tools mapeadas al CLI, token via `PORT_FORWARDER_TOKEN` |
| GUI (7) | Tray + ventana con pestañas (requiere extras opcionales) |

## Requisitos

- Windows 10/11 con `netsh.exe`, `ssh.exe` y `wsl.exe` (System32).
- Python 3.11+ (core sin dependencias externas).
- Una distro WSL real (ej. `ubuntu`) para forwards; un VPS con `GatewayPorts yes` para túneles.
- Admin (UAC) solo para aplicar forwards — el resto corre sin elevación.

## Linux y Docker

El **core es multiplataforma** (Python 3.11+): panel web, supervisor, túneles SSH,
API REST, MCP, programador, perfiles, alertas y CLI funcionan en Linux y macOS
sin dependencias externas. Solo los **forwards Windows→WSL** (`netsh portproxy` +
firewall) son exclusivos de Windows.

### Ejecutar en Linux (sin contenedor)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .  # core, sin extras de GUI

port-forwarder doctor                              # entornos no soportados: avisa
port-forwarder vps add --id vps-main --host vps.example.com --user tunnel --identity ~/.ssh/wsl-manager-main
port-forwarder tunnels add --id tunnel-web --vps vps-main --local 127.0.0.1:8080 --remote 0.0.0.0:80
port-forwarder web start                           # panel web + supervisor en foreground
```

Los datos viven en `$XDG_CONFIG_HOME/PortForwarder` o `~/.config/PortForwarder` y los
logs en `$XDG_DATA_HOME/PortForwarder/logs`.

### Contenedor Docker

```bash
# clave del panel (si se omite, el entrypoint la genera y la muestra en los logs)
export PF_WEB_TOKEN=mi-clave-secreta

docker compose build
docker compose up -d
# panel web en http://localhost:8794 (requiere la clave)
```

- Imagen: `python:3.11-slim` + `openssh-client` (para los túneles SSH).
- Volumen `pf-data` en `/data` (config, secrets, métricas, pidfiles) — es persistente.
- Opcional: monta tus claves SSH con `- ${USERPROFILE}/.ssh:/root/.ssh:ro` en `docker-compose.yml`.
- Puertos: `8794` panel web · `8795` API REST · `8796` MCP (si se activan).
  No chocan con wsl-manager-gui (que usa 8790/8791/8792): ambas apps pueden
  correr a la vez en la misma máquina.

## Instalación

```powershell
# Desde el repo:
python -m pip install -e .

# (Opcional) extras de GUI:
python -m pip install pystray ttkbootstrap Pillow winotify
```

Config inicial en `%APPDATA%\PortForwarder\config.json` (auto-creada).
Ejemplo completo: `config/config.example.json`.

## Uso rápido (CLI)

```bash
port-forwarder doctor                          # entorno sano?
port-forwarder status --json                   # estado global

# Forward Windows -> WSL (pide UAC al aplicar)
port-forwarder forwards add --id fwd-web --listen-port 8080 --distro ubuntu-dev --wsl-port 8080 --auto-apply
port-forwarder forwards test fwd-web
port-forwarder forwards conflicts 8080

# Tunnel hacia VPS (prepara el VPS con vps/install.sh y scripts/setup_ssh_key.ps1)
port-forwarder vps add --id vps-main --host vps.example.com --user tunnel --identity "%USERPROFILE%\.ssh\wsl-manager-main"
port-forwarder tunnels add --id tunnel-web --vps vps-main --local 127.0.0.1:8080 --remote 0.0.0.0:80
port-forwarder tunnels start tunnel-web
port-forwarder tunnels status tunnel-web --json

# Supervisión
port-forwarder supervise                      # supervisor headless (Ctrl+C)
port-forwarder watch --json                   # eventos en vivo
port-forwarder health check --json
port-forwarder alerts list
```

### Panel web

```bash
# Token del panel (recomendado, cifrado DPAPI):
printf 'mi-token' | port-forwarder secrets set web_panel_token

port-forwarder web start                       # dashboard en http://127.0.0.1:8794
port-forwarder web status --json
port-forwarder web stop

# Desde el móvil (misma red), con token obligatorio:
port-forwarder web start --bind 0.0.0.0        # exige token configurado
```

El dashboard muestra forwards/tunnels con estado en vivo, alertas, uptime de túneles y journal de eventos; permite reaplicar forwards, limpiar, arrancar/detener túneles y activar mantenimiento desde el navegador. API JSON en `/api/v1/*` (Bearer token opcional).

> **Seguridad:** los POST del panel exigen `Origin`/`Referer` del mismo host (CSRF).
> Si automatizas con curl, añade `-H "Origin: http://127.0.0.1:8794"`. El token se
> guarda cifrado en secrets (DPAPI): `secrets set web_panel_token`.

### API REST (para scripts e integraciones)

```bash
port-forwarder api enable --port 8795          # activa (token obligatorio)
port-forwarder api tokens create --scope admin # muestra el token UNA sola vez
port-forwarder api tokens list
port-forwarder api serve                       # corre la API en foreground
```

Endpoints en `http://127.0.0.1:8795/api/v1` (tabla completa en el plan, 21.3): `status`, `forwards` (CRUD/apply/clear/test/conflicts), `tunnels` (CRUD/start/stop/restart), `vps`, `health`, `alerts`, `schedule`, `profiles`, `maintenance`, `drift`, `secrets/check`, `doctor`. Scopes: `read` < `write` < `admin` (destructivos exigen `?confirm=1`). Rate limit 120 req/min read, 30 write. Auditoría de cada llamada en SQLite.

### MCP (para agentes LLM)

```bash
port-forwarder mcp test                        # self-test del handshake
PORT_FORWARDER_TOKEN=<token> port-forwarder mcp serve   # stdio
```

Configuración en el cliente (Zed / Claude Code):

```json
{ "mcpServers": { "port-forwarder": {
  "command": "port-forwarder", "args": ["mcp", "serve"],
  "env": { "PORT_FORWARDER_TOKEN": "<token>" } } } }
```

## Exit codes del CLI

| Código | Significado |
|--------|-------------|
| 0 | OK |
| 1 | Error funcional |
| 2 | Argumentos inválidos |
| 3 | Config inválida |

## Tests

```bash
python -m pytest tests/unit -q          # unit (sin admin)
python -m pytest tests/test_cli.py -q   # smoke del CLI (sin admin)
python -m pytest tests -m integration   # E2E real (requiere admin + distro WSL)
```

## Estructura

```
src/
├── app.py                 # Entry GUI (tray + ventana, extras opcionales)
├── core/                  # config, supervisor, scheduler, metrics, profiles, notifier, power_events
├── providers/             # netsh, wsl_ip, ssh_tunnel, tailscale, cloudflare (paridad GUI/CLI/web)
├── cli/                   # port-forwarder (argparse, cero dependencias)
├── api/                   # REST /api/v1 + AuthService (tokens, scopes, rate limit)
├── mcp/                   # servidor MCP stdio (JSON-RPC)
├── web/                   # panel web stdlib + API JSON
├── gui/                   # ventana tkinter + tray (opcional)
└── utils/                 # subprocess, paths, secrets DPAPI
scripts/                   # setup_ssh_key.ps1, check_environment.ps1, install_autossh.sh, smoke_web_live.py, build.ps1, port-forwarder.spec, installer.iss
vps/                       # sshd_config.snippet + install.sh
skills/port-forwarder-cli/ # skill para agentes LLM
```

## Packaging

```powershell
pip install pyinstaller
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
# -> dist\port-forwarder\port-forwarder.exe  (+ PortForwarder-Setup.exe si hay Inno Setup)
```

> Si el `python` del PATH no tiene PyInstaller (p. ej. apunta a otro venv),
> usa el venv del proyecto directamente:
> ```powershell
> .venv\Scripts\python.exe -m PyInstaller --clean --noconfirm scripts\port-forwarder.spec
> ```

## Roadmap pendiente (P2 del plan)

- Wizard de primer uso (U1, GUI), autoarranque, auto-update.
- i18n (U9), command palette (U2), cadenas (A6), escenarios (A7).
- Blueprint de exposición (U11), webhooks con reintento, cambio de red (A5).
- Ver `PLAN-PORTFORWARD.md` (fases 5-8).
