param(
    [int]$Port = 55436,
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.IO.Path]::DirectorySeparatorChar -eq '\') {
    throw "W1E_0026_POSTGRES_LINUX_ONLY"
}
if ($Port -lt 1024 -or $Port -gt 65535) {
    throw "W1E_0026_POSTGRES_PORT_INVALID"
}

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$PythonExe = if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    Join-Path $BackendRoot ".venv/bin/python"
} else {
    if (-not [System.IO.Path]::IsPathRooted($PythonExecutable)) {
        throw "W1E_0026_POSTGRES_PYTHON_MUST_BE_ABSOLUTE"
    }
    [System.IO.Path]::GetFullPath($PythonExecutable)
}

$PostgresBin = "/usr/lib/postgresql/16/bin"
$InitDbExe = Join-Path $PostgresBin "initdb"
$PgCtlExe = Join-Path $PostgresBin "pg_ctl"
$PgIsReadyExe = Join-Path $PostgresBin "pg_isready"
$CreateDbExe = Join-Path $PostgresBin "createdb"
$PsqlExe = "/usr/bin/psql"
foreach ($Executable in @(
        $PythonExe,
        $InitDbExe,
        $PgCtlExe,
        $PgIsReadyExe,
        $CreateDbExe,
        $PsqlExe
    )) {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "W1E_0026_POSTGRES_EXECUTABLE_MISSING: $Executable"
    }
}

# Fail closed before creating a cluster when the selected interpreter lacks the
# packages required to apply migrations and run the live 0026 pytest nodes.
& $PythonExe -B -c "import alembic, sqlalchemy, psycopg, pytest"
if ($LASTEXITCODE -ne 0) {
    throw "W1E_0026_POSTGRES_PYTHON_DEPENDENCIES_MISSING"
}

$PortProbe = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    $Port
)
try {
    $PortProbe.Start()
}
catch {
    throw "W1E_0026_POSTGRES_PORT_IN_USE: $Port"
}
finally {
    $PortProbe.Stop()
}

$TempParent = [System.IO.Path]::GetFullPath("/tmp")
$ClusterRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $TempParent ("sswcenter-w1e-0026-pg-" + [Guid]::NewGuid().ToString("N")))
)
$TempPrefix = $TempParent.TrimEnd('/') + '/'
$ClusterLeaf = Split-Path -Leaf $ClusterRoot
if (
    -not $ClusterRoot.StartsWith($TempPrefix, [StringComparison]::Ordinal) -or
    $ClusterLeaf -cnotmatch '^sswcenter-w1e-0026-pg-[0-9a-f]{32}$'
) {
    throw "W1E_0026_POSTGRES_UNSAFE_CLUSTER_PATH"
}

$DataDirectory = Join-Path $ClusterRoot "data"
$SocketDirectory = Join-Path $ClusterRoot "socket"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$DataRoot = Join-Path $ClusterRoot "sswcenter-w1e-0026-data"
$DatabaseName = "sswcenter_w1e_0026_test"
$PreviousRevision = "20260813_0025_w1_relationship_lock_contract_correction"
$CurrentRevision = "20260814_0026_w1e_care_assignment_family_relationship_lock"
$OwnerDatabaseUrl = "postgresql+psycopg://erp_owner@127.0.0.1:$Port/$DatabaseName"
$AppDatabaseUrl = "postgresql+psycopg://erp_app@127.0.0.1:$Port/$DatabaseName"
$GrantScript = Join-Path $WorkspaceRoot "infra/postgres/grant-application-access.sql"
$PostgresTestFile = Join-Path $BackendRoot "tests/test_w1e_0026_postgres.py"
$InitialGitStatus = ((
        & git -C $WorkspaceRoot status --porcelain --untracked-files=all
    ) -join "`n")

$W1eManifestPaths = @(
    "backend/alembic/versions/20260801_0012_w1e_care_assignment.py",
    "backend/alembic/versions/20260814_0026_w1e_care_assignment_family_relationship_lock.py",
    "backend/app/api/dependencies.py",
    "backend/app/api/w1e.py",
    "backend/app/core/readiness.py",
    "backend/app/db/models.py",
    "backend/app/db/postcheck_current_0026.py",
    "backend/app/db/w1e_family_relationship.py",
    "backend/app/db/postcheck_dispatch.py",
    "backend/app/domains/recipient/schemas.py",
    "backend/app/domains/recipient/service.py",
    "backend/app/domains/staff/service.py",
    "backend/app/domains/w1d/errors.py",
    "backend/app/domains/w1d/service.py",
    "backend/app/domains/w1e/__init__.py",
    "backend/app/domains/w1e/clock.py",
    "backend/app/domains/w1e/errors.py",
    "backend/app/domains/w1e/repository.py",
    "backend/app/domains/w1e/schemas.py",
    "backend/app/domains/w1e/service.py",
    "backend/app/main.py",
    "backend/tests/test_w0_readiness_write_gate.py",
    "backend/tests/test_w1e_0026_integrity_mapping.py",
    "backend/tests/test_w1e_0026_postcheck_unit.py",
    "backend/tests/test_w1e_0026_postgres.py",
    "backend/tests/test_verify_runtime_script.py",
    "backend/tests/test_w1e_phase1_behavior.py",
    "backend/tests/test_w1e_phase1_contract.py",
    "backend/tests/test_w1e_phase1_unit.py",
    "frontend/src/generated/sswcenter-api.ts",
    "scripts/generate-openapi-types.ps1",
    "scripts/PostgresTools.psm1",
    "scripts/RuntimeVersion.psm1",
    "scripts/restore-drill.ps1",
    "scripts/test-w1e-0026-postgres-linux.ps1",
    "scripts/verify-runtime.ps1"
)
function Get-W1eManifest {
    param(
        [string[]]$Paths,
        [string]$WorkspaceRoot
    )
    $Lines = foreach ($RelativePath in $Paths) {
        $FullPath = Join-Path $WorkspaceRoot $RelativePath
        if (-not (Test-Path -LiteralPath $FullPath -PathType Leaf)) {
            throw "W1E_0026_POSTGRES_MANIFEST_FILE_MISSING: $RelativePath"
        }
        $Hash = (Get-FileHash -LiteralPath $FullPath -Algorithm SHA256).Hash
        "{0}|{1}" -f $RelativePath, $Hash
    }
    return (@($Lines) -join "`n")
}
$InitialW1eManifest = Get-W1eManifest -Paths $W1eManifestPaths -WorkspaceRoot $WorkspaceRoot

$W1e0026NodeIds = @(
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_current_head_and_constraints_exist",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_family_check_success_and_rejections",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_general_null_relationship_and_multiple_staff_allowed",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_same_contract_staff_overlap_rejected",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_forward_guards_accept_and_reject_exact_boundaries",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_reverse_guards_reject_parent_mutations",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_contract_concurrent_assignment_vs_parent_update",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_employment_concurrent_assignment_vs_parent_update",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_contract_qualification_reverse_concurrent_no_orphan",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_multi_edge_employment_parent_no_deadlock",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_multi_row_assignment_transaction_fine_grained_fail_fast",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_unrelated_writes_do_not_share_global_mutex",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_disjoint_domain_writes_overlap_and_commit",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_employment_lock_helper_always_locks_employment_path",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_employment_helper_transient_disappearance_still_locks_employment",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_period_fact_correction_boundary",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_postcheck_assertions_pass_without_trigger_bypass",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_lock_function_integer_overload_rejected",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_lock_function_global_remnant_rejected",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_care_assignment_sequence_acl_fails_closed",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_lock_function_catalog_properties_fail_closed",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_http_create_replace_through_real_service_and_audit",
    "tests/test_w1e_0026_postgres.py::test_w1e_0026_pg_trigger_function_catalog_properties_fail_closed"
)
foreach ($RequiredPath in @($GrantScript, $PostgresTestFile)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "W1E_0026_POSTGRES_REQUIRED_FILE_MISSING: $RequiredPath"
    }
}
$ExpectedNodeNames = @(
    $W1e0026NodeIds | ForEach-Object { ($_ -split '::', 2)[1] }
)
$NodeDriftCheck = @'
import ast
import pathlib
import sys

test_path = pathlib.Path(sys.argv[1])
expected = sys.argv[2:]
names = [
    node.name
    for node in ast.parse(test_path.read_text(encoding="utf-8")).body
    if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
]
if names != expected:
    raise SystemExit("W1E_0026_POSTGRES_NODE_DRIFT")
'@
& $PythonExe -B -c $NodeDriftCheck $PostgresTestFile @ExpectedNodeNames
if ($LASTEXITCODE -ne 0) {
    throw "W1E_0026_POSTGRES_NODE_DRIFT"
}

$TrackedEnvironmentNames = @(
    "SSWCENTER_ENVIRONMENT",
    "SSWCENTER_DATABASE_URL",
    "SSWCENTER_APP_DATABASE_URL",
    "SSWCENTER_DATA_ROOT",
    "SSWCENTER_W1E_0026_REAL_PG",
    "PYTHONDONTWRITEBYTECODE",
    "PGCLIENTENCODING",
    "TMPDIR",
    "TMP",
    "TEMP"
)
$PreviousEnvironment = @{}
foreach ($EnvironmentName in $TrackedEnvironmentNames) {
    $PreviousEnvironment[$EnvironmentName] = [Environment]::GetEnvironmentVariable(
        $EnvironmentName,
        "Process"
    )
}

$BaselinePostgresIds = @(
    Get-Process -Name postgres -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Id
)
$StartedPostgresIds = @()
$ClusterStarted = $false
$RunSucceeded = $false
$PrimaryFailure = $null
$CleanupFailure = $null

try {
    New-Item -ItemType Directory -Path $DataDirectory | Out-Null
    New-Item -ItemType Directory -Path $SocketDirectory | Out-Null
    New-Item -ItemType Directory -Path $DataRoot | Out-Null

    & $InitDbExe `
        "--pgdata=$DataDirectory" `
        "--username=postgres" `
        "--auth=trust" `
        "--encoding=UTF8" `
        "--locale=C.utf8" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W1E_0026_POSTGRES_INITDB_FAILED"
    }

    & $PgCtlExe `
        "--pgdata=$DataDirectory" `
        "--log=$LogFile" `
        "--options=-h 127.0.0.1 -p $Port -k $SocketDirectory" `
        start | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W1E_0026_POSTGRES_START_FAILED"
    }
    $ClusterStarted = $true

    & $PgIsReadyExe -h 127.0.0.1 -p $Port -U postgres -d postgres -t 15 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W1E_0026_POSTGRES_NOT_READY"
    }
    $StartedPostgresIds = @(
        Get-Process -Name postgres -ErrorAction SilentlyContinue |
            Where-Object { $BaselinePostgresIds -notcontains $_.Id } |
            Select-Object -ExpandProperty Id
    )
    Write-Output "W1E_0026_POSTGRES_STAGE=cluster_ready"

    $RoleSql = @'
CREATE ROLE erp_owner LOGIN;
CREATE ROLE erp_app LOGIN;
CREATE ROLE erp_backup LOGIN;
'@
    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -d postgres `
        -c $RoleSql | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W1E_0026_POSTGRES_ROLE_BOOTSTRAP_FAILED"
    }
    & $CreateDbExe `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -O erp_owner `
        $DatabaseName
    if ($LASTEXITCODE -ne 0) {
        throw "W1E_0026_POSTGRES_DATABASE_CREATE_FAILED"
    }

    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
    $env:SSWCENTER_APP_DATABASE_URL = $AppDatabaseUrl
    $env:SSWCENTER_DATA_ROOT = $DataRoot
    $env:SSWCENTER_W1E_0026_REAL_PG = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PGCLIENTENCODING = "UTF8"
    # Windows-hosted Codex sessions can leak TEMP/TMP values such as
    # /mnt/c/WINDOWS/TEMP into Linux.  Python's tempfile module then rejects
    # this harness's deliberately isolated /tmp data root as being outside its
    # operating-system temporary directory.  Pin all Linux temp selectors for
    # child processes and restore them in the existing finally block.
    $env:TMPDIR = $TempParent
    $env:TMP = $TempParent
    $env:TEMP = $TempParent

    Push-Location $BackendRoot
    try {
        & $PythonExe -B -m alembic -c alembic.ini upgrade $CurrentRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W1E_0026_POSTGRES_ALEMBIC_FAILED"
        }
        Write-Output "W1E_0026_POSTGRES_STAGE=migration_head_initial"

        & $PythonExe -B -m alembic -c alembic.ini downgrade $PreviousRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W1E_0026_POSTGRES_ALEMBIC_DOWNGRADE_FAILED"
        }

        $DowngradedRevision = [string](& $PsqlExe `
                -v ON_ERROR_STOP=1 `
                -h 127.0.0.1 `
                -p $Port `
                -U erp_owner `
                -d $DatabaseName `
                -Atqc "SELECT version_num FROM erp.alembic_version")
        if (
            $LASTEXITCODE -ne 0 -or
            $DowngradedRevision.Trim() -cne $PreviousRevision
        ) {
            throw "W1E_0026_POSTGRES_DOWNGRADE_REVISION_MISMATCH"
        }
        $DowngradedConstraintCount = [string](& $PsqlExe `
                -v ON_ERROR_STOP=1 `
                -h 127.0.0.1 `
                -p $Port `
                -U erp_owner `
                -d $DatabaseName `
                -Atqc (
                    "SELECT count(*) FROM pg_constraint " +
                    "WHERE conrelid = 'erp.care_assignment'::regclass " +
                    "AND conname = 'ck_care_assignment_family_relationship_present'"
                ))
        if ($LASTEXITCODE -ne 0 -or $DowngradedConstraintCount.Trim() -cne "0") {
            throw "W1E_0026_POSTGRES_DOWNGRADE_CONSTRAINT_PRESENT"
        }
        Write-Output "W1E_0026_POSTGRES_STAGE=migration_downgrade_0025"

        & $PythonExe -B -m alembic -c alembic.ini upgrade $CurrentRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W1E_0026_POSTGRES_ALEMBIC_REUPGRADE_FAILED"
        }
        $ReupgradedRevision = [string](& $PsqlExe `
                -v ON_ERROR_STOP=1 `
                -h 127.0.0.1 `
                -p $Port `
                -U erp_owner `
                -d $DatabaseName `
                -Atqc "SELECT version_num FROM erp.alembic_version")
        if (
            $LASTEXITCODE -ne 0 -or
            $ReupgradedRevision.Trim() -cne $CurrentRevision
        ) {
            throw "W1E_0026_POSTGRES_REUPGRADE_REVISION_MISMATCH"
        }
        $ReupgradedConstraintCount = [string](& $PsqlExe `
                -v ON_ERROR_STOP=1 `
                -h 127.0.0.1 `
                -p $Port `
                -U erp_owner `
                -d $DatabaseName `
                -Atqc (
                    "SELECT count(*) FROM pg_constraint " +
                    "WHERE conrelid = 'erp.care_assignment'::regclass " +
                    "AND conname = 'ck_care_assignment_family_relationship_present'"
                ))
        if ($LASTEXITCODE -ne 0 -or $ReupgradedConstraintCount.Trim() -cne "1") {
            throw "W1E_0026_POSTGRES_REUPGRADE_CONSTRAINT_MISMATCH"
        }
    }
    finally {
        Pop-Location
    }
    Write-Output "W1E_0026_POSTGRES_STAGE=migration_head"

    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U erp_owner `
        -d $DatabaseName `
        -f $GrantScript | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W1E_0026_POSTGRES_APPLICATION_GRANT_FAILED"
    }
    Write-Output "W1E_0026_POSTGRES_STAGE=application_acl"

    Push-Location $BackendRoot
    try {
        $env:SSWCENTER_DATABASE_URL = $AppDatabaseUrl
        # 0026 is intentionally a pinned historical W1E gate. It must use its
        # direct verifier and must never claim the active 0027 current-head
        # marker.
        & $PythonExe -B -m app.db.postcheck_current_0026
        if ($LASTEXITCODE -ne 0) {
            throw "W1E_0026_POSTGRES_CURRENT_POSTCHECK_FAILED"
        }
        $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
        & $PythonExe -B -m pytest -q -p no:cacheprovider @W1e0026NodeIds
        if ($LASTEXITCODE -ne 0) {
            throw "W1E_0026_POSTGRES_LIVE_TEST_FAILED"
        }
    }
    finally {
        Pop-Location
    }

    Write-Output "W1E_0026_POSTGRES_LIVE_GREEN"
    $RunSucceeded = $true
}
catch {
    $PrimaryFailure = $_.Exception
}
finally {
    try {
        if ($ClusterStarted) {
            & $PgCtlExe "--pgdata=$DataDirectory" --mode=fast stop --wait | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "W1E_0026_POSTGRES_STOP_FAILED"
            }
            $ClusterStarted = $false
        }

        if (Test-Path -LiteralPath $ClusterRoot -PathType Container) {
            $ResolvedCleanupRoot = [System.IO.Path]::GetFullPath($ClusterRoot)
            if (
                -not $ResolvedCleanupRoot.StartsWith($TempPrefix, [StringComparison]::Ordinal) -or
                (Split-Path -Leaf $ResolvedCleanupRoot) -cnotmatch '^sswcenter-w1e-0026-pg-[0-9a-f]{32}$'
            ) {
                throw "W1E_0026_POSTGRES_UNSAFE_CLEANUP_PATH"
            }
            [System.IO.Directory]::Delete($ResolvedCleanupRoot, $true)
        }

        $RemainingProcessCount = @(
            Get-Process -Name postgres -ErrorAction SilentlyContinue |
                Where-Object { $StartedPostgresIds -contains $_.Id }
        ).Count
        $TempCount = if (Test-Path -LiteralPath $ClusterRoot) { 1 } else { 0 }
        $FinalGitStatus = ((
                & git -C $WorkspaceRoot status --porcelain --untracked-files=all
            ) -join "`n")
        $GitDeltaCount = if ($FinalGitStatus -ceq $InitialGitStatus) { 0 } else { 1 }

        $FinalW1eManifest = Get-W1eManifest -Paths $W1eManifestPaths -WorkspaceRoot $WorkspaceRoot
        $W1eManifestDeltaCount = if ($FinalW1eManifest -ceq $InitialW1eManifest) { 0 } else { 1 }

        $CleanupPortProbe = [System.Net.Sockets.TcpListener]::new(
            [System.Net.IPAddress]::Loopback,
            $Port
        )
        $ListenerCount = 0
        try {
            $CleanupPortProbe.Start()
        }
        catch {
            $ListenerCount = 1
        }
        finally {
            $CleanupPortProbe.Stop()
        }

        if (
            $ListenerCount -ne 0 -or
            $RemainingProcessCount -ne 0 -or
            $TempCount -ne 0 -or
            $GitDeltaCount -ne 0 -or
            $W1eManifestDeltaCount -ne 0
        ) {
            throw "W1E_0026_POSTGRES_CLEANUP_NOT_ZERO"
        }
        Write-Output (
            "W1E_0026_POSTGRES_CLEANUP listener={0} process={1} temp={2} git_delta={3} manifest_delta={4}" -f
            $ListenerCount,
            $RemainingProcessCount,
            $TempCount,
            $GitDeltaCount,
            $W1eManifestDeltaCount
        )
    }
    catch {
        $CleanupFailure = $_.Exception
    }
    finally {
        foreach ($EnvironmentName in $TrackedEnvironmentNames) {
            $PreviousValue = $PreviousEnvironment[$EnvironmentName]
            if ($null -eq $PreviousValue) {
                Remove-Item -LiteralPath "Env:$EnvironmentName" -ErrorAction SilentlyContinue
            }
            else {
                Set-Item -Path "Env:$EnvironmentName" -Value $PreviousValue
            }
        }
    }
}

if ($null -ne $PrimaryFailure) {
    if ($null -ne $CleanupFailure) {
        throw "W1E_0026_POSTGRES_FAILED_WITH_CLEANUP_FAILURE"
    }
    throw $PrimaryFailure
}
if ($null -ne $CleanupFailure) {
    throw $CleanupFailure
}
if (-not $RunSucceeded) {
    throw "W1E_0026_POSTGRES_RUN_NOT_GREEN"
}

Write-Output "W1E_0026_POSTGRES_SEAL_GREEN"
