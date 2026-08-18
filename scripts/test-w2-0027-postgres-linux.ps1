param(
    [int]$Port = 55437,
    [int]$BackendPort = 0,
    [int]$FrontendPort = 0,
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Receive-W2CapturedStreams {
    param(
        [AllowNull()]$StdoutTask,
        [AllowNull()]$StderrTask,
        [int]$TimeoutMilliseconds = 10000
    )

    $Tasks = @()
    if ($null -ne $StdoutTask) {
        $Tasks += [System.Threading.Tasks.Task]$StdoutTask
    }
    if ($null -ne $StderrTask) {
        $Tasks += [System.Threading.Tasks.Task]$StderrTask
    }

    $Drained = $true
    $FailureMessage = ""
    if ($Tasks.Count -ne 0) {
        try {
            $Drained = [System.Threading.Tasks.Task]::WaitAll(
                [System.Threading.Tasks.Task[]]$Tasks,
                $TimeoutMilliseconds
            )
        }
        catch {
            $Drained = $false
            $FailureMessage = [string]$_.Exception.Message
        }
    }

    $Stdout = ""
    $Stderr = ""
    if ($Drained) {
        try {
            if ($null -ne $StdoutTask) {
                $Stdout = [string]$StdoutTask.Result
            }
            if ($null -ne $StderrTask) {
                $Stderr = [string]$StderrTask.Result
            }
        }
        catch {
            $Drained = $false
            $FailureMessage = [string]$_.Exception.Message
        }
    }

    return [PSCustomObject]@{
        Drained = $Drained
        Stdout = $Stdout
        Stderr = $Stderr
        FailureMessage = $FailureMessage
    }
}

function Stop-W2CapturedProcess {
    param(
        [AllowNull()][System.Diagnostics.Process]$Process,
        [AllowNull()]$StdoutTask,
        [AllowNull()]$StderrTask,
        [int]$TimeoutMilliseconds = 10000
    )

    $Succeeded = $true
    $FailureMessage = ""
    if ($null -ne $Process) {
        try {
            if (-not $Process.HasExited) {
                $Process.Kill($true)
            }
            if (-not $Process.WaitForExit($TimeoutMilliseconds)) {
                $Succeeded = $false
                $FailureMessage = "PROCESS_EXIT_TIMEOUT"
            }
        }
        catch {
            $Succeeded = $false
            $FailureMessage = [string]$_.Exception.Message
        }
    }

    $Captured = Receive-W2CapturedStreams `
        -StdoutTask $StdoutTask `
        -StderrTask $StderrTask `
        -TimeoutMilliseconds $TimeoutMilliseconds
    if (-not $Captured.Drained) {
        $Succeeded = $false
        $FailureMessage = if ([string]::IsNullOrWhiteSpace($FailureMessage)) {
            "STREAM_DRAIN_TIMEOUT"
        }
        else {
            "$FailureMessage;STREAM_DRAIN_TIMEOUT"
        }
    }

    return [PSCustomObject]@{
        Succeeded = $Succeeded
        Stdout = $Captured.Stdout
        Stderr = $Captured.Stderr
        FailureMessage = $FailureMessage
    }
}

if ([System.IO.Path]::DirectorySeparatorChar -eq '\') {
    throw "W2_0027_POSTGRES_LINUX_ONLY"
}
if ($BackendPort -eq 0) { $BackendPort = $Port + 1 }
if ($FrontendPort -eq 0) { $FrontendPort = $Port + 2 }
$RequestedPorts = @($Port, $BackendPort, $FrontendPort)
if (
    @($RequestedPorts | Where-Object { $_ -lt 1024 -or $_ -gt 65535 }).Count -ne 0 -or
    @($RequestedPorts | Sort-Object -Unique).Count -ne 3
) {
    throw "W2_0027_POSTGRES_PORT_INVALID"
}

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$FrontendRoot = Join-Path $WorkspaceRoot "frontend"
$PythonExe = if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    Join-Path $BackendRoot ".venv/bin/python"
} else {
    if (-not [System.IO.Path]::IsPathRooted($PythonExecutable)) {
        throw "W2_0027_POSTGRES_PYTHON_MUST_BE_ABSOLUTE"
    }
    [System.IO.Path]::GetFullPath($PythonExecutable)
}

$PostgresBin = "/usr/lib/postgresql/16/bin"
$InitDbExe = Join-Path $PostgresBin "initdb"
$PgCtlExe = Join-Path $PostgresBin "pg_ctl"
$PgIsReadyExe = Join-Path $PostgresBin "pg_isready"
$CreateDbExe = Join-Path $PostgresBin "createdb"
$PsqlExe = "/usr/bin/psql"
$NodeExe = "/usr/local/bin/node"
$ViteCli = Join-Path $FrontendRoot "node_modules/vite/bin/vite.js"
$PlaywrightCli = Join-Path $FrontendRoot "node_modules/playwright/cli.js"
foreach ($Executable in @(
        $PythonExe,
        $InitDbExe,
        $PgCtlExe,
        $PgIsReadyExe,
        $CreateDbExe,
        $PsqlExe,
        $NodeExe,
        $ViteCli,
        $PlaywrightCli
    )) {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        throw "W2_0027_POSTGRES_EXECUTABLE_MISSING: $Executable"
    }
}

& $PythonExe -B -c "import alembic, sqlalchemy, psycopg, pytest"
if ($LASTEXITCODE -ne 0) {
    throw "W2_0027_POSTGRES_PYTHON_DEPENDENCIES_MISSING"
}

foreach ($RequestedPort in $RequestedPorts) {
    $PortProbe = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        $RequestedPort
    )
    try {
        $PortProbe.Start()
    }
    catch {
        throw "W2_0027_POSTGRES_PORT_IN_USE: $RequestedPort"
    }
    finally {
        $PortProbe.Stop()
    }
}

$TempParent = [System.IO.Path]::GetFullPath("/tmp")
$ClusterRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $TempParent ("sswcenter-w2-0027-pg-" + [Guid]::NewGuid().ToString("N")))
)
$TempPrefix = $TempParent.TrimEnd('/') + '/'
$ClusterLeaf = Split-Path -Leaf $ClusterRoot
if (
    -not $ClusterRoot.StartsWith($TempPrefix, [StringComparison]::Ordinal) -or
    $ClusterLeaf -cnotmatch '^sswcenter-w2-0027-pg-[0-9a-f]{32}$'
) {
    throw "W2_0027_POSTGRES_UNSAFE_CLUSTER_PATH"
}

$DataDirectory = Join-Path $ClusterRoot "data"
$SocketDirectory = Join-Path $ClusterRoot "socket"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$DataRoot = Join-Path $ClusterRoot "sswcenter-w2-0027-data"
$DatabaseName = "sswcenter_w2_0027_test"
$BrowserDatabaseName = "sswcenter_w2_0027_browser_test"
$BrowserDataRoot = Join-Path $ClusterRoot "sswcenter-w2-0027-browser-data"
$PlaywrightOutputRoot = Join-Path $ClusterRoot "playwright-output"
$ViteCacheRoot = Join-Path $ClusterRoot "vite-cache"
$PreviousRevision = "20260814_0026_w1e_care_assignment_family_relationship_lock"
$CurrentRevision = "20260817_0027_w2_official_card_assignee_and_plan_replacement"
$ActiveHeadRevision = "20260818_0029_w3_persistent_apply_workspace"
$RogueRevision = "w2_0027_rogue_second_head"
$OwnerDatabaseUrl = "postgresql+psycopg://erp_owner@127.0.0.1:$Port/$DatabaseName"
$AppDatabaseUrl = "postgresql+psycopg://erp_app@127.0.0.1:$Port/$DatabaseName"
$BrowserOwnerDatabaseUrl = "postgresql+psycopg://erp_owner@127.0.0.1:$Port/$BrowserDatabaseName"
$BrowserAppDatabaseUrl = "postgresql+psycopg://erp_app@127.0.0.1:$Port/$BrowserDatabaseName"
$GrantScript = Join-Path $WorkspaceRoot "infra/postgres/grant-application-access.sql"
$PlaywrightLibraryRoot = Join-Path (
    [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
) ".local/share/sswcenter-playwright-libs/ubuntu-24.04/usr/lib/x86_64-linux-gnu"
if (-not (Test-Path -LiteralPath $PlaywrightLibraryRoot -PathType Container)) {
    throw "W2_0027_BROWSER_LIBRARY_ROOT_MISSING"
}
$InitialGitStatus = ((
        & git -C $WorkspaceRoot status --porcelain --untracked-files=all
    ) -join "`n")

$W2HistoricalNodeIds = @(
    "tests/test_w2_core_postgres.py",
    "tests/test_w2_service_plan_notice_current_postgres.py"
)
$W2HistoricalCurrentApiNode = (
    "tests/test_w2_core_postgres.py::" +
    "test_official_card_http_role_csrf_conflict_and_response_contracts"
)
$W2CurrentHttpNodeIds = @(
    "tests/test_w3_0028_w2_current_http_postgres.py"
)

$TrackedEnvironmentNames = @(
    "SSWCENTER_ENVIRONMENT",
    "SSWCENTER_DATABASE_URL",
    "SSWCENTER_APP_DATABASE_URL",
    "SSWCENTER_DATA_ROOT",
    "SSWCENTER_W2_REAL_PG",
    "SSWCENTER_W2_DATABASE_URL",
    "SSWCENTER_W2_CURRENT_HTTP_REAL_PG",
    "SSWCENTER_W2_CURRENT_HTTP_DATABASE_URL",
    "SSWCENTER_W2_CURRENT_HTTP_APP_DATABASE_URL",
    "SSWCENTER_W2_REAL_E2E",
    "SSWCENTER_W2_E2E_PIN",
    "SSWCENTER_W2_PLAYWRIGHT_OUTPUT_DIR",
    "SSWCENTER_W2_VITE_CACHE_DIR",
    "SSWCENTER_E2E_BACKEND_PORT",
    "SSWCENTER_E2E_FRONTEND_PORT",
    "VITE_DEV_LOGIN_BYPASS",
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
$ClusterMayBeRunning = $false
$RunSucceeded = $false
$PrimaryFailure = $null
$CleanupFailure = $null
$BackendProcess = $null
$BackendStdoutTask = $null
$BackendStderrTask = $null
$FrontendProcess = $null
$FrontendStdoutTask = $null
$FrontendStderrTask = $null
$PlaywrightProcess = $null
$PlaywrightStdoutTask = $null
$PlaywrightStderrTask = $null

try {
    New-Item -ItemType Directory -Path $DataDirectory | Out-Null
    New-Item -ItemType Directory -Path $SocketDirectory | Out-Null
    New-Item -ItemType Directory -Path $DataRoot | Out-Null
    New-Item -ItemType Directory -Path $BrowserDataRoot | Out-Null

    & $InitDbExe `
        "--pgdata=$DataDirectory" `
        "--username=postgres" `
        "--auth=trust" `
        "--encoding=UTF8" `
        "--locale=C.utf8" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W2_0027_POSTGRES_INITDB_FAILED"
    }

    # Be conservative before invoking pg_ctl: a nonzero/timeout result can still
    # leave a spawned postmaster. Cleanup must prove stop before deleting data.
    $ClusterMayBeRunning = $true
    & $PgCtlExe `
        "--pgdata=$DataDirectory" `
        "--log=$LogFile" `
        "--options=-h 127.0.0.1 -p $Port -k $SocketDirectory" `
        --timeout=15 `
        start | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W2_0027_POSTGRES_START_FAILED"
    }

    & $PgIsReadyExe -h 127.0.0.1 -p $Port -U postgres -d postgres -t 15 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W2_0027_POSTGRES_NOT_READY"
    }
    Write-Output "W2_0027_POSTGRES_STAGE=cluster_ready"

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
        throw "W2_0027_POSTGRES_ROLE_BOOTSTRAP_FAILED"
    }
    & $CreateDbExe `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -O erp_owner `
        $DatabaseName
    if ($LASTEXITCODE -ne 0) {
        throw "W2_0027_POSTGRES_DATABASE_CREATE_FAILED"
    }

    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
    $env:SSWCENTER_APP_DATABASE_URL = $AppDatabaseUrl
    $env:SSWCENTER_DATA_ROOT = $DataRoot
    $env:SSWCENTER_W2_REAL_PG = "1"
    $env:SSWCENTER_W2_DATABASE_URL = $OwnerDatabaseUrl
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PGCLIENTENCODING = "UTF8"
    $env:TMPDIR = $TempParent
    $env:TMP = $TempParent
    $env:TEMP = $TempParent

    Push-Location $BackendRoot
    try {
        & $PythonExe -B -m alembic -c alembic.ini upgrade $PreviousRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W2_0027_POSTGRES_ALEMBIC_0026_FAILED"
        }
        $PinnedRevision = [string](& $PsqlExe `
                -v ON_ERROR_STOP=1 `
                -h 127.0.0.1 `
                -p $Port `
                -U erp_owner `
                -d $DatabaseName `
                -Atqc "SELECT version_num FROM erp.alembic_version")
        if ($LASTEXITCODE -ne 0 -or $PinnedRevision.Trim() -cne $PreviousRevision) {
            throw "W2_0027_POSTGRES_0026_REVISION_MISMATCH"
        }
        Write-Output "W2_0027_POSTGRES_STAGE=migration_0026"

        & $PythonExe -B -m alembic -c alembic.ini upgrade $CurrentRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W2_0027_POSTGRES_ALEMBIC_HEAD_FAILED"
        }
        $HeadRevision = [string](& $PsqlExe `
                -v ON_ERROR_STOP=1 `
                -h 127.0.0.1 `
                -p $Port `
                -U erp_owner `
                -d $DatabaseName `
                -Atqc "SELECT version_num FROM erp.alembic_version")
        if ($LASTEXITCODE -ne 0 -or $HeadRevision.Trim() -cne $CurrentRevision) {
            throw "W2_0027_POSTGRES_HEAD_REVISION_MISMATCH"
        }

        # Seed one valid current row before the lifecycle downgrade. The second
        # upgrade must reconstruct its internal recipient_id from the contract,
        # not merely prove an empty catalog can be migrated.
        $LifecycleSeedSql = @'
DO $$
DECLARE
    actor_staff_id bigint;
    actor_account_id bigint;
    recipient_value bigint;
    contract_value bigint;
    service_type_value bigint;
BEGIN
    INSERT INTO erp.staff (name, display_name, birth_date, sex_code)
    VALUES ('W2 0027 lifecycle staff', 'W2 0027 lifecycle staff', DATE '1990-01-01', 'TEST')
    RETURNING id INTO actor_staff_id;
    INSERT INTO erp.user_account (
        staff_id, account_code, display_name, role_code,
        pin_hash, pin_lookup_hmac, pin_key_version
    ) VALUES (
        actor_staff_id, 'W2-0027-LIFECYCLE', 'W2 0027 lifecycle', 'USER',
        'unused-w2-0027-lifecycle', decode('00112233445566778899aabbccddeeff', 'hex'), 1
    ) RETURNING id INTO actor_account_id;
    INSERT INTO erp.recipient (name, mobile_phone, created_by_account_id, updated_by_account_id)
    VALUES ('W2 0027 lifecycle recipient', '01077770000', actor_account_id, actor_account_id)
    RETURNING id INTO recipient_value;
    INSERT INTO erp.recipient_certification_identity (
        recipient_id, certification_number, created_by_account_id, updated_by_account_id
    ) VALUES (recipient_value, 'L7777000000', actor_account_id, actor_account_id);
    INSERT INTO erp.recipient_certification_period (
        recipient_id, grade_code, start_date, end_date,
        created_by_account_id, updated_by_account_id
    ) VALUES (
        recipient_value, '3', DATE '2026-01-01', DATE '2027-12-31',
        actor_account_id, actor_account_id
    );
    SELECT id INTO service_type_value
      FROM erp.service_type
     WHERE code = 'HOME_CARE';
    INSERT INTO erp.recipient_contract (
        recipient_id, service_type_id, start_date, end_date,
        created_by_account_id, updated_by_account_id
    ) VALUES (
        recipient_value, service_type_value, DATE '2026-01-01', DATE '2027-12-31',
        actor_account_id, actor_account_id
    ) RETURNING id INTO contract_value;
    INSERT INTO erp.w2_service_plan_notice (
        recipient_id, recipient_contract_id, notification_date,
        applied_start_date, applied_end_date, created_by_account_id, updated_by_account_id
    ) VALUES (
        recipient_value, contract_value, DATE '2026-08-01',
        DATE '2026-09-01', DATE '2026-12-31', actor_account_id, actor_account_id
    );
END
$$;
'@
        & $PsqlExe `
            -v ON_ERROR_STOP=1 `
            -h 127.0.0.1 `
            -p $Port `
            -U erp_owner `
            -d $DatabaseName `
            -c $LifecycleSeedSql | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "W2_0027_POSTGRES_LIFECYCLE_SEED_FAILED"
        }

        & $PythonExe -B -m alembic -c alembic.ini downgrade $PreviousRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W2_0027_POSTGRES_DOWNGRADE_0026_FAILED"
        }
        $DowngradedRevision = [string](& $PsqlExe `
                -v ON_ERROR_STOP=1 `
                -h 127.0.0.1 `
                -p $Port `
                -U erp_owner `
                -d $DatabaseName `
                -Atqc "SELECT version_num FROM erp.alembic_version")
        if ($LASTEXITCODE -ne 0 -or $DowngradedRevision.Trim() -cne $PreviousRevision) {
            throw "W2_0027_POSTGRES_DOWNGRADE_REVISION_MISMATCH"
        }
        $DowngradeCatalog = @(& $PsqlExe `
                -v ON_ERROR_STOP=1 `
                -h 127.0.0.1 `
                -p $Port `
                -U erp_owner `
                -d $DatabaseName `
                -Atqc "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'erp' AND table_name = 'w2_service_plan_notice' AND column_name = 'recipient_id'; SELECT count(*) FROM pg_constraint WHERE conrelid = 'erp.w2_service_plan_notice'::regclass AND conname IN ('fk_w2_service_plan_notice_contract', 'fk_w2_service_plan_notice_replacement')") |
            ForEach-Object { $_.ToString().Trim() } |
            Where-Object { $_ -ne "" }
        if ($LASTEXITCODE -ne 0 -or ($DowngradeCatalog -join ",") -cne "0,2") {
            throw "W2_0027_POSTGRES_DOWNGRADE_CATALOG_MISMATCH"
        }
        Write-Output "W2_0027_POSTGRES_STAGE=migration_downgrade_0026"

        & $PythonExe -B -m alembic -c alembic.ini upgrade $CurrentRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W2_0027_POSTGRES_REUPGRADE_FAILED"
        }
        $ReupgradedCatalog = @(& $PsqlExe `
                -v ON_ERROR_STOP=1 `
                -h 127.0.0.1 `
                -p $Port `
                -U erp_owner `
                -d $DatabaseName `
                -Atqc "SELECT version_num FROM erp.alembic_version; SELECT count(*) FROM erp.w2_service_plan_notice notice JOIN erp.recipient_contract contract ON contract.id = notice.recipient_contract_id WHERE notice.recipient_id IS NULL OR notice.recipient_id IS DISTINCT FROM contract.recipient_id; SELECT count(*) FROM pg_constraint WHERE conrelid = 'erp.w2_service_plan_notice'::regclass AND conname IN ('fk_w2_service_plan_notice_contract_same_recipient', 'fk_w2_service_plan_notice_replacement_same_recipient')") |
            ForEach-Object { $_.ToString().Trim() } |
            Where-Object { $_ -ne "" }
        if ($LASTEXITCODE -ne 0 -or ($ReupgradedCatalog -join ",") -cne "$CurrentRevision,0,2") {
            throw "W2_0027_POSTGRES_REUPGRADE_CATALOG_OR_BACKFILL_MISMATCH"
        }
        Write-Output "W2_0027_POSTGRES_STAGE=migration_reupgrade_0027"
    }
    finally {
        Pop-Location
    }
    Write-Output "W2_0027_POSTGRES_STAGE=migration_head"

    & $PsqlExe `
        -v ON_ERROR_STOP=1 `
        -h 127.0.0.1 `
        -p $Port `
        -U erp_owner `
        -d $DatabaseName `
        -f $GrantScript | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W2_0027_POSTGRES_APPLICATION_GRANT_FAILED"
    }

    Push-Location $BackendRoot
    try {
        $env:SSWCENTER_DATABASE_URL = $AppDatabaseUrl
        & $PythonExe -B -m app.db.postcheck_current_0027
        if ($LASTEXITCODE -ne 0) {
            throw "W2_0027_POSTGRES_CURRENT_POSTCHECK_FAILED"
        }

        # A historical 0027 catalog is valid only with its sole Alembic head.
        # This isolated mutation proves the direct verifier rejects a rogue
        # second head before it can emit either historical or current markers.
        $RogueHeadInserted = $false
        try {
            & $PsqlExe `
                -v ON_ERROR_STOP=1 `
                -h 127.0.0.1 `
                -p $Port `
                -U erp_owner `
                -d $DatabaseName `
                -c "INSERT INTO erp.alembic_version (version_num) VALUES ('$RogueRevision')" | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "W2_0027_POSTGRES_ROGUE_SECOND_HEAD_INSERT_FAILED"
            }
            $RogueHeadInserted = $true

            $RoguePostcheckOutput = @(& $PythonExe -B -m app.db.postcheck_current_0027 2>&1)
            $RoguePostcheckExitCode = $LASTEXITCODE
            $RoguePostcheckText = (
                $RoguePostcheckOutput |
                    ForEach-Object { $_.ToString() }
            ) -join [Environment]::NewLine
            if ($RoguePostcheckExitCode -eq 0) {
                throw "W2_0027_POSTGRES_ROGUE_SECOND_HEAD_POSTCHECK_ACCEPTED"
            }
            if ($RoguePostcheckText -notmatch "CURRENT_0027_REVISION_MISMATCH") {
                throw "W2_0027_POSTGRES_ROGUE_SECOND_HEAD_MISMATCH_MARKER_MISSING"
            }
            if ($RoguePostcheckText -match "SSWCENTER_CURRENT_0027_DB_POSTCHECK_OK") {
                throw "W2_0027_POSTGRES_ROGUE_SECOND_HEAD_HISTORICAL_MARKER_EMITTED"
            }
            if ($RoguePostcheckText -match "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK") {
                throw "W2_0027_POSTGRES_ROGUE_SECOND_HEAD_CURRENT_HEAD_MARKER_EMITTED"
            }
        }
        finally {
            if ($RogueHeadInserted) {
                & $PsqlExe `
                    -v ON_ERROR_STOP=1 `
                    -h 127.0.0.1 `
                    -p $Port `
                    -U erp_owner `
                    -d $DatabaseName `
                    -c "DELETE FROM erp.alembic_version WHERE version_num = '$RogueRevision'" | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    throw "W2_0027_POSTGRES_ROGUE_SECOND_HEAD_CLEANUP_FAILED"
                }

                $RestoredRevisions = @(
                    & $PsqlExe `
                        -v ON_ERROR_STOP=1 `
                        -h 127.0.0.1 `
                        -p $Port `
                        -U erp_owner `
                        -d $DatabaseName `
                        -Atqc "SELECT version_num FROM erp.alembic_version ORDER BY version_num" |
                        ForEach-Object { $_.ToString().Trim() } |
                        Where-Object { $_ -ne "" }
                )
                if (
                    $LASTEXITCODE -ne 0 -or
                    $RestoredRevisions.Count -ne 1 -or
                    $RestoredRevisions[0] -cne $CurrentRevision
                ) {
                    throw "W2_0027_POSTGRES_ROGUE_SECOND_HEAD_CLEANUP_FAILED"
                }
            }
        }
        Write-Output "W2_0027_POSTGRES_ROGUE_SECOND_HEAD_REJECTED"

        $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
        # This database deliberately remains exact historical 0027.  Its
        # direct TestClient node creates a current app, which must instead be
        # exercised against the separately upgraded active browser database.
        & $PythonExe -B -m pytest -q -p no:cacheprovider -s `
            @W2HistoricalNodeIds `
            --deselect $W2HistoricalCurrentApiNode
        if ($LASTEXITCODE -ne 0) {
            throw "W2_0027_POSTGRES_LIVE_TEST_FAILED"
        }
    }
    finally {
        Pop-Location
    }

    Write-Output "W2_0027_POSTGRES_STAGE=browser_database"
    & $CreateDbExe `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -O erp_owner `
        $BrowserDatabaseName
    if ($LASTEXITCODE -ne 0) {
        throw "W2_0027_BROWSER_DATABASE_CREATE_FAILED"
    }

    Push-Location $BackendRoot
    try {
        $env:SSWCENTER_DATABASE_URL = $BrowserOwnerDatabaseUrl
        $env:SSWCENTER_DATA_ROOT = $BrowserDataRoot
        & $PythonExe -B -m alembic -c alembic.ini upgrade $ActiveHeadRevision
        if ($LASTEXITCODE -ne 0) {
            throw "W2_0027_BROWSER_ALEMBIC_FAILED"
        }
        & $PythonExe -B -m app.db.seed_w0_w2_workflow_test_data
        if ($LASTEXITCODE -ne 0) {
            throw "W2_0027_BROWSER_WORKFLOW_SEED_FAILED"
        }
        & $PythonExe -B -m app.db.seed_w2_official_card_browser_test
        if ($LASTEXITCODE -ne 0) {
            throw "W2_0027_BROWSER_CARD_SEED_FAILED"
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
        -d $BrowserDatabaseName `
        -f $GrantScript | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "W2_0027_BROWSER_APPLICATION_GRANT_FAILED"
    }

    Push-Location $BackendRoot
    try {
        $env:SSWCENTER_DATABASE_URL = $BrowserAppDatabaseUrl
        $env:SSWCENTER_DATA_ROOT = $BrowserDataRoot
        $BrowserDispatchOutput = @(& $PythonExe -B -m app.db.postcheck_dispatch)
        if ($LASTEXITCODE -ne 0) {
            throw "W2_0027_BROWSER_POSTCHECK_FAILED"
        }
        if ($BrowserDispatchOutput -notcontains "SSWCENTER_CURRENT_0029_DB_POSTCHECK_OK") {
            throw "W2_0027_BROWSER_CURRENT_0029_MARKER_MISSING"
        }
        if ($BrowserDispatchOutput -notcontains "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK") {
            throw "W2_0027_BROWSER_CURRENT_HEAD_MARKER_MISSING"
        }
        Write-Output "W2_0027_BROWSER_CURRENT_0029_POSTCHECK_GREEN"
    }
    finally {
        Pop-Location
    }

    Push-Location $BackendRoot
    try {
        # Current FastAPI must retain strict active-head readiness.  Run the
        # original full W2 HTTP contract only against BrowserDatabase, whose
        # catalog is explicitly upgraded to the active 0029 head above; never disguise the
        # pinned historical 0027 lifecycle database as current.
        $env:SSWCENTER_DATABASE_URL = $BrowserOwnerDatabaseUrl
        $env:SSWCENTER_APP_DATABASE_URL = $BrowserAppDatabaseUrl
        $env:SSWCENTER_DATA_ROOT = $BrowserDataRoot
        $env:SSWCENTER_W2_CURRENT_HTTP_REAL_PG = "1"
        $env:SSWCENTER_W2_CURRENT_HTTP_DATABASE_URL = $BrowserOwnerDatabaseUrl
        $env:SSWCENTER_W2_CURRENT_HTTP_APP_DATABASE_URL = $BrowserAppDatabaseUrl
        & $PythonExe -B -m pytest -q -p no:cacheprovider -s @W2CurrentHttpNodeIds
        if ($LASTEXITCODE -ne 0) {
            throw "W2_0027_BROWSER_CURRENT_HTTP_TEST_FAILED"
        }
        Write-Output "W2_0027_BROWSER_CURRENT_HTTP_GREEN"
    }
    finally {
        Pop-Location
    }

    $BackendStartInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $BackendStartInfo.FileName = $PythonExe
    foreach ($Argument in @(
            "-B", "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", [string]$BackendPort
        )) {
        $BackendStartInfo.ArgumentList.Add($Argument)
    }
    $BackendStartInfo.WorkingDirectory = $BackendRoot
    $BackendStartInfo.UseShellExecute = $false
    $BackendStartInfo.CreateNoWindow = $true
    $BackendStartInfo.RedirectStandardOutput = $true
    $BackendStartInfo.RedirectStandardError = $true
    $BackendStartInfo.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $BackendStartInfo.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)
    $BackendStartInfo.EnvironmentVariables["SSWCENTER_ENVIRONMENT"] = "test"
    $BackendStartInfo.EnvironmentVariables["SSWCENTER_DATABASE_URL"] = $BrowserAppDatabaseUrl
    $BackendStartInfo.EnvironmentVariables["SSWCENTER_APP_DATABASE_URL"] = $BrowserAppDatabaseUrl
    $BackendStartInfo.EnvironmentVariables["SSWCENTER_DATA_ROOT"] = $BrowserDataRoot
    $BackendStartInfo.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1"
    $BackendProcess = [System.Diagnostics.Process]::Start($BackendStartInfo)
    if ($null -eq $BackendProcess) {
        throw "W2_0027_BROWSER_BACKEND_START_FAILED"
    }
    $BackendStdoutTask = $BackendProcess.StandardOutput.ReadToEndAsync()
    $BackendStderrTask = $BackendProcess.StandardError.ReadToEndAsync()

    $BackendReady = $false
    for ($Attempt = 0; $Attempt -lt 80; $Attempt++) {
        if ($BackendProcess.HasExited) { break }
        try {
            $ReadyResponse = Invoke-WebRequest `
                -Uri "http://127.0.0.1:$BackendPort/health/ready" `
                -UseBasicParsing `
                -TimeoutSec 2 `
                -ErrorAction SilentlyContinue
            if ($ReadyResponse.StatusCode -eq 200) {
                $BackendReady = $true
                break
            }
        }
        catch {}
        Start-Sleep -Milliseconds 250
    }
    if (-not $BackendReady) {
        throw "W2_0027_BROWSER_BACKEND_NOT_READY"
    }
    Write-Output "W2_0027_BROWSER_BACKEND_READY"

    $env:SSWCENTER_W2_REAL_E2E = "1"
    $env:SSWCENTER_W2_E2E_PIN = "100000"
    $env:SSWCENTER_W2_PLAYWRIGHT_OUTPUT_DIR = $PlaywrightOutputRoot
    $env:SSWCENTER_W2_VITE_CACHE_DIR = $ViteCacheRoot
    $env:SSWCENTER_E2E_BACKEND_PORT = [string]$BackendPort
    $env:SSWCENTER_E2E_FRONTEND_PORT = [string]$FrontendPort
    $env:VITE_DEV_LOGIN_BYPASS = "false"

    $FrontendStartInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $FrontendStartInfo.FileName = $NodeExe
    foreach ($Argument in @(
            $ViteCli,
            "--config", "e2e/w2-official-card-real-pg.vite.config.ts"
        )) {
        $FrontendStartInfo.ArgumentList.Add($Argument)
    }
    $FrontendStartInfo.WorkingDirectory = $FrontendRoot
    $FrontendStartInfo.UseShellExecute = $false
    $FrontendStartInfo.CreateNoWindow = $true
    $FrontendStartInfo.RedirectStandardOutput = $true
    $FrontendStartInfo.RedirectStandardError = $true
    $FrontendStartInfo.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $FrontendStartInfo.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)
    $FrontendProcess = [System.Diagnostics.Process]::Start($FrontendStartInfo)
    if ($null -eq $FrontendProcess) {
        throw "W2_0027_BROWSER_FRONTEND_START_FAILED"
    }
    $FrontendStdoutTask = $FrontendProcess.StandardOutput.ReadToEndAsync()
    $FrontendStderrTask = $FrontendProcess.StandardError.ReadToEndAsync()

    $FrontendReady = $false
    for ($Attempt = 0; $Attempt -lt 80; $Attempt++) {
        if ($FrontendProcess.HasExited) { break }
        try {
            $FrontendResponse = Invoke-WebRequest `
                -Uri "http://127.0.0.1:$FrontendPort/dashboard" `
                -UseBasicParsing `
                -TimeoutSec 2 `
                -ErrorAction SilentlyContinue
            if ($FrontendResponse.StatusCode -eq 200) {
                $FrontendReady = $true
                break
            }
        }
        catch {}
        Start-Sleep -Milliseconds 250
    }
    if (-not $FrontendReady) {
        throw "W2_0027_BROWSER_FRONTEND_NOT_READY"
    }
    Write-Output "W2_0027_BROWSER_FRONTEND_READY"

    $PlaywrightStartInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $PlaywrightStartInfo.FileName = $NodeExe
    foreach ($Argument in @(
            $PlaywrightCli,
            "test",
            "e2e/w2-official-card-reassign-real-pg.spec.ts",
            "--config=e2e/w2-official-card-real-pg.config.ts",
            "--workers=1"
        )) {
        $PlaywrightStartInfo.ArgumentList.Add($Argument)
    }
    $PlaywrightStartInfo.WorkingDirectory = $FrontendRoot
    $PlaywrightStartInfo.UseShellExecute = $false
    $PlaywrightStartInfo.CreateNoWindow = $true
    $PlaywrightStartInfo.RedirectStandardOutput = $true
    $PlaywrightStartInfo.RedirectStandardError = $true
    $PlaywrightStartInfo.StandardOutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $PlaywrightStartInfo.StandardErrorEncoding = [System.Text.UTF8Encoding]::new($false)
    $ExistingLibraryPath = [Environment]::GetEnvironmentVariable(
        "LD_LIBRARY_PATH",
        "Process"
    )
    $PlaywrightStartInfo.EnvironmentVariables["LD_LIBRARY_PATH"] = if (
        [string]::IsNullOrWhiteSpace($ExistingLibraryPath)
    ) {
        $PlaywrightLibraryRoot
    }
    else {
        "$PlaywrightLibraryRoot`:$ExistingLibraryPath"
    }
    $PlaywrightProcess = [System.Diagnostics.Process]::Start($PlaywrightStartInfo)
    if ($null -eq $PlaywrightProcess) {
        throw "W2_0027_BROWSER_PLAYWRIGHT_START_FAILED"
    }
    $PlaywrightStdoutTask = $PlaywrightProcess.StandardOutput.ReadToEndAsync()
    $PlaywrightStderrTask = $PlaywrightProcess.StandardError.ReadToEndAsync()
    $PlaywrightTimedOut = -not $PlaywrightProcess.WaitForExit(180000)
    $PlaywrightTerminationFailed = $false
    if ($PlaywrightTimedOut) {
        try {
            if (-not $PlaywrightProcess.HasExited) {
                $PlaywrightProcess.Kill($true)
            }
            if (-not $PlaywrightProcess.WaitForExit(10000)) {
                $PlaywrightTerminationFailed = $true
            }
        }
        catch {
            $PlaywrightTerminationFailed = $true
            Write-Output (
                "W2_0027_BROWSER_PLAYWRIGHT_TERMINATION_FAILED " +
                [string]$_.Exception.Message
            )
        }
    }

    $PlaywrightCaptured = Receive-W2CapturedStreams `
        -StdoutTask $PlaywrightStdoutTask `
        -StderrTask $PlaywrightStderrTask `
        -TimeoutMilliseconds 10000
    $PlaywrightStdout = [string]$PlaywrightCaptured.Stdout
    $PlaywrightStderr = [string]$PlaywrightCaptured.Stderr
    @($PlaywrightStdout, $PlaywrightStderr) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { Write-Output $_.TrimEnd() }
    if (-not $PlaywrightCaptured.Drained) {
        Write-Output (
            "W2_0027_BROWSER_PLAYWRIGHT_STREAM_DRAIN_TIMEOUT " +
            [string]$PlaywrightCaptured.FailureMessage
        )
    }
    if ($PlaywrightTimedOut) {
        if ($PlaywrightTerminationFailed) {
            Write-Output "W2_0027_BROWSER_PLAYWRIGHT_BOUNDED_STOP_FAILED"
        }
        throw "W2_0027_BROWSER_PLAYWRIGHT_TIMEOUT"
    }
    if (-not $PlaywrightCaptured.Drained) {
        throw "W2_0027_BROWSER_PLAYWRIGHT_STREAM_DRAIN_TIMEOUT"
    }
    $PlaywrightExitCode = $PlaywrightProcess.ExitCode
    $PlaywrightProcess = $null
    $PlaywrightStdoutTask = $null
    $PlaywrightStderrTask = $null
    $PlaywrightText = "$PlaywrightStdout`n$PlaywrightStderr"
    if (
        $PlaywrightExitCode -ne 0 -or
        $PlaywrightText -notmatch "W2_OFFICIAL_CARD_BROWSER_GREEN" -or
        $PlaywrightText -notmatch "1 passed"
    ) {
        throw "W2_0027_BROWSER_PLAYWRIGHT_FAILED"
    }

    $BrowserDatabaseEvidenceSql = @"
WITH expected AS (
    SELECT
        card.id AS card_id,
        initial_staff.id AS initial_staff_id,
        candidate_staff.id AS candidate_staff_id,
        admin_account.id AS admin_account_id
    FROM erp.w2_official_work_card AS card
    JOIN erp.staff AS initial_staff
      ON initial_staff.memo = 'SSWCENTER_W0_W2_WORKFLOW_TEST_DATA_V1|SW_ACTIVE'
    JOIN erp.staff AS candidate_staff
      ON candidate_staff.memo = 'SSWCENTER_W0_W2_WORKFLOW_TEST_DATA_V1|NU_ACTIVE'
    JOIN erp.user_account AS admin_account
      ON admin_account.account_code = 'ADMIN-001'
    WHERE card.occurrence_key = 'w2-browser-e2e-plan-notice'
      AND card.kind = 'PLAN_NOTICE'
      AND card.work_title = '계획서통보'
      AND card.target_name = '김순자'
      AND card.detail = '급여계획서 갱신 통보 브라우저 검증'
      AND card.due_date = DATE '2026-08-20'
      AND card.renewal_key = 'w2-browser-e2e-recipient-renewal'
      AND card.assignee_staff_id = candidate_staff.id
      AND card.closed_at_utc IS NULL
      AND card.row_version = 2
)
SELECT
    (SELECT count(*) FROM expected)::text || '|' ||
    (
        SELECT count(*)
        FROM erp.audit_event AS audit
        JOIN expected ON expected.card_id = audit.entity_pk
        WHERE audit.action_code = 'W2_OFFICIAL_WORK_CARD_REASSIGNED'
          AND audit.entity_type = 'w2_official_work_card'
          AND audit.actor_account_id = expected.admin_account_id
          AND audit.before_json ->> 'assignee_staff_id' = expected.initial_staff_id::text
          AND audit.before_json ->> 'row_version' = '1'
          AND audit.after_json ->> 'assignee_staff_id' = expected.candidate_staff_id::text
          AND audit.after_json ->> 'row_version' = '2'
    )::text;
"@
    $BrowserDatabaseEvidence = [string](& $PsqlExe `
            -v ON_ERROR_STOP=1 `
            -h 127.0.0.1 `
            -p $Port `
            -U erp_owner `
            -d $BrowserDatabaseName `
            -Atqc $BrowserDatabaseEvidenceSql)
    if (
        $LASTEXITCODE -ne 0 -or
        $BrowserDatabaseEvidence.Trim() -cne "1|1"
    ) {
        throw "W2_0027_BROWSER_DATABASE_EVIDENCE_FAILED"
    }
    Write-Output "W2_0027_BROWSER_REAL_PG_GREEN"

    $BlobDirectory = Join-Path $DataRoot "blobs"
    $OfficialDocumentDirectory = Join-Path $DataRoot "official-documents"
    New-Item -ItemType Directory -Path $BlobDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $OfficialDocumentDirectory -Force | Out-Null
    [System.IO.File]::WriteAllText(
        (Join-Path $BlobDirectory "w2-0027-restore-blob.txt"),
        "w2 0027 restore blob",
        [System.Text.UTF8Encoding]::new($false)
    )
    [System.IO.File]::WriteAllText(
        (Join-Path $OfficialDocumentDirectory "w2-0027-restore-document.txt"),
        "w2 0027 restore official document",
        [System.Text.UTF8Encoding]::new($false)
    )

    $BackupRoot = Join-Path $ClusterRoot "sswcenter-backups"
    $BackupOutput = @(
        & (Join-Path $PSScriptRoot "backup-postgres.ps1") `
            -DatabaseUrl $OwnerDatabaseUrl `
            -DestinationRoot $BackupRoot `
            -DataRoot $DataRoot `
            -AppVersion "w2-0027-test"
    )
    if ($LASTEXITCODE -ne 0) {
        throw "W2_0027_POSTGRES_BACKUP_FAILED"
    }
    $BackupDirectory = (
        Get-ChildItem -LiteralPath $BackupRoot -Directory |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
    ).FullName
    if ([string]::IsNullOrWhiteSpace($BackupDirectory)) {
        throw "W2_0027_POSTGRES_BACKUP_DIRECTORY_MISSING"
    }

    $ReviewDatabaseName = "sswcenter_w2_0027_restore_review"
    $ReviewDataRoot = Join-Path $ClusterRoot "sswcenter-restore-review-w2-0027"
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
        throw "W2_0027_POSTGRES_RESTORE_FAILED"
    }
    if ($RestoreOutput -notcontains "RESTORE_DRILL_OK $ReviewDatabaseName") {
        throw "W2_0027_POSTGRES_RESTORE_MARKER_MISSING"
    }
    if ($RestoreOutput -notcontains "SSWCENTER_CURRENT_0027_DB_POSTCHECK_OK") {
        throw "W2_0027_POSTGRES_RESTORE_HISTORICAL_0027_MARKER_MISSING"
    }
    if ($RestoreOutput -contains "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK") {
        throw "W2_0027_POSTGRES_RESTORE_EMITTED_CURRENT_HEAD_MARKER"
    }
    $ReviewDatabaseCount = [int](& $PsqlExe `
            -v ON_ERROR_STOP=1 `
            -h 127.0.0.1 `
            -p $Port `
            -U postgres `
            -d postgres `
            -Atqc "SELECT count(*) FROM pg_database WHERE datname = '$ReviewDatabaseName'")
    if ($LASTEXITCODE -ne 0 -or $ReviewDatabaseCount -ne 0) {
        throw "W2_0027_POSTGRES_RESTORE_DATABASE_CLEANUP_FAILED"
    }
    if (Test-Path -LiteralPath $ReviewDataRoot) {
        throw "W2_0027_POSTGRES_RESTORE_DATA_CLEANUP_FAILED"
    }
    Write-Output "W2_0027_POSTGRES_RESTORE_GREEN"

    Write-Output "W2_0027_POSTGRES_LIVE_GREEN"
    $RunSucceeded = $true
}
catch {
    $PrimaryFailure = $_.Exception
}
finally {
    try {
        $CleanupProblems = [System.Collections.Generic.List[string]]::new()
        $ChildProcessCleanupFailed = $false
        if ($null -ne $PlaywrightProcess) {
            try {
                $PlaywrightCleanup = Stop-W2CapturedProcess `
                    -Process $PlaywrightProcess `
                    -StdoutTask $PlaywrightStdoutTask `
                    -StderrTask $PlaywrightStderrTask
                if (-not $PlaywrightCleanup.Succeeded) {
                    $ChildProcessCleanupFailed = $true
                    [void]$CleanupProblems.Add(
                        "PLAYWRIGHT:" + [string]$PlaywrightCleanup.FailureMessage
                    )
                    Write-Output (
                        "W2_0027_BROWSER_PLAYWRIGHT_CLEANUP_FAILED " +
                        [string]$PlaywrightCleanup.FailureMessage
                    )
                }
                if ($null -ne $PrimaryFailure) {
                    @($PlaywrightCleanup.Stdout, $PlaywrightCleanup.Stderr) |
                        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                        ForEach-Object { Write-Output ("W2_0027_BROWSER_PLAYWRIGHT_LOG " + $_.TrimEnd()) }
                }
            }
            catch {
                $ChildProcessCleanupFailed = $true
                [void]$CleanupProblems.Add(
                    "PLAYWRIGHT_EXCEPTION:" + [string]$_.Exception.Message
                )
                Write-Output (
                    "W2_0027_BROWSER_PLAYWRIGHT_CLEANUP_FAILED " +
                    [string]$_.Exception.Message
                )
            }
        }
        if ($null -ne $FrontendProcess) {
            try {
                $FrontendCleanup = Stop-W2CapturedProcess `
                    -Process $FrontendProcess `
                    -StdoutTask $FrontendStdoutTask `
                    -StderrTask $FrontendStderrTask
                if (-not $FrontendCleanup.Succeeded) {
                    $ChildProcessCleanupFailed = $true
                    [void]$CleanupProblems.Add(
                        "FRONTEND:" + [string]$FrontendCleanup.FailureMessage
                    )
                    Write-Output (
                        "W2_0027_BROWSER_FRONTEND_CLEANUP_FAILED " +
                        [string]$FrontendCleanup.FailureMessage
                    )
                }
                if ($null -ne $PrimaryFailure) {
                    @($FrontendCleanup.Stdout, $FrontendCleanup.Stderr) |
                        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                        ForEach-Object { Write-Output ("W2_0027_BROWSER_FRONTEND_LOG " + $_.TrimEnd()) }
                }
            }
            catch {
                $ChildProcessCleanupFailed = $true
                [void]$CleanupProblems.Add(
                    "FRONTEND_EXCEPTION:" + [string]$_.Exception.Message
                )
                Write-Output (
                    "W2_0027_BROWSER_FRONTEND_CLEANUP_FAILED " +
                    [string]$_.Exception.Message
                )
            }
        }
        if ($null -ne $BackendProcess) {
            try {
                $BackendCleanup = Stop-W2CapturedProcess `
                    -Process $BackendProcess `
                    -StdoutTask $BackendStdoutTask `
                    -StderrTask $BackendStderrTask
                if (-not $BackendCleanup.Succeeded) {
                    $ChildProcessCleanupFailed = $true
                    [void]$CleanupProblems.Add(
                        "BACKEND:" + [string]$BackendCleanup.FailureMessage
                    )
                    Write-Output (
                        "W2_0027_BROWSER_BACKEND_CLEANUP_FAILED " +
                        [string]$BackendCleanup.FailureMessage
                    )
                }
                if ($null -ne $PrimaryFailure) {
                    @($BackendCleanup.Stdout, $BackendCleanup.Stderr) |
                        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
                        ForEach-Object { Write-Output ("W2_0027_BROWSER_BACKEND_LOG " + $_.TrimEnd()) }
                }
            }
            catch {
                $ChildProcessCleanupFailed = $true
                [void]$CleanupProblems.Add(
                    "BACKEND_EXCEPTION:" + [string]$_.Exception.Message
                )
                Write-Output (
                    "W2_0027_BROWSER_BACKEND_CLEANUP_FAILED " +
                    [string]$_.Exception.Message
                )
            }
        }

        if ($ClusterMayBeRunning) {
            try {
                & $PgCtlExe `
                    "--pgdata=$DataDirectory" `
                    --mode=fast `
                    --timeout=15 `
                    stop `
                    --wait | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    [void]$CleanupProblems.Add("POSTGRES_STOP_FAILED")
                    Write-Output "W2_0027_POSTGRES_STOP_FAILED"
                }
                else {
                    $ClusterMayBeRunning = $false
                }
            }
            catch {
                [void]$CleanupProblems.Add(
                    "POSTGRES_STOP_EXCEPTION:" + [string]$_.Exception.Message
                )
                Write-Output (
                    "W2_0027_POSTGRES_STOP_FAILED " + [string]$_.Exception.Message
                )
            }
        }

        if (Test-Path -LiteralPath $ClusterRoot -PathType Container) {
            if ($ClusterMayBeRunning) {
                [void]$CleanupProblems.Add("TEMP_DELETE_SKIPPED_CLUSTER_MAY_BE_RUNNING")
                Write-Output "W2_0027_POSTGRES_TEMP_DELETE_SKIPPED_CLUSTER_MAY_BE_RUNNING"
            }
            else {
                try {
                    $ResolvedCleanupRoot = [System.IO.Path]::GetFullPath($ClusterRoot)
                    if (
                        -not $ResolvedCleanupRoot.StartsWith($TempPrefix, [StringComparison]::Ordinal) -or
                        (Split-Path -Leaf $ResolvedCleanupRoot) -cnotmatch '^sswcenter-w2-0027-pg-[0-9a-f]{32}$'
                    ) {
                        [void]$CleanupProblems.Add("UNSAFE_CLEANUP_PATH")
                        Write-Output "W2_0027_POSTGRES_UNSAFE_CLEANUP_PATH"
                    }
                    else {
                        [System.IO.Directory]::Delete($ResolvedCleanupRoot, $true)
                    }
                }
                catch {
                    [void]$CleanupProblems.Add(
                        "TEMP_DELETE_EXCEPTION:" + [string]$_.Exception.Message
                    )
                    Write-Output (
                        "W2_0027_POSTGRES_TEMP_DELETE_FAILED " +
                        [string]$_.Exception.Message
                    )
                }
            }
        }

        $RemainingProcessCount = -1
        try {
            $RemainingProcessCount = @(
                Get-Process -Name postgres -ErrorAction SilentlyContinue |
                    Where-Object { $BaselinePostgresIds -notcontains $_.Id }
            ).Count
        }
        catch {
            [void]$CleanupProblems.Add(
                "PROCESS_OBSERVATION_EXCEPTION:" + [string]$_.Exception.Message
            )
        }
        $TempCount = if (Test-Path -LiteralPath $ClusterRoot) { 1 } else { 0 }
        $GitDeltaCount = 1
        try {
            $FinalGitStatus = ((
                    & git -C $WorkspaceRoot status --porcelain --untracked-files=all
                ) -join "`n")
            if ($LASTEXITCODE -ne 0) {
                [void]$CleanupProblems.Add("GIT_OBSERVATION_FAILED")
            }
            else {
                $GitDeltaCount = if ($FinalGitStatus -ceq $InitialGitStatus) { 0 } else { 1 }
            }
        }
        catch {
            [void]$CleanupProblems.Add(
                "GIT_OBSERVATION_EXCEPTION:" + [string]$_.Exception.Message
            )
        }

        $ListenerCount = 0
        foreach ($CleanupPort in $RequestedPorts) {
            $CleanupPortProbe = $null
            try {
                $CleanupPortProbe = [System.Net.Sockets.TcpListener]::new(
                    [System.Net.IPAddress]::Loopback,
                    $CleanupPort
                )
                $CleanupPortProbe.Start()
            }
            catch {
                $ListenerCount += 1
            }
            finally {
                if ($null -ne $CleanupPortProbe) {
                    try {
                        $CleanupPortProbe.Stop()
                    }
                    catch {
                        [void]$CleanupProblems.Add(
                            "LISTENER_STOP_EXCEPTION:" + [string]$_.Exception.Message
                        )
                    }
                }
            }
        }

        Write-Output (
            "W2_0027_POSTGRES_CLEANUP listener={0} process={1} temp={2} git_delta={3}" -f
            $ListenerCount,
            $RemainingProcessCount,
            $TempCount,
            $GitDeltaCount
        )
        foreach ($CleanupProblem in $CleanupProblems) {
            Write-Output ("W2_0027_POSTGRES_CLEANUP_FAILURE " + $CleanupProblem)
        }
        if (
            $ChildProcessCleanupFailed -or
            $CleanupProblems.Count -ne 0 -or
            $ListenerCount -ne 0 -or
            $RemainingProcessCount -ne 0 -or
            $TempCount -ne 0 -or
            $GitDeltaCount -ne 0
        ) {
            throw "W2_0027_POSTGRES_CLEANUP_NOT_ZERO"
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
        throw "W2_0027_POSTGRES_FAILED_WITH_CLEANUP_FAILURE"
    }
    throw $PrimaryFailure
}
if ($null -ne $CleanupFailure) {
    throw $CleanupFailure
}
if (-not $RunSucceeded) {
    throw "W2_0027_POSTGRES_RUN_NOT_GREEN"
}

Write-Output "W2_0027_POSTGRES_SEAL_GREEN"
