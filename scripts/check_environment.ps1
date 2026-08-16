# ============================================================
# check_environment.ps1 — diagnostico rapido del entorno
# ============================================================
$ErrorActionPreference = "SilentlyContinue"

Write-Host "== Version de Windows =="
[System.Environment]::OSVersion.VersionString

Write-Host "`n== Herramientas =="
foreach ($tool in @("netsh.exe", "ssh.exe", "wsl.exe", "powershell.exe")) {
    $found = Get-Command $tool -ErrorAction SilentlyContinue
    if ($found) { Write-Host "OK   $tool -> $($found.Source)" }
    else { Write-Host "FALTA $tool" }
}

Write-Host "`n== WSL =="
wsl.exe -l -q 2>$null

Write-Host "`n== Privilegios =="
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Host ("Admin: " + $(if ($isAdmin) { "SI" } else { "NO (forwards pediran UAC)" }))

Write-Host "`n== Portproxies actuales =="
netsh.exe interface portproxy show all

Write-Host "`n== Python =="
python --version 2>$null
Write-Host "Listo. Si algo falta, revisa docs/troubleshooting.md"
