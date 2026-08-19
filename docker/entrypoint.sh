#!/bin/sh
# Entrypoint del contenedor: crea la config inicial (con clave del panel web)
# si no existe y delega en el CLI (por defecto: port-forwarder web start).
set -e

CONFIG_DIR="${XDG_CONFIG_HOME:-/root/.config}/PortForwarder"
CONFIG="$CONFIG_DIR/config.json"
TOKEN="${PORT_FORWARDER_WEB_TOKEN:-}"

if [ ! -f "$CONFIG" ]; then
    if [ -z "$TOKEN" ]; then
        TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(16))')"
        echo "[entrypoint] Clave generada para el panel web: $TOKEN" >&2
    fi
    mkdir -p "$CONFIG_DIR"
    cat > "$CONFIG" <<EOF
{
  "version": 2,
  "ui": {
    "web_panel_enabled": true,
    "web_panel_port": 8794,
    "web_panel_bind": "0.0.0.0",
    "web_panel_token": "$TOKEN"
  }
}
EOF
    echo "[entrypoint] config inicial creada en $CONFIG" >&2
fi

exec port-forwarder "$@"
