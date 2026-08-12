param(
    [string]$DatabaseName = "sswcenter_wave0_test",
    [string]$AdminUser = "postgres",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 5432
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($DatabaseName -notmatch '^[a-zA-Z0-9_]+_test$') {
    throw "Test database name must contain only letters, digits, underscores and end with _test"
}
if (-not $env:PGPASSWORD) {
    throw "Set PGPASSWORD only for this shell before creating the isolated test database"
}

$PsqlExe = "C:\Program Files\PostgreSQL\17\bin\psql.exe"
$CreatedbExe = "C:\Program Files\PostgreSQL\17\bin\createdb.exe"
if (-not (Test-Path -LiteralPath $PsqlExe)) {
    throw "PostgreSQL 17 psql.exe is missing"
}
if (-not (Test-Path -LiteralPath $CreatedbExe)) {
    throw "PostgreSQL 17 createdb.exe is missing"
}

$Exists = & $PsqlExe `
    -w `
    -h $HostName `
    -p $Port `
    -U $AdminUser `
    -d postgres `
    -tAc "SELECT 1 FROM pg_database WHERE datname = '$DatabaseName'"
if ($LASTEXITCODE -ne 0) {
    throw "Unable to query PostgreSQL"
}

if ($Exists.Trim() -ne "1") {
    & $CreatedbExe `
        -w `
        -h $HostName `
        -p $Port `
        -U $AdminUser `
        --encoding UTF8 `
        --template template0 `
        $DatabaseName
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create isolated test database"
    }
}

$env:SSWCENTER_ENVIRONMENT = "test"
$env:SSWCENTER_DATABASE_URL = (
    "postgresql+psycopg://{0}@{1}:{2}/{3}" -f
    $AdminUser,
    $HostName,
    $Port,
    $DatabaseName
)

$WorkspaceRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $WorkspaceRoot "backend\.venv\Scripts\python.exe"
Push-Location (Join-Path $WorkspaceRoot "backend")
try {
    & $PythonExe -m alembic -c alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic upgrade failed"
    }
    & $PythonExe -m alembic -c alembic.ini current
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic current failed"
    }
}
finally {
    Pop-Location
}

Write-Output "Isolated PostgreSQL test database is ready: $DatabaseName"
