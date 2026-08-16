# Troubleshooting

| Síntoma | Causa probable | Acción |
|---------|----------------|--------|
| `exit 3` al ejecutar cualquier comando | config.json inválida (p.ej. tunnel con `vps_id` inexistente) | `port-forwarder config import config/config.example.json` para restaurar, o edita el archivo. Hay backups en `%APPDATA%\PortForwarder\backups\`. |
| `forwards apply` falla | sin admin | Acepta el prompt UAC (solo aplicar/limpiar requiere elevación) |
| Forward aplicado pero sin respuesta | distro WSL detenida / servicio caído | `wsl -l` para el nombre; el health gate pausa el forward tras K fallos |
| `forwards add --auto-apply` dice "no se encontro IP" | distro no responde `hostname -I` (docker-desktop/rancher usan BusyBox) | Usa una distro real (ubuntu). El supervisor reaplica solo al cambiar la IP |
| IP cambió tras `wsl --shutdown` | NAT asigna IP nueva | Espera un ciclo del supervisor (interval configurable) o `forwards apply --all` |
| Tunnel se reinicia en bucle | VPS inalcanzable o `GatewayPorts off` | `port-forwarder doctor`; verifica `vps/sshd_config.snippet` en el VPS |
| `tunnels status` dice stopped con health gate | servicio local no responde (T5) | Levanta el servicio local antes de arrancar el tunnel |
| `secrets check` falla | secret no definido | `port-forwarder secrets set <ref>` (el valor se pide por stdin) |
| Panel web no abre | puerto ocupado o bind inválido | `port-forwarder web status`; cambia `ui.web_panel_port`; usa `--bind 0.0.0.0` + token para red |
| `web start --bind 0.0.0.0` se niega | falta token | `printf 'token' | port-forwarder secrets set web_panel_token` y reintenta |
| `web start` con curl/POST da 403 | proteccion CSRF (v0.2.1) | añade `-H "Origin: http://127.0.0.1:8790"` (el mismo host y puerto del panel) |
| `conflicts` reporta puerto ocupado | otro servicio escucha | Cambia el puerto o detén el servicio |
| Logs sin secretos visibles | redactor global (por diseño) | Busca el evento en SQLite (`events`) si necesitas auditoría |
| `python -m src.cli` no encuentra `src` | ejecutado fuera del repo | Corre desde `port-forwarder-app/` o instala con `pip install -e .` |

## Checklist de release manual (14.3)

- [ ] Instalación limpia Win 10/11 (config auto-creada, `doctor` sano)
- [ ] Forward real: `forwards add --auto-apply` → `forwards test` → `forwards clear`
- [ ] Suspender/reanudar reaplica en < 60s (A4)
- [ ] Matar ssh a mano → el supervisor lo reinicia solo
- [ ] `wsl --shutdown` externo → forwards reaplicados
- [ ] Conflicto de puerto detectado (`forwards conflicts`)
- [ ] Panel web: dashboard, acciones y token
- [ ] Bundle `diag` sin secretos
