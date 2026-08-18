param(
    [int]$Port = 55438,
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.IO.Path]::DirectorySeparatorChar -eq '\') {
    throw "W3_0028_POSTGRES_LINUX_ONLY"
}
if ($Port -lt 1024 -or $Port -gt 65535) {
    throw "W3_0028_POSTGRES_PORT_INVALID"
}

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$PythonExe = if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    Join-Path $BackendRoot ".venv/bin/python"
} else {
    if (-not [System.IO.Path]::IsPathRooted($PythonExecutable)) {
        throw "W3_0028_POSTGRES_PYTHON_MUST_BE_ABSOLUTE"
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
        throw "W3_0028_POSTGRES_EXECUTABLE_MISSING: $Executable"
    }
}

& $PythonExe -B -c "import alembic, sqlalchemy, psycopg, pytest"
if ($LASTEXITCODE -ne 0) {
    throw "W3_0028_POSTGRES_PYTHON_DEPENDENCIES_MISSING"
}

$PortProbe = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    $Port
)
try {
    $PortProbe.Start()
}
catch {
    throw "W3_0028_POSTGRES_PORT_IN_USE: $Port"
}
finally {
    $PortProbe.Stop()
}

$TempParent = [System.IO.Path]::GetFullPath("/tmp")
$ClusterRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $TempParent ("sswcenter-w3-0028-pg-" + [Guid]::NewGuid().ToString("N")))
)
$TempPrefix = $TempParent.TrimEnd('/') + '/'
$ClusterLeaf = Split-Path -Leaf $ClusterRoot
if (
    -not $ClusterRoot.StartsWith($TempPrefix, [StringComparison]::Ordinal) -or
    $ClusterLeaf -cnotmatch '^sswcenter-w3-0028-pg-[0-9a-f]{32}$'
) {
    throw "W3_0028_POSTGRES_UNSAFE_CLUSTER_PATH"
}

$DataDirectory = Join-Path $ClusterRoot "data"
$SocketDirectory = Join-Path $ClusterRoot "socket"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$DataRoot = Join-Path $ClusterRoot "sswcenter-w3-0028-data"
$DatabaseName = "sswcenter_w3_0028_test"
$PreviousRevision = "20260817_0027_w2_official_card_assignee_and_plan_replacement"
$CurrentRevision = "20260817_0028_w3_source_intake_foundation"
$OwnerDatabaseUrl = "postgresql+psycopg://erp_owner@127.0.0.1:$Port/$DatabaseName"
$AppDatabaseUrl = "postgresql+psycopg://erp_app@127.0.0.1:$Port/$DatabaseName"
$GrantScript = Join-Path $WorkspaceRoot "infra/postgres/grant-application-access.sql"
$PostgresTestFile = Join-Path $BackendRoot "tests/test_w3_0028_postgres.py"
$InitialGitStatus = ((
        & git -C $WorkspaceRoot status --porcelain --untracked-files=all
    ) -join "`n")

$W3NodeIds = @(
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_current_revision_and_postcheck",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_duplicate_snapshot_identity_rejected",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_one_active_per_source_date",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_append_only_same_digest_receipts",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_duplicate_retry_and_blocked_receipts_link_one_existing_run",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_composite_lineage_rejects_direct_sql_mismatch",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_receipt_row_and_attempt_are_append_only_for_erp_app",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_fk_restrict_and_closed_status",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_direct_sql_hostile_generic_columns",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_weakened_or_moved_check",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_missing_or_extra_catalog",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_lowercase_active_predicate",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_app_status_update_only_other_columns_are_42501",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_hostile_filename_update_grant",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_rogue_second_head_fails_direct_dispatcher_and_readiness",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_two_connection_active_partial_unique_race",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_dispatcher_rejects_historical_revision_without_head_marker",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_app_direct_verifier_rejects_hidden_no_privilege_w3_relation",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_app_url_is_not_superuser",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_unexpected_owner",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_sequence_and_schema_acl_drift",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_table_and_column_acl_provenance",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_deferrable_pk_hash_and_extra_indexes",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_set_role_membership_bypass",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_fk_trigger_and_replication_bypass",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_fk_inventory_collision_and_metadata_drift",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_hidden_matview_and_standalone_sequence",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_unlogged_persistence",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_identity_sequence_option_drift",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_rls_policy",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_raw_admin_option_set_false_membership",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_raw_inherit_true_set_false_membership",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_rejects_rolinherit_false",
    "tests/test_w3_0028_postgres.py::test_w3_0028_pg_postcheck_accepts_unrelated_w3x_namespace_object"
)
foreach ($RequiredPath in @($GrantScript, $PostgresTestFile)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "W3_0028_POSTGRES_REQUIRED_FILE_MISSING: $RequiredPath"
    }
}
$ExpectedNodeNames = @(
    $W3NodeIds | ForEach-Object { ($_ -split '::', 2)[1] }
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
    raise SystemExit("W3_0028_POSTGRES_NODE_DRIFT")
'@
& $PythonExe -B -c $NodeDriftCheck $PostgresTestFile @ExpectedNodeNames
if ($LASTEXITCODE -ne 0) {
    throw "W3_0028_POSTGRES_NODE_DRIFT"
}

$TrackedEnvironmentNames = @(
    "SSWCENTER_ENVIRONMENT",
    "SSWCENTER_DATABASE_URL",
    "SSWCENTER_APP_DATABASE_URL",
    "SSWCENTER_DATA_ROOT",
    "SSWCENTER_W3_0028_REAL_PG",
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
$ClusterMayBeRunning = $false
$RunSucceeded = $false
$PrimaryFailure = $null
$CleanupFailure = $null
$CleanupProblems = @()

function Get-W3TableCount {
    $Catalog = @(& $PsqlExe `
            -v ON_ERROR_STOP=1 `
            -h 127.0.0.1 `
            -p $Port `
            -U erp_owner `
            -d $DatabaseName `
            -Atqc "SELECT version_num FROM erp.alembic_version; SELECT count(*) FROM information_schema.tables WHERE table_schema = 'erp' AND table_name LIKE 'w3\_%' ESCAPE '\'") |
        ForEach-Object { $_.ToString().Trim() } |
        Where-Object { $_ -ne "" }
    return $Catalog
}

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
        throw "W3_0028_POSTGRES_INITDB_FAILED"
    }

    $ClusterMayBeRunning = $true
    & $PgCtlExe `
        "--pgdata=$DataDirectory" `
        "--log=$LogFile" `
        "--options=-h 127.0.0.1 -p $Port -k $SocketDirectory" `
        start | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W3_0028_POSTGRES_START_FAILED"
    }
    $ClusterStarted = $true

    & $PgIsReadyExe -h 127.0.0.1 -p $Port -U postgres -d postgres -t 15 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W3_0028_POSTGRES_NOT_READY"
    }
    $StartedPostgresIds = @(
        Get-Process -Name postgres -ErrorAction SilentlyContinue |
            Where-Object { $BaselinePostgresIds -notcontains $_.Id } |
            Select-Object -ExpandProperty Id
    )
    Write-Output "W3_0028_POSTGRES_STAGE=cluster_ready"

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
        throw "W3_0028_POSTGRES_ROLE_BOOTSTRAP_FAILED"
    }
    & $CreateDbExe `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -O erp_owner `
        $DatabaseName
    if ($LASTEXITCODE -ne 0) {
        throw "W3_0028_POSTGRES_DATABASE_CREATE_FAILED"
    }

    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
    $env:SSWCENTER_APP_DATABASE_URL = $AppDatabaseUrl
    $env:SSWCENTER_DATA_ROOT = $DataRoot
    $env:SSWCENTER_W3_0028_REAL_PG = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PGCLIENTENCODING = "UTF8"
    $env:TMPDIR = $TempParent
    $env:TMP = $TempParent
    $env:TEMP = $TempParent

    Push-Location $BackendRoot
    try {
        & $PythonExe -B -m alembic -c alembic.ini upgrade $PreviousRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W3_0028_POSTGRES_ALEMBIC_0027_FAILED"
        }
        $Pinned0027 = Get-W3TableCount
        if ($LASTEXITCODE -ne 0 -or ($Pinned0027 -join ",") -cne "$PreviousRevision,0") {
            throw "W3_0028_POSTGRES_0027_CATALOG_MISMATCH"
        }
        Write-Output "W3_0028_POSTGRES_STAGE=migration_0027"

        & $PythonExe -B -m alembic -c alembic.ini upgrade $CurrentRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W3_0028_POSTGRES_ALEMBIC_0028_FAILED"
        }
        $Fresh0028 = Get-W3TableCount
        if ($LASTEXITCODE -ne 0 -or ($Fresh0028 -join ",") -cne "$CurrentRevision,6") {
            throw "W3_0028_POSTGRES_0028_CATALOG_MISMATCH"
        }
        Write-Output "W3_0028_POSTGRES_STAGE=migration_0028"

        & $PythonExe -B -m alembic -c alembic.ini downgrade $PreviousRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W3_0028_POSTGRES_DOWNGRADE_0027_FAILED"
        }
        $Downgraded = Get-W3TableCount
        if ($LASTEXITCODE -ne 0 -or ($Downgraded -join ",") -cne "$PreviousRevision,0") {
            throw "W3_0028_POSTGRES_DOWNGRADE_CATALOG_MISMATCH"
        }
        Write-Output "W3_0028_POSTGRES_STAGE=migration_downgrade_0027"

        & $PythonExe -B -m alembic -c alembic.ini upgrade $CurrentRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W3_0028_POSTGRES_REUPGRADE_0028_FAILED"
        }
        $Reupgraded = Get-W3TableCount
        if ($LASTEXITCODE -ne 0 -or ($Reupgraded -join ",") -cne "$CurrentRevision,6") {
            throw "W3_0028_POSTGRES_REUPGRADE_CATALOG_MISMATCH"
        }
        Write-Output "W3_0028_POSTGRES_STAGE=migration_reupgrade_0028"
    }
    finally {
        Pop-Location
    }
    Write-Output "W3_0028_POSTGRES_STAGE=migration_head"

    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U erp_owner `
        -d $DatabaseName `
        -f $GrantScript | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W3_0028_POSTGRES_APPLICATION_GRANT_FAILED"
    }
    Write-Output "W3_0028_POSTGRES_STAGE=application_acl"

    Push-Location $BackendRoot
    try {
        $env:SSWCENTER_DATABASE_URL = $AppDatabaseUrl
        $DispatchOutput = @(& $PythonExe -B -m app.db.postcheck_current_0028)
        if ($LASTEXITCODE -ne 0) {
            throw "W3_0028_POSTGRES_HISTORICAL_POSTCHECK_FAILED"
        }
        if ($DispatchOutput -notcontains "SSWCENTER_CURRENT_0028_DB_POSTCHECK_OK") {
            throw "W3_0028_POSTGRES_HISTORICAL_MARKER_MISSING"
        }
        if ($DispatchOutput -contains "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK") {
            throw "W3_0028_POSTGRES_HISTORICAL_EMITTED_CURRENT_HEAD_MARKER"
        }
        $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
        & $PythonExe -B -m pytest -q -p no:cacheprovider -s @W3NodeIds
        if ($LASTEXITCODE -ne 0) {
            throw "W3_0028_POSTGRES_LIVE_TEST_FAILED"
        }
    }
    finally {
        Pop-Location
    }

    $BlobDirectory = Join-Path $DataRoot "blobs"
    $OfficialDocumentDirectory = Join-Path $DataRoot "official-documents"
    New-Item -ItemType Directory -Path $BlobDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $OfficialDocumentDirectory -Force | Out-Null
    [System.IO.File]::WriteAllText(
        (Join-Path $BlobDirectory "w3-0028-restore-blob.txt"),
        "w3 0028 restore blob",
        [System.Text.UTF8Encoding]::new($false)
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $OfficialDocumentDirectory "w3-0028-restore-document.txt"),
        "w3 0028 restore official document",
        [System.Text.UTF8Encoding]::new($false)
    )
    $BackupRoot = Join-Path $ClusterRoot "sswcenter-backups"
    $BackupOutput = @(
        & (Join-Path $PSScriptRoot "backup-postgres.ps1") `
            -DatabaseUrl $OwnerDatabaseUrl `
            -DestinationRoot $BackupRoot `
            -DataRoot $DataRoot `
            -AppVersion "w3-0028-test"
    )
    if ($LASTEXITCODE -ne 0) {
        throw "W3_0028_POSTGRES_BACKUP_FAILED"
    }
    $BackupDirectory = (
        Get-ChildItem -LiteralPath $BackupRoot -Directory |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
    ).FullName
    if ([string]::IsNullOrWhiteSpace($BackupDirectory)) {
        throw "W3_0028_POSTGRES_BACKUP_DIRECTORY_MISSING"
    }
    $ReviewDatabaseName = "sswcenter_w3_0028_restore_review"
    $ReviewDataRoot = Join-Path $ClusterRoot "sswcenter-restore-review-w3-0028"
    $AdminDatabaseUrl = "postgresql+psycopg://postgres@127.0.0.1:$Port/postgres"
    $RestoreOutput = @(
        & (Join-Path $PSScriptRoot "restore-drill.ps1") `
            -BackupDirectory $BackupDirectory `
            -AdminDatabaseUrl $AdminDatabaseUrl `
            -ReviewDatabaseName $ReviewDatabaseName `
            -ReviewDataRoot $ReviewDataRoot `
            -PythonExe $PythonExe
    )
    if ($LASTEXITCODE -ne 0) {
        throw "W3_0028_POSTGRES_RESTORE_FAILED"
    }
    if ($RestoreOutput -notcontains "RESTORE_DRILL_OK $ReviewDatabaseName") {
        throw "W3_0028_POSTGRES_RESTORE_MARKER_MISSING"
    }
    if ($RestoreOutput -notcontains "SSWCENTER_CURRENT_0028_DB_POSTCHECK_OK") {
        throw "W3_0028_POSTGRES_RESTORE_CURRENT_0028_MARKER_MISSING"
    }
    if ($RestoreOutput -contains "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK") {
        throw "W3_0028_POSTGRES_RESTORE_EMITTED_CURRENT_HEAD_MARKER"
    }
    Write-Output "W3_0028_POSTGRES_RESTORE_GREEN"
    Write-Output "W3_0028_POSTGRES_LIVE_GREEN"
    $RunSucceeded = $true
}
catch {
    $PrimaryFailure = $_.Exception
}
finally {
    try {
        if ($ClusterMayBeRunning) {
            try {
                & $PgCtlExe `
                    "--pgdata=$DataDirectory" `
                    --mode=fast `
                    --timeout=15 `
                    stop `
                    --wait | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    $CleanupProblems += "W3_0028_POSTGRES_STOP_FAILED"
                    Write-Output "W3_0028_POSTGRES_STOP_FAILED"
                }
                else {
                    $ClusterStarted = $false
                    $ClusterMayBeRunning = $false
                    Write-Output "W3_0028_POSTGRES_STOP_BOUNDED_OK"
                }
            }
            catch {
                $CleanupProblems += (
                    "W3_0028_POSTGRES_STOP_EXCEPTION:" + [string]$_.Exception.Message
                )
                Write-Output (
                    "W3_0028_POSTGRES_STOP_FAILED " + [string]$_.Exception.Message
                )
            }
        }

        if (Test-Path -LiteralPath $ClusterRoot -PathType Container) {
            if ($ClusterMayBeRunning) {
                $CleanupProblems += "W3_0028_POSTGRES_TEMP_DELETE_SKIPPED_CLUSTER_MAY_BE_RUNNING"
            }
            else {
                $ResolvedCleanupRoot = [System.IO.Path]::GetFullPath($ClusterRoot)
                if (
                    -not $ResolvedCleanupRoot.StartsWith($TempPrefix, [StringComparison]::Ordinal) -or
                    (Split-Path -Leaf $ResolvedCleanupRoot) -cnotmatch '^sswcenter-w3-0028-pg-[0-9a-f]{32}$'
                ) {
                    throw "W3_0028_POSTGRES_UNSAFE_CLEANUP_PATH"
                }
                [System.IO.Directory]::Delete($ResolvedCleanupRoot, $true)
            }
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
            $GitDeltaCount -ne 0
        ) {
            $CleanupProblems += (
                "W3_0028_POSTGRES_CLEANUP listener={0} process={1} temp={2} git_delta={3}" -f
                $ListenerCount,
                $RemainingProcessCount,
                $TempCount,
                $GitDeltaCount
            )
        }
        else {
            Write-Output (
                "W3_0028_POSTGRES_CLEANUP listener={0} process={1} temp={2} git_delta={3}" -f
                $ListenerCount,
                $RemainingProcessCount,
                $TempCount,
                $GitDeltaCount
            )
        }
        if ($CleanupProblems.Count -ne 0) {
            foreach ($CleanupProblem in $CleanupProblems) {
                Write-Output ("W3_0028_POSTGRES_CLEANUP_FAILURE " + $CleanupProblem)
            }
            throw "W3_0028_POSTGRES_CLEANUP_NOT_ZERO"
        }
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
        throw "W3_0028_POSTGRES_FAILED_WITH_CLEANUP_FAILURE"
    }
    throw $PrimaryFailure
}
if ($null -ne $CleanupFailure) {
    throw $CleanupFailure
}
if (-not $RunSucceeded) {
    throw "W3_0028_POSTGRES_RUN_NOT_GREEN"
}

Write-Output "W3_0028_POSTGRES_SEAL_GREEN"
