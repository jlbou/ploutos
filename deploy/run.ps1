<#
.SYNOPSIS
    Lanza los scripts de deploy/ desde PowerShell.

.DESCRIPTION
    LA TRAMPA QUE RESUELVE (medida el 22/09/2026): en PowerShell, `bash` NO es
    el de Git Bash. Windows trae un stub de WSL en WindowsApps que gana en el
    PATH, asi que `bash deploy/fetch-backup.sh` responde

        Subsistema de Windows para Linux no tiene distribuciones instaladas.

    ...que no tiene nada que ver con el problema real. Este lanzador busca el
    Git Bash de verdad y le pasa el script.

.EXAMPLE
    .\deploy\run.ps1 fetch-backup ploutos
    .\deploy\run.ps1 sync ploutos
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string] $Script,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Arguments
)

$ErrorActionPreference = 'Stop'

$candidates = @(
    'C:\Program Files\Git\bin\bash.exe',
    'C:\Program Files\Git\usr\bin\bash.exe',
    "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe"
)

$bash = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $bash) {
    Write-Error @"
No encuentro Git Bash. Buscado en:
$($candidates -join "`n")

Instalalo desde https://git-scm.com/download/win, o abre Git Bash
directamente y lanza el script desde alli.
"@
    exit 1
}

$repo = Split-Path -Parent $PSScriptRoot
$name = if ($Script.EndsWith('.sh')) { $Script } else { "$Script.sh" }
$target = Join-Path $PSScriptRoot $name

if (-not (Test-Path $target)) {
    $disponibles = (Get-ChildItem $PSScriptRoot -Filter '*.sh' |
        Where-Object { $_.Name -notlike '_*' } |
        ForEach-Object { $_.BaseName }) -join ', '
    Write-Error "No existe deploy/$name. Disponibles: $disponibles"
    exit 1
}

# Git Bash necesita rutas estilo Unix.
$unixPath = 'deploy/' + $name

Push-Location $repo
try {
    & $bash $unixPath @Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
