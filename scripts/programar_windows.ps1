# Crea (o actualiza) la tarea "VigilanteVuelos" en el Programador de tareas.
# No necesita administrador: la tarea es del usuario actual.
#
# Se dispara al iniciar sesión (con 5 min de margen para que haya red) y cada hora
# desde $Hora hasta medianoche. El programa corre con --una-vez-al-dia, así que solo
# la primera ejecución buena del día consulta precios; las demás salen al momento.
#
#   Programar:     powershell -ExecutionPolicy Bypass -File scripts\programar_windows.ps1
#   Otra hora:     powershell -ExecutionPolicy Bypass -File scripts\programar_windows.ps1 -Hora 10:00
#   Desprogramar:  Unregister-ScheduledTask -TaskName VigilanteVuelos -Confirm:$false

param([string]$Hora = "08:00")

$repo = Split-Path -Parent $PSScriptRoot
$accion = New-ScheduledTaskAction -Execute "$repo\scripts\ejecutar.cmd" -WorkingDirectory $repo

$alIniciar = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$alIniciar.Delay = "PT5M"

$cadaHora = New-ScheduledTaskTrigger -Daily -At $Hora
$horasHastaMedianoche = 24 - [int]($Hora.Split(":")[0])
$repeticion = (New-ScheduledTaskTrigger -Once -At $Hora `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Hours $horasHastaMedianoche)).Repetition
$cadaHora.Repetition = $repeticion

# Sin "solo con red": si no hay internet falla, no cuenta como hecha y la siguiente hora reintenta.
$ajustes = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName "VigilanteVuelos" `
    -Description "Consulta precios de vuelos una vez al dia y avisa si hay chollo (vigilante-vuelos)" `
    -Action $accion `
    -Trigger @($alIniciar, $cadaHora) `
    -Settings $ajustes `
    -Force | Out-Null

Write-Host "Tarea 'VigilanteVuelos': al iniciar sesion y cada hora desde las $Hora (una consulta al dia)."
Write-Host "Probarla ahora: Start-ScheduledTask -TaskName VigilanteVuelos"
