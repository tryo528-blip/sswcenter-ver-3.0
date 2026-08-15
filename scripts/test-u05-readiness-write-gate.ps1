param(
    [int]$Port = 55433,
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$PostgresBin = "C:\Program Files\PostgreSQL\17\bin"
$InitDbExe = Join-Path $PostgresBin "initdb.exe"
$PgCtlExe = Join-Path $PostgresBin "pg_ctl.exe"
$PgIsReadyExe = Join-Path $PostgresBin "pg_isready.exe"
$CreateDbExe = Join-Path $PostgresBin "createdb.exe"
$PythonExe = if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    Join-Path (Split-Path -Parent $PSScriptRoot) "backend\.venv\Scripts\python.exe"
} else {
    [System.IO.Path]::GetFullPath($PythonExecutable)
}

foreach ($Executable in @($InitDbExe, $PgCtlExe, $PgIsReadyExe, $CreateDbExe, $PythonExe)) {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "Required executable is missing: $Executable"
    }
}

if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use"
}

$TempRoot = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Temp")).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
)
$ClusterRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $TempRoot ("sswcenter-u05-pg-" + [Guid]::NewGuid().ToString("N")))
)
$ClusterPrefix = $TempRoot + [System.IO.Path]::DirectorySeparatorChar
if (-not $ClusterRoot.StartsWith($ClusterPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Ephemeral cluster path escaped the temporary directory"
}

$DataDirectory = Join-Path $ClusterRoot "data"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$DatabaseName = "sswcenter_u05_test"
$DatabaseUrl = "postgresql+psycopg://postgres@127.0.0.1:$Port/$DatabaseName"
$ClusterStarted = $false
$PreviousTemp = [Environment]::GetEnvironmentVariable("TEMP", "Process")
$PreviousTmp = [Environment]::GetEnvironmentVariable("TMP", "Process")
$PreviousTmpDir = [Environment]::GetEnvironmentVariable("TMPDIR", "Process")
$ProcessEnvironmentNames = @(
    "PGCLIENTENCODING",
    "SSWCENTER_ENVIRONMENT",
    "SSWCENTER_DATABASE_URL",
    "SSWCENTER_DATA_ROOT",
    "SSWCENTER_U05_LIVE"
)
$PreviousProcessEnvironment = @{}
foreach ($Name in $ProcessEnvironmentNames) {
    $PreviousProcessEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
}

$env:TEMP = $TempRoot
$env:TMP = $TempRoot
$env:TMPDIR = $TempRoot

New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
try {
    & $InitDbExe --pgdata=$DataDirectory --username=postgres --auth=trust --encoding=UTF8 --locale=C
    if ($LASTEXITCODE -ne 0) { throw "initdb failed" }

    & $PgCtlExe --pgdata=$DataDirectory --log=$LogFile --options="-h 127.0.0.1 -p $Port" start
    if ($LASTEXITCODE -ne 0) { throw "pg_ctl start failed" }
    $ClusterStarted = $true

    $Ready = $false
    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        & $PgIsReadyExe -h 127.0.0.1 -p $Port -U postgres -d postgres -t 1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $Ready = $true
            break
        }
        Start-Sleep -Milliseconds 200
    }
    if (-not $Ready) { throw "ephemeral PostgreSQL did not become ready" }

    & $CreateDbExe -h 127.0.0.1 -p $Port -U postgres $DatabaseName
    if ($LASTEXITCODE -ne 0) { throw "createdb failed" }

    $env:PGCLIENTENCODING = "UTF8"
    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_DATABASE_URL = $DatabaseUrl
    $env:SSWCENTER_DATA_ROOT = Join-Path $ClusterRoot "sswcenter-u05-runtime-data"
    $env:SSWCENTER_U05_LIVE = "1"
    New-Item -ItemType Directory -Path $env:SSWCENTER_DATA_ROOT -Force | Out-Null

    Push-Location (Join-Path $PSScriptRoot ".." "backend")
    try {
        & $PythonExe -m alembic -c alembic.ini upgrade head
        if ($LASTEXITCODE -ne 0) { throw "alembic upgrade head failed" }
        & $PythonExe -m pytest -q tests/test_u05_readiness_write_gate_postgres.py
        if ($LASTEXITCODE -ne 0) { throw "U-05 PostgreSQL probe failed" }
    }
    finally {
        Pop-Location
    }
    Write-Output "U05_EPHEMERAL_POSTGRES_GREEN"
}
finally {
    foreach ($Name in $ProcessEnvironmentNames) {
        $PreviousValue = $PreviousProcessEnvironment[$Name]
        if ($null -eq $PreviousValue) {
            Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
        } else {
            Set-Item -LiteralPath "Env:$Name" -Value $PreviousValue
        }
    }
    if ($null -eq $PreviousTemp) {
        Remove-Item Env:TEMP -ErrorAction SilentlyContinue
    } else {
        $env:TEMP = $PreviousTemp
    }
    if ($null -eq $PreviousTmp) {
        Remove-Item Env:TMP -ErrorAction SilentlyContinue
    } else {
        $env:TMP = $PreviousTmp
    }
    if ($null -eq $PreviousTmpDir) {
        Remove-Item Env:TMPDIR -ErrorAction SilentlyContinue
    } else {
        $env:TMPDIR = $PreviousTmpDir
    }

    if ($ClusterStarted) {
        & $PgCtlExe --pgdata=$DataDirectory stop --mode=fast | Out-Null
    }

    $ResolvedCluster = [System.IO.Path]::GetFullPath($ClusterRoot)
    if (
        $ResolvedCluster.StartsWith($ClusterPrefix, [StringComparison]::OrdinalIgnoreCase) -and
        $ResolvedCluster -match "sswcenter-u05-pg-[0-9a-f]{32}$" -and
        (Test-Path -LiteralPath $ResolvedCluster)
    ) {
        Remove-Item -LiteralPath $ResolvedCluster -Recurse -Force
    }
}
