# Evidencia de hallazgos (auditoria 2026-08-14)

## E1 — CSRF en panel web (H1)

```bash
# Panel SIN token (config por defecto), bind 127.0.0.1, sin Origin/Referer:
curl -X POST "http://127.0.0.1:8902/api/v1/forwards/clear?confirm=1"   # -> 200
curl -X POST "http://127.0.0.1:8902/api/v1/maintenance/on?confirm=1"   # -> 200
```
Cualquier formulario HTML de una pagina visitada por el usuario dispara las mismas
peticiones (POST simple, sin CORS preflight).

## E2 — XSS almacenado en dashboard (H2)

```bash
# 1. Plantar payload via API (scope write):
curl -X POST -H "Authorization: Bearer $W" -H "Content-Type: application/json" \
  -d '{"id":"<img src=x onerror=alert(document.cookie)>","listen_port":7777,"wsl_port":7777}' \
  http://127.0.0.1:8901/api/v1/forwards
# -> {"ok": true, "data": {"id": "<img src=x onerror=alert(document.cookie)>", ...}}

# 2. El dashboard lo renderiza con innerHTML sin escapar (src/web/server.py,
#    DASHBOARD_HTML: renderForwards/renderTunnels/renderAlerts).
```

## E3 — Crash del servidor API bajo concurrencia (H3)

```bash
# 130 GETs en paralelo a /api/v1/status (con token valido):
#  - rafaga 1 (concurrencia 130): {0: 130} -> servidor muerto (0 LISTENING)
#  - rafaga 2 (concurrencia 10 x 13): {0: 130} -> servidor muerto de nuevo
# Despues: curl -> 000, netstat -> 0 LISTENING, log sin traceback.
# Causa raiz probable: MetricsStore (conexion sqlite unica) compartida entre
# hilos de ThreadingHTTPServer (audit() en cada request) sin lock + hilos ilimitados.
```

## E4 — Token del panel en claro + fuga en diag (H4)

```bash
# config.json contiene el token en claro: True
# diag.json (bundle de soporte compartible) contiene "clave-plana-panel-12345"
```

## E5 — Headers ausentes (M1)

```bash
# API:  HTTP/1.0 200 OK | Content-Type: application/json | Cache-Control: no-store
# Web:  HTTP/1.0 200 OK | Content-Type: text/html | Cache-Control: no-store
# Faltan: X-Content-Type-Options, X-Frame-Options, CSP, Referrer-Policy, Permissions-Policy
```

## E6 — Fuerza bruta sin limite (M2)

```bash
# 40 tokens invalidos en paralelo -> todos 401, ningun 429/backoff/Retry-After.
```

## E7 — Validacion de tipos (L1)

```bash
# API: listen_port="abc" -> TypeError sin capturar (500 con detalle interno).
# MCP: idem -> error JSON-RPC limpio -32602 (bien).
```

## E8 — schedule_add type invalido (L2)

```bash
curl -X POST -H "Authorization: Bearer $W" -H "Content-Type: application/json" \
  -d '{"name":"malo","type":"evil-type","time":"09:00"}' http://127.0.0.1:8901/api/v1/schedule
# -> {"ok": true, ... "tarea 'malo' programada"}  (type invalido almacenado)
```

## E9 — Sin secretos hardcodeados / DPAPI OK

```bash
# grep de patrones (BEGIN PRIVATE, sk_live_, ghp_, AKIA, urls con credenciales): 0
# find *.env *.pem *.key: 0
# secrets.json NO contiene el valor ("valor-ultra-secreto-999": 0 coincidencias)
```

## E10 — Metodos no soportados (I7)

```bash
# PUT/OPTIONS/HEAD sobre /api/v1/status con token read -> 501 (sin bypass de auth)
```
