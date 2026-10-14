# Hace que el icono de la bandeja arranque solo al iniciar sesión en Windows.
# Crea un acceso directo en la carpeta Inicio del usuario; no necesita administrador.
#
#   Activar:     powershell -ExecutionPolicy Bypass -File scripts\arranque_con_windows.ps1
#   Desactivar:  powershell -ExecutionPolicy Bypass -File scripts\arranque_con_windows.ps1 -Quitar

param([switch]$Quitar)

$repo = Split-Path -Parent $PSScriptRoot
$acceso = Join-Path ([Environment]::GetFolderPath("Startup")) "Vigilante de vuelos.lnk"

if ($Quitar) {
    if (Test-Path $acceso) { Remove-Item $acceso }
    Write-Host "El vigilante ya no arranca con Windows."
    exit
}

$atajo = (New-Object -ComObject WScript.Shell).CreateShortcut($acceso)
$atajo.TargetPath = Join-Path $repo ".venv\Scripts\pythonw.exe"
$atajo.Arguments = "-m vigilante.bandeja"
$atajo.WorkingDirectory = $repo
$atajo.Description = "Icono de la bandeja del vigilante de vuelos"
$atajo.Save()

Write-Host "Listo: el icono aparecera en la bandeja cada vez que inicies sesion."
Write-Host "Acceso directo creado en: $acceso"
