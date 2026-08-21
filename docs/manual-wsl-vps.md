# Manual: publicar servicios de WSL en Internet a través de tu VPS

Cómo exponer **un servicio que corre dentro de WSL** (web, API, base de datos…)
de forma **pública en Internet** con el túnel SSH de Port Forwarding Manager.

```
Internet ──► VPS (sshd escucha en 0.0.0.0:18097) ──► túnel SSH reverso ──►
        TU PC (ssh.exe) ──► 127.0.0.1:9000 (localhost mirroring WSL2) ──►
        WSL Debian: servicio escuchando en :9000
```

---

## Índice

1. [Requisitos](#requisitos)
2. [El servicio dentro de WSL](#1-el-servicio-dentro-de-wsl)
3. [Llegar al servicio desde Windows](#2-llegar-al-servicio-desde-windows)
4. [Preparar el VPS](#3-preparar-el-vps)
5. [Crear el túnel (CLI)](#4-crear-el-túnel-cli)
6. [Crear el túnel (ventana gráfica)](#5-crear-el-túnel-ventana-gráfica)
7. [Arrancar y comprobar](#6-arrancar-y-comprobar)
8. [Monitorizar el túnel](#7-monitorizar-el-túnel)
9. [Solución de problemas](#8-solución-de-problemas)
10. [Consejos avanzados](#9-consejos-avanzados)

## Requisitos

- **Port Forwarding Manager** instalado y tu VPS registrado.
- **WSL2** con una distro (ej. Debian) y el servicio que quieres publicar.
- **VPS** con `sshd` en un puerto conocido (ej. `debian@167.114.169.134:10000`).

## 1. El servicio dentro de WSL

El servicio debe escuchar en `0.0.0.0` o `127.0.0.1` dentro de WSL:

```bash
# dentro de WSL (Debian): servidor web de ejemplo en el puerto 9000
python3 -m http.server 9000 --bind 0.0.0.0
```

Comprueba que escucha:

```bash
wsl -d Debian -- bash -c "ss -tln | head"
#   LISTEN 0  128  0.0.0.0:9000  ...   ← listo
```

> Si escucha solo en `127.0.0.1` dentro de WSL también funciona (el espejo de
> localhost de WSL2 lo alcanza desde Windows).

## 2. Llegar al servicio desde Windows

WSL2 **espeja localhost**: un servicio dentro de WSL es alcanzable desde
Windows en `127.0.0.1:<puerto>`.

```powershell
# desde Windows: debe responder el servicio de WSL
Invoke-WebRequest -Uri http://127.0.0.1:9000/
```

**Alternativa** (si el espejo fallara), usar la IP directa de WSL:

```bash
wsl -d Debian -- hostname -I        # ej. 172.26.159.208
# y en el túnel usar --local 172.26.159.208:9000
```

## 3. Preparar el VPS

El VPS debe permitir bind remoto público (`GatewayPorts yes`) y reenvío TCP.
La app incluye el script:

```bash
# en el VPS, una sola vez:
sudo bash install.sh           # o copia vps/sshd_config.snippet a sshd_config
sudo systemctl restart sshd
```

## 4. Crear el túnel (CLI)

```bash
# local = servicio de WSL (vía localhost) · remote = puerto público del VPS
port-forwarder tunnels add --id wsl-web --vps "vps1 de canada" \
  --local 127.0.0.1:9000 --remote 0.0.0.0:18097
```

## 5. Crear el túnel (ventana gráfica)

Ventana → pestaña **Tunnels**:
1. **Servidores VPS** → Nuevo VPS... (si no está registrado).
2. **Nuevo tunnel...**: ID (`wsl-web`), VPS, Local `127.0.0.1:9000`, Remoto `0.0.0.0:18097`.

## 6. Arrancar y comprobar

```bash
port-forwarder tunnels start wsl-web
port-forwarder tunnels status wsl-web --json     # alive: true
```

Prueba el público desde cualquier sitio (o desde la misma PC):

```powershell
Invoke-WebRequest -Uri http://167.114.169.134:18097/
# → 200, mismo contenido que http://127.0.0.1:9000
```

## 7. Monitorizar el túnel

- **Estado + tráfico**: `port-forwarder tunnels status wsl-web --json` →
  `traffic` (bytes rx/tx acumulados y velocidad).
- **Panel web** (http://127.0.0.1:8794): estado, uptime y tráfico en vivo.
- **Ventana**: pestaña Tunnels con columna **Tráfico**.
- **Auto-supervisión**: el supervisor reinicia el túnel si se cae
  (keepalive SSH incluido en cliente y VPS).

## 8. Solución de problemas

| Problema | Causa | Solución |
|----------|-------|----------|
| `alive: false` al arrancar | Auth SSH o bind remoto | Revisa `logs/tunnel-<id>.log`; `GatewayPorts yes` en el VPS |
| El público no responde (timeout) | Firewall del VPS | Abre el puerto: `sudo ufw allow 18097/tcp` |
| El público responde pero vacío | El servicio de WSL no escucha | `ss -tln` en WSL; bind `0.0.0.0` |
| Conecta pero se corta | NAT/firewall | Keepalive ya activo (ServerAliveInterval=30 + VPS ClientAliveInterval 60) |
| Localhost mirroring no funciona | WSL antiguo | Usa la IP de WSL (`wsl hostname -I`) como `--local` |
| El túnel no sobrevive al cierre | Proceso lanzado y cerrado | Lánzalo con `web start`/supervisor o la ventana (DETACHED_PROCESS) |

## 9. Consejos avanzados

- **Varios puertos**: añade más `--remote` repetibles al crear el túnel
  (`--remote 0.0.0.0:18097 --remote 0.0.0.0:18098`) para publicar varios
  servicios de WSL con un solo túnel.
- **Autoarranque con Windows**: Ajustes → "Autoarranque" (inicia el panel +
  supervisor en segundo plano, sin terminal visible).
- **Dominio propio**: apunta un subdominio de tu VPS al puerto público y usa
  Nginx/Caddy en el VPS como proxy reverso con HTTPS.
- **Seguridad**: no expongas servicios sin autenticación; usa token del panel,
  claves SSH (no contraseñas) y limita `AllowUsers` en el VPS.

---

*Documento generado para la integración WSL ↔ VPS con Port Forwarding Manager.*