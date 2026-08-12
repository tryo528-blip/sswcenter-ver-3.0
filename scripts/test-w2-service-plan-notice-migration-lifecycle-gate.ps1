param(
    [int]$Port = 55446
)

# Minimal ephemeral-PostgreSQL harness for the opt-in migration lifecycle test
# test_downgrade_upgrade_downgrade_reupgrade_lifecycle in
# backend/tests/test_w2_service_plan_notice_postgres.py. Unlike the main RED
# gate harness, this creates a completely EMPTY disposable database (no
# migrations pre-applied) and lets the test itself drive alembic upgrade to
# W2_PREV_HEAD, then attempt the (currently absent) W2 migration and convert
# that failure into the correct W2_MIGRATION_MISSING_FOR_LIFECYCLE_TEST RED
# outcome.

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

foreach ($executable in @($PythonExe, $InitDbExe, $PgCtlExe, $PgIsReadyExe, $CreateDbExe)) {
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw "Required executable is missing: $executable"
    }
}

$ExistingListener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($ExistingListener) {
    throw "Port $Port is already in use"
}

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA is required for the ephemeral cluster"
}
$AllowedTempRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $env:LOCALAPPDATA "Temp")
).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
if (-not (Test-Path -LiteralPath $AllowedTempRoot -PathType Container)) {
    throw "User temporary directory is unavailable: $AllowedTempRoot"
}
$env:TEMP = $AllowedTempRoot
$env:TMP = $AllowedTempRoot
$env:TMPDIR = $AllowedTempRoot
$AllowedTempPrefix = $AllowedTempRoot + [System.IO.Path]::DirectorySeparatorChar
$ClusterRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $AllowedTempRoot ("sswcenter-w2-mig-pg-" + [Guid]::NewGuid().ToString("N")))
)
$ClusterLeaf = Split-Path -Leaf $ClusterRoot
if (-not $ClusterRoot.StartsWith($AllowedTempPrefix, [StringComparison]::OrdinalIgnoreCase) -or
    -not $ClusterLeaf.StartsWith("sswcenter-w2-mig-pg-", [StringComparison]::Ordinal)) {
    throw "Ephemeral cluster path escaped the temporary directory"
}

$DataDirectory = Join-Path $ClusterRoot "data"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$DatabaseName = "sswcenter_w2_mig_lifecycle_test"
$ClusterStarted = $false

New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null

try {
    & $InitDbExe --pgdata=$DataDirectory --username=postgres --auth=trust --encoding=UTF8 --locale=C
    if ($LASTEXITCODE -ne 0) { throw "initdb failed" }

    & $PgCtlExe --pgdata=$DataDirectory --log=$LogFile --options="-h 127.0.0.1 -p $Port" start
    if ($LASTEXITCODE -ne 0) { throw "Unable to start the ephemeral PostgreSQL cluster" }
    $ClusterStarted = $true

    & $PgIsReadyExe -h 127.0.0.1 -p $Port -U postgres -d postgres -t 10
    if ($LASTEXITCODE -ne 0) { throw "Ephemeral PostgreSQL did not become ready" }

    # Deliberately empty — no createdb migration pre-application. The test's
    # own _revision() helper treats a DB with no erp.alembic_version table as
    # current=None and drives the initial upgrade to W2_PREV_HEAD itself.
    & $CreateDbExe -h 127.0.0.1 -p $Port -U postgres $DatabaseName
    if ($LASTEXITCODE -ne 0) { throw "Unable to create the disposable migration-lifecycle database" }

    # Intentionally NOT set: SSWCENTER_DATABASE_URL (so the same-target-refusal
    # check in the test has nothing to collide with).
    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_W2_SVC_PLAN_NOTICE_MIG_PG = "1"
    $env:SSWCENTER_W2_SVC_PLAN_NOTICE_MIG_DATABASE_URL = (
        "postgresql+psycopg://postgres@127.0.0.1:{0}/{1}" -f $Port, $DatabaseName
    )
    $env:SSWCENTER_PIN_PEPPER = "w2-mig-gate-test-pin-pepper"
    $env:SSWCENTER_PIN_LOOKUP_KEY = "w2-mig-gate-test-pin-lookup"
    $env:SSWCENTER_CSRF_SIGNING_KEY = "w2-mig-gate-test-csrf"
    $env:SSWCENTER_RESIDENT_NUMBER_KEY_V1 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
    $env:SSWCENTER_RESIDENT_NUMBER_LOOKUP_KEY = "YWJjZGVmMDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODk="
    $env:SSWCENTER_RESIDENT_NUMBER_ACTIVE_KEY_VERSION = "1"
    $env:SSWCENTER_DATA_ROOT = Join-Path $ClusterRoot "sswcenter-test-files"
    New-Item -ItemType Directory -Path $env:SSWCENTER_DATA_ROOT -Force | Out-Null
    $env:PYTHONDONTWRITEBYTECODE = "1"

    Push-Location $BackendRoot
    try {
        & $PythonExe -m pytest -q -v `
            "tests/test_w2_service_plan_notice_postgres.py::test_downgrade_upgrade_downgrade_reupgrade_lifecycle"
        $PytestExitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    Write-Output ("W2_MIG_GATE_PYTEST_EXIT={0}" -f $PytestExitCode)
    Write-Output "W2_MIG_GATE_DONE"
}
finally {
    if ($ClusterStarted) {
        & $PgCtlExe --pgdata=$DataDirectory stop --mode=fast --wait
        $ClusterStarted = $false
        Start-Sleep -Seconds 1
    }
    $ResolvedClusterRoot = [System.IO.Path]::GetFullPath($ClusterRoot)
    if ($ResolvedClusterRoot.StartsWith($AllowedTempPrefix, [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $ResolvedClusterRoot).StartsWith("sswcenter-w2-mig-pg-", [StringComparison]::Ordinal) -and
        (Test-Path -LiteralPath $ResolvedClusterRoot)) {
        try { [System.IO.Directory]::Delete($ResolvedClusterRoot, $true) } catch {}
    }
}
