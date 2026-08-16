# ============================================================
# setup_ssh_key.ps1 — genera llave dedicada y la copia al VPS
# Uso:  powershell -ExecutionPolicy Bypass -File setup_ssh_key.ps1 -VpsHost vps.example.com -VpsUser tunnel [-KeyName wsl-manager-main]
# ============================================================
param(
    [Parameter(Mandatory = $true)][string]$VpsHost,
    [Parameter(Mandatory = $true)][string]$VpsUser,
    [string]$KeyName = "wsl-manager-main",
    [int]$VpsPort = 22
)

$ErrorActionPreference = "Stop"
$keyPath = Join-Path $env:USERPROFILE ".ssh\$KeyName"

if (-not (Test-Path $keyPath)) {
    Write-Host "Generando llave ed25519 (sin passphrase): $keyPath"
    ssh-keygen -t ed25519 -N '""' -f $keyPath
} else {
    Write-Host "Llave existente: $keyPath"
}

Write-Host "Copiando llave publica a ${VpsUser}@${VpsHost}:$VpsPort ..."
Get-Content "$keyPath.pub" | ssh -p $VpsPort "${VpsUser}@${VpsHost}" "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"

Write-Host "Listo. Prueba con: ssh -i $keyPath -p $VpsPort ${VpsUser}@${VpsHost}"
Write-Host "Nota: en el VPS configura GatewayPorts yes (ver vps/sshd_config.snippet)."
