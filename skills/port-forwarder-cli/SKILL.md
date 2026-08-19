---
name: port-forwarder-cli
description: "Operar Port Forwarding Manager desde la terminal: forwards Windows-WSL (netsh), tunnels a VPS, health checks, perfiles, secrets y diagnostico. Para exponer servicios o gestionar forwards/tunnels sin la GUI."
---

# Port Forwarding Manager CLI — Guia para agentes LLM

## 1. Contexto y cuando usar

Port Forwarding Manager es una app de escritorio (system tray) para gestionar **redireccion de puertos**: forwards Windows<->WSL (netsh portproxy + firewall) y tunnels hacia VPS (SSH, Tailscale, Cloudflare). Su CLI (`port-forwarder`, o `python -m src.cli` desde el repo) tiene la **misma capacidad que la GUI** (paridad garantizada: ambos usan los mismos providers). Usa esta skill siempre que debas:

- Crear, aplicar, probar o limpiar forwards (netsh portproxy + firewall).
- Iniciar, detener o reconectar tunnels SSH/Tailscale/Cloudflare hacia un VPS.
- Gestionar VPS, health checks, alertas, mapa de puertos, drift y mantenimiento.
- Programar tareas, aplicar perfiles de exposicion o gestionar secrets/webhooks.
- Diagnosticar problemas (doctor, diag).

## 2. Requisitos previos

- Windows 10/11 con `netsh.exe` y `ssh.exe` disponibles.
- La app instalada y el binario `port-forwarder` en PATH (o `python -m src.cli` desde el repo).
- VPS configurado con `GatewayPorts yes` (para tunnels SSH) y llave copiada.
- Para aplicar/limpiar forwards: permisos de administrador (la app solicita UAC).

## 3. Convenciones

| Regla | Detalle |
|-------|---------|
| Salida | Humana por defecto; `--json` para parsear |
| Exit codes | `0` OK, `1` error funcional, `2` argumentos invalidos, `3` config invalida |
| Seguridad | `secrets` **nunca** imprime el valor en claro; solo confirma existencia |
| Destructivos | `clear`, `stop-all`, `drift reconcile --cleanup` exigen flag `--yes` |

## 4. Comandos

### Estado y consulta

```bash
port-forwarder status [--json]
port-forwarder forwards list [--json]
port-forwarder tunnels list [--json]
port-forwarder tunnels status <id> [--json]
port-forwarder vps list [--json]
port-forwarder portmap [--json]
port-forwarder connections <forward_id> [--json]
port-forwarder web status [--json]
```

### Forwards (Windows-WSL, requieren admin al aplicar/limpiar)

```bash
port-forwarder forwards add --id fwd-web --listen-port 8080 --distro ubuntu-dev --wsl-port 3000 [--listen-address 0.0.0.0] [--proto tcp|udp] [--auto-apply] [--no-health-check]
port-forwarder forwards remove <id>
port-forwarder forwards apply [--all]        # sin --all solo aplica los auto_apply
port-forwarder forwards clear --yes          # limpieza total (destructivo)
port-forwarder forwards test <id>
port-forwarder forwards conflicts <puerto>
port-forwarder forwards clone <id> --new-id X [--listen-port N] [--wsl-port N]
```

> [!WARNING] Forward con admin
> Aplicar/limpiar forwards requiere elevacion (UAC). Si el comando falla por permisos, avisar al usuario para que acepte el prompt.

### Tunnels (hacia VPS)

```bash
port-forwarder tunnels add --id tunnel-web --vps vps-main --local 127.0.0.1:3000 --remote 0.0.0.0:80 [--remote 0.0.0.0:443] [--jump vps-a] [--keepalive-interval 30] [--keepalive-count 3] [--no-auto-start] [--no-health-gate]
port-forwarder tunnels add --id tun-ts --type tailscale --local-url http://127.0.0.1:3000 [--funnel]   # o --type cloudflare
port-forwarder tunnels remove <id>
port-forwarder tunnels start <id> | stop <id> | restart <id>
port-forwarder tunnels start-all
port-forwarder tunnels stop-all --yes        # destructivo
port-forwarder tunnels status <id> [--json]
port-forwarder tunnels latency <id>
port-forwarder tunnels clone <id> --new-id X
```

### VPS

```bash
port-forwarder vps add --id vps-main --host vps.example.com --user tunnel [--port 22] [--identity "ruta"]
port-forwarder vps remove <id>
```

### Health, alertas y umbrales

```bash
port-forwarder health check [--json]
port-forwarder alerts list [--json] [--state open|resolved]
port-forwarder alerts resolve <id>
port-forwarder alert thresholds [get]
port-forwarder alert set --tunnel-down-minutes 2 --forward-fail-count 3 [--vps-latency-ms N] [--check-interval-seconds N]
```

### Drift y mantenimiento

```bash
port-forwarder drift check [--json]            # config vs realidad (F13)
port-forwarder drift reconcile [--cleanup] --yes   # aplica lo que falta (destructivo)
port-forwarder maintenance on | off
port-forwarder maintenance status [--json]
port-forwarder maintenance schedule --start HH:MM --end HH:MM
```

### Webhooks (M11)

```bash
port-forwarder webhooks add --url https://hooks.example.com/x --events alert,tunnel-down [--secret <ref>]
port-forwarder webhooks list [--json]
port-forwarder webhooks remove <id>
```

### Programacion y perfiles

```bash
port-forwarder schedule list [--json]
port-forwarder schedule add --name "Web 9-18h" --type tunnel_start --tunnel tunnel-web --time 09:00 --days mon,tue,wed,thu,fri
# tipos: tunnel_start | tunnel_stop | forwards_apply | forwards_clear | apply_profile | snapshot_state
port-forwarder schedule remove <id>
port-forwarder profile list [--json]
port-forwarder profile apply <nombre>
port-forwarder profile capture <nombre> [--desc "descripcion"]
```

### Secrets y configuracion

```bash
port-forwarder secrets set <ref>          # pide el valor por stdin (nunca por argumento)
port-forwarder secrets check <ref>
port-forwarder config validate
port-forwarder config export <ruta>
port-forwarder config import <ruta>
```

### Diagnostico y modos operativos

```bash
port-forwarder doctor
port-forwarder diag
port-forwarder supervise                 # supervisor headless (Ctrl+C para salir)
port-forwarder watch                     # eventos en vivo estilo tail
port-forwarder gui show|hide|quit        # control de la GUI via IPC
```

### Panel web local

```bash
port-forwarder web start [--port 8794] [--bind 127.0.0.1] [--no-supervisor]
port-forwarder web stop
port-forwarder web status [--json]
printf 'token' | port-forwarder secrets set web_panel_token   # token cifrado (DPAPI)
```

- Abre el dashboard en `http://127.0.0.1:8794` (mismo estado y acciones que CLI/GUI).
- El panel arranca tambien el supervisor salvo `--no-supervisor`.
- El token del panel se guarda en secrets (DPAPI); si se usa, la API exige
  `Authorization: Bearer <token>` (el navegador la pide una vez).
- **CSRF (importante):** los POST del panel exigen `Origin`/`Referer` del mismo
  host. Scripts con curl: añade `-H "Origin: http://127.0.0.1:8794"`.
- Para consultar desde el movil: `--bind 0.0.0.0` y token obligatorio (sin token, `web start` solo avisa, no bloquea).

### API REST

```bash
port-forwarder api enable [--port 8795]  # activa (token obligatorio)
port-forwarder api disable
port-forwarder api status [--json]
port-forwarder api serve [--port N]      # foreground
port-forwarder api tokens create --scope read|write|admin [--expires 30d]
port-forwarder api tokens list [--json]
port-forwarder api tokens revoke <id>
```

- Endpoints en `http://127.0.0.1:8795/api/v1/*`; header `Authorization: Bearer <token>`.
- Scopes: read < write < admin; destructivos exigen `?confirm=1`.
- El token se muestra **una sola vez** al crearlo.

### MCP

```bash
PORT_FORWARDER_TOKEN=<token> port-forwarder mcp serve   # stdio para agentes
port-forwarder mcp test                                 # self-test
```

- Cliente (Zed/Claude Code): `command: port-forwarder, args: ["mcp","serve"], env: {PORT_FORWARDER_TOKEN: "<token>"}`.
- Tools: `status`, `forward_*` (list/add/remove/apply/clear/test/conflicts), `tunnel_*` (list/start/stop/restart), `vps_*` (list/add/remove), `health_check`, `alert_*`, `schedule_*`, `profile_*`, `maintenance_*`, `drift_check`, `doctor`. Cada tool devuelve `{ok, data, message}`.
- El token solo se exige si la env var esta definida; `mcp test` valida el handshake.

## 5. Flujo recomendado

1. `port-forwarder doctor` → confirmar entorno sano (ssh/netsh/VPS alcanzable; si falla, resolver).
2. `port-forwarder status --json` → estado actual.
3. Ejecutar la accion pedida (forward o tunnel).
4. Verificar: `port-forwarder forwards test <id>` y/o `tunnels status <id>`.
5. Si algo falla: reportar exit code + salida relevante.

## 6. Reglas para agentes

- **Nunca** ejecutar acciones destructivas (`forwards clear`, `tunnels stop-all`, `vps remove`, `schedule remove`, `drift reconcile --cleanup`) sin confirmacion explicita del usuario; las que lo piden llevan `--yes`.
- `secrets set` se alimenta por stdin; **jamas** pasar el valor como argumento (queda en historial del shell).
- No imprimir contenido de `secrets` ni llaves; usar `secrets check`.
- Usar `--json` y validar el exit code antes de interpretar la salida.
- Si `doctor` reporta problemas (VPS inalcanzable, GatewayPorts off, puerto en conflicto), corregirlos antes de operar.
- Recordar que los forwards requieren admin (UAC); si falla por permisos, avisar al usuario.
- Salida final al usuario: resumen breve con estado antes/despues.

## 7. Troubleshooting

| Sintoma | Causa probable | Accion |
|---------|----------------|--------|
| exit 3 | config.json invalida | `config validate` y revisar schema |
| `forwards apply` falla | sin admin | reintentar aceptando UAC |
| tunnel se reinicia en bucle | VPS inalcanzable o GatewayPorts off | `doctor`, verificar sshd_config del VPS y firewall |
| `forwards conflicts` reporta puerto ocupado | otro servicio lo usa | elegir otro puerto o detener el servicio |
| `secrets check` falla | secret no definido | `secrets set <ref>` primero |
| IP no encontrada | distro WSL detenida o inexistente | verificar nombre de distro con `status --json` |
| `drift reconcile` no aplica | falta `--yes` | confirmar con el usuario y anadir `--yes` |
