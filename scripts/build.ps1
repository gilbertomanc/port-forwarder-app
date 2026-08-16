# ============================================================
# build.ps1 — empaqueta con PyInstaller y, si existe Inno Setup
# (ISCC.exe), genera el instalador.
# Requisitos:  pip install pyinstaller
#              Inno Setup 6+ (opcional) instalado en su ruta por defecto
# Uso: powershell -ExecutionPolicy Bypass -File scripts\build.ps1
# ============================================================
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

Write-Host "== 1/2 PyInstaller (one-dir) =="
python -m PyInstaller --clean --noconfirm scripts\port-forwarder.spec
if (-not (Test-Path "dist\port-forwarder\port-forwarder.exe")) {
    throw "build fallo: no existe dist\port-forwarder\port-forwarder.exe"
}
Write-Host "OK: dist\port-forwarder\port-forwarder.exe"

Write-Host "`n== 2/2 Inno Setup (instalador) =="
$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
    & $iscc "scripts\installer.iss"
    if ($LASTEXITCODE -ne 0) { throw "ISCC fallo" }
    Write-Host "OK: installer en dist\PortForwarder-Setup.exe"
} else {
    Write-Host "AVISO: Inno Setup no encontrado en $iscc"
    Write-Host "  Instala Inno Setup 6 y repite este paso, o ejecuta a mano:"
    Write-Host "  `"$iscc`" scripts\installer.iss"
}
Write-Host "`nListo."
