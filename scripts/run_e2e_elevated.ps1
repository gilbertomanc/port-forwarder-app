# Helper interno: corre el test E2E de forwards ELEVADO (UAC) y guarda
# la salida en %TEMP%\pf-e2e-out.txt / pf-e2e-err.txt
$ErrorActionPreference = "Stop"
$repo = "C:\Users\gcastillo.13138\Desktop\hola-mundo\2-dev\wsl+ssh\port-forwarder-app"
Set-Location $repo
$out = Join-Path $env:TEMP "pf-e2e-out.txt"
$err = Join-Path $env:TEMP "pf-e2e-err.txt"
python -m pytest tests/integration -m integration -s -v *> $out
if ($LASTEXITCODE -ne 0) {
    Copy-Item $out $err -Force
}
exit $LASTEXITCODE
