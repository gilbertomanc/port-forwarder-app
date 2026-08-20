#!/usr/bin/env bash
# ============================================================
# install.sh — prepara el VPS para tunnels SSH de la app.
# Uso: sudo bash install.sh [usuario_tunnel]
# ============================================================
set -euo pipefail

TUNNEL_USER="${1:-tunnel}"

echo "== Creando usuario dedicado: $TUNNEL_USER =="
if ! id "$TUNNEL_USER" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "$TUNNEL_USER"
    mkdir -p "/home/$TUNNEL_USER/.ssh"
    touch "/home/$TUNNEL_USER/.ssh/authorized_keys"
    chown -R "$TUNNEL_USER:$TUNNEL_USER" "/home/$TUNNEL_USER/.ssh"
    chmod 700 "/home/$TUNNEL_USER/.ssh"
    chmod 600 "/home/$TUNNEL_USER/.ssh/authorized_keys"
fi

echo "== Aplicando sshd_config.snippet =="
cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak.$(date +%F)
cat >> /etc/ssh/sshd_config <<'EOF'

# Port Forwarding Manager
GatewayPorts yes
AllowTcpForwarding yes
PasswordAuthentication no
AllowUsers tunnel
ClientAliveInterval 60
ClientAliveCountMax 3
TCPKeepAlive yes
EOF

echo "== Reiniciando sshd =="
systemctl restart sshd

echo "Listo. Copia tu llave publica a /home/$TUNNEL_USER/.ssh/authorized_keys"
echo "(o usa scripts/setup_ssh_key.ps1 desde Windows)."
