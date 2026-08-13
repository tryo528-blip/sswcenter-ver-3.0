param([int]$Port = 55449)

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
$PreviousRevision = "20260812_0019_r0_w2_read_only"
$ExpectedRevision = "20260813_0025_w1_relationship_lock_contract_correction"

foreach ($Executable in @($PythonExe, $InitDbExe, $PgCtlExe, $PgIsReadyExe, $CreateDbExe, $PsqlExe)) {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "W2_CORE_HARNESS_MISSING_EXECUTABLE: $Executable"
    }
}
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    throw "W2_CORE_HARNESS_PORT_IN_USE: $Port"
}
if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "W2_CORE_HARNESS_LOCALAPPDATA_MISSING"
}

$TempParent = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Temp")).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
)
if (-not (Test-Path -LiteralPath $TempParent -PathType Container)) {
    throw "W2_CORE_HARNESS_TEMP_PARENT_MISSING"
}
$ClusterRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $TempParent ("sswcenter-w2-core-pg-" + [Guid]::NewGuid().ToString("N")))
)
$env:TEMP = $TempParent
$env:TMP = $TempParent
$env:TMPDIR = $TempParent
$ExpectedPrefix = $TempParent + [System.IO.Path]::DirectorySeparatorChar
$ClusterLeaf = Split-Path -Leaf $ClusterRoot
if (
    -not $ClusterRoot.StartsWith($ExpectedPrefix, [StringComparison]::OrdinalIgnoreCase) -or
    $ClusterLeaf -cnotmatch '^sswcenter-w2-core-pg-[0-9a-f]{32}$'
) {
    throw "W2_CORE_HARNESS_UNSAFE_TEMP_PATH"
}

$DataDirectory = Join-Path $ClusterRoot "data"
$RuntimeDataRoot = Join-Path $ClusterRoot "sswcenter-w2-core-runtime"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$UpgradeDatabase = "sswcenter_w2_upgrade_test"
$FreshDatabase = "sswcenter_w2_fresh_test"
$ClusterStarted = $false

function Remove-W2CoreTree {
    param([Parameter(Mandatory = $true)][string]$Path)
    $Resolved = [System.IO.Path]::GetFullPath($Path)
    $Parent = Split-Path -Parent $Resolved
    $Leaf = Split-Path -Leaf $Resolved
    if (
        -not [string]::Equals($Parent, $TempParent, [StringComparison]::OrdinalIgnoreCase) -or
        $Leaf -cnotmatch '^sswcenter-w2-core-pg-[0-9a-f]{32}$'
    ) {
        throw "W2_CORE_HARNESS_UNSAFE_CLEANUP_PATH"
    }
    if (Test-Path -LiteralPath $Resolved) {
        [System.IO.Directory]::Delete($Resolved, $true)
    }
}

function Set-W2DatabaseEnvironment {
    param([Parameter(Mandatory = $true)][string]$DatabaseName)
    $OwnerUrl = "postgresql+psycopg://erp_owner@127.0.0.1:$Port/$DatabaseName"
    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_DATABASE_URL = $OwnerUrl
    $env:SSWCENTER_OWNER_DATABASE_URL = $OwnerUrl
    $env:SSWCENTER_APP_DATABASE_URL = "postgresql+psycopg://erp_app@127.0.0.1:$Port/$DatabaseName"
    $env:SSWCENTER_DATA_ROOT = $RuntimeDataRoot
    $env:SSWCENTER_PIN_PEPPER = "w2-core-test-pin-pepper"
    $env:SSWCENTER_PIN_LOOKUP_KEY = "w2-core-test-pin-lookup"
    $env:SSWCENTER_CSRF_SIGNING_KEY = "w2-core-test-csrf"
    return $OwnerUrl
}

New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $RuntimeDataRoot -Force | Out-Null

try {
    & $InitDbExe --pgdata=$DataDirectory --username=postgres --auth=trust --encoding=UTF8 --locale=C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "W2_CORE_HARNESS_INITDB_FAILED" }
    & $PgCtlExe --pgdata=$DataDirectory --log=$LogFile --options="-h 127.0.0.1 -p $Port" start
    if ($LASTEXITCODE -ne 0) { throw "W2_CORE_HARNESS_POSTGRES_START_FAILED" }
    $ClusterStarted = $true
    & $PgIsReadyExe -h 127.0.0.1 -p $Port -U postgres -d postgres -t 15 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "W2_CORE_HARNESS_POSTGRES_NOT_READY" }
    & $PsqlExe -v ON_ERROR_STOP=1 -h 127.0.0.1 -p $Port -U postgres -d postgres -c (
        "CREATE ROLE erp_owner LOGIN; CREATE ROLE erp_app LOGIN; CREATE ROLE erp_backup LOGIN;"
    ) | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "W2_CORE_HARNESS_ROLE_CREATE_FAILED" }

    foreach ($DatabaseName in @($UpgradeDatabase, $FreshDatabase)) {
        & $CreateDbExe -h 127.0.0.1 -p $Port -U postgres -O erp_owner $DatabaseName
        if ($LASTEXITCODE -ne 0) {
            throw "W2_CORE_HARNESS_DATABASE_CREATE_FAILED: $DatabaseName"
        }
    }

    Push-Location $BackendRoot
    try {
        [void](Set-W2DatabaseEnvironment -DatabaseName $UpgradeDatabase)
        & $PythonExe -m alembic -c alembic.ini upgrade $PreviousRevision
        if ($LASTEXITCODE -ne 0) { throw "W2_CORE_HARNESS_PREVIOUS_UPGRADE_FAILED" }
        & $PythonExe -m alembic -c alembic.ini upgrade $ExpectedRevision
        if ($LASTEXITCODE -ne 0) { throw "W2_CORE_HARNESS_FORWARD_UPGRADE_FAILED" }
        & $PythonExe -m app.db.postcheck_current_0025
        if ($LASTEXITCODE -ne 0) { throw "W2_CORE_HARNESS_UPGRADE_POSTCHECK_FAILED" }

        [void](Set-W2DatabaseEnvironment -DatabaseName $FreshDatabase)
        & $PythonExe -m alembic -c alembic.ini upgrade $ExpectedRevision
        if ($LASTEXITCODE -ne 0) { throw "W2_CORE_HARNESS_FRESH_UPGRADE_FAILED" }
        & $PythonExe -m app.db.postcheck_current_0025
        if ($LASTEXITCODE -ne 0) { throw "W2_CORE_HARNESS_FRESH_POSTCHECK_FAILED" }

        $UpgradeUrl = Set-W2DatabaseEnvironment -DatabaseName $UpgradeDatabase
        $env:SSWCENTER_W2_REAL_PG = "1"
        $env:SSWCENTER_W2_DATABASE_URL = $UpgradeUrl
        & $PythonExe -m pytest -q `
            tests/test_w2_core_postgres.py `
            tests/test_w2_service_plan_notice_current_postgres.py
        if ($LASTEXITCODE -ne 0) { throw "W2_CORE_HARNESS_PRODUCT_TEST_FAILED" }

        $env:SSWCENTER_W1C_REAL_PG = "1"
        $env:SSWCENTER_W1D_REAL_PG = "1"
        $env:SSWCENTER_W1_RECIPIENT_REAL_PG = "1"
        $env:SSWCENTER_W1D_EXPECTED_RUNTIME_REVISION = $ExpectedRevision
        $env:SSWCENTER_DATABASE_URL = (
            "postgresql+psycopg://erp_app@127.0.0.1:$Port/$UpgradeDatabase"
        )
        $env:SSWCENTER_W1_RECIPIENT_DATABASE_URL = $env:SSWCENTER_DATABASE_URL
        $env:SSWCENTER_W1_RECIPIENT_OWNER_DATABASE_URL = $UpgradeUrl
        & $PythonExe -m pytest -q `
            tests/test_w1_recipient_contract_correction_postgres.py `
            tests/test_w1c_postgres.py `
            tests/test_w1d_postgres.py
        if ($LASTEXITCODE -ne 0) { throw "W1_W2_HARNESS_REGRESSION_TEST_FAILED" }
        Write-Output "W1_W2_INTEGRATED_POSTGRES_GREEN"
    }
    finally {
        Pop-Location
    }

    foreach ($DatabaseName in @($UpgradeDatabase, $FreshDatabase)) {
        $Revision = & $PsqlExe -v ON_ERROR_STOP=1 -h 127.0.0.1 -p $Port -U erp_owner -d $DatabaseName -tAc (
            "SELECT version_num FROM erp.alembic_version"
        )
        if ($LASTEXITCODE -ne 0 -or ($Revision -join "").Trim() -ne $ExpectedRevision) {
            throw "W2_CORE_HARNESS_REVISION_MISMATCH: $DatabaseName"
        }
        Write-Output "W2_CORE_DB_OK database=$DatabaseName revision=$ExpectedRevision"
    }
    Write-Output "W2_CORE_POSTGRES_GREEN"
}
finally {
    if ($ClusterStarted) {
        & $PgCtlExe --pgdata=$DataDirectory --mode=fast stop | Out-Null
        $ClusterStarted = $false
    }
    Remove-W2CoreTree -Path $ClusterRoot
    $ListenerCount = @(
        Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    ).Count
    $TempCount = @(
        Get-ChildItem -LiteralPath $TempParent -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -eq $ClusterLeaf }
    ).Count
    Write-Output "W2_CORE_CLEANUP listener=$ListenerCount temp=$TempCount"
}
