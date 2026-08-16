#!/usr/bin/env bash
# ============================================================
# install_autossh.sh — instala autossh en la distro WSL (opcional).
# El supervisor Python es el mecanismo P0; autossh es refuerzo.
# ============================================================
set -euo pipefail

echo "Instalando openssh-client y autossh..."
sudo apt-get update
sudo apt-get install -y openssh-client autossh

echo "Listo. Uso alternativo en WSL:"
echo "  autossh -M 0 -N -R 0.0.0.0:80:localhost:3000 tunnel@vps.example.com"
