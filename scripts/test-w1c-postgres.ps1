param(
    [int]$Port = 55441
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$PythonExe = Join-Path $BackendRoot ".venv\Scripts\python.exe"
$PostgresBin = "C:\Program Files\PostgreSQL\17\bin"
$InitDbExe = Join-Path $PostgresBin "initdb.exe"
$PgCtlExe = Join-Path $PostgresBin "pg_ctl.exe"
$PgIsReadyExe = Join-Path $PostgresBin "pg_isready.exe"
$CreateDbExe = Join-Path $PostgresBin "createdb.exe"
$PsqlExe = Join-Path $PostgresBin "psql.exe"
$BaseRevision = "20260730_0009_w1b_recipient"
$ExpectedRevision = "20260730_0010_w1c_certification_ledgers"

foreach ($Executable in @(
    $PythonExe,
    $InitDbExe,
    $PgCtlExe,
    $PgIsReadyExe,
    $CreateDbExe,
    $PsqlExe
)) {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "W1C_HARNESS_MISSING_EXECUTABLE: $Executable"
    }
}

if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    throw "W1C_HARNESS_PORT_IN_USE: $Port"
}

$TempParent = if (-not [string]::IsNullOrWhiteSpace($env:SSWCENTER_W1C_TEMP_ROOT)) {
    [System.IO.Path]::GetFullPath($env:SSWCENTER_W1C_TEMP_ROOT)
}
else {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        throw "W1C_HARNESS_LOCALAPPDATA_MISSING"
    }
    [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Temp"))
}
$TempParent = $TempParent.TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
)
if (-not (Test-Path -LiteralPath $TempParent -PathType Container)) {
    throw "W1C_HARNESS_TEMP_PARENT_MISSING"
}
$env:TEMP = $TempParent
$env:TMP = $TempParent
$env:TMPDIR = $TempParent
$ClusterRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $TempParent ("sswcenter-w1c-pg-" + [Guid]::NewGuid().ToString("N")))
)
$ExpectedPrefix = $TempParent + [System.IO.Path]::DirectorySeparatorChar
$ClusterLeaf = Split-Path -Leaf $ClusterRoot
if (
    -not $ClusterRoot.StartsWith($ExpectedPrefix, [StringComparison]::OrdinalIgnoreCase) -or
    -not $ClusterLeaf.StartsWith("sswcenter-w1c-pg-", [StringComparison]::Ordinal)
) {
    throw "W1C_HARNESS_UNSAFE_TEMP_PATH"
}

$DataDirectory = Join-Path $ClusterRoot "data"
$RuntimeDataRoot = Join-Path $ClusterRoot "sswcenter-w1c-runtime"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$DatabaseName = "sswcenter_w1c_review"
$OwnerDatabaseUrl = "postgresql+psycopg://erp_owner@127.0.0.1:$Port/$DatabaseName"
$AppDatabaseUrl = "postgresql+psycopg://erp_app@127.0.0.1:$Port/$DatabaseName"
$ClusterStarted = $false

function Remove-W1cTree {
    param([Parameter(Mandatory = $true)][string]$Path)

    $resolved = [System.IO.Path]::GetFullPath($Path)
    $parent = Split-Path -Parent $resolved
    $leaf = Split-Path -Leaf $resolved
    if (
        -not [string]::Equals($parent, $TempParent, [StringComparison]::OrdinalIgnoreCase) -or
        $leaf -cnotmatch '^sswcenter-w1c-pg-[0-9a-f]{32}$'
    ) {
        throw "W1C_HARNESS_UNSAFE_CLEANUP_PATH"
    }
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            if (Test-Path -LiteralPath $resolved) {
                [System.IO.Directory]::Delete($resolved, $true)
            }
        }
        catch {
            if ($attempt -eq 3) { throw }
        }
        if (-not (Test-Path -LiteralPath $resolved)) { return }
        if ($attempt -lt 3) { Start-Sleep -Milliseconds 250 }
    }
    throw "W1C_HARNESS_CLEANUP_FAILED"
}

New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $RuntimeDataRoot -Force | Out-Null

try {
    & $InitDbExe `
        --pgdata=$DataDirectory `
        --username=postgres `
        --auth=trust `
        --encoding=UTF8 `
        --locale=C | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W1C_HARNESS_INITDB_FAILED"
    }

    & $PgCtlExe `
        --pgdata=$DataDirectory `
        --log=$LogFile `
        --options="-h 127.0.0.1 -p $Port" `
        start
    if ($LASTEXITCODE -ne 0) {
        throw "W1C_HARNESS_POSTGRES_START_FAILED"
    }
    $ClusterStarted = $true

    & $PgIsReadyExe -h 127.0.0.1 -p $Port -U postgres -d postgres -t 15 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W1C_HARNESS_POSTGRES_NOT_READY"
    }
    $RoleSql = @"
CREATE ROLE erp_owner LOGIN;
CREATE ROLE erp_app LOGIN;
CREATE ROLE erp_backup LOGIN;
"@
    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -d postgres `
        -c $RoleSql | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W1C_HARNESS_ROLE_CREATE_FAILED"
    }
    & $CreateDbExe `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -O erp_owner `
        $DatabaseName
    if ($LASTEXITCODE -ne 0) {
        throw "W1C_HARNESS_DATABASE_CREATE_FAILED"
    }

    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
    $env:SSWCENTER_OWNER_DATABASE_URL = $OwnerDatabaseUrl
    $env:SSWCENTER_APP_DATABASE_URL = $AppDatabaseUrl
    $env:SSWCENTER_DATA_ROOT = $RuntimeDataRoot
    $env:SSWCENTER_W1C_REAL_PG = "1"
    $env:SSWCENTER_PIN_PEPPER = "w1c-test-pin-pepper"
    $env:SSWCENTER_PIN_LOOKUP_KEY = "w1c-test-pin-lookup"
    $env:SSWCENTER_CSRF_SIGNING_KEY = "w1c-test-csrf"

    Push-Location $BackendRoot
    try {
        & $PythonExe -m alembic -c alembic.ini upgrade $BaseRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W1C_HARNESS_BASE_UPGRADE_FAILED"
        }
        & $PythonExe -m alembic -c alembic.ini upgrade $ExpectedRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W1C_HARNESS_UPGRADE_FAILED"
        }
        & $PythonExe -m alembic -c alembic.ini downgrade $BaseRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W1C_HARNESS_DOWNGRADE_FAILED"
        }
        & $PythonExe -m alembic -c alembic.ini upgrade $ExpectedRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W1C_HARNESS_REUPGRADE_FAILED"
        }

        $CurrentRevision = & $PsqlExe `
            -v ON_ERROR_STOP=1 `
            -h 127.0.0.1 `
            -p $Port `
            -U erp_owner `
            -d $DatabaseName `
            -tAc "SELECT version_num FROM erp.alembic_version"
        if (
            $LASTEXITCODE -ne 0 -or
            ($CurrentRevision -join "").Trim() -ne $ExpectedRevision
        ) {
            throw "W1C_HARNESS_REVISION_MISMATCH"
        }

        $RuntimeRole = @(
            & $PsqlExe `
                -v ON_ERROR_STOP=1 `
                -h 127.0.0.1 `
                -p $Port `
                -U erp_app `
                -d $DatabaseName `
                -tAc "SELECT current_user"
        )
        if (
            $LASTEXITCODE -ne 0 -or
            ($RuntimeRole -join "").Trim() -ne "erp_app"
        ) {
            throw "W1C_HARNESS_APP_ROLE_MISMATCH"
        }
        Write-Output "W1C_APP_ROLE_OK"

        # Historical 0010 lifecycle is sealed above. Current ORM/tests/postcheck
        # require the live Alembic head (includes 0017 recipient_guardian.email).
        & $PythonExe -m alembic -c alembic.ini upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw "W1C_HARNESS_HEAD_UPGRADE_FAILED"
        }
        Write-Output "W1C_HEAD_UPGRADE_OK"

        $env:SSWCENTER_DATABASE_URL = $AppDatabaseUrl
        & $PythonExe -m pytest -q tests/test_w1c_postgres.py
        if ($LASTEXITCODE -ne 0) {
            throw "W1C_HARNESS_POSTGRES_TEST_FAILED"
        }
        $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
        $PostcheckOutput = @(& $PythonExe -m app.db.postcheck_w1a_vs1)
        $PostcheckOutput | Write-Output
        if (
            $LASTEXITCODE -ne 0 -or
            $PostcheckOutput -notcontains "RECIPIENT_GUARDIAN_EMAIL_DB_POSTCHECK_OK"
        ) {
            throw "W1C_HARNESS_POSTCHECK_FAILED"
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($ClusterStarted) {
        & $PgCtlExe --pgdata=$DataDirectory stop --mode=fast --wait
        $ClusterStarted = $false
    }
    if (Test-Path -LiteralPath $ClusterRoot) {
        Remove-W1cTree -Path $ClusterRoot
    }
}

$ListenerRemaining = @(
    Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
).Count
$TempClusterRemaining = @(
    Get-ChildItem -LiteralPath $TempParent -Directory -Filter "sswcenter-w1c-pg-*" `
        -Force -ErrorAction SilentlyContinue
).Count
Write-Output ("W1C_LISTENER_REMAINING=" + $ListenerRemaining)
Write-Output ("W1C_TEMP_CLUSTER_REMAINING=" + $TempClusterRemaining)
if ($ListenerRemaining -ne 0 -or $TempClusterRemaining -ne 0) {
    throw "W1C_HARNESS_FINAL_INVARIANT_FAILED"
}
Write-Output "W1C_POSTGRES_GREEN"
