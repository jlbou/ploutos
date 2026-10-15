<#
.SYNOPSIS
    Registra (o quita) la tarea programada DIARIA de copias de seguridad (PRD 11: "backup
    diario fuera del VPS"; semanal hasta el 28/09/2026, decision del propietario). Al registrarla
    quita la semanal antigua si sigue ahi.

.DESCRIPTION
    La tarea se registra para TU usuario y solo corre cuando has iniciado
    sesion. Es deliberado:

      * "ejecutar aunque el usuario no haya iniciado sesion" obligaria a
        guardar tu contrasenya de Windows dentro de la tarea, y
      * en esa modalidad el proceso no llega al agente SSH, que es donde vive
        tu clave descifrada. La tarea fallaria siempre con
        "Permission denied (publickey)".

    Para que un portatil apagado a la hora prevista no se salte la copia (el propietario, 01/10/2026),
    la tarea arranca a las $At, cada hora hasta medianoche, al iniciar sesion y al
    desbloquear, siempre con -SoloSiFalta: el script no hace nada si la copia de hoy ya
    salio bien o si aun no es la hora. Y "arrancar en cuanto se pueda tras una ejecucion
    perdida" para la de las $At.

.EXAMPLE
    .\deploy\install-backup-task.ps1
    .\deploy\install-backup-task.ps1 -At 10:00
    .\deploy\install-backup-task.ps1 -Remove
#>

[CmdletBinding()]
param(
    [string] $At = '12:00',

    [string] $Target = 'ploutos',

    [switch] $Remove
)

$ErrorActionPreference = 'Stop'

$taskName = 'Ploutos - copia de seguridad diaria'
$antigua = 'Ploutos - copia de seguridad semanal'

if (Get-ScheduledTask -TaskName $antigua -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $antigua -Confirm:$false
    Write-Output "Quitada la tarea antigua: $antigua"
}

if ($Remove) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Output "Tarea eliminada: $taskName"
    } else {
        Write-Output "No existe la tarea: $taskName"
    }
    exit 0
}

$repo = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot 'daily-backup.ps1'

if (-not (Test-Path $script)) {
    Write-Error "No encuentro $script"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`" -Target $Target -SoloSiFalta -Desde $At" `
    -WorkingDirectory $repo

$usuario = "$env:USERDOMAIN\$env:USERNAME"

# A las $At y despues cada hora hasta medianoche.
$diaria = New-ScheduledTaskTrigger -Daily -At $At
$horas = 24 - [datetime]::ParseExact($At, 'HH:mm', $null).Hour
$diaria.Repetition = (New-ScheduledTaskTrigger -Once -At $At -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Hours $horas -Minutes -1)).Repetition

# Al iniciar sesion y al desbloquear (StateChange 8 = SessionUnlock): el primer momento en que el
# portatil esta en uso despues de la hora.
$alEntrar = New-ScheduledTaskTrigger -AtLogOn -User $usuario
$claseSesion = Get-CimClass -Namespace 'Root/Microsoft/Windows/TaskScheduler' -ClassName 'MSFT_TaskSessionStateChangeTrigger'
$alDesbloquear = New-CimInstance -CimClass $claseSesion -ClientOnly -Property @{ StateChange = 8; UserId = $usuario }

$trigger = @($diaria, $alEntrar, $alDesbloquear)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId $usuario `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description 'Baja las copias de seguridad de la base de datos de Ploutos desde el VPS y comprueba que se pueden restaurar. Avisa por Telegram si falla.' `
    -Force | Out-Null

Write-Output "Tarea registrada: $taskName"
Write-Output "  cuando:   a las $At, cada hora hasta medianoche, al iniciar sesion y al desbloquear"
Write-Output "            (solo hace la copia si la de hoy aun no ha salido bien)"
Write-Output "  ejecuta:  deploy\daily-backup.ps1 -Target $Target"
Write-Output "  registro: var\backup-task.log"
Write-Output ""
Write-Output "Solo corre con la sesion iniciada. Si el portatil esta apagado a esa hora,"
Write-Output "se hace en cuanto lo uses. Si se corta a medias, la siguiente lo avisa y la repite."
Write-Output ""
Write-Output "Probarla ahora:  Start-ScheduledTask -TaskName '$taskName'"
Write-Output "Quitarla:        .\deploy\install-backup-task.ps1 -Remove"
