# Arquitectura

Sigue las secciones 4 y 12 del plan. Capas:

```
┌─────────────────────────────────────────────────────────┐
│ Interfaces:  GUI (tray/tkinter) · CLI (port-forwarder)   │
│              Panel web (/api/v1 + dashboard)             │
├─────────────────────────────────────────────────────────┤
│ Servicios (core): Supervisor (un solo loop) · Scheduler  │
│   · Profiles · MetricsStore (SQLite) · Secrets (DPAPI)   │
│   · Notifier · EventBus (pub/sub)                        │
├─────────────────────────────────────────────────────────┤
│ Providers (paridad garantizada):                         │
│   NetshProvider (portproxy+firewall)                     │
│   WslIpProvider (IPs con cache)                          │
│   SshTunnelProvider (ssh -R, pidfiles, backoff)          │
├─────────────────────────────────────────────────────────┤
│ Sistema: netsh.exe · powershell.exe (firewall) ·         │
│          wsl.exe · ssh.exe · winotify (opcional)         │
└─────────────────────────────────────────────────────────┘
```

## Modelo de threads (4.3)

| Thread | Rol |
|--------|-----|
| Supervisor | Loop único: IPs → forwards → tunnels → health → métricas (daemon) |
| Scheduler | Evalúa tareas por minuto (daemon) |
| Web panel | `ThreadingHTTPServer.serve_forever` (daemon) |
| GUI | Main thread de tkinter + tray |

Todos comparten `EventBus` (thread-safe) para `state-changed`, `tunnel-down`, etc.
`MetricsStore` es thread-safe por conexión única + commit por operación.

## Flujo clave: reaplicar forwards (8.5)

1. `Supervisor.run_once()` obtiene `get_all_ips(distro)` (cache 5s).
2. Si la IP cambió → evento `wsl_ip_changed` + reaplicar.
3. Por cada forward `auto_apply`: si no existe en netsh o difiere → `remove` (si existía) + `add` con la IP nueva.
4. Health gate (F7): tras K fallos de TCP al `listen_port` → `paused`, reintento cada 60s; al recuperarse → `ok` + reaplicar.
5. Tunnels: `is_alive()` (proceso + health gate T5); si muerto y `auto_start` → restart con backoff exponencial 5s·2ⁿ (cap 300s).

## Errores (4.4)

- Providers devuelven `CommandResult(ok, output, error, exit_code)`; nunca lanzan en flujos de consulta.
- El supervisor captura cualquier excepción por ciclo (el loop nunca muere) y registra alerta en SQLite.
- Config inválida → `ConfigError` → CLI exit 3 con mensaje accionable (`config import` para restaurar).
- Los comandos destructivos exigen `--yes` (CLI) o confirmación (web/GUI).

## Seguridad (13)

- Secrets cifrados con DPAPI (CurrentUser) vía ctypes; nunca se imprimen.
- Redactor global de logs (tokens, passphrases, llaves).
- Backups de config antes de cada escritura (`backups/`).
- Panel web: loopback por defecto; token Bearer si se expone en red.
- Journal de todas las acciones en SQLite (`events`, `forward_events`).
