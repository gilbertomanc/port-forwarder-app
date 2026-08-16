# Decisiones (Fase 0 del plan)

| # | Decisión | Estado |
|---|----------|--------|
| 1 | **Stack**: core y CLI en **Python stdlib puro** (sin pydantic/typer). La validación de config se hace con dataclasses + checks manuales replicando el Anexo B. Motivo: cero fricción de instalación en cualquier Windows con Python; el plan permite argparse estándar (19.3). | ✅ |
| 2 | GUI (ttkbootstrap + pystray) como **extras opcionales** (`pip install "port-forwarder[gui]"`), con mensaje claro si faltan. | ✅ |
| 3 | Panel web (10.5) con **http.server stdlib** en vez de FastAPI: misma API JSON `/api/v1`, cero dependencias, token Bearer opcional, bind loopback por defecto. FastAPI queda para la API REST de la sección 21 (P1). | ✅ |
| 3b | **API REST (21)** y **servidor MCP (21.4)** también en **stdlib puro** (http.server + JSON-RPC 2.0): AuthService con tokens hash+scopes+rate limit+auditoría, MCP stdio con handshake estándar y token vía `PORT_FORWARDER_TOKEN`. Se descarta FastAPI/mcp por consistencia (cero dependencias) y soporte incierto en Python 3.14. | ✅ |
| 3c | Providers **Tailscale/Cloudflare** (T7/T8): comandos por convención de cada herramienta, sin instalación real en este entorno — cubiertos con tests de mocks y estados degradados si el binario no existe. | ✅ (pendiente prueba real) |
| 4 | VPS real: **no disponible en este entorno** — la app se probó con hosts ficticios (`vps.example.com`) y distros WSL docker/rancher (sin `hostname -I`). El código trata ambos casos con estados degradados claros. | ⏳ pendiente |
| 5 | Retención de métricas: **30 días** (`ui.metrics_retention_days`, configurable). | ✅ |
| 6 | Idioma: **es** por defecto (`ui.language`), i18n en P2. | ✅ |
| 7 | Scope P0 confirmado: config+logger+event_bus, providers netsh/wsl/ssh, supervisor, scheduler, profiles, metrics, secrets DPAPI, CLI completo (19), panel web (10.5), scripts VPS, tests. | ✅ |
| 8 | **P1/P2 adicionales entregados**: API REST completa (21.3), MCP stdio (21.4), tailscale/cloudflare (T7/T8), packaging PyInstaller one-dir + script Inno (15), mantenimiento (F15/A8), drift (F13), clones (F14), webhooks (M11), conexiones activas (F16), auto-assign (F17). | ✅ |

## Notas de arquitectura

- **Un solo loop** (12.3): el Supervisor es el único que toca providers; GUI/CLI/web
  solo disparan acciones o leen estado. Paridad garantizada por diseño.
- **UAC selectivo** (13.2): solo `add_forward`/`remove_forward` elevan cuando el
  proceso no es admin; el resto corre sin elevación.
- **IP dinámica de WSL** (punto crítico del plan): IP obtenida al momento de
  aplicar, cache con TTL, y el supervisor reaplica al detectar cambio.
