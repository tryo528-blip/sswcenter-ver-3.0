param(
    [int]$Port = 55440,
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([System.IO.Path]::DirectorySeparatorChar -eq '\') {
    throw "W3_0029_POSTGRES_LINUX_ONLY"
}
if ($Port -lt 1024 -or $Port -gt 65535) {
    throw "W3_0029_POSTGRES_PORT_INVALID"
}

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
if ($WorkspaceRoot -cne "/home/codexctl/workspace/sswcenter-3-0") {
    throw "W3_0029_POSTGRES_WORKSPACE_ROOT_MISMATCH: $WorkspaceRoot"
}
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$PythonExe = if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    Join-Path $BackendRoot ".venv/bin/python"
}
else {
    if (-not [System.IO.Path]::IsPathRooted($PythonExecutable)) {
        throw "W3_0029_POSTGRES_PYTHON_MUST_BE_ABSOLUTE"
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
        throw "W3_0029_POSTGRES_EXECUTABLE_MISSING: $Executable"
    }
}

& $PythonExe -B -c "import alembic, fastapi, openpyxl, psycopg, pytest, sqlalchemy"
if ($LASTEXITCODE -ne 0) {
    throw "W3_0029_POSTGRES_PYTHON_DEPENDENCIES_MISSING"
}

$PortProbe = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    $Port
)
try {
    $PortProbe.Start()
}
catch {
    throw "W3_0029_POSTGRES_PORT_IN_USE: $Port"
}
finally {
    $PortProbe.Stop()
}

$TempParent = [System.IO.Path]::GetFullPath("/tmp")
$ClusterRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $TempParent ("sswcenter-w3-0029-pg-" + [Guid]::NewGuid().ToString("N")))
)
$TempPrefix = $TempParent.TrimEnd('/') + '/'
$ClusterLeaf = Split-Path -Leaf $ClusterRoot
if (
    -not $ClusterRoot.StartsWith($TempPrefix, [StringComparison]::Ordinal) -or
    $ClusterLeaf -cnotmatch '^sswcenter-w3-0029-pg-[0-9a-f]{32}$'
) {
    throw "W3_0029_POSTGRES_UNSAFE_CLUSTER_PATH"
}

$DataDirectory = Join-Path $ClusterRoot "data"
$SocketDirectory = Join-Path $ClusterRoot "socket"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$DataRoot = Join-Path $ClusterRoot "sswcenter-w3-0029-data"
$DatabaseName = "sswcenter_w3_0029_test"
$PreviousRevision = "20260817_0028_w3_source_intake_foundation"
$CurrentRevision = "20260818_0029_w3_persistent_apply_workspace"
$OwnerDatabaseUrl = "postgresql+psycopg://erp_owner@127.0.0.1:$Port/$DatabaseName"
$AppDatabaseUrl = "postgresql+psycopg://erp_app@127.0.0.1:$Port/$DatabaseName"
$AdminDatabaseUrl = "postgresql+psycopg://postgres@127.0.0.1:$Port/postgres"
$GrantScript = Join-Path $WorkspaceRoot "infra/postgres/grant-application-access.sql"
$PostgresTestFile = Join-Path $BackendRoot "tests/test_w3_0029_postgres.py"
foreach ($RequiredPath in @($GrantScript, $PostgresTestFile)) {
    if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
        throw "W3_0029_POSTGRES_REQUIRED_FILE_MISSING: $RequiredPath"
    }
}

$InitialGitStatus = ((
        & git -C $WorkspaceRoot status --porcelain --untracked-files=all
    ) -join "`n")
$TrackedEnvironmentNames = @(
    "SSWCENTER_ENVIRONMENT",
    "SSWCENTER_DATABASE_URL",
    "SSWCENTER_APP_DATABASE_URL",
    "SSWCENTER_DATA_ROOT",
    "SSWCENTER_W3_0029_REAL_PG",
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
$ClusterMayBeRunning = $false
$RunSucceeded = $false
$PrimaryFailure = $null
$CleanupFailure = $null
$CleanupProblems = @()

function Get-W3Catalog {
    return @(& $PsqlExe `
            -v ON_ERROR_STOP=1 `
            -h 127.0.0.1 `
            -p $Port `
            -U erp_owner `
            -d $DatabaseName `
            -Atqc (
                "SELECT version_num FROM erp.alembic_version; " +
                "SELECT count(*) FROM information_schema.tables " +
                "WHERE table_schema = 'erp' " +
                "AND table_name LIKE 'w3\_%' ESCAPE '\';"
            )) |
        ForEach-Object { $_.ToString().Trim() } |
        Where-Object { $_ -ne "" }
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
        throw "W3_0029_POSTGRES_INITDB_FAILED"
    }

    $ClusterMayBeRunning = $true
    & $PgCtlExe `
        "--pgdata=$DataDirectory" `
        "--log=$LogFile" `
        "--options=-h 127.0.0.1 -p $Port -k $SocketDirectory" `
        start | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W3_0029_POSTGRES_START_FAILED"
    }
    & $PgIsReadyExe -h 127.0.0.1 -p $Port -U postgres -d postgres -t 15 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W3_0029_POSTGRES_NOT_READY"
    }
    $StartedPostgresIds = @(
        Get-Process -Name postgres -ErrorAction SilentlyContinue |
            Where-Object { $BaselinePostgresIds -notcontains $_.Id } |
            Select-Object -ExpandProperty Id
    )
    Write-Output "W3_0029_POSTGRES_STAGE=cluster_ready"

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
        throw "W3_0029_POSTGRES_ROLE_BOOTSTRAP_FAILED"
    }
    & $CreateDbExe `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -O erp_owner `
        $DatabaseName
    if ($LASTEXITCODE -ne 0) {
        throw "W3_0029_POSTGRES_DATABASE_CREATE_FAILED"
    }

    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
    $env:SSWCENTER_APP_DATABASE_URL = $AppDatabaseUrl
    $env:SSWCENTER_DATA_ROOT = $DataRoot
    $env:SSWCENTER_W3_0029_REAL_PG = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PGCLIENTENCODING = "UTF8"
    $env:TMPDIR = $TempParent
    $env:TMP = $TempParent
    $env:TEMP = $TempParent

    Push-Location $BackendRoot
    try {
        & $PythonExe -B -m alembic -c alembic.ini upgrade $PreviousRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W3_0029_POSTGRES_ALEMBIC_0028_FAILED"
        }
        $Pinned0028 = Get-W3Catalog
        if ($LASTEXITCODE -ne 0 -or ($Pinned0028 -join ",") -cne "$PreviousRevision,6") {
            throw "W3_0029_POSTGRES_0028_CATALOG_MISMATCH"
        }
        Write-Output "W3_0029_POSTGRES_STAGE=migration_0028"

        & $PythonExe -B -m alembic -c alembic.ini upgrade $CurrentRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W3_0029_POSTGRES_ALEMBIC_0029_FAILED"
        }
        $Fresh0029 = Get-W3Catalog
        if ($LASTEXITCODE -ne 0 -or ($Fresh0029 -join ",") -cne "$CurrentRevision,16") {
            throw "W3_0029_POSTGRES_0029_CATALOG_MISMATCH"
        }
        Write-Output "W3_0029_POSTGRES_STAGE=migration_0029"

        & $PythonExe -B -m alembic -c alembic.ini downgrade $PreviousRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W3_0029_POSTGRES_DOWNGRADE_0028_FAILED"
        }
        $Downgraded = Get-W3Catalog
        if ($LASTEXITCODE -ne 0 -or ($Downgraded -join ",") -cne "$PreviousRevision,6") {
            throw "W3_0029_POSTGRES_DOWNGRADE_CATALOG_MISMATCH"
        }
        $ParentUniqueCount = @(& $PsqlExe `
                -v ON_ERROR_STOP=1 `
                -h 127.0.0.1 `
                -p $Port `
                -U erp_owner `
                -d $DatabaseName `
                -Atqc (
                    "SELECT count(*) FROM pg_constraint " +
                    "WHERE connamespace = 'erp'::regnamespace " +
                    "AND conname IN " +
                    "('uq_w3_source_snapshot_id_source_date', " +
                    "'uq_w3_import_run_id_snapshot');"
                ))
        if (($ParentUniqueCount -join "").Trim() -cne "0") {
            throw "W3_0029_POSTGRES_DOWNGRADE_PARENT_UNIQUE_DRIFT"
        }
        Write-Output "W3_0029_POSTGRES_STAGE=migration_downgrade_0028"

        & $PythonExe -B -m alembic -c alembic.ini upgrade $CurrentRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W3_0029_POSTGRES_REUPGRADE_0029_FAILED"
        }
        $Reupgraded = Get-W3Catalog
        if ($LASTEXITCODE -ne 0 -or ($Reupgraded -join ",") -cne "$CurrentRevision,16") {
            throw "W3_0029_POSTGRES_REUPGRADE_CATALOG_MISMATCH"
        }
        Write-Output "W3_0029_POSTGRES_STAGE=migration_reupgrade_0029"
    }
    finally {
        Pop-Location
    }

    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U erp_owner `
        -d $DatabaseName `
        -f $GrantScript | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W3_0029_POSTGRES_APPLICATION_GRANT_FAILED"
    }
    Write-Output "W3_0029_POSTGRES_STAGE=application_acl"

    Push-Location $BackendRoot
    try {
        $env:SSWCENTER_DATABASE_URL = $AppDatabaseUrl
        $DispatchOutput = @(& $PythonExe -B -m app.db.postcheck_dispatch)
        if ($LASTEXITCODE -ne 0) {
            throw "W3_0029_POSTGRES_CURRENT_POSTCHECK_FAILED"
        }
        if ($DispatchOutput -notcontains "SSWCENTER_CURRENT_0029_DB_POSTCHECK_OK") {
            throw "W3_0029_POSTGRES_CURRENT_MARKER_MISSING"
        }
        if ($DispatchOutput -notcontains "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK") {
            throw "W3_0029_POSTGRES_HEAD_MARKER_MISSING"
        }
        $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
        & $PythonExe -B -m pytest `
            -q `
            -p no:cacheprovider `
            -s `
            tests/test_w3_0029_postgres.py
        if ($LASTEXITCODE -ne 0) {
            throw "W3_0029_POSTGRES_LIVE_TEST_FAILED"
        }
    }
    finally {
        Pop-Location
    }
    Write-Output "W3_0029_POSTGRES_LIVE_GREEN"

    Push-Location $BackendRoot
    try {
        $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
        & $PythonExe -B -m alembic -c alembic.ini downgrade $PreviousRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W3_0029_POSTGRES_DATAFUL_DOWNGRADE_FAILED"
        }
        $DatafulDowngraded = Get-W3Catalog
        if (
            $LASTEXITCODE -ne 0 -or
            ($DatafulDowngraded -join ",") -cne "$PreviousRevision,6"
        ) {
            throw "W3_0029_POSTGRES_DATAFUL_DOWNGRADE_CATALOG_MISMATCH"
        }
        $PreservedActiveState = @(& $PsqlExe `
                -v ON_ERROR_STOP=1 `
                -h 127.0.0.1 `
                -p $Port `
                -U erp_owner `
                -d $DatabaseName `
                -Atqc (
                    "SELECT count(*) FROM erp.w3_source_snapshot " +
                    "WHERE status = 'ACTIVE'; " +
                    "SELECT count(*) FROM erp.w3_import_run AS run " +
                    "JOIN erp.w3_source_snapshot AS snapshot " +
                    "ON snapshot.id = run.snapshot_id " +
                    "WHERE snapshot.status = 'ACTIVE' AND run.status = 'APPLIED';"
                )) |
            ForEach-Object { $_.ToString().Trim() } |
            Where-Object { $_ -ne "" }
        if (($PreservedActiveState -join ",") -cne "1,1") {
            throw "W3_0029_POSTGRES_DATAFUL_DOWNGRADE_STATE_MISMATCH"
        }

        & $PythonExe -B -m alembic -c alembic.ini upgrade $CurrentRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W3_0029_POSTGRES_DATAFUL_REUPGRADE_FAILED"
        }
        $DatafulReupgraded = Get-W3Catalog
        if (
            $LASTEXITCODE -ne 0 -or
            ($DatafulReupgraded -join ",") -cne "$CurrentRevision,16"
        ) {
            throw "W3_0029_POSTGRES_DATAFUL_REUPGRADE_CATALOG_MISMATCH"
        }
        $BackfilledActiveState = @(& $PsqlExe `
                -v ON_ERROR_STOP=1 `
                -h 127.0.0.1 `
                -p $Port `
                -U erp_owner `
                -d $DatabaseName `
                -Atqc (
                    "SELECT count(*) FROM erp.w3_apply_control AS control " +
                    "JOIN erp.w3_source_snapshot AS snapshot " +
                    "ON snapshot.id = control.active_snapshot_id " +
                    "AND snapshot.source_type = control.source_type " +
                    "AND snapshot.target_date = control.target_date " +
                    "JOIN erp.w3_import_run AS run " +
                    "ON run.id = control.active_import_run_id " +
                    "AND run.snapshot_id = snapshot.id " +
                    "WHERE snapshot.status = 'ACTIVE' AND run.status = 'APPLIED'; " +
                    "SELECT count(*) FROM erp.w3_source_snapshot AS snapshot " +
                    "LEFT JOIN erp.w3_apply_control AS control " +
                    "ON control.source_type = snapshot.source_type " +
                    "AND control.target_date = snapshot.target_date " +
                    "AND control.active_snapshot_id = snapshot.id " +
                    "WHERE snapshot.status = 'ACTIVE' " +
                    "AND control.source_type IS NULL;"
                )) |
            ForEach-Object { $_.ToString().Trim() } |
            Where-Object { $_ -ne "" }
        if (($BackfilledActiveState -join ",") -cne "1,0") {
            throw "W3_0029_POSTGRES_DATAFUL_REUPGRADE_BACKFILL_MISMATCH"
        }
    }
    finally {
        Pop-Location
    }

    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U erp_owner `
        -d $DatabaseName `
        -f $GrantScript | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W3_0029_POSTGRES_DATAFUL_REUPGRADE_GRANT_FAILED"
    }

    Push-Location $BackendRoot
    try {
        $env:SSWCENTER_DATABASE_URL = $AppDatabaseUrl
        $DatafulDispatchOutput = @(& $PythonExe -B -m app.db.postcheck_dispatch)
        if ($LASTEXITCODE -ne 0) {
            throw "W3_0029_POSTGRES_DATAFUL_REUPGRADE_POSTCHECK_FAILED"
        }
        if ($DatafulDispatchOutput -notcontains "SSWCENTER_CURRENT_0029_DB_POSTCHECK_OK") {
            throw "W3_0029_POSTGRES_DATAFUL_REUPGRADE_CURRENT_MARKER_MISSING"
        }
        if ($DatafulDispatchOutput -notcontains "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK") {
            throw "W3_0029_POSTGRES_DATAFUL_REUPGRADE_HEAD_MARKER_MISSING"
        }
        $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
    }
    finally {
        Pop-Location
    }
    Write-Output "W3_0029_POSTGRES_DATAFUL_REUPGRADE_GREEN"

    $BackupRoot = Join-Path $ClusterRoot "sswcenter-backups"
    $BackupOutput = @(
        & (Join-Path $PSScriptRoot "backup-postgres.ps1") `
            -DatabaseUrl $OwnerDatabaseUrl `
            -DestinationRoot $BackupRoot `
            -DataRoot $DataRoot `
            -AppVersion "w3-0029-test"
    )
    if ($LASTEXITCODE -ne 0) {
        throw "W3_0029_POSTGRES_BACKUP_FAILED"
    }
    $BackupDirectoryItem = Get-ChildItem -LiteralPath $BackupRoot -Directory |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $BackupDirectoryItem) {
        throw "W3_0029_POSTGRES_BACKUP_DIRECTORY_MISSING"
    }
    $BackupDirectory = $BackupDirectoryItem.FullName
    $ReviewDatabaseName = "sswcenter_w3_0029_restore_review"
    $ReviewDataRoot = Join-Path $ClusterRoot "sswcenter-restore-review-w3-0029"
    $RestoreOutput = @(
        & (Join-Path $PSScriptRoot "restore-drill.ps1") `
            -BackupDirectory $BackupDirectory `
            -AdminDatabaseUrl $AdminDatabaseUrl `
            -ReviewDatabaseName $ReviewDatabaseName `
            -ReviewDataRoot $ReviewDataRoot `
            -PythonExe $PythonExe
    )
    if ($LASTEXITCODE -ne 0) {
        throw "W3_0029_POSTGRES_RESTORE_FAILED"
    }
    if ($RestoreOutput -notcontains "RESTORE_DRILL_OK $ReviewDatabaseName") {
        throw "W3_0029_POSTGRES_RESTORE_MARKER_MISSING"
    }
    if ($RestoreOutput -notcontains "SSWCENTER_CURRENT_0029_DB_POSTCHECK_OK") {
        throw "W3_0029_POSTGRES_RESTORE_CURRENT_MARKER_MISSING"
    }
    if ($RestoreOutput -notcontains "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK") {
        throw "W3_0029_POSTGRES_RESTORE_HEAD_MARKER_MISSING"
    }
    Write-Output "W3_0029_POSTGRES_RESTORE_GREEN"
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
                    $CleanupProblems += "W3_0029_POSTGRES_STOP_FAILED"
                }
                else {
                    $ClusterMayBeRunning = $false
                    Write-Output "W3_0029_POSTGRES_STOP_BOUNDED_OK"
                }
            }
            catch {
                $CleanupProblems += (
                    "W3_0029_POSTGRES_STOP_EXCEPTION:" + [string]$_.Exception.Message
                )
            }
        }

        if (Test-Path -LiteralPath $ClusterRoot -PathType Container) {
            if ($ClusterMayBeRunning) {
                $CleanupProblems += "W3_0029_POSTGRES_TEMP_DELETE_SKIPPED_CLUSTER_RUNNING"
            }
            else {
                $ResolvedCleanupRoot = [System.IO.Path]::GetFullPath($ClusterRoot)
                if (
                    -not $ResolvedCleanupRoot.StartsWith(
                        $TempPrefix,
                        [StringComparison]::Ordinal
                    ) -or
                    (Split-Path -Leaf $ResolvedCleanupRoot) -cnotmatch `
                        '^sswcenter-w3-0029-pg-[0-9a-f]{32}$'
                ) {
                    throw "W3_0029_POSTGRES_UNSAFE_CLEANUP_PATH"
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
                "W3_0029_POSTGRES_CLEANUP listener={0} process={1} temp={2} git_delta={3}" -f
                $ListenerCount,
                $RemainingProcessCount,
                $TempCount,
                $GitDeltaCount
            )
        }
        else {
            Write-Output (
                "W3_0029_POSTGRES_CLEANUP listener={0} process={1} temp={2} git_delta={3}" -f
                $ListenerCount,
                $RemainingProcessCount,
                $TempCount,
                $GitDeltaCount
            )
        }
        if ($CleanupProblems.Count -ne 0) {
            foreach ($CleanupProblem in $CleanupProblems) {
                Write-Output ("W3_0029_POSTGRES_CLEANUP_FAILURE " + $CleanupProblem)
            }
            throw "W3_0029_POSTGRES_CLEANUP_NOT_ZERO"
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
        throw "W3_0029_POSTGRES_FAILED_WITH_CLEANUP_FAILURE"
    }
    throw $PrimaryFailure
}
if ($null -ne $CleanupFailure) {
    throw $CleanupFailure
}
if (-not $RunSucceeded) {
    throw "W3_0029_POSTGRES_RUN_NOT_GREEN"
}

Write-Output "W3_0029_POSTGRES_SEAL_GREEN"
