<#
.SYNOPSIS
    Baja las copias de seguridad del VPS. Lo ejecuta la tarea programada.

.DESCRIPTION
    Deja registro en var/backup-task.log y avisa por Telegram si falla.

    POR QUE AVISA: una copia de seguridad que falla en silencio es peor que no
    tenerla, porque crees que estas cubierto. Si la clave SSH deja de estar
    cargada, si el servidor no responde o si una copia se corrompe, hay que
    enterarse ese dia y no el dia que haga falta restaurar.

    DIARIA desde el 28/09/2026 (el propietario): el PRD 11 pide "backup diario de la base de
    datos fuera del VPS". Antes era semanal: si el VPS moria un sabado, se perdia
    casi una semana de historia.

    DESDE EL 01/10/2026 (el propietario), porque el 30/09 la copia se CORTO a medias (Windows
    la mato, 0xC000013A) y nadie lo supo:
      * La tarea la lanza a las 12:00, al iniciar sesion, al desbloquear y cada hora
        hasta medianoche, siempre con -SoloSiFalta: si la de hoy ya salio bien, o aun
        no son las 12:00, no hace nada. Asi se hace la primera vez que el portatil
        esta encendido a partir de las 12:00, sin depender de que lo este a esa hora.
      * Deja una marca (var/backup-en-curso.txt) al empezar y la quita al acabar. Si
        la encuentra al empezar, la anterior se corto: lo avisa y la repite.
      * Cuando sale bien, late a Healthchecks (HEALTHCHECK_COPIA_PORTATIL en el .env
        del portatil); si falla, manda /fail. Si pasan dos dias sin latido (portatil
        apagado, roto o la tarea muerta), avisa Healthchecks: lo unico que puede
        avisar cuando el portatil no se enciende.
      * Un fallo se avisa por Telegram UNA vez al dia: con reintentos cada hora,
        sin esto un VPS caido mandaria doce mensajes.

.EXAMPLE
    .\deploy\daily-backup.ps1                 # ahora, pase lo que pase
    .\deploy\daily-backup.ps1 -SoloSiFalta    # lo que hace la tarea
#>

[CmdletBinding()]
param(
    [string] $Target = 'ploutos',

    # Solo si hoy aun no hay una copia buena y ya son las $Desde (hora local).
    [switch] $SoloSiFalta,

    [string] $Desde = '12:00',

    # Si el SSH a $Target no conecta (02/10/2026: algunas redes del propietario cortan el SSH a la IP publica del VPS y
    # la copia fallo con "Connection timed out during banner exchange"), se reintenta por aqui: el alias de
    # ~/.ssh/config que va por Tailscale (misma clave, misma huella del servidor).
    [string] $TargetAlternativo = 'ploutos-ts'
)

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $repo 'var'
$log = Join-Path $logDir 'backup-task.log'
$ultimaOk = Join-Path $logDir 'backup-ultima-ok.txt'       # fecha local (yyyy-MM-dd) de la ultima copia buena
$enCurso = Join-Path $logDir 'backup-en-curso.txt'         # existe mientras corre; si queda, la anterior se corto
$avisoFallo = Join-Path $logDir 'backup-aviso-fallo.txt'   # dia del ultimo aviso de fallo (uno al dia)
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$hoy = (Get-Date).ToString('yyyy-MM-dd')

function Read-Primera {
    param([string] $Path)
    if (Test-Path $Path) { return (Get-Content $Path -TotalCount 1) }
    return $null
}

if ($SoloSiFalta) {
    # Antes de la hora, o ya hecha hoy: nada, y sin escribir en el registro (se lanza cada hora).
    if ((Get-Date) -lt [datetime]::ParseExact($Desde, 'HH:mm', $null)) { exit 0 }
    if ((Read-Primera $ultimaOk) -eq $hoy) { exit 0 }
}

function Write-Log {
    param([string] $Message)
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    $line = "$stamp $Message"
    Add-Content -Path $log -Value $line -Encoding utf8
    Write-Output $line
}

# Un valor del .env del portatil. Nunca se escribe en el registro.
function Read-Env {
    param([string] $Name)
    $envFile = Join-Path $repo '.env'
    if (-not (Test-Path $envFile)) { return $null }
    foreach ($line in Get-Content $envFile) {
        if ($line -match "^\s*$Name\s*=\s*(.+?)\s*$") { return $Matches[1] }
    }
    return $null
}

# Aviso por Telegram leyendo .env. NUNCA imprime el token: si la llamada falla,
# se registra el codigo de estado, no la URL (que lleva el token dentro).
function Send-Telegram {
    param([string] $Text)
    $token = Read-Env 'TELEGRAM_BOT_TOKEN'
    $chat = Read-Env 'TELEGRAM_CHAT_ID'
    if (-not $token -or -not $chat) {
        Write-Log 'AVISO: sin credenciales de Telegram en .env; no se pudo notificar'
        return
    }
    try {
        $uri = "https://api.telegram.org/bot$token/sendMessage"
        Invoke-RestMethod -Method Post -Uri $uri -Body @{ chat_id = $chat; text = $Text } -TimeoutSec 15 | Out-Null
        Write-Log 'aviso enviado por Telegram'
    } catch {
        Write-Log "AVISO: no se pudo notificar por Telegram ($($_.Exception.Message -replace [regex]::Escape($token), '***'))"
    }
}

# Un fallo, UNA vez al dia por Telegram (la tarea reintenta cada hora); siempre en el registro.
function Send-Fallo {
    param([string] $Text)
    if ((Read-Primera $avisoFallo) -eq $hoy) {
        Write-Log '(fallo ya avisado hoy por Telegram)'
        return
    }
    Set-Content -Path $avisoFallo -Value $hoy -Encoding ascii
    Send-Telegram $Text
}

# El latido de la copia del portatil. La URL es secreta (quien la tenga puede tapar una caida).
function Send-Latido {
    param([switch] $Fallo)
    $url = Read-Env 'HEALTHCHECK_COPIA_PORTATIL'
    if (-not $url) {
        Write-Log '(sin HEALTHCHECK_COPIA_PORTATIL en .env: no se late)'
        return
    }
    if ($Fallo) { $url = "$url/fail" }
    try {
        Invoke-RestMethod -Method Get -Uri $url -TimeoutSec 10 | Out-Null
        Write-Log $(if ($Fallo) { 'latido de fallo enviado a Healthchecks' } else { 'latido enviado a Healthchecks' })
    } catch {
        Write-Log 'AVISO: no se pudo latir a Healthchecks'
    }
}

# Errores de RED del SSH (no de la copia): con estos se prueba el destino alternativo.
$sinConexion = 'timed out|kex_exchange_identification|banner exchange|Connection refused|Could not resolve hostname|Network is unreachable|No route to host'

# Baja las copias de un destino. Devuelve el codigo y la salida; nunca lanza. Con 'Stop', la primera linea de
# error del ssh (stderr) cortaba el script entero (asi fallo el 02/10): aqui se recoge como una linea mas.
function Invoke-Fetch {
    param([string] $Destino)
    $ErrorActionPreference = 'Continue'
    try {
        $salida = & (Join-Path $PSScriptRoot 'run.ps1') fetch-backup $Destino 2>&1
        return @{ Codigo = $LASTEXITCODE; Salida = @($salida | ForEach-Object { "$_" }) }
    } catch {
        return @{ Codigo = 255; Salida = @("ERROR: $($_.Exception.Message)") }
    }
}

Write-Log "--- copia diaria, destino $Target ---"

$cortada = Read-Primera $enCurso
if ($cortada) {
    Write-Log "AVISO: la copia que empezo $cortada no termino (se corto a medias); se repite ahora"
    Send-Telegram "Ploutos: la copia de seguridad que empezo $cortada se corto a medias (portatil apagado o sesion cerrada). Se repite ahora."
}
Set-Content -Path $enCurso -Value (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm UTC') -Encoding ascii

try {
    $r = Invoke-Fetch $Target
    if ($r.Codigo -ne 0 -and $TargetAlternativo -and (($r.Salida -join "`n") -match $sinConexion)) {
        foreach ($line in $r.Salida) { Write-Log "   $line" }
        Write-Log "   (sin conexion con '$Target': se reintenta por '$TargetAlternativo')"
        $r = Invoke-Fetch $TargetAlternativo
    }
    $output = $r.Salida
    $code = $r.Codigo
    foreach ($line in $output) { Write-Log "   $line" }

    if ($code -ne 0) {
        Write-Log "FALLO (codigo $code)"
        Send-Fallo "Ploutos: la copia de seguridad diaria ha FALLADO (codigo $code).`nSe reintenta cada hora; mira var/backup-task.log en el portatil."
        Send-Latido -Fallo
        exit 1
    }

    # Cuando es la copia mas reciente, POR FAMILIA y por la fecha del NOMBRE.
    # Revision del 23/09/2026, dos fallos que hacian que este aviso no saltara nunca:
    # - la fecha del fichero es la de la DESCARGA (scp no la conserva), no la de
    #   la copia: una copia vieja recien bajada parecia de hoy;
    # - mezclaba las dos bases: si la principal dejara de copiarse y la de papel
    #   no, la de papel la tapaba.
    $backups = Get-ChildItem (Join-Path $repo 'var/backups') -Filter '*.db.gz' -ErrorAction SilentlyContinue
    # La de la IA es opcional hasta que se despliegue: sin copias suyas no es un fallo.
    $opcionales = @('ploutos-paper-ai', 'ploutos-exec', 'ploutos-medios', 'ploutos-embudo', 'ploutos-libros')
    $vieja = $false
    # Las cinco bases desde el 25/09 (noticias y comandos se anyadieron a la vigilancia el 27/09); el ejecutor desde el
    # 03/10, los medios en sombra desde el 07/10 y el embudo de noticias de L desde el 12/10.
    foreach ($familia in @('ploutos', 'ploutos-paper', 'ploutos-paper-ai', 'ploutos-news', 'ploutos-control', 'ploutos-exec', 'ploutos-medios', 'ploutos-embudo', 'ploutos-libros')) {
        $fechas = @($backups | ForEach-Object {
            if ($_.Name -match "^$familia-(\d{8}T\d{6})Z\.db\.gz$") {
                [datetime]::ParseExact($Matches[1], 'yyyyMMddTHHmmss', $null, 'AssumeUniversal,AdjustToUniversal')
            }
        })
        if ($fechas.Count -eq 0 -and $opcionales -contains $familia) {
            Write-Log "(sin copias de '$familia': aun no desplegada)"
            continue
        }
        if ($fechas.Count -eq 0) {
            Write-Log "FALLO: ninguna copia local de '$familia' despues de ejecutarla"
            Send-Fallo "Ploutos: la copia diaria termino sin errores pero no hay ninguna copia de '$familia'. Revisalo."
            Send-Latido -Fallo
            exit 1
        }
        $newest = ($fechas | Sort-Object -Descending)[0]
        $ageDays = [math]::Round(((Get-Date).ToUniversalTime() - $newest).TotalDays, 1)
        Write-Log "OK: $familia, $($fechas.Count) copia(s); la mas reciente se hizo hace $ageDays dias"

        # Vieja = el temporizador del servidor ha dejado de generar copias de esta base. La del
        # servidor es de cada noche (03:15 UTC): mas de 2 dias ya no es un retraso normal.
        if ($ageDays -gt 2) {
            $vieja = $true
            Write-Log "AVISO: la copia mas reciente de '$familia' se hizo hace $ageDays dias"
            Send-Fallo "Ploutos: la copia mas reciente de '$familia' se hizo hace $ageDays dias. Comprueba el temporizador del servidor."
        }
    }
    if ($vieja) {
        Send-Latido -Fallo
        exit 1
    }
    Set-Content -Path $ultimaOk -Value $hoy -Encoding ascii
    Send-Latido
    exit 0
}
catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    Send-Fallo "Ploutos: la copia de seguridad diaria ha fallado.`n$($_.Exception.Message)"
    Send-Latido -Fallo
    exit 1
}
finally {
    # Solo llega aqui si el proceso NO lo matan: si Windows lo corta, la marca se queda y la siguiente lo avisa.
    Remove-Item -Path $enCurso -ErrorAction SilentlyContinue
}
