# Limpia procesos python de la app (api serve / web start) y temporales pf-*
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'api serve|web start' } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Output ("matado pid " + $_.ProcessId)
    }
Start-Sleep -Seconds 1
Get-ChildItem "$env:TEMP" -Filter "pf-*" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Write-Output "limpieza completa"
