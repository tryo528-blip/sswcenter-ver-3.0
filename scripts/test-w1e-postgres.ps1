param(
    # Bind omissions so the preflight emits a stable harness marker before mutable work.
    [string]$ExpectedSha = "",
    [int]$Port = 55443
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$PythonExe = Join-Path $BackendRoot ".venv\Scripts\python.exe"
$PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$PostgresBin = "C:\Program Files\PostgreSQL\17\bin"
$InitDbExe = Join-Path $PostgresBin "initdb.exe"
$PgCtlExe = Join-Path $PostgresBin "pg_ctl.exe"
$PgIsReadyExe = Join-Path $PostgresBin "pg_isready.exe"
$CreateDbExe = Join-Path $PostgresBin "createdb.exe"
$PsqlExe = Join-Path $PostgresBin "psql.exe"
$GitCommand = Get-Command git.exe -ErrorAction Stop
$GitExe = $GitCommand.Source
$ExpectedW1eRevision = "20260801_0012_w1e_care_assignment"
$W1dHead = "20260730_0011_w1d_recipient_contract"
$ExpectedW1eTests = @(
    "test_w1e_pg_catalog_and_deferred_guard_shape",
    "test_w1e_pg_general_overlap_and_containment",
    "test_w1e_pg_composite_employment_fk_rejects_staff_mismatch",
    "test_w1e_pg_forward_employment_and_position_containment",
    "test_w1e_pg_general_qualification_covers_every_day_and_service",
    "test_w1e_pg_reverse_guards_and_period_fact_correction",
    "test_w1e_pg_position_reparent_rejects_old_key_orphan",
    "test_w1e_pg_qualification_rekey_rejects_old_key_orphan",
    "test_w1e_pg_contract_service_transition_rechecks_qualification"
)

function Write-W1eHarnessFailure {
    param([string]$Marker, [string]$Detail = "")
    if ([string]::IsNullOrWhiteSpace($Detail)) {
        Write-Output $Marker
    }
    else {
        Write-Output ("{0}: {1}" -f $Marker, $Detail)
    }
    throw $Marker
}

function Write-W1eProductFailure {
    param([string]$Marker, [string]$Detail = "")
    if ([string]::IsNullOrWhiteSpace($Detail)) {
        Write-Output $Marker
    }
    else {
        Write-Output ("{0}: {1}" -f $Marker, $Detail)
    }
    throw $Marker
}

function Get-W1eProcessSnapshot {
    try {
        $rows = @(
            Get-CimInstance `
                Win32_Process `
                -OperationTimeoutSec 10 `
                -ErrorAction Stop
        )
        return $rows
    }
    catch {
        Write-W1eHarnessFailure `
            "W1E_HARNESS_PROCESS_ENUM_FAILED" `
            ([string]$_.Exception.Message)
    }
}

function Get-W1eListenerSnapshot {
    try {
        $probe = @'
$ErrorActionPreference = "Stop"
$rows = @(
    Get-NetTCPConnection -State Listen -ErrorAction Stop |
        Select-Object LocalAddress, LocalPort, OwningProcess
)
[pscustomobject]@{ Rows = $rows } | ConvertTo-Json -Depth 3 -Compress
'@
        $encodedProbe = [Convert]::ToBase64String(
            [Text.Encoding]::Unicode.GetBytes($probe)
        )
        $listenerRun = Invoke-W1eTimedCommand `
            -FilePath $PowerShellExe `
            -TimeoutSec 20 `
            -TimeoutMarker "W1E_HARNESS_LISTENER_ENUM_TIMEOUT" `
            -ArgumentList @(
                "-NoProfile", "-NonInteractive", "-EncodedCommand", $encodedProbe
            )
        if ([int]$listenerRun.ExitCode -ne 0) {
            Write-W1eCommandEvidence $listenerRun
            Write-W1eHarnessFailure "W1E_HARNESS_LISTENER_ENUM_FAILED" (
                "exit={0}" -f $listenerRun.ExitCode
            )
        }
        $payload = ([string]$listenerRun.Stdout).Trim() | ConvertFrom-Json
        return $payload.Rows
    }
    catch {
        $message = [string]$_.Exception.Message
        if ($message -match "W1E_HARNESS_") {
            throw
        }
        Write-W1eHarnessFailure "W1E_HARNESS_LISTENER_ENUM_FAILED" $message
    }
}

function Get-W1eProcessIdentity {
    param([Parameter(Mandatory = $true)]$ProcessRow)
    if (
        $null -eq $ProcessRow.ProcessId -or
        $null -eq $ProcessRow.CreationDate -or
        [string]::IsNullOrWhiteSpace([string]$ProcessRow.CreationDate)
    ) {
        Write-W1eHarnessFailure "W1E_HARNESS_PROCESS_IDENTITY_INCOMPLETE" (
            "name={0};pid={1}" -f $ProcessRow.Name, $ProcessRow.ProcessId
        )
    }
    return ("{0}|{1}" -f [int]$ProcessRow.ProcessId, [string]$ProcessRow.CreationDate)
}

function Test-W1eResidualPostgresProcess {
    param(
        [Parameter(Mandatory = $true)]$ProcessRow,
        [Parameter(Mandatory = $true)][hashtable]$BaselineSet,
        [Parameter(Mandatory = $true)][string[]]$OwnedPathVariants,
        [Parameter(Mandatory = $true)][int]$OwnedPort
    )
    if ($ProcessRow.Name -notmatch '^(postgres|pg_ctl)\.exe$') {
        return $false
    }
    $identity = Get-W1eProcessIdentity $ProcessRow
    if (-not $BaselineSet.ContainsKey($identity)) {
        return $true
    }
    if (-not $ProcessRow.CommandLine) {
        return $false
    }
    foreach ($ownedPath in $OwnedPathVariants) {
        if (
            -not [string]::IsNullOrWhiteSpace($ownedPath) -and
            $ProcessRow.CommandLine.IndexOf(
                $ownedPath,
                [StringComparison]::OrdinalIgnoreCase
            ) -ge 0
        ) {
            return $true
        }
    }
    return ($ProcessRow.CommandLine -match ("-p\s*{0}\b" -f $OwnedPort))
}

function Get-W1eDescendantPids {
    param(
        [Parameter(Mandatory = $true)][int]$RootPid,
        [Parameter(Mandatory = $true)]$Snapshot
    )
    $byParent = @{}
    foreach ($row in @($Snapshot)) {
        $parentPid = [int]$row.ParentProcessId
        if (-not $byParent.ContainsKey($parentPid)) {
            $byParent[$parentPid] = New-Object System.Collections.ArrayList
        }
        [void]$byParent[$parentPid].Add([int]$row.ProcessId)
    }
    $depth = @{}
    $depth[[int]$RootPid] = 0
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue([int]$RootPid)
    while ($queue.Count -gt 0) {
        $currentPid = [int]$queue.Dequeue()
        if ($byParent.ContainsKey($currentPid)) {
            foreach ($childPidValue in @($byParent[$currentPid])) {
                $childPid = [int]$childPidValue
                if (-not $depth.ContainsKey($childPid)) {
                    $depth[$childPid] = [int]$depth[$currentPid] + 1
                    $queue.Enqueue($childPid)
                }
            }
        }
    }
    $descendants = @(
        $depth.Keys |
            Where-Object { [int]$_ -ne [int]$RootPid } |
            Sort-Object { -[int]$depth[[int]$_] } |
            ForEach-Object { [int]$_ }
    )
    return ([int[]]$descendants)
}

function Stop-W1eProcessTreeFailClosed {
    param(
        [Parameter(Mandatory = $true)][int]$RootPid,
        [string]$Context = "child"
    )
    $snapshot = Get-W1eProcessSnapshot
    $descendants = @(
        Get-W1eDescendantPids -RootPid $RootPid -Snapshot $snapshot
    )
    $capturedPids = @($descendants) + @([int]$RootPid)
    foreach ($targetPidValue in @($descendants)) {
        $targetPid = [int]$targetPidValue
        $isAlive = @(
            $snapshot | Where-Object { [int]$_.ProcessId -eq $targetPid }
        ).Count -gt 0
        if ($isAlive) {
            try {
                Stop-Process -Id $targetPid -Force -ErrorAction Stop
            }
            catch {
                # A race is acceptable only when the final snapshot proves zero.
            }
        }
    }
    $rootAlive = @(
        $snapshot | Where-Object { [int]$_.ProcessId -eq [int]$RootPid }
    ).Count -gt 0
    if ($rootAlive) {
        try {
            Stop-Process -Id ([int]$RootPid) -Force -ErrorAction Stop
        }
        catch {
            # A race is acceptable only when the final snapshot proves zero.
        }
    }
    Start-Sleep -Milliseconds 500
    $verificationSnapshot = Get-W1eProcessSnapshot
    $residualPids = @(
        $capturedPids | Where-Object {
            $candidatePid = [int]$_
            @(
                $verificationSnapshot |
                    Where-Object { [int]$_.ProcessId -eq $candidatePid }
            ).Count -gt 0
        }
    )
    if ($residualPids.Count -gt 0) {
        Write-W1eHarnessFailure "W1E_HARNESS_PROCESS_TREE_RESIDUAL" (
            "context={0};pids={1}" -f $Context, ($residualPids -join ",")
        )
    }
}

function ConvertTo-W1eProcessArgument {
    param([AllowEmptyString()][string]$Argument)
    if ($Argument.Length -gt 0 -and $Argument -notmatch '[\s"]') {
        return $Argument
    }
    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashCount = 0
    foreach ($character in $Argument.ToCharArray()) {
        if ($character -eq [char]'\') {
            $backslashCount++
            continue
        }
        if ($character -eq [char]'"') {
            if ($backslashCount -gt 0) {
                [void]$builder.Append(
                    ((('\' * (2 * $backslashCount)) -join ''))
                )
            }
            [void]$builder.Append('\')
            [void]$builder.Append('"')
            $backslashCount = 0
            continue
        }
        if ($backslashCount -gt 0) {
            [void]$builder.Append(((('\' * $backslashCount) -join '')))
            $backslashCount = 0
        }
        [void]$builder.Append($character)
    }
    if ($backslashCount -gt 0) {
        [void]$builder.Append(((('\' * (2 * $backslashCount)) -join '')))
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function ConvertTo-W1eProcessArguments {
    param([string[]]$ArgumentList = @())
    return (@(
        $ArgumentList | ForEach-Object {
            ConvertTo-W1eProcessArgument ([string]$_)
        }
    ) -join " ")
}

function Invoke-W1eTimedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = "",
        [int]$TimeoutSec = 600,
        [string]$TimeoutMarker = "W1E_HARNESS_CHILD_TIMEOUT"
    )
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = ConvertTo-W1eProcessArguments $ArgumentList
    if (-not [string]::IsNullOrWhiteSpace($WorkingDirectory)) {
        $startInfo.WorkingDirectory = $WorkingDirectory
    }
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $drainTasks = [System.Threading.Tasks.Task[]]@($stdoutTask, $stderrTask)
    if (-not $process.WaitForExit($TimeoutSec * 1000)) {
        Stop-W1eProcessTreeFailClosed `
            -RootPid ([int]$process.Id) `
            -Context $TimeoutMarker
        try {
            [void][System.Threading.Tasks.Task]::WaitAll($drainTasks, 5000)
        }
        catch {
            Write-W1eHarnessFailure "W1E_HARNESS_STREAM_READ_FAILED" (
                [string]$_.Exception.Message
            )
        }
        Write-W1eHarnessFailure $TimeoutMarker ("timeoutSec={0}" -f $TimeoutSec)
    }
    try {
        $streamsDrained = [System.Threading.Tasks.Task]::WaitAll($drainTasks, 5000)
    }
    catch {
        Write-W1eHarnessFailure "W1E_HARNESS_STREAM_READ_FAILED" (
            [string]$_.Exception.Message
        )
    }
    if (-not $streamsDrained) {
        Stop-W1eProcessTreeFailClosed `
            -RootPid ([int]$process.Id) `
            -Context "W1E_HARNESS_STREAM_DRAIN_TIMEOUT"
        try {
            $streamsDrained = [System.Threading.Tasks.Task]::WaitAll(
                $drainTasks,
                5000
            )
        }
        catch {
            Write-W1eHarnessFailure "W1E_HARNESS_STREAM_READ_FAILED" (
                [string]$_.Exception.Message
            )
        }
        if (-not $streamsDrained) {
            Write-W1eHarnessFailure "W1E_HARNESS_STREAM_DRAIN_TIMEOUT"
        }
        Write-W1eHarnessFailure "W1E_HARNESS_STREAM_DRAIN_TIMEOUT" (
            "descendant handles required forced cleanup"
        )
    }
    try {
        $stdout = [string]$stdoutTask.GetAwaiter().GetResult()
        $stderr = [string]$stderrTask.GetAwaiter().GetResult()
    }
    catch {
        Write-W1eHarnessFailure "W1E_HARNESS_STREAM_READ_FAILED" (
            [string]$_.Exception.Message
        )
    }
    $result = New-Object psobject -Property @{
        ExitCode = [int]$process.ExitCode
        Stdout   = $stdout
        Stderr   = $stderr
    }
    return ,$result
}

function Invoke-W1eDetachedPgCtlStart {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [int]$TimeoutSec = 60
    )
    try {
        $process = Start-Process `
            -FilePath $FilePath `
            -ArgumentList (ConvertTo-W1eProcessArguments $ArgumentList) `
            -WorkingDirectory $WorkingDirectory `
            -PassThru `
            -WindowStyle Hidden
    }
    catch {
        Write-W1eHarnessFailure "W1E_HARNESS_POSTGRES_START_LAUNCH_FAILED" (
            [string]$_.Exception.Message
        )
    }
    if (-not $process.WaitForExit($TimeoutSec * 1000)) {
        Stop-W1eProcessTreeFailClosed `
            -RootPid ([int]$process.Id) `
            -Context "W1E_HARNESS_POSTGRES_START_TIMEOUT"
        Write-W1eHarnessFailure "W1E_HARNESS_POSTGRES_START_TIMEOUT" (
            "timeoutSec={0}" -f $TimeoutSec
        )
    }
    return ,(New-Object psobject -Property @{
            ExitCode = [int]$process.ExitCode
            Stdout   = ""
            Stderr   = ""
            Transport = "detached-hidden"
        })
}

function Write-W1eCommandEvidence {
    param([Parameter(Mandatory = $true)]$Result)
    ([string]$Result.Stdout) -split "`r?`n" | ForEach-Object {
        if (-not [string]::IsNullOrWhiteSpace($_)) {
            Write-Output $_
        }
    }
    ([string]$Result.Stderr) -split "`r?`n" | ForEach-Object {
        if (-not [string]::IsNullOrWhiteSpace($_)) {
            [Console]::Error.WriteLine($_)
        }
    }
}

function Get-W1eCommandFailureKind {
    param(
        [Parameter(Mandatory = $true)]$Result,
        [Parameter(Mandatory = $true)]
        [ValidateSet("Migration", "Pytest")]
        [string]$Context
    )
    $evidence = ([string]$Result.Stdout) + "`n" + ([string]$Result.Stderr)
    $infrastructurePattern = @(
        "connection refused",
        "could not connect",
        "password authentication failed",
        "no pg_hba.conf entry",
        "server closed the connection unexpectedly",
        "connection (?:is )?(?:closed|failed|reset)",
        "SSL SYSCALL",
        "timeout expired",
        "OperationalError",
        "InterfaceError",
        "AdminShutdown",
        "CrashShutdown",
        "CannotConnectNow",
        "W1E_HARNESS_",
        "INTERNALERROR",
        "ModuleNotFoundError",
        "ImportError",
        "No module named",
        "can't open file"
    ) -join "|"
    if ($evidence -match $infrastructurePattern) {
        return "Harness"
    }
    if ($Context -eq "Migration") {
        $productPattern = @(
            [regex]::Escape($ExpectedW1eRevision),
            "20260801_0012_w1e_care_assignment\.py",
            "sqlalchemy\.exc\.(?:ProgrammingError|IntegrityError|DataError|InternalError)",
            "psycopg\.errors\.[A-Za-z]+"
        ) -join "|"
        if ($evidence -match $productPattern) {
            return "Product"
        }
    }
    elseif (
        $evidence -match
        "(?m)^(?:FAILED|ERROR)\s+tests[\\/]test_w1e_postgres\.py::"
    ) {
        return "Product"
    }
    return "Harness"
}

function Get-W1eArtifactSnapshot {
    $paths = New-Object System.Collections.ArrayList
    $scanRoots = @(
        (Join-Path $BackendRoot "app"),
        (Join-Path $BackendRoot "alembic"),
        (Join-Path $BackendRoot "tests")
    )
    foreach ($scanRoot in $scanRoots) {
        if (-not (Test-Path -LiteralPath $scanRoot -PathType Container)) {
            continue
        }
        foreach ($cacheDirectory in @(
            Get-ChildItem -LiteralPath $scanRoot -Recurse -Force -Directory |
                Where-Object { $_.Name -in @("__pycache__", ".pytest_cache", ".ruff_cache") }
        )) {
            [void]$paths.Add([System.IO.Path]::GetFullPath($cacheDirectory.FullName))
        }
        foreach ($pycFile in @(
            Get-ChildItem -LiteralPath $scanRoot -Recurse -Force -File -Filter "*.pyc"
        )) {
            [void]$paths.Add([System.IO.Path]::GetFullPath($pycFile.FullName))
        }
    }
    foreach ($rootCacheName in @(".pytest_cache", ".ruff_cache")) {
        $rootCache = Join-Path $BackendRoot $rootCacheName
        if (Test-Path -LiteralPath $rootCache) {
            [void]$paths.Add([System.IO.Path]::GetFullPath($rootCache))
        }
    }
    return ([string[]]@($paths | Sort-Object -Unique))
}

function Get-W1eRevision {
    $revisionRun = Invoke-W1eTimedCommand `
        -FilePath $PsqlExe `
        -TimeoutSec 30 `
        -TimeoutMarker "W1E_HARNESS_REVISION_QUERY_TIMEOUT" `
        -ArgumentList @(
            "-X", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1",
            "-p", [string]$Port, "-U", "erp_owner", "-d", $DatabaseName,
            "-tAc", "SELECT version_num FROM erp.alembic_version"
        )
    if ([int]$revisionRun.ExitCode -ne 0) {
        Write-W1eCommandEvidence $revisionRun
        Write-W1eHarnessFailure "W1E_HARNESS_REVISION_QUERY_FAILED" (
            "exit={0}" -f $revisionRun.ExitCode
        )
    }
    return ([string]$revisionRun.Stdout).Trim()
}

foreach ($executable in @(
    $GitExe,
    $PythonExe,
    $PowerShellExe,
    $InitDbExe,
    $PgCtlExe,
    $PgIsReadyExe,
    $CreateDbExe,
    $PsqlExe
)) {
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        Write-W1eHarnessFailure "W1E_HARNESS_MISSING_EXECUTABLE" $executable
    }
}

if ($ExpectedSha -notmatch '^[0-9a-fA-F]{40}$') {
    Write-W1eHarnessFailure "W1E_HARNESS_EXPECTED_SHA_INVALID" $ExpectedSha
}
$ExpectedSha = $ExpectedSha.ToLowerInvariant()

$GitRootRun = Invoke-W1eTimedCommand `
    -FilePath $GitExe `
    -WorkingDirectory $WorkspaceRoot `
    -TimeoutSec 30 `
    -TimeoutMarker "W1E_HARNESS_GIT_ROOT_TIMEOUT" `
    -ArgumentList @("rev-parse", "--show-toplevel")
if ([int]$GitRootRun.ExitCode -ne 0) {
    Write-W1eCommandEvidence $GitRootRun
    Write-W1eHarnessFailure "W1E_HARNESS_GIT_ROOT_FAILED"
}
$ObservedGitRoot = [System.IO.Path]::GetFullPath(
    ([string]$GitRootRun.Stdout).Trim()
)
if (-not $ObservedGitRoot.Equals($WorkspaceRoot, [StringComparison]::OrdinalIgnoreCase)) {
    Write-W1eHarnessFailure "W1E_HARNESS_GIT_ROOT_MISMATCH" (
        "expected={0};actual={1}" -f $WorkspaceRoot, $ObservedGitRoot
    )
}

$HeadRun = Invoke-W1eTimedCommand `
    -FilePath $GitExe `
    -WorkingDirectory $WorkspaceRoot `
    -TimeoutSec 30 `
    -TimeoutMarker "W1E_HARNESS_GIT_HEAD_TIMEOUT" `
    -ArgumentList @("rev-parse", "HEAD")
if ([int]$HeadRun.ExitCode -ne 0) {
    Write-W1eCommandEvidence $HeadRun
    Write-W1eHarnessFailure "W1E_HARNESS_GIT_HEAD_FAILED"
}
$ObservedSha = ([string]$HeadRun.Stdout).Trim().ToLowerInvariant()
if ($ObservedSha -ne $ExpectedSha) {
    Write-W1eHarnessFailure "W1E_HARNESS_EXACT_SHA_MISMATCH" (
        "expected={0};actual={1}" -f $ExpectedSha, $ObservedSha
    )
}

$GitStatusRun = Invoke-W1eTimedCommand `
    -FilePath $GitExe `
    -WorkingDirectory $WorkspaceRoot `
    -TimeoutSec 30 `
    -TimeoutMarker "W1E_HARNESS_GIT_STATUS_TIMEOUT" `
    -ArgumentList @("status", "--porcelain=v1", "--untracked-files=all")
if ([int]$GitStatusRun.ExitCode -ne 0) {
    Write-W1eCommandEvidence $GitStatusRun
    Write-W1eHarnessFailure "W1E_HARNESS_GIT_STATUS_FAILED"
}
$InitialGitStatus = ([string]$GitStatusRun.Stdout).Trim()
if (-not [string]::IsNullOrWhiteSpace($InitialGitStatus)) {
    Write-W1eHarnessFailure "W1E_HARNESS_GIT_NOT_CLEAN" $InitialGitStatus
}
Write-Output ("W1E_EXACT_SHA_OK={0}" -f $ObservedSha)

$PreflightListeners = Get-W1eListenerSnapshot
$PortUsers = @(
    $PreflightListeners | Where-Object { [int]$_.LocalPort -eq [int]$Port }
)
if ($PortUsers.Count -gt 0) {
    Write-W1eHarnessFailure "W1E_HARNESS_PORT_IN_USE" ([string]$Port)
}

$PreflightProcesses = Get-W1eProcessSnapshot
$BeforePostgresProcessSet = @{}
foreach ($preflightProcess in @(
    $PreflightProcesses |
        Where-Object { $_.Name -match '^(postgres|pg_ctl)\.exe$' }
)) {
    $processIdentity = Get-W1eProcessIdentity $preflightProcess
    $BeforePostgresProcessSet[$processIdentity] = $true
}
Write-Output (
    "W1E_PREFLIGHT_POSTGRES_PROCESS_BASELINE={0}" -f
    $BeforePostgresProcessSet.Count
)

$BeforeArtifacts = @(Get-W1eArtifactSnapshot)
$BeforeArtifactSet = @{}
foreach ($artifactPath in $BeforeArtifacts) {
    $BeforeArtifactSet[[string]$artifactPath] = $true
}

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    Write-W1eHarnessFailure "W1E_HARNESS_LOCALAPPDATA_MISSING"
}
$LocalAppDataRoot = [System.IO.Path]::GetFullPath(
    $env:LOCALAPPDATA
).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
)
$LocalAppDataPrefix = $LocalAppDataRoot + [System.IO.Path]::DirectorySeparatorChar
$TempParent = [System.IO.Path]::GetFullPath(
    (Join-Path $LocalAppDataRoot "Temp")
).TrimEnd(
    [System.IO.Path]::DirectorySeparatorChar,
    [System.IO.Path]::AltDirectorySeparatorChar
)
if (
    -not $TempParent.StartsWith(
        $LocalAppDataPrefix,
        [StringComparison]::OrdinalIgnoreCase
    ) -or
    -not (Test-Path -LiteralPath $TempParent -PathType Container)
) {
    Write-W1eHarnessFailure "W1E_HARNESS_USER_TEMP_UNAVAILABLE" $TempParent
}
$env:TEMP = $TempParent
$env:TMP = $TempParent
$env:TMPDIR = $TempParent
Write-Output ("W1E_USER_TEMP_OK={0}" -f $TempParent)
$ClusterRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $TempParent ("sswcenter-w1e-pg-" + [Guid]::NewGuid().ToString("N")))
)
$ExpectedTempPrefix = $TempParent + [System.IO.Path]::DirectorySeparatorChar
$ClusterLeaf = Split-Path -Leaf $ClusterRoot
if (
    -not $ClusterRoot.StartsWith(
        $ExpectedTempPrefix,
        [StringComparison]::OrdinalIgnoreCase
    ) -or
    -not $ClusterLeaf.StartsWith("sswcenter-w1e-pg-", [StringComparison]::Ordinal)
) {
    Write-W1eHarnessFailure "W1E_HARNESS_UNSAFE_TEMP_PATH" $ClusterRoot
}

$DataDirectory = Join-Path $ClusterRoot "data"
$RuntimeDataRoot = Join-Path $ClusterRoot "sswcenter-w1e-runtime"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$DatabaseName = "sswcenter_w1e_review"
$OwnerDatabaseUrl = "postgresql+psycopg://erp_owner@127.0.0.1:$Port/$DatabaseName"
$AppDatabaseUrl = "postgresql+psycopg://erp_app@127.0.0.1:$Port/$DatabaseName"
$ClusterStarted = $false
$ProductFailure = $false
$AllProductStagesOk = $false
$CleanupHarnessFailure = $false
$ScriptExitCode = 0
$ListenerResidual = 0
$ProcessResidual = 0
$TempResidual = 0
$ArtifactResidual = 0
$ArtifactRemovedCount = 0
$GitResidual = 0

try {
    New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $RuntimeDataRoot -Force | Out-Null

    $InitRun = Invoke-W1eTimedCommand `
        -FilePath $InitDbExe `
        -TimeoutSec 120 `
        -TimeoutMarker "W1E_HARNESS_INITDB_TIMEOUT" `
        -ArgumentList @(
            "--pgdata=$DataDirectory", "--username=postgres", "--auth=trust",
            "--encoding=UTF8", "--locale=C"
        )
    Write-Output ("W1E_STAGE_INITDB_EXIT={0}" -f $InitRun.ExitCode)
    if ([int]$InitRun.ExitCode -ne 0) {
        Write-W1eCommandEvidence $InitRun
        Write-W1eHarnessFailure "W1E_HARNESS_INITDB_FAILED"
    }

    $StartRun = Invoke-W1eDetachedPgCtlStart `
        -FilePath $PgCtlExe `
        -WorkingDirectory $WorkspaceRoot `
        -TimeoutSec 60 `
        -ArgumentList @(
            "--pgdata=$DataDirectory", "--log=$LogFile",
            "--options=-h 127.0.0.1 -p $Port", "start", "--wait"
        )
    Write-Output ("W1E_STAGE_POSTGRES_START_TRANSPORT={0}" -f $StartRun.Transport)
    Write-Output ("W1E_STAGE_POSTGRES_START_EXIT={0}" -f $StartRun.ExitCode)
    if ([int]$StartRun.ExitCode -ne 0) {
        Write-W1eCommandEvidence $StartRun
        Write-W1eHarnessFailure "W1E_HARNESS_POSTGRES_START_FAILED"
    }
    $ClusterStarted = $true

    $ReadyRun = Invoke-W1eTimedCommand `
        -FilePath $PgIsReadyExe `
        -TimeoutSec 30 `
        -TimeoutMarker "W1E_HARNESS_POSTGRES_READY_TIMEOUT" `
        -ArgumentList @(
            "-h", "127.0.0.1", "-p", [string]$Port,
            "-U", "postgres", "-d", "postgres", "-t", "15"
        )
    Write-Output ("W1E_STAGE_POSTGRES_READY_EXIT={0}" -f $ReadyRun.ExitCode)
    if ([int]$ReadyRun.ExitCode -ne 0) {
        Write-W1eCommandEvidence $ReadyRun
        Write-W1eHarnessFailure "W1E_HARNESS_POSTGRES_NOT_READY"
    }

    $RoleSql = "CREATE ROLE erp_owner LOGIN; CREATE ROLE erp_app LOGIN; CREATE ROLE erp_backup LOGIN;"
    $RoleRun = Invoke-W1eTimedCommand `
        -FilePath $PsqlExe `
        -TimeoutSec 30 `
        -TimeoutMarker "W1E_HARNESS_ROLE_CREATE_TIMEOUT" `
        -ArgumentList @(
            "-X", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1",
            "-p", [string]$Port, "-U", "postgres", "-d", "postgres",
            "-c", $RoleSql
        )
    Write-Output ("W1E_STAGE_ROLE_CREATE_EXIT={0}" -f $RoleRun.ExitCode)
    if ([int]$RoleRun.ExitCode -ne 0) {
        Write-W1eCommandEvidence $RoleRun
        Write-W1eHarnessFailure "W1E_HARNESS_ROLE_CREATE_FAILED"
    }

    $CreateDatabaseRun = Invoke-W1eTimedCommand `
        -FilePath $CreateDbExe `
        -TimeoutSec 30 `
        -TimeoutMarker "W1E_HARNESS_DATABASE_CREATE_TIMEOUT" `
        -ArgumentList @(
            "-h", "127.0.0.1", "-p", [string]$Port,
            "-U", "postgres", "-O", "erp_owner", $DatabaseName
        )
    Write-Output ("W1E_STAGE_DATABASE_CREATE_EXIT={0}" -f $CreateDatabaseRun.ExitCode)
    if ([int]$CreateDatabaseRun.ExitCode -ne 0) {
        Write-W1eCommandEvidence $CreateDatabaseRun
        Write-W1eHarnessFailure "W1E_HARNESS_DATABASE_CREATE_FAILED"
    }

    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
    $env:SSWCENTER_OWNER_DATABASE_URL = $OwnerDatabaseUrl
    $env:SSWCENTER_APP_DATABASE_URL = $AppDatabaseUrl
    $env:SSWCENTER_DATA_ROOT = $RuntimeDataRoot
    $env:SSWCENTER_W1E_REAL_PG = "1"
    $env:SSWCENTER_PIN_PEPPER = "w1e-test-pin-pepper"
    $env:SSWCENTER_PIN_LOOKUP_KEY = "w1e-test-pin-lookup"
    $env:SSWCENTER_CSRF_SIGNING_KEY = "w1e-test-csrf"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTEST_ADDOPTS = ""
    $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"

    $BaseUpgradeRun = Invoke-W1eTimedCommand `
        -FilePath $PythonExe `
        -WorkingDirectory $BackendRoot `
        -TimeoutSec 600 `
        -TimeoutMarker "W1E_HARNESS_BASE_UPGRADE_TIMEOUT" `
        -ArgumentList @("-m", "alembic", "-c", "alembic.ini", "upgrade", $W1dHead)
    Write-Output ("W1E_STAGE_BASE_UPGRADE_EXIT={0}" -f $BaseUpgradeRun.ExitCode)
    if ([int]$BaseUpgradeRun.ExitCode -ne 0) {
        Write-W1eCommandEvidence $BaseUpgradeRun
        Write-W1eHarnessFailure "W1E_HARNESS_W1D_BASE_UPGRADE_FAILED"
    }
    $BaseRevision = Get-W1eRevision
    Write-Output ("W1E_STAGE_BASE_REVISION={0}" -f $BaseRevision)
    if ($BaseRevision -ne $W1dHead) {
        Write-W1eHarnessFailure "W1E_HARNESS_W1D_BASE_REVISION_MISMATCH" (
            "expected={0};actual={1}" -f $W1dHead, $BaseRevision
        )
    }

    $UpgradeRun = Invoke-W1eTimedCommand `
        -FilePath $PythonExe `
        -WorkingDirectory $BackendRoot `
        -TimeoutSec 600 `
        -TimeoutMarker "W1E_HARNESS_UPGRADE_TIMEOUT" `
        -ArgumentList @(
            "-m", "alembic", "-c", "alembic.ini", "upgrade", $ExpectedW1eRevision
        )
    Write-Output ("W1E_STAGE_UPGRADE_EXIT={0}" -f $UpgradeRun.ExitCode)
    if ([int]$UpgradeRun.ExitCode -ne 0) {
        Write-W1eCommandEvidence $UpgradeRun
        $UpgradeFailureKind = Get-W1eCommandFailureKind `
            -Result $UpgradeRun `
            -Context "Migration"
        if ($UpgradeFailureKind -eq "Harness") {
            Write-W1eHarnessFailure "W1E_HARNESS_MIGRATION_UPGRADE_COMMAND_FAILED" (
                "exit={0}" -f $UpgradeRun.ExitCode
            )
        }
        $ProductFailure = $true
        Write-W1eProductFailure "W1E_MIGRATION_UPGRADE_FAILED"
    }
    $UpgradeRevision = Get-W1eRevision
    Write-Output ("W1E_STAGE_UPGRADE_REVISION={0}" -f $UpgradeRevision)
    if ($UpgradeRevision -ne $ExpectedW1eRevision) {
        $ProductFailure = $true
        Write-W1eProductFailure "W1E_MIGRATION_UPGRADE_REVISION_MISMATCH" (
            "expected={0};actual={1}" -f $ExpectedW1eRevision, $UpgradeRevision
        )
    }

    $DowngradeRun = Invoke-W1eTimedCommand `
        -FilePath $PythonExe `
        -WorkingDirectory $BackendRoot `
        -TimeoutSec 600 `
        -TimeoutMarker "W1E_HARNESS_DOWNGRADE_TIMEOUT" `
        -ArgumentList @("-m", "alembic", "-c", "alembic.ini", "downgrade", $W1dHead)
    Write-Output ("W1E_STAGE_DOWNGRADE_EXIT={0}" -f $DowngradeRun.ExitCode)
    if ([int]$DowngradeRun.ExitCode -ne 0) {
        Write-W1eCommandEvidence $DowngradeRun
        $DowngradeFailureKind = Get-W1eCommandFailureKind `
            -Result $DowngradeRun `
            -Context "Migration"
        if ($DowngradeFailureKind -eq "Harness") {
            Write-W1eHarnessFailure "W1E_HARNESS_MIGRATION_DOWNGRADE_COMMAND_FAILED" (
                "exit={0}" -f $DowngradeRun.ExitCode
            )
        }
        $ProductFailure = $true
        Write-W1eProductFailure "W1E_MIGRATION_DOWNGRADE_FAILED"
    }
    $DowngradeRevision = Get-W1eRevision
    Write-Output ("W1E_STAGE_DOWNGRADE_REVISION={0}" -f $DowngradeRevision)
    if ($DowngradeRevision -ne $W1dHead) {
        $ProductFailure = $true
        Write-W1eProductFailure "W1E_MIGRATION_DOWNGRADE_REVISION_MISMATCH" (
            "expected={0};actual={1}" -f $W1dHead, $DowngradeRevision
        )
    }
    $DowngradeTableRun = Invoke-W1eTimedCommand `
        -FilePath $PsqlExe `
        -TimeoutSec 30 `
        -TimeoutMarker "W1E_HARNESS_DOWNGRADE_TABLE_QUERY_TIMEOUT" `
        -ArgumentList @(
            "-X", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1",
            "-p", [string]$Port, "-U", "erp_owner", "-d", $DatabaseName,
            "-tAc", "SELECT to_regclass('erp.care_assignment') IS NULL"
        )
    if ([int]$DowngradeTableRun.ExitCode -ne 0) {
        Write-W1eCommandEvidence $DowngradeTableRun
        Write-W1eHarnessFailure "W1E_HARNESS_DOWNGRADE_TABLE_QUERY_FAILED"
    }
    $DowngradeTableAbsent = ([string]$DowngradeTableRun.Stdout).Trim()
    Write-Output ("W1E_STAGE_DOWNGRADE_TABLE_ABSENT={0}" -f $DowngradeTableAbsent)
    if ($DowngradeTableAbsent -ne "t") {
        $ProductFailure = $true
        Write-W1eProductFailure "W1E_MIGRATION_DOWNGRADE_TABLE_RESIDUAL"
    }

    $ReupgradeRun = Invoke-W1eTimedCommand `
        -FilePath $PythonExe `
        -WorkingDirectory $BackendRoot `
        -TimeoutSec 600 `
        -TimeoutMarker "W1E_HARNESS_REUPGRADE_TIMEOUT" `
        -ArgumentList @(
            "-m", "alembic", "-c", "alembic.ini", "upgrade", $ExpectedW1eRevision
        )
    Write-Output ("W1E_STAGE_REUPGRADE_EXIT={0}" -f $ReupgradeRun.ExitCode)
    if ([int]$ReupgradeRun.ExitCode -ne 0) {
        Write-W1eCommandEvidence $ReupgradeRun
        $ReupgradeFailureKind = Get-W1eCommandFailureKind `
            -Result $ReupgradeRun `
            -Context "Migration"
        if ($ReupgradeFailureKind -eq "Harness") {
            Write-W1eHarnessFailure "W1E_HARNESS_MIGRATION_REUPGRADE_COMMAND_FAILED" (
                "exit={0}" -f $ReupgradeRun.ExitCode
            )
        }
        $ProductFailure = $true
        Write-W1eProductFailure "W1E_MIGRATION_REUPGRADE_FAILED"
    }
    $ReupgradeRevision = Get-W1eRevision
    Write-Output ("W1E_STAGE_REUPGRADE_REVISION={0}" -f $ReupgradeRevision)
    if ($ReupgradeRevision -ne $ExpectedW1eRevision) {
        $ProductFailure = $true
        Write-W1eProductFailure "W1E_MIGRATION_REUPGRADE_REVISION_MISMATCH" (
            "expected={0};actual={1}" -f $ExpectedW1eRevision, $ReupgradeRevision
        )
    }

    $RuntimeRoleRun = Invoke-W1eTimedCommand `
        -FilePath $PsqlExe `
        -TimeoutSec 30 `
        -TimeoutMarker "W1E_HARNESS_APP_ROLE_QUERY_TIMEOUT" `
        -ArgumentList @(
            "-X", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1",
            "-p", [string]$Port, "-U", "erp_app", "-d", $DatabaseName,
            "-tAc", "SELECT current_user"
        )
    if ([int]$RuntimeRoleRun.ExitCode -ne 0) {
        Write-W1eCommandEvidence $RuntimeRoleRun
        Write-W1eHarnessFailure "W1E_HARNESS_APP_ROLE_QUERY_FAILED"
    }
    $RuntimeRole = ([string]$RuntimeRoleRun.Stdout).Trim()
    if ($RuntimeRole -ne "erp_app") {
        Write-W1eHarnessFailure "W1E_HARNESS_APP_ROLE_MISMATCH" $RuntimeRole
    }
    Write-Output "W1E_APP_ROLE_OK=erp_app"

    $env:SSWCENTER_DATABASE_URL = $AppDatabaseUrl
    $PytestNodeIds = @(
        $ExpectedW1eTests |
            ForEach-Object { "tests/test_w1e_postgres.py::{0}" -f $_ }
    )
    $UniquePytestNodeIds = @($PytestNodeIds | Sort-Object -Unique)
    Write-Output (
        "W1E_STAGE_POSTGRES_TARGET_NODE_IDS total={0} unique={1}" -f
        $PytestNodeIds.Count,
        $UniquePytestNodeIds.Count
    )
    if ($PytestNodeIds.Count -ne 9 -or $UniquePytestNodeIds.Count -ne 9) {
        Write-W1eHarnessFailure "W1E_HARNESS_PYTEST_TARGET_SET_INVALID"
    }
    $PytestArguments = @(
        "-m", "pytest", "-vv", "--tb=line", "--color=no", "-p", "no:cacheprovider"
    )
    $PytestArguments += $PytestNodeIds
    $PytestRun = Invoke-W1eTimedCommand `
        -FilePath $PythonExe `
        -WorkingDirectory $BackendRoot `
        -TimeoutSec 1200 `
        -TimeoutMarker "W1E_HARNESS_PYTEST_TIMEOUT" `
        -ArgumentList $PytestArguments
    Write-W1eCommandEvidence $PytestRun
    Write-Output ("W1E_STAGE_POSTGRES_TEST_EXIT={0}" -f $PytestRun.ExitCode)
    if ([int]$PytestRun.ExitCode -ne 0) {
        $PytestFailureKind = Get-W1eCommandFailureKind `
            -Result $PytestRun `
            -Context "Pytest"
        if ($PytestFailureKind -eq "Harness") {
            Write-W1eHarnessFailure "W1E_HARNESS_PYTEST_INFRA_FAILED" (
                "exit={0}" -f $PytestRun.ExitCode
            )
        }
        $ProductFailure = $true
        Write-W1eProductFailure "W1E_POSTGRES_PRODUCT_TEST_FAILED" (
            "exit={0}" -f $PytestRun.ExitCode
        )
    }
    $PassedSummaryMatches = [regex]::Matches(
        [string]$PytestRun.Stdout,
        "(?m)(?:^|\s)9 passed(?:\s+in\s+|,|$)"
    )
    Write-Output ("W1E_STAGE_POSTGRES_SUMMARY_MATCHES={0}" -f $PassedSummaryMatches.Count)
    if ($PassedSummaryMatches.Count -ne 1) {
        Write-W1eHarnessFailure "W1E_HARNESS_PYTEST_SUMMARY_UNOBSERVED" (
            "expected=1;actual={0}" -f $PassedSummaryMatches.Count
        )
    }
    $PytestStatusEvidence = (
        ([string]$PytestRun.Stdout) + "`n" + ([string]$PytestRun.Stderr)
    )
    if (
        $PytestStatusEvidence -match
        "(?m)(?:^|\s)\d+\s+(?:deselected|skipped|failed|errors?|xfailed|xpassed)\b"
    ) {
        Write-W1eHarnessFailure "W1E_HARNESS_PYTEST_SUMMARY_AMBIGUOUS"
    }
    $PassedNodeMatches = [regex]::Matches(
        [string]$PytestRun.Stdout,
        "(?m)^tests[\\/]test_w1e_postgres\.py::(?<name>test_[^\s\[]+)\s+PASSED(?:\s+\[[^\]\r\n]+\])?\s*$"
    )
    $ObservedPassedTests = @(
        $PassedNodeMatches |
            ForEach-Object { $_.Groups["name"].Value } |
            Sort-Object -Unique
    )
    $MissingPassedTests = @(
        $ExpectedW1eTests | Where-Object { $ObservedPassedTests -notcontains $_ }
    )
    $UnexpectedPassedTests = @(
        $ObservedPassedTests | Where-Object { $ExpectedW1eTests -notcontains $_ }
    )
    Write-Output (
        "W1E_STAGE_POSTGRES_NODE_IDS total={0} unique={1} missing={2} unexpected={3}" -f
        $PassedNodeMatches.Count,
        $ObservedPassedTests.Count,
        $MissingPassedTests.Count,
        $UnexpectedPassedTests.Count
    )
    if (
        $PassedNodeMatches.Count -ne 9 -or
        $ObservedPassedTests.Count -ne 9 -or
        $MissingPassedTests.Count -ne 0 -or
        $UnexpectedPassedTests.Count -ne 0
    ) {
        Write-W1eHarnessFailure "W1E_HARNESS_PYTEST_NODE_SET_MISMATCH" (
            "missing={0};unexpected={1}" -f
            ($MissingPassedTests -join ","),
            ($UnexpectedPassedTests -join ",")
        )
    }
    $AllProductStagesOk = $true
    Write-Output "W1E_POSTGRES_PRODUCT_GREEN tests=9"
}
catch {
    $ScriptExitCode = 1
    $FailureMessage = [string]$_.Exception.Message
    if ($FailureMessage -match "W1E_HARNESS_") {
        Write-Output ("W1E_WRAPPER_HARNESS_FAILURE: {0}" -f $FailureMessage)
    }
    elseif ($ProductFailure) {
        Write-Output ("W1E_WRAPPER_PRODUCT_FAILURE: {0}" -f $FailureMessage)
    }
    else {
        Write-Output ("W1E_WRAPPER_HARNESS_FAILURE: {0}" -f $FailureMessage)
    }
}
finally {
    if ($ClusterStarted) {
        try {
            $StopRun = Invoke-W1eTimedCommand `
                -FilePath $PgCtlExe `
                -TimeoutSec 60 `
                -TimeoutMarker "W1E_HARNESS_POSTGRES_STOP_TIMEOUT" `
                -ArgumentList @(
                    "--pgdata=$DataDirectory", "stop", "--mode=immediate", "--wait"
                )
            Write-Output ("W1E_STAGE_POSTGRES_STOP_EXIT={0}" -f $StopRun.ExitCode)
            if ([int]$StopRun.ExitCode -ne 0) {
                Write-W1eCommandEvidence $StopRun
                $CleanupHarnessFailure = $true
                Write-Output "W1E_HARNESS_POSTGRES_STOP_FAILED"
            }
        }
        catch {
            $CleanupHarnessFailure = $true
            Write-Output ("W1E_HARNESS_POSTGRES_STOP_FAILED: {0}" -f $_.Exception.Message)
        }
        $ClusterStarted = $false
        Start-Sleep -Seconds 2
    }

    try {
        $processSnapshot = Get-W1eProcessSnapshot
        $relatedProcesses = @(
            $processSnapshot | Where-Object {
                $_.Name -match '^(postgres|pg_ctl)\.exe$' -and
                $_.CommandLine -and
                $_.CommandLine.IndexOf(
                    $DataDirectory,
                    [StringComparison]::OrdinalIgnoreCase
                ) -ge 0
            }
        )
        foreach ($relatedProcess in $relatedProcesses) {
            try {
                Stop-Process -Id ([int]$relatedProcess.ProcessId) -Force -ErrorAction Stop
            }
            catch {
                $CleanupHarnessFailure = $true
                Write-Output (
                    "W1E_HARNESS_PG_CHILD_KILL_FAILED: pid={0}" -f
                    $relatedProcess.ProcessId
                )
            }
        }
    }
    catch {
        $CleanupHarnessFailure = $true
        Write-Output ("W1E_HARNESS_PROCESS_ENUM_FAILED: {0}" -f $_.Exception.Message)
    }
    Start-Sleep -Seconds 1

    try {
        $listenerSnapshot = Get-W1eListenerSnapshot
        $portListeners = @(
            $listenerSnapshot | Where-Object { [int]$_.LocalPort -eq [int]$Port }
        )
        $ListenerResidual = $portListeners.Count
    }
    catch {
        $CleanupHarnessFailure = $true
        $ListenerResidual = 1
        Write-Output ("W1E_HARNESS_LISTENER_ENUM_FAILED: {0}" -f $_.Exception.Message)
    }

    try {
        $verificationProcesses = Get-W1eProcessSnapshot
        $DataDirectoryWindows = $DataDirectory.Replace("/", "\").TrimEnd("\")
        $DataDirectoryPosix = $DataDirectory.Replace("\", "/").TrimEnd("/")
        $remainingProcesses = @(
            $verificationProcesses | Where-Object {
                Test-W1eResidualPostgresProcess `
                    -ProcessRow $_ `
                    -BaselineSet $BeforePostgresProcessSet `
                    -OwnedPathVariants @(
                        $DataDirectory,
                        $DataDirectoryWindows,
                        $DataDirectoryPosix
                    ) `
                    -OwnedPort $Port
            }
        )
        $ProcessResidual = $remainingProcesses.Count
    }
    catch {
        $CleanupHarnessFailure = $true
        $ProcessResidual = 1
        Write-Output ("W1E_HARNESS_PROCESS_ENUM_FAILED: {0}" -f $_.Exception.Message)
    }

    if (Test-Path -LiteralPath $ClusterRoot) {
        $ResolvedCleanup = [System.IO.Path]::GetFullPath($ClusterRoot)
        $ResolvedLeaf = Split-Path -Leaf $ResolvedCleanup
        if (
            -not $ResolvedCleanup.StartsWith(
                $ExpectedTempPrefix,
                [StringComparison]::OrdinalIgnoreCase
            ) -or
            -not $ResolvedLeaf.StartsWith(
                "sswcenter-w1e-pg-",
                [StringComparison]::Ordinal
            )
        ) {
            $CleanupHarnessFailure = $true
            Write-Output "W1E_HARNESS_UNSAFE_CLEANUP_PATH"
        }
        else {
            $removed = $false
            for ($attempt = 1; $attempt -le 3 -and -not $removed; $attempt++) {
                try {
                    [System.IO.Directory]::Delete($ResolvedCleanup, $true)
                    $removed = $true
                }
                catch {
                    Write-Output (
                        "W1E_HARNESS_CLEANUP_REMOVE_WARNING: attempt={0};detail={1}" -f
                        $attempt, $_.Exception.Message
                    )
                    Start-Sleep -Seconds (2 * $attempt)
                }
            }
            if (-not $removed) {
                $CleanupHarnessFailure = $true
                Write-Output "W1E_HARNESS_CLEANUP_REMOVE_RETRY_FAILED"
            }
        }
    }
    if (Test-Path -LiteralPath $ClusterRoot) {
        $TempResidual = 1
    }

    try {
        $AfterArtifacts = @(Get-W1eArtifactSnapshot)
        $NewArtifacts = @(
            $AfterArtifacts | Where-Object {
                -not $BeforeArtifactSet.ContainsKey([string]$_)
            }
        )
        $BackendPrefix = [System.IO.Path]::GetFullPath($BackendRoot).TrimEnd(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        ) + [System.IO.Path]::DirectorySeparatorChar
        $NewPycFiles = @(
            $NewArtifacts | Where-Object {
                ([System.IO.Path]::GetExtension([string]$_)) -eq ".pyc"
            }
        )
        foreach ($newPycFile in $NewPycFiles) {
            $resolvedPyc = [System.IO.Path]::GetFullPath([string]$newPycFile)
            if (
                $resolvedPyc.StartsWith(
                    $BackendPrefix,
                    [StringComparison]::OrdinalIgnoreCase
                ) -and
                (Test-Path -LiteralPath $resolvedPyc -PathType Leaf)
            ) {
                [System.IO.File]::Delete($resolvedPyc)
                $ArtifactRemovedCount++
            }
        }
        $NewCacheDirectories = @(
            $NewArtifacts |
                Where-Object {
                    $leaf = Split-Path -Leaf ([string]$_)
                    $leaf -in @("__pycache__", ".pytest_cache", ".ruff_cache")
                } |
                Sort-Object { ([string]$_).Length } -Descending
        )
        foreach ($newCacheDirectory in $NewCacheDirectories) {
            $resolvedCache = [System.IO.Path]::GetFullPath(
                [string]$newCacheDirectory
            )
            if (
                $resolvedCache.StartsWith(
                    $BackendPrefix,
                    [StringComparison]::OrdinalIgnoreCase
                ) -and
                (Test-Path -LiteralPath $resolvedCache -PathType Container)
            ) {
                [System.IO.Directory]::Delete($resolvedCache, $true)
                $ArtifactRemovedCount++
            }
        }
        $FinalArtifacts = @(Get-W1eArtifactSnapshot)
        $ArtifactResidual = @(
            $FinalArtifacts | Where-Object {
                -not $BeforeArtifactSet.ContainsKey([string]$_)
            }
        ).Count
    }
    catch {
        $CleanupHarnessFailure = $true
        $ArtifactResidual = 1
        Write-Output ("W1E_HARNESS_ARTIFACT_CLEANUP_FAILED: {0}" -f $_.Exception.Message)
    }

    try {
        $FinalHeadRun = Invoke-W1eTimedCommand `
            -FilePath $GitExe `
            -WorkingDirectory $WorkspaceRoot `
            -TimeoutSec 30 `
            -TimeoutMarker "W1E_HARNESS_FINAL_GIT_HEAD_TIMEOUT" `
            -ArgumentList @("rev-parse", "HEAD")
        $FinalStatusRun = Invoke-W1eTimedCommand `
            -FilePath $GitExe `
            -WorkingDirectory $WorkspaceRoot `
            -TimeoutSec 30 `
            -TimeoutMarker "W1E_HARNESS_FINAL_GIT_STATUS_TIMEOUT" `
            -ArgumentList @("status", "--porcelain=v1", "--untracked-files=all")
        if (
            [int]$FinalHeadRun.ExitCode -ne 0 -or
            [int]$FinalStatusRun.ExitCode -ne 0 -or
            ([string]$FinalHeadRun.Stdout).Trim().ToLowerInvariant() -ne $ExpectedSha -or
            -not [string]::IsNullOrWhiteSpace(([string]$FinalStatusRun.Stdout).Trim())
        ) {
            $GitResidual = 1
            $CleanupHarnessFailure = $true
            Write-Output "W1E_HARNESS_FINAL_GIT_STATE_MISMATCH"
        }
    }
    catch {
        $GitResidual = 1
        $CleanupHarnessFailure = $true
        Write-Output ("W1E_HARNESS_FINAL_GIT_CHECK_FAILED: {0}" -f $_.Exception.Message)
    }

    Write-Output (
        "W1E_CLEANUP listener={0} process={1} temp={2} artifact={3} git={4} artifact_removed={5}" -f
        $ListenerResidual,
        $ProcessResidual,
        $TempResidual,
        $ArtifactResidual,
        $GitResidual,
        $ArtifactRemovedCount
    )
    if (
        $ListenerResidual -gt 0 -or
        $ProcessResidual -gt 0 -or
        $TempResidual -gt 0 -or
        $ArtifactResidual -gt 0 -or
        $GitResidual -gt 0
    ) {
        $CleanupHarnessFailure = $true
        Write-Output "W1E_HARNESS_CLEANUP_RESIDUAL_NONZERO"
    }
}

if (
    $AllProductStagesOk -and
    -not $ProductFailure -and
    -not $CleanupHarnessFailure -and
    $ListenerResidual -eq 0 -and
    $ProcessResidual -eq 0 -and
    $TempResidual -eq 0 -and
    $ArtifactResidual -eq 0 -and
    $GitResidual -eq 0 -and
    $ScriptExitCode -eq 0
) {
    Write-Output "W1E_POSTGRES_GREEN"
}
else {
    $ScriptExitCode = 1
    if ($CleanupHarnessFailure) {
        Write-Output "W1E_WRAPPER_HARNESS_FAILURE: W1E_HARNESS_CLEANUP_GATE"
    }
}

if ($ScriptExitCode -ne 0) {
    exit $ScriptExitCode
}
