param(
    [int]$Port = 55442,
    [int]$BackendPort = 18092,
    [int]$FrontendPort = 14192
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$FrontendRoot = Join-Path $WorkspaceRoot "frontend"
$PythonExe = Join-Path $BackendRoot ".venv\Scripts\python.exe"
$NpmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
$NpmExe = if ($NpmCmd) { $NpmCmd.Source } else { $null }
$PostgresBin = "C:\Program Files\PostgreSQL\17\bin"
$InitDbExe = Join-Path $PostgresBin "initdb.exe"
$PgCtlExe = Join-Path $PostgresBin "pg_ctl.exe"
$PgIsReadyExe = Join-Path $PostgresBin "pg_isready.exe"
$CreateDbExe = Join-Path $PostgresBin "createdb.exe"
$PsqlExe = Join-Path $PostgresBin "psql.exe"
$ExpectedW1dRevision = "20260730_0011_w1d_recipient_contract"
$W1cHead = "20260730_0010_w1c_certification_ledgers"
$CurrentHead = "20260808_0017_recipient_guardian_email"

function Write-W1dHarnessFailure {
    param([string]$Marker, [string]$Detail = "")
    if ([string]::IsNullOrWhiteSpace($Detail)) {
        Write-Output $Marker
    }
    else {
        Write-Output ("{0}: {1}" -f $Marker, $Detail)
    }
    throw $Marker
}

function Write-W1dProductFailure {
    param([string]$Marker, [string]$Detail = "")
    if ([string]::IsNullOrWhiteSpace($Detail)) {
        Write-Output $Marker
    }
    else {
        Write-Output ("{0}: {1}" -f $Marker, $Detail)
    }
    throw $Marker
}

# R8-11: fail-closed Win32_Process snapshot (never SilentlyContinue-as-empty).
function Get-W1dProcessSnapshot {
    try {
        $rows = @(Get-CimInstance Win32_Process -ErrorAction Stop)
        return ,$rows
    }
    catch {
        Write-W1dHarnessFailure "W1D_HARNESS_PROCESS_ENUM_FAILED" ([string]$_.Exception.Message)
    }
}

function Get-W1dListenerSnapshot {
    try {
        $rows = @(Get-NetTCPConnection -State Listen -ErrorAction Stop)
        return ,$rows
    }
    catch {
        # No listeners may throw on some Windows builds; treat empty only when
        # the exception is clearly a no-match. Any other failure is harness fail.
        $msg = [string]$_.Exception.Message
        if ($msg -match 'No matching|No MSFT_NetTCPConnection|not find') {
            return ,@()
        }
        Write-W1dHarnessFailure "W1D_HARNESS_LISTENER_ENUM_FAILED" $msg
    }
}

function Get-W1dDescendantPids {
    param(
        [Parameter(Mandatory = $true)][int]$RootPid,
        [Parameter(Mandatory = $true)]$Snapshot
    )
    $byParent = @{}
    foreach ($row in @($Snapshot)) {
        $ppid = [int]$row.ParentProcessId
        if (-not $byParent.ContainsKey($ppid)) {
            $byParent[$ppid] = New-Object System.Collections.ArrayList
        }
        [void]$byParent[$ppid].Add([int]$row.ProcessId)
    }
    # BFS depth map from root; sort descendants deepest-first.
    $depth = @{}
    $depth[[int]$RootPid] = 0
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue([int]$RootPid)
    while ($queue.Count -gt 0) {
        $cur = [int]$queue.Dequeue()
        if ($byParent.ContainsKey($cur)) {
            foreach ($childObj in @($byParent[$cur])) {
                $c = [int]$childObj
                if (-not $depth.ContainsKey($c)) {
                    $depth[$c] = [int]$depth[$cur] + 1
                    $queue.Enqueue($c)
                }
            }
        }
    }
    $list = New-Object System.Collections.ArrayList
    foreach ($key in @($depth.Keys)) {
        $k = [int]$key
        if ($k -ne [int]$RootPid) {
            [void]$list.Add($k)
        }
    }
    # Sort deepest first (stable for kill order).
    $arr = @($list | Sort-Object { -[int]$depth[[int]$_] })
    # Always return a flat Object[] of ints (possibly empty).
    if ($null -eq $arr) { return ,@() }
    if ($arr -is [System.Array]) { return ,([int[]]@($arr)) }
    return ,([int[]]@([int]$arr))
}

function Test-W1dPidAliveInSnapshot {
    param(
        [Parameter(Mandatory = $true)][int]$TargetPid,
        [Parameter(Mandatory = $true)]$Snapshot
    )
    $want = [int]$TargetPid
    foreach ($row in @($Snapshot)) {
        if ([int]$row.ProcessId -eq $want) { return $true }
    }
    return $false
}

function Stop-W1dProcessTreeFailClosed {
    param(
        [Parameter(Mandatory = $true)][int]$RootPid,
        [string]$Context = "child"
    )
    # Fail-closed snapshot; already-exited PIDs during kill are OK if final verify is empty.
    $root = [int]$RootPid
    $snap = Get-W1dProcessSnapshot
    $descRaw = Get-W1dDescendantPids -RootPid $root -Snapshot $snap
    $descendants = @()
    foreach ($item in @($descRaw)) {
        if ($null -eq $item) { continue }
        $descendants += [int]$item
    }
    $captured = @()
    foreach ($d in $descendants) { $captured += [int]$d }
    $captured += $root
    $captured = @($captured | Select-Object -Unique)
    $killErrors = New-Object System.Collections.ArrayList
    foreach ($killPidObj in $descendants) {
        $killPid = [int]$killPidObj
        if (-not (Test-W1dPidAliveInSnapshot -TargetPid $killPid -Snapshot $snap)) { continue }
        try {
            Stop-Process -Id $killPid -Force -ErrorAction Stop
        }
        catch {
            # Race: process may exit between snapshot and kill. Record; verify decides.
            [void]$killErrors.Add(("pid={0}:{1}" -f $killPid, $_.Exception.Message))
        }
    }
    if (Test-W1dPidAliveInSnapshot -TargetPid $root -Snapshot $snap) {
        try {
            Stop-Process -Id $root -Force -ErrorAction Stop
        }
        catch {
            [void]$killErrors.Add(("root={0}:{1}" -f $root, $_.Exception.Message))
        }
    }
    Start-Sleep -Milliseconds 500
    $verifySnap = Get-W1dProcessSnapshot
    $alive = @()
    foreach ($checkPidObj in $captured) {
        $checkPid = [int]$checkPidObj
        if (Test-W1dPidAliveInSnapshot -TargetPid $checkPid -Snapshot $verifySnap) {
            $alive += $checkPid
        }
    }
    if ($alive.Count -gt 0) {
        Write-W1dHarnessFailure "W1D_HARNESS_PROCESS_TREE_RESIDUAL" (
            "context={0} pids={1} killErrors={2}" -f $Context, ($alive -join ","), ($killErrors -join ";")
        )
    }
    # If no residual alive, kill races are not harness failures.
}

# J-W1D-R3-H05/B02 + R8-11: bounded child process (PowerShell 5.1 compatible).
# Returns hashtable: ExitCode, Text (stdout+stderr joined).
function Invoke-W1dTimedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = "",
        [int]$TimeoutSec = 600,
        [string]$TimeoutMarker = "W1D_HARNESS_CHILD_TIMEOUT"
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FilePath
    $psi.Arguments = ($ArgumentList | ForEach-Object {
            if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
        }) -join ' '
    if (-not [string]::IsNullOrWhiteSpace($WorkingDirectory)) {
        $psi.WorkingDirectory = $WorkingDirectory
    }
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()
    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()
    if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
        # R8-11: snapshot full tree BEFORE kill; deepest-first; verify gone.
        # Enumeration/kill/verify failure is harness failure (still reaches outer finally).
        try {
            Stop-W1dProcessTreeFailClosed -RootPid ([int]$proc.Id) -Context $TimeoutMarker
        }
        catch {
            # Ensure marker is still the timeout, with tree detail.
            Write-W1dHarnessFailure $TimeoutMarker (
                "timeoutSec={0}; tree={1}" -f $TimeoutSec, ([string]$_.Exception.Message)
            )
        }
        Write-W1dHarnessFailure $TimeoutMarker ("timeoutSec={0}" -f $TimeoutSec)
    }
    $stdout = [string]$stdoutTask.Result
    $stderr = [string]$stderrTask.Result
    $combined = ($stdout + "`n" + $stderr)
    # Do not Write-Output lines here: that pollutes the returned hashtable on PS 5.1.
    # Caller streams Text to host and uses ExitCode/Text fields.
    $result = New-Object psobject -Property @{
        ExitCode = [int]$proc.ExitCode
        Text     = $combined
    }
    return ,$result
}

foreach ($Executable in @(
    $PythonExe,
    $InitDbExe,
    $PgCtlExe,
    $PgIsReadyExe,
    $CreateDbExe,
    $PsqlExe
)) {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        Write-W1dHarnessFailure "W1D_HARNESS_MISSING_EXECUTABLE" $Executable
    }
}

# R8-11: preflight ports via full listener snapshot + filter (no SilentlyContinue-as-zero).
$PreflightListeners = Get-W1dListenerSnapshot
foreach ($checkPort in @($Port, $BackendPort, $FrontendPort)) {
    $inUse = @($PreflightListeners | Where-Object { [int]$_.LocalPort -eq [int]$checkPort })
    if ($inUse.Count -gt 0) {
        Write-W1dHarnessFailure "W1D_HARNESS_PORT_IN_USE" $checkPort
    }
}

$TempParent = if (-not [string]::IsNullOrWhiteSpace($env:SSWCENTER_W1D_TEMP_ROOT)) {
    [System.IO.Path]::GetFullPath($env:SSWCENTER_W1D_TEMP_ROOT)
}
else {
    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        Write-W1dHarnessFailure "W1D_HARNESS_LOCALAPPDATA_MISSING"
    }
    [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Temp"))
}
$TempParent = $TempParent.TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
)
if (-not (Test-Path -LiteralPath $TempParent -PathType Container)) {
    Write-W1dHarnessFailure "W1D_HARNESS_TEMP_PARENT_MISSING" $TempParent
}
$env:TEMP = $TempParent
$env:TMP = $TempParent
$env:TMPDIR = $TempParent
$ClusterRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $TempParent ("sswcenter-w1d-pg-" + [Guid]::NewGuid().ToString("N")))
)
$ExpectedPrefix = $TempParent + [System.IO.Path]::DirectorySeparatorChar
$ClusterLeaf = Split-Path -Leaf $ClusterRoot
if (
    -not $ClusterRoot.StartsWith($ExpectedPrefix, [StringComparison]::OrdinalIgnoreCase) -or
    $ClusterLeaf -cnotmatch '^sswcenter-w1d-pg-[0-9a-f]{32}$'
) {
    Write-W1dHarnessFailure "W1D_HARNESS_UNSAFE_TEMP_PATH"
}

$DataDirectory = Join-Path $ClusterRoot "data"
$RuntimeDataRoot = Join-Path $ClusterRoot "sswcenter-w1d-runtime"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$DatabaseName = "sswcenter_w1d_review"
$OwnerDatabaseUrl = "postgresql+psycopg://erp_owner@127.0.0.1:$Port/$DatabaseName"
$AppDatabaseUrl = "postgresql+psycopg://erp_app@127.0.0.1:$Port/$DatabaseName"
$ClusterStarted = $false
$ProductFailure = $false
$ScriptExitCode = 0
$ListenerResidual = 0
$ProcessResidual = 0
$TempResidual = 0
$ArtifactResidual = 0
$CleanupHarnessFailure = $false
$AllProductStagesOk = $false
$RootNodeModules = Join-Path $WorkspaceRoot "node_modules"
$HadRootNodeModules = Test-Path -LiteralPath $RootNodeModules
$PwTestResults = Join-Path $FrontendRoot "test-results"
$PwReport = Join-Path $FrontendRoot "playwright-report"
$HadTestResults = Test-Path -LiteralPath $PwTestResults
$HadPwReport = Test-Path -LiteralPath $PwReport
$ArtifactRemovedCount = 0
$CapturedChildPids = New-Object System.Collections.ArrayList

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
        Write-W1dHarnessFailure "W1D_HARNESS_INITDB_FAILED"
    }

    & $PgCtlExe `
        --pgdata=$DataDirectory `
        --log=$LogFile `
        --options="-h 127.0.0.1 -p $Port" `
        start
    if ($LASTEXITCODE -ne 0) {
        Write-W1dHarnessFailure "W1D_HARNESS_POSTGRES_START_FAILED"
    }
    $ClusterStarted = $true

    & $PgIsReadyExe -h 127.0.0.1 -p $Port -U postgres -d postgres -t 15 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-W1dHarnessFailure "W1D_HARNESS_POSTGRES_NOT_READY"
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
        Write-W1dHarnessFailure "W1D_HARNESS_ROLE_CREATE_FAILED"
    }

    & $CreateDbExe `
        -h 127.0.0.1 `
        -p $Port `
        -U postgres `
        -O erp_owner `
        $DatabaseName
    if ($LASTEXITCODE -ne 0) {
        Write-W1dHarnessFailure "W1D_HARNESS_DATABASE_CREATE_FAILED"
    }

    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
    $env:SSWCENTER_OWNER_DATABASE_URL = $OwnerDatabaseUrl
    $env:SSWCENTER_APP_DATABASE_URL = $AppDatabaseUrl
    $env:SSWCENTER_DATA_ROOT = $RuntimeDataRoot
    $env:SSWCENTER_W1D_REAL_PG = "1"
    $env:SSWCENTER_PIN_PEPPER = "w1d-test-pin-pepper"
    $env:SSWCENTER_PIN_LOOKUP_KEY = "w1d-test-pin-lookup"
    $env:SSWCENTER_CSRF_SIGNING_KEY = "w1d-test-csrf"

    Push-Location $BackendRoot
    try {
        & $PythonExe -m alembic -c alembic.ini upgrade $W1cHead
        if ($LASTEXITCODE -ne 0) {
            Write-W1dHarnessFailure "W1D_HARNESS_BASE_UPGRADE_FAILED" "W1C head upgrade failed"
        }

        & $PythonExe -m alembic -c alembic.ini upgrade $ExpectedW1dRevision
        if ($LASTEXITCODE -ne 0) {
            $ProductFailure = $true
            Write-W1dProductFailure "W1D_MIGRATION_UPGRADE_FAILED" "W1D revision upgrade failed (product RED if W1D revision absent)"
        }

        & $PythonExe -m alembic -c alembic.ini downgrade $W1cHead
        if ($LASTEXITCODE -ne 0) {
            $ProductFailure = $true
            Write-W1dProductFailure "W1D_MIGRATION_DOWNGRADE_FAILED"
        }

        & $PythonExe -m alembic -c alembic.ini upgrade $ExpectedW1dRevision
        if ($LASTEXITCODE -ne 0) {
            $ProductFailure = $true
            Write-W1dProductFailure "W1D_MIGRATION_REUPGRADE_FAILED"
        }

        $CurrentRevision = & $PsqlExe `
            -v ON_ERROR_STOP=1 `
            -h 127.0.0.1 `
            -p $Port `
            -U erp_owner `
            -d $DatabaseName `
            -tAc "SELECT version_num FROM erp.alembic_version"
        if ($LASTEXITCODE -ne 0) {
            Write-W1dHarnessFailure "W1D_HARNESS_REVISION_QUERY_FAILED"
        }
        $RevisionText = ($CurrentRevision -join "").Trim()
        Write-Output ("W1D_REVISION_OBSERVED={0}" -f $RevisionText)

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
            Write-W1dHarnessFailure "W1D_HARNESS_APP_ROLE_MISMATCH"
        }
        Write-Output "W1D_APP_ROLE_OK"

        # Historical 0010->0011->0010->0011 lifecycle and exact 0011 observation
        # are sealed above. Current ORM/seed/E2E require the live Alembic head
        # (includes 0015 recipient_status).
        & $PythonExe -m alembic -c alembic.ini upgrade $CurrentHead
        if ($LASTEXITCODE -ne 0) {
            Write-W1dHarnessFailure "W1D_HARNESS_HEAD_UPGRADE_FAILED" "current-head upgrade failed"
        }
        $HeadRevision = & $PsqlExe `
            -v ON_ERROR_STOP=1 `
            -h 127.0.0.1 `
            -p $Port `
            -U erp_owner `
            -d $DatabaseName `
            -tAc "SELECT version_num FROM erp.alembic_version"
        if ($LASTEXITCODE -ne 0) {
            Write-W1dHarnessFailure "W1D_HARNESS_HEAD_UPGRADE_FAILED" "current-head revision query failed"
        }
        $HeadRevisionText = ($HeadRevision -join "").Trim()
        if ($HeadRevisionText -ne $CurrentHead) {
            Write-W1dHarnessFailure "W1D_HARNESS_HEAD_UPGRADE_FAILED" (
                "expected={0} actual={1}" -f $CurrentHead, $HeadRevisionText
            )
        }
        Write-Output "W1D_HEAD_UPGRADE_OK"
        $env:SSWCENTER_W1D_EXPECTED_RUNTIME_REVISION = $CurrentHead

        $env:SSWCENTER_DATABASE_URL = $AppDatabaseUrl

        # Stage A — harness once (never reclassified as product).
        $HarnessRun = Invoke-W1dTimedCommand `
            -FilePath $PythonExe `
            -WorkingDirectory $BackendRoot `
            -TimeoutSec 300 `
            -TimeoutMarker "W1D_HARNESS_PYTEST_HARNESS_TIMEOUT" `
            -ArgumentList @("-m", "pytest", "-q", "tests/test_w1d_postgres.py", "-k", "harness_w1c_head", "--tb=line", "-p", "no:cacheprovider")
        ([string]$HarnessRun.Text) -split "`r?`n" | ForEach-Object {
            if (-not [string]::IsNullOrWhiteSpace($_)) { Write-Output $_ }
        }
        $HarnessExit = [int]$HarnessRun.ExitCode
        Write-Output ("W1D_STAGE_HARNESS_EXIT={0}" -f $HarnessExit)
        if ($HarnessExit -ne 0) {
            Write-W1dHarnessFailure "W1D_HARNESS_W1C_HEAD_SELF_CHECK_FAILED" ("pytest exit={0}" -f $HarnessExit)
        }
        Write-Output "W1D_HARNESS_W1C_HEAD_SELF_CHECK_OK"

        # Stage B — virgin-counter first product test (must be first issuance).
        $Pg00Run = Invoke-W1dTimedCommand `
            -FilePath $PythonExe `
            -WorkingDirectory $BackendRoot `
            -TimeoutSec 600 `
            -TimeoutMarker "W1D_HARNESS_PYTEST_PG00_TIMEOUT" `
            -ArgumentList @("-m", "pytest", "-q", "tests/test_w1d_postgres.py", "-k", "pg_00_first_contract", "--tb=line", "-p", "no:cacheprovider")
        ([string]$Pg00Run.Text) -split "`r?`n" | ForEach-Object {
            if (-not [string]::IsNullOrWhiteSpace($_)) { Write-Output $_ }
        }
        $Pg00Exit = [int]$Pg00Run.ExitCode
        Write-Output ("W1D_STAGE_PG00_EXIT={0}" -f $Pg00Exit)
        if ($Pg00Exit -ne 0) {
            $ProductFailure = $true
            Write-Output "W1D_STAGE_PG00_PRODUCT_RED"
        }
        else {
            Write-Output "W1D_STAGE_PG00_OK"
        }

        # Stage C — remaining product tests (exclude harness + pg_00).
        $RestRun = Invoke-W1dTimedCommand `
            -FilePath $PythonExe `
            -WorkingDirectory $BackendRoot `
            -TimeoutSec 1200 `
            -TimeoutMarker "W1D_HARNESS_PYTEST_PRODUCT_TIMEOUT" `
            -ArgumentList @("-m", "pytest", "-q", "tests/test_w1d_postgres.py", "-k", "not harness_w1c_head and not pg_00_first_contract", "--tb=line", "-p", "no:cacheprovider")
        ([string]$RestRun.Text) -split "`r?`n" | ForEach-Object {
            if (-not [string]::IsNullOrWhiteSpace($_)) { Write-Output $_ }
        }
        $RestExit = [int]$RestRun.ExitCode
        Write-Output ("W1D_STAGE_PRODUCT_REST_EXIT={0}" -f $RestExit)
        if ($RestExit -ne 0) {
            $ProductFailure = $true
            Write-Output "W1D_STAGE_PRODUCT_REST_RED"
        }

        if ($RevisionText -ne $ExpectedW1dRevision) {
            $ProductFailure = $true
            Write-Output (
                "W1D_MIGRATION_REVISION_MISMATCH: expected={0} actual={1}" -f
                $ExpectedW1dRevision, $RevisionText
            )
        }
        if ($ProductFailure) {
            Write-Output (
                "W1D_POSTGRES_PRODUCT_STAGE_FAILED: pg00={0} rest={1}" -f $Pg00Exit, $RestExit
            )
        }

        # Stage D — live Playwright E2E (R4-08/09).
        # Missing npm is harness failure — never skip to GREEN.
        if ([string]::IsNullOrWhiteSpace($NpmExe)) {
            Write-W1dHarnessFailure "W1D_HARNESS_E2E_NPM_MISSING"
        }
        $E2EPin = "246813"
        if ($E2EPin -cnotmatch '^[0-9]{6}$') {
            Write-W1dHarnessFailure "W1D_HARNESS_E2E_PIN_SHAPE_INVALID"
        }
        $E2ESeedName = "W1D-E2E-SEED"
        $env:SSWCENTER_W1D_LIVE_E2E = "1"
        $env:SSWCENTER_W1D_E2E_PIN = $E2EPin
        $env:SSWCENTER_W1D_E2E_RECIPIENT_NAME = $E2ESeedName
        $env:SSWCENTER_E2E_FRONTEND_PORT = [string]$FrontendPort
        $env:SSWCENTER_E2E_BACKEND_PORT = [string]$BackendPort
        $env:SSWCENTER_DATABASE_URL = $AppDatabaseUrl

        # R4-08: ensure known-PIN ADMIN via owner SQL, then bootstrap/API recipients.
        $SeedScript = @"
import json, os, sys, urllib.error, urllib.request
from datetime import date
from http.cookiejar import CookieJar
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.core.security import PinProtector
from app.db.models import Staff, UserAccount

pin = os.environ['SSWCENTER_W1D_E2E_PIN']
base_name = os.environ['SSWCENTER_W1D_E2E_RECIPIENT_NAME']
backend = os.environ['SSWCENTER_E2E_BACKEND_BASE']
owner_url = os.environ['SSWCENTER_OWNER_DATABASE_URL']
pepper = os.environ['SSWCENTER_PIN_PEPPER']
lookup = os.environ['SSWCENTER_PIN_LOOKUP_KEY']
projects = ['chromium-1440x1000','chromium-1440x900','chromium-1366x768']
scenarios = ['contract-create','transition-stale','ended-new-only']
prot = PinProtector(pepper, lookup)

# 1) Deterministic ADMIN with exported PIN (owner path; always).
engine = create_engine(owner_url, pool_pre_ping=True)
Session = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
with Session() as s:
    hmac = prot.lookup_hmac(pin)
    existing = s.execute(
        text("SELECT id FROM erp.user_account WHERE pin_lookup_hmac = :h LIMIT 1"),
        {"h": hmac},
    ).scalar()
    if existing is None:
        staff = Staff(
            name='W1D E2E STAFF',
            birth_date=date(1990, 1, 1),
            sex_code='MALE',
            display_name='W1D E2E',
            row_version=1,
        )
        s.add(staff)
        s.flush()
        acc = UserAccount(
            staff_id=staff.id,
            account_code='W1D_E2E_ADMIN',
            display_name='W1D E2E ADMIN',
            role_code='ADMIN',
            pin_hash=prot.hash_pin(pin),
            pin_lookup_hmac=hmac,
            pin_key_version=1,
            row_version=1,
        )
        s.add(acc)
        s.flush()
        s.execute(
            text(
                "UPDATE erp.installation_state SET bootstrap_completed = true, "
                "first_admin_account_id = :aid WHERE singleton_key = true"
            ),
            {"aid": acc.id},
        )
        s.commit()
        print('W1D_E2E_ADMIN_CREATED id=' + str(acc.id))
    else:
        s.execute(
            text(
                "UPDATE erp.user_account SET pin_hash = :ph, pin_lookup_hmac = :h, "
                "pin_key_version = 1, active = true, role_code = 'ADMIN' WHERE id = :id"
            ),
            {"ph": prot.hash_pin(pin), "h": hmac, "id": int(existing)},
        )
        s.execute(
            text(
                "UPDATE erp.installation_state SET bootstrap_completed = true "
                "WHERE singleton_key = true"
            )
        )
        s.commit()
        print('W1D_E2E_ADMIN_REFRESHED id=' + str(existing))

class Client:
    def __init__(self, root):
        self.root = root.rstrip('/')
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = None
    def request(self, method, path, body=None, headers=None):
        data = None
        hdrs = {'Accept': 'application/json'}
        if headers:
            hdrs.update(headers)
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            hdrs['Content-Type'] = 'application/json'
        if self.csrf and method in ('POST','PUT','PATCH','DELETE'):
            hdrs['X-CSRF-Token'] = self.csrf
        req = urllib.request.Request(self.root + path, data=data, headers=hdrs, method=method)
        try:
            with self.opener.open(req, timeout=30) as resp:
                raw = resp.read().decode('utf-8')
                return resp.status, raw
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode('utf-8', errors='replace')
            return exc.code, raw
    def refresh_csrf(self):
        for c in self.jar:
            if c.name == 'sswcenter_csrf':
                self.csrf = c.value
                return

# 2) Login + create unique recipients via API (proves W1B path).
client = Client(backend)
status, raw = client.request('POST', '/api/auth/login', {'pin': pin})
client.refresh_csrf()
if status != 200:
    print('W1D_HARNESS_E2E_LOGIN_SEED_FAILED status=' + str(status))
    sys.exit(4)
print('W1D_E2E_LOGIN_SEED_OK')

created = 0
for proj in projects:
    for scen in scenarios:
        name = f'{base_name}-{proj}-{scen}'
        day = (created % 28) + 1
        status, raw = client.request('POST', '/api/v1/recipients', {
            'name': name,
            'birth_date': f'1950-01-{day:02d}',
            'sex_code': 'MALE',
            'postal_code': 'W1D-POSTAL',
            'address': f'{name} address',
            'home_phone': '010-1000-0001',
            'mobile_phone': '010-1000-0002',
        })
        if status not in (200, 201):
            print(
                'W1D_HARNESS_E2E_RECIPIENT_CREATE_FAILED status='
                + str(status)
            )
            sys.exit(5)
        created += 1
print('W1D_E2E_SEED_RECIPIENTS=' + str(created))

# 2b) R12 transition-stale fixture: W1C identity/cert/grade + public W1D create x2.
import re
with engine.begin() as conn:
    has_identity = conn.execute(
        text("SELECT to_regclass('erp.recipient_certification_identity')")
    ).scalar()
    has_cert_period = conn.execute(
        text("SELECT to_regclass('erp.recipient_certification_period')")
    ).scalar()
    has_grade = conn.execute(
        text("SELECT to_regclass('erp.recipient_grade_period')")
    ).scalar()
    has_contract = conn.execute(
        text("SELECT to_regclass('erp.recipient_contract')")
    ).scalar()
# W1C baseline tables are required harness deps — never product-absent RED.
if not has_identity or not has_cert_period or not has_grade:
    print('W1D_HARNESS_E2E_W1C_BASELINE_TABLES_MISSING')
    sys.exit(19)
if not has_contract:
    # Expected Phase 1 product-absent RED (W1D 0011 only).
    print('W1D_E2E_SEED_TRANSITION_STALE_PRODUCT_ABSENT')
else:
    transition_markers = []
    recipient_ids_seen = []
    product_seed_red = False
    for pidx, proj in enumerate(projects):
        if product_seed_red:
            break
        tname = f'{base_name}-{proj}-transition-stale'
        year = 2030 + pidx
        cert_start = f'{year}-01-01'
        cert_end = f'{year}-12-31'
        with engine.begin() as conn:
            rid = conn.execute(
                text("SELECT id FROM erp.recipient WHERE name = :n LIMIT 1"),
                {"n": tname},
            ).scalar()
        if rid is None:
            print('W1D_HARNESS_E2E_TRANSITION_RECIPIENT_MISSING name=' + tname)
            sys.exit(20)
        rid = int(rid)
        recipient_ids_seen.append(rid)
        # R12-01: exact canonical L + 10 digits (never 11).
        cert_no = f'L{year:04d}{pidx:01d}{(rid % 100000):05d}'
        if not re.fullmatch(r'^L[0-9]{10}$', cert_no) or len(cert_no) != 11:
            print('W1D_HARNESS_E2E_TRANSITION_CERT_NO_SHAPE cert_no_len=' + str(len(cert_no)))
            sys.exit(21)

        # R16 helpers: product markers first; W1C 2xx malform is product RED (H01).
        def emit_product_red(code, **safe):
            # Module-scope seed script: no nonlocal; caller assigns product_seed_red.
            extra = ' '.join(f'{k}={v}' for k, v in safe.items())
            print(
                (
                    'W1D_E2E_TRANSITION_PRODUCT_'
                    + code
                    + (' ' + extra if extra else '')
                ).strip()
            )

        def strict_json_int(value):
            """type(value) is int only — never bool, never int(coercion)."""
            if type(value) is not int:
                return None
            return value

        def strict_api_date_str(value, expected=None):
            """Exact YYYY-MM-DD string; no str()/slice coercion."""
            if type(value) is not str:
                return None
            if not re.fullmatch(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$', value):
                return None
            if expected is not None and value != expected:
                return None
            return value

        def parse_json_object(raw):
            try:
                body = json.loads(raw)
            except Exception:
                return None, 'BODY_NOT_JSON'
            if type(body) is not dict:
                return None, 'BODY_NOT_OBJECT'
            return body, None

        def exact_keyset(body, keys):
            if set(body.keys()) != set(keys):
                return False
            return True

        def validate_w1c_identity_2xx(body, *, expected_rid, expected_cert_no):
            """Exact identity response keyset + primitives (R18 H01)."""
            keys = ('recipient_id', 'certification_number', 'row_version')
            if not exact_keyset(body, keys):
                return 'KEYSET'
            rid_v = strict_json_int(body.get('recipient_id'))
            if rid_v is None or rid_v != expected_rid:
                return 'RECIPIENT_ID'
            if type(body.get('certification_number')) is not str:
                return 'NUMBER_TYPE'
            if body.get('certification_number') != expected_cert_no:
                return 'NUMBER_VALUE'
            rv = strict_json_int(body.get('row_version'))
            if rv is None or rv != 1:
                return 'ROW_VERSION'
            return None

        def validate_w1c_cert_2xx(body, *, expected_rid, expected_start, expected_end):
            keys = (
                'id', 'recipient_id', 'start_date', 'end_date',
                'invalidated_at_utc', 'replacement_certification_period_id',
                'row_version',
            )
            if not exact_keyset(body, keys):
                return None, 'KEYSET'
            cid = strict_json_int(body.get('id'))
            if cid is None or cid <= 0:
                return None, 'ID'
            rid_v = strict_json_int(body.get('recipient_id'))
            if rid_v is None or rid_v != expected_rid:
                return None, 'RECIPIENT_ID'
            if strict_api_date_str(body.get('start_date'), expected_start) is None:
                return None, 'START_DATE'
            if strict_api_date_str(body.get('end_date'), expected_end) is None:
                return None, 'END_DATE'
            if body.get('invalidated_at_utc') is not None:
                return None, 'INVALIDATED'
            if body.get('replacement_certification_period_id') is not None:
                return None, 'REPLACEMENT'
            rv = strict_json_int(body.get('row_version'))
            if rv is None or rv != 1:
                return None, 'ROW_VERSION'
            return cid, None

        def validate_w1c_grade_2xx(
            body, *, expected_rid, expected_parent, expected_start, expected_end
        ):
            keys = (
                'id', 'recipient_id', 'certification_period_id', 'grade_code',
                'start_date', 'end_date', 'invalidated_at_utc',
                'replacement_grade_period_id', 'row_version',
            )
            if not exact_keyset(body, keys):
                return None, 'KEYSET'
            gid = strict_json_int(body.get('id'))
            if gid is None or gid <= 0:
                return None, 'ID'
            rid_v = strict_json_int(body.get('recipient_id'))
            if rid_v is None or rid_v != expected_rid:
                return None, 'RECIPIENT_ID'
            parent = strict_json_int(body.get('certification_period_id'))
            if parent is None or parent != expected_parent:
                return None, 'PARENT'
            if type(body.get('grade_code')) is not str or body.get('grade_code') != '3':
                return None, 'GRADE_CODE'
            if strict_api_date_str(body.get('start_date'), expected_start) is None:
                return None, 'START_DATE'
            if strict_api_date_str(body.get('end_date'), expected_end) is None:
                return None, 'END_DATE'
            if body.get('invalidated_at_utc') is not None:
                return None, 'INVALIDATED'
            if body.get('replacement_grade_period_id') is not None:
                return None, 'REPLACEMENT'
            rv = strict_json_int(body.get('row_version'))
            if rv is None or rv != 1:
                return None, 'ROW_VERSION'
            return gid, None

        def r18_w1c_mutant_selfcheck():
            """Deterministic pure validators for missing/extra/wrong type/bool/value."""
            good_id = {
                'recipient_id': rid,
                'certification_number': cert_no,
                'row_version': 1,
            }
            if validate_w1c_identity_2xx(
                good_id, expected_rid=rid, expected_cert_no=cert_no
            ) is not None:
                print('W1D_HARNESS_R18_W1C_MUTANT_GOOD_ID')
                sys.exit(28)
            mutants = [
                ({k: v for k, v in good_id.items() if k != 'row_version'}, 'missing'),
                ({**good_id, 'extra': 1}, 'extra'),
                ({**good_id, 'recipient_id': '1'}, 'type'),
                ({**good_id, 'recipient_id': True}, 'bool'),
                ({**good_id, 'recipient_id': rid + 1}, 'value'),
                ({**good_id, 'row_version': 2}, 'rv'),
            ]
            for body, tag in mutants:
                code = validate_w1c_identity_2xx(
                    body, expected_rid=rid, expected_cert_no=cert_no
                )
                if code is None:
                    print('W1D_HARNESS_R18_W1C_MUTANT_ACCEPTED_ID ' + tag)
                    sys.exit(28)
            good_cert = {
                'id': 1,
                'recipient_id': rid,
                'start_date': cert_start,
                'end_date': cert_end,
                'invalidated_at_utc': None,
                'replacement_certification_period_id': None,
                'row_version': 1,
            }
            cid, err = validate_w1c_cert_2xx(
                good_cert,
                expected_rid=rid,
                expected_start=cert_start,
                expected_end=cert_end,
            )
            if err is not None or cid != 1:
                print('W1D_HARNESS_R18_W1C_MUTANT_GOOD_CERT')
                sys.exit(28)
            for body, tag in (
                ({k: v for k, v in good_cert.items() if k != 'id'}, 'missing'),
                ({**good_cert, 'extra': True}, 'extra'),
                ({**good_cert, 'id': True}, 'bool'),
                ({**good_cert, 'row_version': 0}, 'rv0'),
            ):
                _cid, err = validate_w1c_cert_2xx(
                    body,
                    expected_rid=rid,
                    expected_start=cert_start,
                    expected_end=cert_end,
                )
                if err is None:
                    print('W1D_HARNESS_R18_W1C_MUTANT_ACCEPTED_CERT ' + tag)
                    sys.exit(28)
            good_grade = {
                'id': 2,
                'recipient_id': rid,
                'certification_period_id': 1,
                'grade_code': '3',
                'start_date': cert_start,
                'end_date': cert_end,
                'invalidated_at_utc': None,
                'replacement_grade_period_id': None,
                'row_version': 1,
            }
            gid, err = validate_w1c_grade_2xx(
                good_grade,
                expected_rid=rid,
                expected_parent=1,
                expected_start=cert_start,
                expected_end=cert_end,
            )
            if err is not None or gid != 2:
                print('W1D_HARNESS_R18_W1C_MUTANT_GOOD_GRADE')
                sys.exit(28)
            for body, tag in (
                ({k: v for k, v in good_grade.items() if k != 'grade_code'}, 'missing'),
                ({**good_grade, 'extra': 0}, 'extra'),
                ({**good_grade, 'id': False}, 'bool'),
                ({**good_grade, 'grade_code': 3}, 'type'),
            ):
                _gid, err = validate_w1c_grade_2xx(
                    body,
                    expected_rid=rid,
                    expected_parent=1,
                    expected_start=cert_start,
                    expected_end=cert_end,
                )
                if err is None:
                    print('W1D_HARNESS_R18_W1C_MUTANT_ACCEPTED_GRADE ' + tag)
                    sys.exit(28)
            print('W1D_R18_W1C_MUTANT_SELFCHECK_OK')

        r18_w1c_mutant_selfcheck()

        def db_strict_int(value):
            """DB driver int only (fail closed; no str/float coercion)."""
            if type(value) is bool:
                return None
            if type(value) is int:
                return value
            return None

        def db_date_to_str(value):
            """DB date/datetime/str → exact YYYY-MM-DD or None (fail closed)."""
            if value is None:
                return None
            if type(value) is str:
                return strict_api_date_str(value)
            # datetime is subclass of date — prefer date path for pure dates.
            from datetime import date as _date, datetime as _datetime
            if type(value) is _date:
                return value.isoformat()
            if isinstance(value, _datetime):
                return value.date().isoformat()
            return None

        def db_ts_to_str_or_none(value):
            if value is None:
                return None
            if type(value) is str:
                return value if value else None
            return str(value)

        # --- W1C identity (transport/non-2xx harness; malformed 2xx product) ---
        try:
            st, raw = client.request(
                'POST',
                f'/api/v1/recipients/{rid}/certification-identity',
                {'certification_number': cert_no},
            )
        except Exception as exc:
            print(
                'W1D_HARNESS_E2E_TRANSITION_IDENTITY_TRANSPORT '
                + type(exc).__name__
            )
            sys.exit(22)
        if st not in (200, 201):
            print(
                'W1D_HARNESS_E2E_TRANSITION_IDENTITY_FAILED status=' + str(st)
            )
            sys.exit(22)
        id_body, perr = parse_json_object(raw)
        if perr:
            emit_product_red('W1C_IDENTITY_' + perr)
            product_seed_red = True
            break
        id_err = validate_w1c_identity_2xx(
            id_body, expected_rid=rid, expected_cert_no=cert_no
        )
        if id_err is not None:
            emit_product_red('W1C_IDENTITY_' + id_err)
            product_seed_red = True
            break

        # --- W1C certification period ---
        try:
            st, raw = client.request(
                'POST',
                f'/api/v1/recipients/{rid}/certification-periods',
                {'start_date': cert_start, 'end_date': cert_end},
            )
        except Exception as exc:
            print(
                'W1D_HARNESS_E2E_TRANSITION_CERT_TRANSPORT '
                + type(exc).__name__
            )
            sys.exit(26)
        if st not in (200, 201):
            print('W1D_HARNESS_E2E_TRANSITION_CERT_FAILED status=' + str(st))
            sys.exit(26)
        cert_body, perr = parse_json_object(raw)
        if perr:
            emit_product_red('W1C_CERT_' + perr)
            product_seed_red = True
            break
        cert_period_id, cerr = validate_w1c_cert_2xx(
            cert_body,
            expected_rid=rid,
            expected_start=cert_start,
            expected_end=cert_end,
        )
        if cerr is not None:
            emit_product_red('W1C_CERT_' + cerr)
            product_seed_red = True
            break

        # --- W1C grade period ---
        try:
            st, raw = client.request(
                'POST',
                f'/api/v1/recipients/{rid}/grade-periods',
                {
                    'certification_period_id': cert_period_id,
                    'grade_code': '3',
                    'start_date': cert_start,
                    'end_date': cert_end,
                },
            )
        except Exception as exc:
            print(
                'W1D_HARNESS_E2E_TRANSITION_GRADE_TRANSPORT '
                + type(exc).__name__
            )
            sys.exit(27)
        if st not in (200, 201):
            print('W1D_HARNESS_E2E_TRANSITION_GRADE_FAILED status=' + str(st))
            sys.exit(27)
        grade_body, perr = parse_json_object(raw)
        if perr:
            emit_product_red('W1C_GRADE_' + perr)
            product_seed_red = True
            break
        grade_period_id, gerr = validate_w1c_grade_2xx(
            grade_body,
            expected_rid=rid,
            expected_parent=cert_period_id,
            expected_start=cert_start,
            expected_end=cert_end,
        )
        if gerr is not None:
            emit_product_red('W1C_GRADE_' + gerr)
            product_seed_red = True
            break

        # R16-H02: strict W1D ContractResponse API typing (no coercion).
        required_contract_keys = (
            'id', 'recipient_id', 'service_type_code', 'service_group_code',
            'start_date', 'end_date', 'service_start_date',
            'signer_name', 'signer_relationship_text', 'signer_phone',
            'end_reason_text', 'invalidated_at_utc', 'replacement_contract_id',
            'row_version',
        )
        forbidden_keys = (
            'contract_no', 'contract_sequence', 'end_reason_code', 'discharge_date'
        )
        created_ids = []
        created_by_id = {}
        issued_no = None

        def strict_api_contract_response(body, *, svc):
            """Strict JSON/API ContractResponse → exact field dict or (None, code)."""
            body_keys = set(body.keys())
            req_set = set(required_contract_keys)
            if body_keys != req_set:
                return None, 'CREATE_KEYSET'
            for fk in forbidden_keys:
                if fk in body:
                    return None, 'FORBIDDEN_FIELD'
            cid = strict_json_int(body.get('id'))
            if cid is None or cid <= 0:
                return None, 'CONTRACT_ID'
            rid_v = strict_json_int(body.get('recipient_id'))
            if rid_v is None or rid_v != rid:
                return None, 'RECIPIENT_ID'
            if type(body.get('service_type_code')) is not str:
                return None, 'SERVICE_CODE_TYPE'
            if body.get('service_type_code') != svc:
                return None, 'SERVICE_CODE'
            if type(body.get('service_group_code')) is not str:
                return None, 'SERVICE_GROUP_TYPE'
            if body.get('service_group_code') != 'LONG_TERM_CARE':
                return None, 'SERVICE_GROUP'
            start = strict_api_date_str(body.get('start_date'), cert_start)
            if start is None:
                return None, 'START_DATE'
            # Newly-created active contracts: exact null (not coerced).
            for null_f in (
                'end_date', 'service_start_date',
                'signer_name', 'signer_relationship_text', 'signer_phone',
                'end_reason_text', 'invalidated_at_utc', 'replacement_contract_id',
            ):
                if body.get(null_f) is not None:
                    return None, 'FIELD_NOT_NULL'
            rv = strict_json_int(body.get('row_version'))
            if rv is None or rv < 1:
                return None, 'ROW_VERSION'
            return {
                'id': cid,
                'recipient_id': rid_v,
                'service_type_code': body.get('service_type_code'),
                'service_group_code': body.get('service_group_code'),
                'start_date': start,
                'end_date': None,
                'service_start_date': None,
                'signer_name': None,
                'signer_relationship_text': None,
                'signer_phone': None,
                'end_reason_text': None,
                'invalidated_at_utc': None,
                'replacement_contract_id': None,
                'row_version': rv,
            }, None

        def normalize_db_contract_row(tr):
            """DB driver values → same ContractResponse field set (fail closed)."""
            tid = db_strict_int(tr['id'])
            if tid is None or tid <= 0:
                return None
            stc = tr['service_code']
            sgc = tr['service_group_code']
            if type(stc) is not str or type(sgc) is not str:
                return None
            start = db_date_to_str(tr['start_date'])
            if start is None:
                return None
            end = db_date_to_str(tr['end_date']) if tr['end_date'] is not None else None
            if tr['end_date'] is not None and end is None:
                return None
            ssd = (
                db_date_to_str(tr['service_start_date'])
                if tr['service_start_date'] is not None
                else None
            )
            if tr['service_start_date'] is not None and ssd is None:
                return None
            inv = (
                db_ts_to_str_or_none(tr['invalidated_at_utc'])
                if tr['invalidated_at_utc'] is not None
                else None
            )
            rep = tr['replacement_contract_id']
            if rep is not None:
                rep = db_strict_int(rep)
                if rep is None:
                    return None
            rv = db_strict_int(tr['row_version'])
            if rv is None or rv < 1:
                return None
            for text_f in (
                'signer_name', 'signer_relationship_text',
                'signer_phone', 'end_reason_text',
            ):
                tv = tr[text_f]
                if tv is not None and type(tv) is not str:
                    return None
            return {
                'id': tid,
                'recipient_id': rid,
                'service_type_code': stc,
                'service_group_code': sgc,
                'start_date': start,
                'end_date': end,
                'service_start_date': ssd,
                'signer_name': tr['signer_name'],
                'signer_relationship_text': tr['signer_relationship_text'],
                'signer_phone': tr['signer_phone'],
                'end_reason_text': tr['end_reason_text'],
                'invalidated_at_utc': inv,
                'replacement_contract_id': rep,
                'row_version': rv,
            }

        for svc in ('HOME_CARE', 'HOME_BATH'):
            try:
                st, raw = client.request(
                    'POST',
                    f'/api/v1/recipients/{rid}/contracts',
                    {
                        'service_type_code': svc,
                        'start_date': cert_start,
                        'end_date': None,
                        'service_start_date': None,
                        'signer_name': None,
                        'signer_relationship_text': None,
                        'signer_phone': None,
                        'end_reason_text': None,
                    },
                )
            except Exception as exc:
                print(
                    'W1D_HARNESS_E2E_TRANSITION_CONTRACT_TRANSPORT '
                    + type(exc).__name__
                )
                sys.exit(70)
            if st != 201:
                emit_product_red('CREATE_RED', status=st, service=svc)
                product_seed_red = True
                break
            body, perr = parse_json_object(raw)
            if perr:
                emit_product_red('CREATE_' + perr, service=svc)
                product_seed_red = True
                break
            norm, code = strict_api_contract_response(body, svc=svc)
            if norm is None:
                emit_product_red(code, service=svc)
                product_seed_red = True
                break
            cid = norm['id']
            created_ids.append(cid)
            created_by_id[cid] = norm
            try:
                with engine.begin() as conn:
                    rno = conn.execute(
                        text(
                            "SELECT recipient_no FROM erp.recipient WHERE id = :id"
                        ),
                        {"id": rid},
                    ).scalar()
            except Exception as exc:
                print(
                    'W1D_HARNESS_E2E_TRANSITION_RECIPIENT_NO_QUERY '
                    + type(exc).__name__
                )
                sys.exit(71)
            # R18 M01: raw str only; no str()/strip() coercion.
            if type(rno) is not str or not re.fullmatch(r'^[0-9]{6,}$', rno):
                emit_product_red('RECIPIENT_NO_FORMAT', service=svc)
                product_seed_red = True
                break
            rno_s = rno
            if issued_no is None:
                issued_no = rno_s
            elif rno_s != issued_no:
                emit_product_red('RECIPIENT_NO_MUTATED', service=svc)
                product_seed_red = True
                break
        if product_seed_red:
            break
        if len(created_ids) != 2 or len(set(created_ids)) != 2:
            emit_product_red('CONTRACT_ID_SET')
            product_seed_red = True
            break
        # Full PostgreSQL product verification (schema/row product RED).
        try:
            with engine.begin() as conn:
                rrows = conn.execute(
                    text(
                        "SELECT id, name, recipient_no FROM erp.recipient WHERE id = :id"
                    ),
                    {"id": rid},
                ).mappings().all()
                if len(rrows) != 1:
                    emit_product_red('RECIPIENT_ROW_CARDINALITY')
                    product_seed_red = True
                else:
                    rrow = rrows[0]
                    rid_db = db_strict_int(rrow['id'])
                    if rid_db != rid or str(rrow['name']) != tname:
                        print('W1D_HARNESS_E2E_TRANSITION_RECIPIENT_ROW_MISMATCH')
                        sys.exit(52)
                    rno_final = rrow['recipient_no']
                    if (
                        type(rno_final) is not str
                        or not re.fullmatch(r'^[0-9]{6,}$', rno_final)
                        or rno_final != issued_no
                    ):
                        emit_product_red('RECIPIENT_NO_PERSISTED')
                        product_seed_red = True
                irows = conn.execute(
                    text(
                        "SELECT recipient_id, certification_number, row_version "
                        "FROM erp.recipient_certification_identity "
                        "WHERE recipient_id = :rid"
                    ),
                    {"rid": rid},
                ).mappings().all()
                if len(irows) != 1:
                    print('W1D_HARNESS_E2E_TRANSITION_IDENTITY_ROW_CARDINALITY')
                    sys.exit(54)
                irow = irows[0]
                if db_strict_int(irow['recipient_id']) != rid:
                    print('W1D_HARNESS_E2E_TRANSITION_IDENTITY_ROW_RECIPIENT')
                    sys.exit(54)
                if str(irow['certification_number']) != cert_no:
                    print('W1D_HARNESS_E2E_TRANSITION_IDENTITY_ROW_NUMBER')
                    sys.exit(55)
                if db_strict_int(irow['row_version']) is None or db_strict_int(
                    irow['row_version']
                ) < 1:
                    print('W1D_HARNESS_E2E_TRANSITION_IDENTITY_ROW_VERSION_DB')
                    sys.exit(56)
                crow = conn.execute(
                    text(
                        """
                        SELECT id, start_date, end_date, invalidated_at_utc
                        FROM erp.recipient_certification_period
                        WHERE recipient_id = :rid AND invalidated_at_utc IS NULL
                        ORDER BY id
                        """
                    ),
                    {"rid": rid},
                ).mappings().all()
                if len(crow) != 1 or db_strict_int(crow[0]['id']) != cert_period_id:
                    print('W1D_HARNESS_E2E_TRANSITION_CERT_ROW')
                    sys.exit(57)
                if db_date_to_str(crow[0]['start_date']) != cert_start:
                    print('W1D_HARNESS_E2E_TRANSITION_CERT_START')
                    sys.exit(58)
                if db_date_to_str(crow[0]['end_date']) != cert_end:
                    print('W1D_HARNESS_E2E_TRANSITION_CERT_END')
                    sys.exit(59)
                grow = conn.execute(
                    text(
                        """
                        SELECT id, certification_period_id, grade_code,
                               start_date, end_date
                        FROM erp.recipient_grade_period
                        WHERE recipient_id = :rid AND invalidated_at_utc IS NULL
                        ORDER BY id
                        """
                    ),
                    {"rid": rid},
                ).mappings().all()
                if len(grow) != 1 or db_strict_int(grow[0]['id']) != grade_period_id:
                    print('W1D_HARNESS_E2E_TRANSITION_GRADE_ROW')
                    sys.exit(60)
                if db_strict_int(grow[0]['certification_period_id']) != cert_period_id:
                    print('W1D_HARNESS_E2E_TRANSITION_GRADE_PARENT')
                    sys.exit(61)
                if str(grow[0]['grade_code']) != '3':
                    print('W1D_HARNESS_E2E_TRANSITION_GRADE_CODE')
                    sys.exit(62)
                if db_date_to_str(grow[0]['start_date']) != cert_start:
                    print('W1D_HARNESS_E2E_TRANSITION_GRADE_START')
                    sys.exit(63)
                if db_date_to_str(grow[0]['end_date']) != cert_end:
                    print('W1D_HARNESS_E2E_TRANSITION_GRADE_END')
                    sys.exit(64)
                if product_seed_red:
                    pass
                else:
                    # R14-01/R16-H02: exact two IDs + per-ID full equality.
                    trows = conn.execute(
                        text(
                            """
                            SELECT c.id, st.code AS service_code,
                                   sg.code AS service_group_code,
                                   c.start_date, c.end_date, c.service_start_date,
                                   c.signer_name, c.signer_relationship_text,
                                   c.signer_phone, c.end_reason_text,
                                   c.invalidated_at_utc, c.replacement_contract_id,
                                   c.row_version
                            FROM erp.recipient_contract c
                            JOIN erp.service_type st ON st.id = c.service_type_id
                            LEFT JOIN erp.service_group sg
                              ON sg.id = st.service_group_id
                            WHERE c.recipient_id = :rid
                              AND c.id IN (:id0, :id1)
                              AND c.invalidated_at_utc IS NULL
                            ORDER BY c.id
                            """
                        ),
                        {
                            "rid": rid,
                            "id0": created_ids[0],
                            "id1": created_ids[1],
                        },
                    ).mappings().all()
                    if len(trows) != 2:
                        emit_product_red('CONTRACT_COUNT', count=len(trows))
                        product_seed_red = True
                    found_ids = []
                    parse_fail = False
                    for r in trows:
                        fid = db_strict_int(r['id'])
                        if fid is None:
                            parse_fail = True
                            break
                        found_ids.append(fid)
                    if parse_fail:
                        emit_product_red('DB_ID_PARSE')
                        product_seed_red = True
                    else:
                        found_ids = sorted(found_ids)
                    if not product_seed_red and found_ids != sorted(created_ids):
                        emit_product_red('CONTRACT_IDS_MISMATCH')
                        product_seed_red = True
                    codes = (
                        sorted(str(r['service_code']) for r in trows) if trows else []
                    )
                    if not product_seed_red and codes != ['HOME_BATH', 'HOME_CARE']:
                        emit_product_red(
                            'MULTISET', multiset=','.join(codes) if codes else '-'
                        )
                        product_seed_red = True
                    if not product_seed_red:
                        db_by_id = {}
                        for tr in trows:
                            tid = db_strict_int(tr['id'])
                            if tid is None:
                                emit_product_red('DB_ID_PARSE')
                                product_seed_red = True
                                break
                            dnorm = normalize_db_contract_row(tr)
                            if dnorm is None:
                                emit_product_red('DB_NORMALIZE_FAILED', id=tid)
                                product_seed_red = True
                                break
                            db_by_id[tid] = dnorm
                        if not product_seed_red:
                            for tid in created_ids:
                                api_obj = created_by_id.get(tid)
                                db_obj = db_by_id.get(tid)
                                if api_obj is None or db_obj is None:
                                    emit_product_red('PER_ID_MISSING', id=tid)
                                    product_seed_red = True
                                    break
                                # R24: both sides already JSON-primitive normalized
                                # (strict_api + normalize_db); exact equality only.
                                if api_obj != db_obj:
                                    emit_product_red('PER_ID_MISMATCH', id=tid)
                                    product_seed_red = True
                                    break
                    death_n = conn.execute(
                        text(
                            "SELECT COUNT(*) FROM erp.recipient_contract "
                            "WHERE recipient_id = :rid AND end_reason_text = '사망'"
                        ),
                        {"rid": rid},
                    ).scalar()
                    death_n_i = db_strict_int(death_n)
                    if death_n_i is None:
                        # some drivers return long; accept non-bool Integral via int only if type is int
                        if type(death_n) is int:
                            death_n_i = death_n
                        else:
                            try:
                                death_n_i = int(death_n or 0)
                            except Exception:
                                death_n_i = None
                    if death_n_i is None or death_n_i != 0:
                        emit_product_red('DEATH_DEFAULT')
                        product_seed_red = True
        except SystemExit:
            raise
        except Exception as exc:
            # R16-H03: SQLSTATE 08* harness BEFORE product subclasses.
            # Emit exception class only — never SQL text/message/PII.
            from sqlalchemy.exc import (
                DBAPIError,
                DataError,
                IntegrityError,
                OperationalError,
                ProgrammingError,
            )

            def _sqlstate_of(err):
                orig = getattr(err, 'orig', None)
                if orig is None:
                    return None
                for attr in ('sqlstate', 'pgcode'):
                    val = getattr(orig, attr, None)
                    if val is not None and str(val):
                        return str(val)
                return None

            exc_name = type(exc).__name__
            if isinstance(exc, OperationalError):
                print(
                    'W1D_HARNESS_E2E_TRANSITION_PRODUCT_VERIFY_CONNECT '
                    + exc_name
                )
                sys.exit(72)
            if isinstance(exc, DBAPIError):
                ss = _sqlstate_of(exc)
                if ss and ss.startswith('08'):
                    print(
                        'W1D_HARNESS_E2E_TRANSITION_PRODUCT_VERIFY_CONNECT '
                        + exc_name
                    )
                    sys.exit(72)
                if isinstance(exc, (ProgrammingError, DataError, IntegrityError)):
                    emit_product_red('DB_PROGRAMMING', exc_class=exc_name)
                    product_seed_red = True
                else:
                    emit_product_red('DB_DATA', exc_class=exc_name)
                    product_seed_red = True
            elif isinstance(exc, (TypeError, ValueError, KeyError)):
                emit_product_red('ROW_SHAPE', exc_class=exc_name)
                product_seed_red = True
            else:
                print(
                    'W1D_HARNESS_E2E_TRANSITION_PRODUCT_VERIFY_QUERY '
                    + exc_name
                )
                sys.exit(72)
        if product_seed_red:
            break
        multiset = 'HOME_BATH,HOME_CARE'
        cids_s = ','.join(str(x) for x in sorted(created_ids))
        marker = (
            f'W1D_E2E_TRANSITION_FIXTURE recipient_id={rid} '
            f'cert_period_id={cert_period_id} grade_period_id={grade_period_id} '
            f'contract_ids={cids_s} service_multiset={multiset}'
        )
        transition_markers.append(marker)
        print(marker)
        print(f'W1D_E2E_TRANSITION_RECIPIENT_NO_ISSUED recipient_id={rid} issued=1')
    if product_seed_red:
        # Product-present invariant failure: still complete seed for W1B baselines.
        print('W1D_E2E_SEED_TRANSITION_STALE_PRODUCT_RED')
    else:
        if len(transition_markers) != 3:
            print(
                'W1D_HARNESS_E2E_TRANSITION_MARKER_COUNT expected=3 actual='
                + str(len(transition_markers))
            )
            sys.exit(30)
        if len(set(transition_markers)) != 3:
            print('W1D_HARNESS_E2E_TRANSITION_MARKER_DUPLICATE')
            sys.exit(31)
        if len(set(recipient_ids_seen)) != 3:
            print('W1D_HARNESS_E2E_TRANSITION_RECIPIENT_IDS_NOT_UNIQUE')
            sys.exit(32)
        print('W1D_E2E_SEED_TRANSITION_STALE_OK count=3')

# 3) Ended contracts for mobile (R5-02): fail-closed when table exists.
with engine.begin() as conn:
    has_table = conn.execute(text("SELECT to_regclass('erp.recipient_contract')")).scalar()
if not has_table:
    # Product-absent RED: exact table-absent skip (not a soft success of ended-seed).
    print('W1D_E2E_SEED_ENDED_CONTRACT_TABLE_ABSENT')
else:
    with engine.begin() as conn:
        stid = conn.execute(
            text("SELECT id FROM erp.service_type WHERE code = 'HOME_CARE' LIMIT 1")
        ).scalar()
        if stid is None:
            print('W1D_HARNESS_E2E_ENDED_CONTRACT_HOME_CARE_MISSING')
            sys.exit(6)
        aid = conn.execute(
            text(
                "SELECT id FROM erp.user_account "
                "WHERE role_code = 'ADMIN' AND active IS TRUE ORDER BY id LIMIT 1"
            )
        ).scalar()
        if aid is None:
            print('W1D_HARNESS_E2E_ENDED_CONTRACT_ADMIN_MISSING')
            sys.exit(7)
        expected_ended = [
            f'{base_name}-{proj}-ended-new-only' for proj in projects
        ]
        rows = []
        for ended_name in expected_ended:
            rid = conn.execute(
                text("SELECT id FROM erp.recipient WHERE name = :n LIMIT 1"),
                {"n": ended_name},
            ).scalar()
            if rid is None:
                print('W1D_HARNESS_E2E_ENDED_CONTRACT_RECIPIENT_MISSING')
                sys.exit(8)
            rows.append((int(rid), ended_name))
        if len(rows) != 3:
            print(
                'W1D_HARNESS_E2E_ENDED_CONTRACT_RECIPIENTS_COUNT '
                + str(len(rows))
            )
            sys.exit(9)
        for rid, _name in rows:
            conn.execute(
                text(
                    "INSERT INTO erp.recipient_contract ("
                    "recipient_id, service_type_id, start_date, end_date, "
                    "created_by_account_id, updated_by_account_id, row_version"
                    ") VALUES ("
                    ":rid, :stid, DATE '2025-01-01', DATE '2025-06-30', "
                    ":aid, :aid, 1"
                    ")"
                ),
                {"rid": int(rid), "stid": int(stid), "aid": int(aid)},
            )
        # Verify exactly one ended active contract per mobile recipient.
        verified = 0
        for rid, _name in rows:
            n = conn.execute(
                text(
                    "SELECT COUNT(*) FROM erp.recipient_contract "
                    "WHERE recipient_id = :rid "
                    "AND end_date = DATE '2025-06-30' "
                    "AND start_date = DATE '2025-01-01' "
                    "AND invalidated_at_utc IS NULL"
                ),
                {"rid": int(rid)},
            ).scalar()
            if int(n) != 1:
                print(
                    'W1D_HARNESS_E2E_ENDED_CONTRACT_VERIFY_FAILED count='
                    + str(n)
                )
                sys.exit(10)
            verified += 1
        if verified != 3:
            print('W1D_HARNESS_E2E_ENDED_CONTRACT_VERIFY_COUNT ' + str(verified))
            sys.exit(11)
        print('W1D_E2E_SEED_ENDED_CONTRACT_OK count=3')
print('W1D_E2E_SEED_OK')
"@
        $SeedFile = Join-Path $ClusterRoot "seed_e2e.py"
        # UTF-8 without BOM for Python source (PS 5.1 Set-Content -Encoding UTF8 writes BOM).
        [System.IO.File]::WriteAllText(
            $SeedFile,
            $SeedScript,
            (New-Object System.Text.UTF8Encoding $false)
        )

        $Uvicorn = Start-Process -FilePath $PythonExe -ArgumentList @(
            "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", [string]$BackendPort
        ) -WorkingDirectory $BackendRoot -PassThru -WindowStyle Hidden
        $UvicornPid = $Uvicorn.Id
        try {
            $ready = $false
            for ($i = 0; $i -lt 60; $i++) {
                try {
                    $r = Invoke-WebRequest -UseBasicParsing -Uri ("http://127.0.0.1:{0}/health/ready" -f $BackendPort) -TimeoutSec 2
                    if ($r.StatusCode -eq 200) { $ready = $true; break }
                } catch {}
                Start-Sleep -Milliseconds 250
            }
            if (-not $ready) {
                Write-W1dHarnessFailure "W1D_HARNESS_E2E_BACKEND_NOT_READY"
            }
            Write-Output "W1D_E2E_BACKEND_READY"

            # API seed against live backend (bootstrap + recipients).
            $env:SSWCENTER_E2E_BACKEND_BASE = ("http://127.0.0.1:{0}" -f $BackendPort)
            $env:SSWCENTER_OWNER_DATABASE_URL = $OwnerDatabaseUrl
            $prevEap = $ErrorActionPreference
            $prevPythonPath = $env:PYTHONPATH
            $ErrorActionPreference = "Continue"
            $env:PYTHONPATH = $BackendRoot
            Push-Location $BackendRoot
            try {
                $SeedOut = @(& $PythonExe $SeedFile 2>&1)
                $SeedExit = $LASTEXITCODE
            }
            finally {
                Pop-Location
                if ($null -eq $prevPythonPath) {
                    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
                }
                else {
                    $env:PYTHONPATH = $prevPythonPath
                }
                $ErrorActionPreference = $prevEap
            }
            $SeedOut | ForEach-Object { Write-Output ($_ | Out-String).TrimEnd() }
            if ($SeedExit -ne 0 -or (($SeedOut | Out-String) -notmatch "W1D_E2E_SEED_OK")) {
                Write-W1dHarnessFailure "W1D_HARNESS_E2E_SEED_FAILED" ("exit={0}" -f $SeedExit)
            }
            # R13: any controlled product marker is product RED (W1B baselines still run).
            if (($SeedOut | Out-String) -match "W1D_E2E_SEED_TRANSITION_STALE_PRODUCT_RED|W1D_E2E_TRANSITION_PRODUCT_") {
                $ProductFailure = $true
                Write-Output "W1D_STAGE_E2E_TRANSITION_FIXTURE_PRODUCT_RED"
            }
            Write-Output "W1D_E2E_SEED_ADMIN_PIN_EXPORTED"
            Write-Output ("W1D_E2E_SEED_RECIPIENT_BASE={0}" -f $E2ESeedName)

            # Frontend: Playwright config webServer uses SSWCENTER_E2E_FRONTEND_PORT.
            Push-Location $FrontendRoot
            try {
                $E2ERun = Invoke-W1dTimedCommand `
                    -FilePath $NpmExe `
                    -WorkingDirectory $FrontendRoot `
                    -TimeoutSec 900 `
                    -TimeoutMarker "W1D_HARNESS_PLAYWRIGHT_TIMEOUT" `
                    -ArgumentList @(
                        "exec", "--", "playwright", "test",
                        "e2e/w1d-contract-transition.spec.ts",
                        "--workers=1", "--reporter=line"
                    )
                $E2EExit = [int]$E2ERun.ExitCode
                $E2EText = [string]$E2ERun.Text
                $E2EText -split "`r?`n" | ForEach-Object {
                    if (-not [string]::IsNullOrWhiteSpace($_)) { Write-Output $_ }
                }
                Write-Output ("W1D_STAGE_E2E_EXIT={0}" -f $E2EExit)

                # R5-03: baseline-complete markers required; harness dominates product.
                $BaselineMatches = [regex]::Matches(
                    $E2EText,
                    "W1D_E2E_W1B_BASELINE_OK project=([^\s]+) scenario=([^\s]+)"
                )
                $BaselineKeys = @(
                    $BaselineMatches |
                        ForEach-Object { "{0}|{1}" -f $_.Groups[1].Value, $_.Groups[2].Value } |
                        Select-Object -Unique
                )
                $BaselineCount = $BaselineKeys.Count
                Write-Output ("W1D_E2E_BASELINE_MARKER_COUNT={0}" -f $BaselineCount)
                $BaselineComplete = ($BaselineCount -eq 9)

                # Explicit harness / infrastructure only — not ordinary expect timeouts.
                $HarnessMarkers = @(
                    "W1D_HARNESS_",
                    "browserType.launch",
                    "Executable doesn't exist",
                    "net::ERR_",
                    "ECONNREFUSED",
                    "Target closed",
                    "browser has been closed",
                    "NS_ERROR_",
                    "W1D_HARNESS_E2E_"
                )
                $ProductMarkers = @(
                    "W1D_E2E_CONTRACT_PANEL_MISSING",
                    "W1D_E2E_TRANSITION_PANEL_MISSING",
                    "W1D_E2E_ABS08_CONTRACT_NO",
                    "W1D_E2E_CON01_SERVICE",
                    "W1D_E2E_REC03_NUMBER_NOT_ISSUED",
                    "W1D_E2E_TRN01_",
                    "W1D_E2E_TRN03_",
                    "W1D_E2E_TRN04_",
                    "W1D_E2E_CON03_"
                )
                $HasHarness = $false
                foreach ($hm in $HarnessMarkers) {
                    if ($E2EText -match [regex]::Escape($hm)) { $HasHarness = $true; break }
                }
                $HasProduct = $false
                foreach ($pm in $ProductMarkers) {
                    if ($E2EText -match [regex]::Escape($pm)) { $HasProduct = $true; break }
                }

                if ($HasHarness) {
                    # Harness dominates even when product markers also present (R5-03).
                    Write-Output "W1D_STAGE_E2E_HARNESS_RED"
                    Write-W1dHarnessFailure "W1D_HARNESS_E2E_BASELINE_OR_INFRA" "see playwright output"
                }
                elseif (-not $BaselineComplete) {
                    Write-Output (
                        "W1D_STAGE_E2E_INCOMPLETE_BASELINE count={0}" -f $BaselineCount
                    )
                    Write-W1dHarnessFailure "W1D_HARNESS_E2E_INCOMPLETE_BASELINE" (
                        "expected=9 actual={0}" -f $BaselineCount
                    )
                }
                elseif ($E2EExit -eq 0) {
                    Write-Output "W1D_STAGE_E2E_OK"
                }
                elseif ($HasProduct) {
                    $ProductFailure = $true
                    Write-Output "W1D_STAGE_E2E_PRODUCT_RED"
                }
                else {
                    Write-Output "W1D_STAGE_E2E_UNRECOGNIZED"
                    Write-W1dHarnessFailure "W1D_HARNESS_E2E_UNRECOGNIZED" ("exit={0}" -f $E2EExit)
                }
            }
            finally {
                Pop-Location
            }
        }
        finally {
            if ($UvicornPid -and $UvicornPid -gt 0) {
                # R9-05: every unexpected tree-cleanup exception is a hard harness failure.
                # Already-exited races must complete inside Stop-W1dProcessTreeFailClosed
                # without throwing (final PID snapshot proves zero residual).
                try {
                    Stop-W1dProcessTreeFailClosed -RootPid ([int]$UvicornPid) -Context "uvicorn"
                }
                catch {
                    $script:CleanupHarnessFailure = $true
                    $msg = [string]$_.Exception.Message
                    if ([string]::IsNullOrWhiteSpace($msg)) {
                        $msg = [string]$_
                    }
                    Write-Output ("W1D_HARNESS_UVICORN_TREE_KILL_FAILED: {0}" -f $msg)
                    # No SilentlyContinue fallback kill — residual gates own final proof.
                }
            }
            # Frontend/backend residual listeners: enumerate all then filter (R8-11).
            try {
                $allListen = Get-W1dListenerSnapshot
                $fe = @($allListen | Where-Object { [int]$_.LocalPort -eq [int]$FrontendPort })
                $be = @($allListen | Where-Object { [int]$_.LocalPort -eq [int]$BackendPort })
                foreach ($conn in ($fe + $be)) {
                    try {
                        Stop-Process -Id ([int]$conn.OwningProcess) -Force -ErrorAction Stop
                    }
                    catch {
                        $script:CleanupHarnessFailure = $true
                        Write-Output (
                            "W1D_HARNESS_LISTENER_KILL_FAILED: port={0} pid={1}" -f
                            $conn.LocalPort, $conn.OwningProcess
                        )
                    }
                }
            }
            catch {
                $script:CleanupHarnessFailure = $true
                Write-Output ("W1D_HARNESS_LISTENER_ENUM_FAILED: {0}" -f $_.Exception.Message)
            }
            # Remove only harness-created Playwright artifacts (R4-09 / R8-11).
            if (-not $HadTestResults -and (Test-Path -LiteralPath $PwTestResults)) {
                try {
                    [System.IO.Directory]::Delete($PwTestResults, $true)
                    $script:ArtifactRemovedCount++
                    Write-Output "W1D_CLEANUP_PW_TEST_RESULTS_REMOVED"
                } catch {
                    $script:CleanupHarnessFailure = $true
                    Write-Output "W1D_HARNESS_CLEANUP_PW_TEST_RESULTS_FAILED"
                }
            }
            if (-not $HadPwReport -and (Test-Path -LiteralPath $PwReport)) {
                try {
                    [System.IO.Directory]::Delete($PwReport, $true)
                    $script:ArtifactRemovedCount++
                    Write-Output "W1D_CLEANUP_PW_REPORT_REMOVED"
                } catch {
                    $script:CleanupHarnessFailure = $true
                    Write-Output "W1D_HARNESS_CLEANUP_PW_REPORT_FAILED"
                }
            }
            # Root node_modules: only remove if harness created it (absent before).
            if (-not $HadRootNodeModules -and (Test-Path -LiteralPath $RootNodeModules)) {
                try {
                    [System.IO.Directory]::Delete($RootNodeModules, $true)
                    $script:ArtifactRemovedCount++
                    Write-Output "W1D_CLEANUP_ROOT_NODE_MODULES_REMOVED"
                } catch {
                    $script:CleanupHarnessFailure = $true
                    Write-Output "W1D_HARNESS_CLEANUP_ROOT_NODE_MODULES_FAILED"
                }
            }
        }

        if ($ProductFailure) {
            Write-W1dProductFailure "W1D_PRODUCT_STAGES_FAILED" "see stage exits"
        }
        $script:AllProductStagesOk = $true
    }
    finally {
        Pop-Location
    }
    # GREEN is emitted only after final cleanup residual gates pass (B02).
}
catch {
    $ScriptExitCode = 1
    $FailMsg = [string]$_.Exception.Message
    # Prefer explicit harness markers even if product stages already failed.
    if ($FailMsg -match 'W1D_HARNESS_') {
        Write-Output ("W1D_WRAPPER_HARNESS_FAILURE: {0}" -f $FailMsg)
    }
    elseif ($ProductFailure) {
        Write-Output ("W1D_WRAPPER_PRODUCT_FAILURE: {0}" -f $FailMsg)
    }
    else {
        Write-Output ("W1D_WRAPPER_HARNESS_FAILURE: {0}" -f $FailMsg)
    }
}
finally {
    if ($ClusterStarted) {
        try {
            & $PgCtlExe --pgdata=$DataDirectory stop --mode=immediate --wait | Out-Null
            if ($LASTEXITCODE -ne 0) {
                $CleanupHarnessFailure = $true
                Write-Output "W1D_HARNESS_POSTGRES_STOP_FAILED"
            }
        }
        catch {
            $CleanupHarnessFailure = $true
            Write-Output "W1D_HARNESS_POSTGRES_STOP_FAILED"
        }
        $ClusterStarted = $false
        Start-Sleep -Seconds 2
    }

    # R8-11: terminate remaining postgres children via full snapshot + filter.
    try {
        $allProcs = Get-W1dProcessSnapshot
        $pgChildren = @(
            $allProcs | Where-Object {
                $_.Name -match '^(postgres|pg_ctl)\.exe$' -and
                $_.CommandLine -and
                $_.CommandLine.IndexOf($DataDirectory, [StringComparison]::OrdinalIgnoreCase) -ge 0
            }
        )
        foreach ($row in $pgChildren) {
            try {
                Stop-Process -Id ([int]$row.ProcessId) -Force -ErrorAction Stop
            }
            catch {
                $CleanupHarnessFailure = $true
                Write-Output (
                    "W1D_HARNESS_PG_CHILD_KILL_FAILED: pid={0}" -f $row.ProcessId
                )
            }
        }
    }
    catch {
        $CleanupHarnessFailure = $true
        Write-Output ("W1D_HARNESS_PROCESS_ENUM_FAILED: {0}" -f $_.Exception.Message)
    }
    Start-Sleep -Seconds 1

    try {
        $allListen = Get-W1dListenerSnapshot
        $PgListen = @($allListen | Where-Object { [int]$_.LocalPort -eq [int]$Port })
        $BeListen = @($allListen | Where-Object { [int]$_.LocalPort -eq [int]$BackendPort })
        $FeListen = @($allListen | Where-Object { [int]$_.LocalPort -eq [int]$FrontendPort })
    }
    catch {
        $CleanupHarnessFailure = $true
        Write-Output ("W1D_HARNESS_LISTENER_ENUM_FAILED: {0}" -f $_.Exception.Message)
        $PgListen = @()
        $BeListen = @()
        $FeListen = @()
    }
    if ($PgListen.Count -gt 0 -or $BeListen.Count -gt 0 -or $FeListen.Count -gt 0) {
        $ListenerResidual = $PgListen.Count + $BeListen.Count + $FeListen.Count
    }
    Write-Output (
        "W1D_CLEANUP_LISTENERS pg={0} backend={1} frontend={2}" -f
        $PgListen.Count, $BeListen.Count, $FeListen.Count
    )
    # Residual by normalized CommandLine data-dir and port (slash normalize).
    $DataDirNorm = $DataDirectory.Replace("/", "\").TrimEnd("\")
    $DataDirAlt = $DataDirectory.Replace("\", "/").TrimEnd("/")
    try {
        $allProcs2 = Get-W1dProcessSnapshot
        $PgProcesses = @(
            $allProcs2 | Where-Object {
                $_.Name -match '^(postgres|pg_ctl)\.exe$' -and
                $_.CommandLine -and
                (
                    $_.CommandLine.IndexOf($DataDirectory, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
                    $_.CommandLine.IndexOf($DataDirNorm, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
                    $_.CommandLine.IndexOf($DataDirAlt, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
                    $_.CommandLine -match ("-p\s*{0}\b" -f $Port)
                )
            }
        )
        $BeProcesses = @(
            $allProcs2 | Where-Object {
                $_.CommandLine -and
                $_.CommandLine -match 'uvicorn' -and
                $_.CommandLine -match ("--port\s+{0}\b" -f $BackendPort)
            }
        )
        $FeProcesses = @(
            $allProcs2 | Where-Object {
                $_.CommandLine -and
                (
                    ($_.CommandLine -match 'vite' -and $_.CommandLine -match ("--port\s+{0}\b" -f $FrontendPort)) -or
                    ($_.CommandLine -match 'playwright' -and $_.CommandLine -match 'w1d-contract-transition')
                )
            }
        )
    }
    catch {
        $CleanupHarnessFailure = $true
        Write-Output ("W1D_HARNESS_PROCESS_ENUM_FAILED: {0}" -f $_.Exception.Message)
        $PgProcesses = @()
        $BeProcesses = @()
        $FeProcesses = @()
    }
    $ProcessResidual = $PgProcesses.Count + $BeProcesses.Count + $FeProcesses.Count
    Write-Output (
        "W1D_CLEANUP_PROCESSES pg={0} backend={1} frontend={2}" -f
        $PgProcesses.Count, $BeProcesses.Count, $FeProcesses.Count
    )
    if ($ProcessResidual -gt 0) {
        Write-Output ("W1D_HARNESS_PROCESS_RESIDUAL={0}" -f $ProcessResidual)
    }
    if (Test-Path -LiteralPath $ClusterRoot) {
        $ResolvedCleanup = [System.IO.Path]::GetFullPath($ClusterRoot)
        $ResolvedParent = Split-Path -Parent $ResolvedCleanup
        $ResolvedLeaf = Split-Path -Leaf $ResolvedCleanup
        if (
            -not [string]::Equals(
                $ResolvedParent,
                $TempParent,
                [StringComparison]::OrdinalIgnoreCase
            ) -or
            $ResolvedLeaf -cnotmatch '^sswcenter-w1d-pg-[0-9a-f]{32}$'
        ) {
            $CleanupHarnessFailure = $true
            Write-Output "W1D_HARNESS_UNSAFE_CLEANUP_PATH"
        }
        else {
            $removed = $false
            for ($attempt = 1; $attempt -le 3 -and -not $removed; $attempt++) {
                try {
                    [System.IO.Directory]::Delete($ResolvedCleanup, $true)
                    $removed = $true
                }
                catch {
                    Write-Output ("W1D_HARNESS_CLEANUP_REMOVE_WARNING: attempt={0} {1}" -f $attempt, $_.Exception.Message)
                    Start-Sleep -Seconds (2 * $attempt)
                }
            }
            if (-not $removed) {
                $CleanupHarnessFailure = $true
                Write-Output "W1D_HARNESS_CLEANUP_REMOVE_RETRY_FAILED"
            }
        }
    }
    if (Test-Path -LiteralPath $ClusterRoot) {
        $TempResidual = 1
    }
    # R8-11: harness-owned artifact residual (created by run, not removed).
    $ArtifactResidual = 0
    if (-not $HadTestResults -and (Test-Path -LiteralPath $PwTestResults)) {
        $ArtifactResidual++
    }
    if (-not $HadPwReport -and (Test-Path -LiteralPath $PwReport)) {
        $ArtifactResidual++
    }
    if (-not $HadRootNodeModules -and (Test-Path -LiteralPath $RootNodeModules)) {
        $ArtifactResidual++
    }
    Write-Output (
        "W1D_CLEANUP listener={0} process={1} temp={2} artifact={3} artifact_removed={4}" -f
        $ListenerResidual, $ProcessResidual, $TempResidual, $ArtifactResidual, $ArtifactRemovedCount
    )
    if (
        $ListenerResidual -gt 0 -or
        $ProcessResidual -gt 0 -or
        $TempResidual -gt 0 -or
        $ArtifactResidual -gt 0
    ) {
        $CleanupHarnessFailure = $true
        Write-Output "W1D_HARNESS_CLEANUP_RESIDUAL_NONZERO"
    }
}
# B02: GREEN only after every stage AND cleanup residual gates succeed.
if (
    $AllProductStagesOk -and
    -not $ProductFailure -and
    -not $CleanupHarnessFailure -and
    $ListenerResidual -eq 0 -and
    $ProcessResidual -eq 0 -and
    $TempResidual -eq 0 -and
    $ArtifactResidual -eq 0 -and
    $ScriptExitCode -eq 0
) {
    Write-Output "W1D_POSTGRES_GREEN"
}
elseif ($CleanupHarnessFailure) {
    $ScriptExitCode = 1
    Write-Output "W1D_WRAPPER_HARNESS_FAILURE: W1D_HARNESS_CLEANUP_GATE"
}
if ($ScriptExitCode -ne 0) {
    exit $ScriptExitCode
}
