# Reporte de Seguridad — Port Forwarding Manager v0.2.0

| Campo | Valor |
|---|---|
| **Fecha** | 2026-08-14 |
| **Alcance** | `port-forwarder-app/` (core, CLI, API REST, MCP, panel web, packaging) |
| **Metodología** | PTES (reconocimiento → enumeración → explotación → reporte) + code security review (SAST, revisión manual de flujos) |
| **Herramientas** | bandit 1.9.4, pip-audit, curl (matriz AuthZ, CSRF, XSS), pruebas de concurrencia, grep de secretos |
| **Autorización** | Propietario del sistema (aplicación local de desarrollo) |

## Resumen ejecutivo

La aplicación tiene una **base sólida**: cero dependencias runtime (stdlib), sin inyección de comandos, matriz AuthZ correcta en la API REST (401/403/200 por scope), secrets cifrados con DPAPI que no se filtran, redactor de logs y sin secretos hardcodeados. Los hallazgos se concentran en las **interfaces web** (panel y API): **CSRF y XSS almacenado** en el dashboard, **crash del servidor bajo concurrencia** y **fuga del token del panel** en el bundle de diagnóstico.

| Severidad | Cantidad |
|---|---|
| Critical | 0 |
| High | 4 |
| Medium | 4 |
| Low | 4 |
| Info | 8 |

---

## Hallazgos

### H1 — CSRF en el panel web: acciones destructivas sin protección — HIGH

- **CWE-352 (CSRF)** · OWASP A01/A05 (Broken Access Control / Misconfiguration) · API4 OWASP API
- **Descripción:** el panel web expone acciones POST destructivas (`forwards/clear`, `maintenance/on`, `tunnels/stop`, `forwards/apply`) **sin verificar Origin/Referer, sin token CSRF y sin autenticación por defecto**. Cualquier página web abierta por el usuario (o cualquier host de la LAN si el panel usa `--bind 0.0.0.0`) puede disparar esas acciones con un simple formulario HTML.
- **Evidencia (E1):** `POST /api/v1/forwards/clear?confirm=1` y `POST /api/v1/maintenance/on?confirm=1` → **200** sin ningún header de origen ni token.
- **Reproducción:**
  ```bash
  curl -X POST "http://127.0.0.1:8902/api/v1/forwards/clear?confirm=1"   # -> 200
  ```
- **Impacto:** limpieza de forwards, detención de túneles, activación de mantenimiento sin consentimiento.
- **Recomendación:** exigir `Origin`/`Referer` del mismo host en los POST; añadir token CSRF (cookie `SameSite=Strict` o header `X-CSRF`); habilitar token Bearer por defecto en el panel.

### H2 — XSS almacenado en el dashboard web — HIGH

- **CWE-79** · OWASP A03 (Injection) · T1059.007 / T1189 (MITRE)
- **Descripción:** `renderForwards`, `renderTunnels` y `renderAlerts` del dashboard construyen HTML con `innerHTML` **sin escapar** `id` de forwards/tunnels, hosts remotos y mensajes de alerta. Un payload plantado en un `id` (vía CLI o API con token write) se ejecuta en el navegador de quien abra el dashboard.
- **Evidencia (E2):** el API acepta y devuelve el id `<img src=x onerror=alert(document.cookie)>`; el código del dashboard lo inserta vía `innerHTML`.
- **Impacto:** robo del token del panel (localStorage) → abuso de la API; ejecución de JS en el contexto del usuario.
- **Recomendación:** escapar con `textContent` o función `escapeHtml()` en todos los sinks de `innerHTML`; añadir CSP (`script-src 'self' 'unsafe-inline'` mínimo, idealmente nonce).

### H3 — DoS/estabilidad: el servidor API muere con ~130 conexiones concurrentes — HIGH

- **CWE-400 / CWE-362 (race)** · OWASP A04 (Insecure Design) · T1499.004 (MITRE)
- **Descripción:** `ThreadingHTTPServer` crea un hilo por conexión **sin límite** y `audit()` escribe en una **única conexión SQLite compartida** (`MetricsStore._conn`) desde todos los hilos sin lock. Con 130 peticiones en paralelo el proceso deja de responder (reproducido 2 veces; 0 LISTENING).
- **Evidencia (E3):** ráfaga de 130 GETs → `{0: 130}`, `curl` → 000, `netstat` → sin listener.
- **Impacto:** cualquier proceso local (o host de la LAN con bind abierto) puede tumbar la API; pérdida de supervisión.
- **Recomendación:** serializar SQLite con `threading.Lock` en `MetricsStore`; limitar hilos (pool acotado o `socketserver.ThreadingMixIn` con semáforo); manejar fallos de hilo sin matar `serve_forever`.

### H4 — Fuga del token del panel web: en claro en config y en el bundle `diag` — HIGH

- **CWE-312 / CWE-256** · OWASP A02 (Cryptographic Failures) · T1552 (MITRE)
- **Descripción:** `ui.web_panel_token` se guarda **en claro** en `config.json` y se incluye **íntegro en `diag.json`** (el bundle de diagnóstico diseñado para compartirse con soporte). Viola el principio 13.1 del plan (secrets cifrados en `secrets.json`, referencias `secret_ref` en config).
- **Evidencia (E4):** token presente en `config.json` y en `diag.json`.
- **Impacto:** si el usuario comparte `diag.json`, el token permite control total del panel web y de la API.
- **Recomendación:** mover el token a `SecretsStore` (DPAPI) con `secret_ref`, o almacenar solo su hash (como los tokens de la API); **excluir/redactar** `ui.web_panel_token` en `diag`.

### M1 — Headers de seguridad ausentes en API y dashboard — MEDIUM

- **CWE-1021 / CWE-693** · OWASP A05
- **Descripción:** ninguna respuesta incluye `X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`, `Referrer-Policy` ni `Permissions-Policy`. El dashboard tiene botones destructivos → **clickjacking** viable (iframe invisible).
- **Evidencia (E5):** solo `Content-Type` y `Cache-Control: no-store`.
- **Recomendación:** `X-Frame-Options: DENY` (o `frame-ancestors 'none'`), `X-Content-Type-Options: nosniff`, CSP mínima, `Referrer-Policy: no-referrer`.

### M2 — Autenticación sin límite de intentos fallidos — MEDIUM

- **CWE-307** · OWASP A07 · T1110 (MITRE)
- **Descripción:** el rate limit solo aplica a peticiones **autenticadas**; los fallos de auth (token inválido) no cuentan: 40 intentos en paralelo → 401 sin 429 ni backoff. **Mitigado por entropía** (token_urlsafe(32) ≈ 256 bits): fuerza bruta infeasible; el riesgo real es CPU/DoS menor.
- **Evidencia (E6).**
- **Recomendación:** contabilizar fallos de auth en el rate limit y añadir backoff exponencial por IP/token.

### M3 — Forwards en `0.0.0.0` + firewall abierto a cualquier origen, sin advertencia — MEDIUM

- **CWE-284** · OWASP A01 · T1046 (MITRE)
- **Descripción:** por defecto `listen_address=0.0.0.0` y la regla `New-NetFirewallRule -Action Allow` acepta **cualquier origen**. Es el propósito de la app, pero el usuario no recibe ninguna advertencia de que el servicio queda expuesto a toda la red (y más allá según el router).
- **Recomendación:** añadir aviso en CLI/GUI al aplicar (`forwards apply`), opción `--remote-address LocalSubnet` para la regla de firewall, y validar `listen_address` no-loopback.

### M4 — Sin TLS: token Bearer en claro si el panel/API se exponen en red — MEDIUM

- **CWE-319** · OWASP A02
- **Descripción:** HTTP plano en loopback es aceptable; con `--bind 0.0.0.0` el token viaja en claro por la LAN (sniffable). El aviso actual solo exige token, no cifrado.
- **Recomendación:** documentar uso con Tailscale (C2S cifrado) o añadir TLS autofirmado; al menos avisar explícitamente en `web start --bind`.

### L1 — Validación de tipos insuficiente en la API REST — LOW

- **CWE-20** · OWASP A03
- **Descripción:** `listen_port="abc"` en `POST /forwards` produce un `TypeError` sin capturar → **500 con detalles internos** (ruta/stack). El MCP sí valida correctamente (`-32602` limpio).
- **Evidencia (E7).**
- **Recomendación:** validar/castear tipos en `AppService` y devolver 400; añadir `except (TypeError, ValueError)` en el router.

### L2 — `schedule_add` acepta `type` inválido — LOW

- **CWE-20**
- **Descripción:** `POST /schedule` con `"type":"evil-type"` se almacena; al disparar la tarea no hace nada (sin error). El CLI valida con `choices`; la API y el MCP no.
- **Evidencia (E8).**
- **Recomendación:** validar `type` contra el enum en `AppService.schedule_add` (y `time` con formato HH:MM).

### L3 — Respuestas 500 filtran detalles internos — LOW

- **CWE-209**
- **Descripción:** los errores del router devuelven `{"error": str(e)}` (mensajes de excepción con rutas internas).
- **Recomendación:** loguear el detalle y devolver mensaje genérico.

### L4 — `api.rate_limit_per_minute` de config no se aplica — LOW

- **CWE-770**
- **Descripción:** `cmd_api serve` y la GUI crean `AuthService()` con defaults (120/30) ignorando `cfg.api.rate_limit_per_minute`.
- **Recomendación:** pasar `cfg.api.rate_limit_per_minute` al `AuthService`.

### Info (verificados, sin acción requerida)

| ID | Hallazgo | Detalle |
|---|---|---|
| I1 | Sin inyección de comandos | Todos los subprocess usan listas de args (sin `shell=True`); scripts PS internos con valores tipados (int/enum); UAC con `EncodedCommand` (base64) |
| I2 | B104 `0.0.0.0` (bandit) | Es el listen de forwards por diseño (ver M3) |
| I3 | B608 SQL (bandit) | Falso positivo: tabla/columna provienen de dict hardcodeado; valores parametrizados |
| I4 | Sin repo git ni .gitignore | Recomendación: `git init` + gitleaks pre-commit antes de compartir el código |
| I5 | Dependencias de la app: 0 runtime | pip-audit solo marca paquetes del entorno global (torch, pypdf, yt-dlp, setuptools) — fuera del alcance de la app |
| I6 | Sin secretos hardcodeados | Scan de patrones: 0; secrets DPAPI OK (valor ausente en secrets.json); redactor de logs verificado |
| I7 | Métodos no soportados → 501 | PUT/OPTIONS/HEAD no eluden auth |
| I8 | Matriz AuthZ correcta | 401 sin token, 403 scope insuficiente, 200 con scope, `?confirm=1` en admin |

---

## Cobertura OWASP / MITRE / CWE

| OWASP Top 10 | Hallazgos |
|---|---|
| A01 Broken Access Control | H1, M3 |
| A02 Cryptographic Failures | H4, M4 |
| A03 Injection | H2, L1 |
| A04 Insecure Design | H3 |
| A05 Security Misconfiguration | H1, M1, L3 |
| A07 Identification/Auth Failures | M2 |

| MITRE ATT&CK | Técnicas |
|---|---|
| T1059.007 / T1189 | H2 (XSS / drive-by) |
| T1499.004 | H3 (endpoint DoS) |
| T1552 | H4 (credenciales no protegidas) |
| T1110 | M2 (brute force) |
| T1046 | M3 (escaneo de servicios expuestos) |

## Recomendaciones priorizadas

1. **P0 (crítico de producto):** CSRF (H1) y XSS (H2) en el panel web — origin check + escape HTML + token por defecto.
2. **P0:** crash por concurrencia (H3) — lock en `MetricsStore` + límite de hilos.
3. **P1:** mover `web_panel_token` a secrets DPAPI y redactarlo en `diag` (H4).
4. **P1:** headers de seguridad (M1), aviso de exposición de forwards (M3).
5. **P2:** rate limit de auth (M2), validación de tipos/enums (L1/L2), error genérico (L3), config de rate limit (L4).

## Archivos de evidencia

- `security/report.md` (este documento)
- `security/evidence/endpoint-authz.csv` — matriz completa de endpoints
- `security/evidence/evidence.md` — reproducción de cada hallazgo

*Auditoría realizada con autorización del propietario sobre una aplicación local en desarrollo. Los secretos encontrados se han redactado; ningún valor real aparece en este reporte.*

---

## Remediación aplicada (2026-08-14, v0.2.1)

| Hallazgo | Fix | Verificación |
|---|---|---|
| **H1 CSRF** | Origin/Referer obligatorios y del mismo host en todos los POST del panel web (`_csrf_ok`); script sin Origin/Referer → 403 | En vivo: sin Origin → 403, Origin malo → 403, Origin correcto → pasa; tests `test_csrf_*` |
| **H2 XSS** | Escape `esc()` en todos los sinks `innerHTML` del dashboard (id, hosts, mensajes, badges) + headers `X-Content-Type-Options`, `X-Frame-Options: DENY`, `CSP frame-ancestors 'none'`, `Referrer-Policy` | En vivo: headers presentes; tests `test_dashboard_escapes_user_data` + `test_security_headers_present` |
| **H3 Crash por concurrencia** | `BoundedThreadingHTTPServer` (máx. 50 conexiones, rechaza el exceso) + `threading.Lock` en todos los métodos de `MetricsStore` (conexión SQLite serializada) | En vivo: 200 conexiones paralelas → server vivo (antes moría con 130); tests `test_concurrent_access_no_crash` + `test_api_survives_concurrent_burst` |
| **H4 Fuga del token del panel** | Token via `secrets set web_panel_token` (DPAPI); el campo legado de config queda deprecado con aviso; `diag` redacta `ui.web_panel_token` | En vivo: token ausente en config.json y diag.json (0 coincidencias); tests `test_redact_config_hides_panel_token` |

**Nota operativa (H1):** los scripts que llamen a la API del panel web (`/api/v1/*` del puerto 8794) deben enviar `Origin: http://<host>:<puerto>` en los POST. La API REST (`/api/v1` del puerto 8795) no se ve afectada (token Bearer obligatorio).

Suite tras la remediación: **134 passed, 2 skipped** (E2E requieren admin).
