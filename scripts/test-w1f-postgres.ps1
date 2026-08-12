param(
    # Bind omissions so the preflight emits a stable harness marker before mutable work.
    [string]$ExpectedSha = "",
    [int]$Port = 55444
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
$W1cHead = "20260730_0010_w1c_certification_ledgers"
$W1dHead = "20260730_0011_w1d_recipient_contract"
$W1eHead = "20260801_0012_w1e_care_assignment"
$ContinuingEducationHead = "20260802_0013_staff_continuing_education"
$RecipientPlanNotificationHead = "20260803_0014_recipient_plan_notification"
$CurrentHead = "20260808_0017_recipient_guardian_email"

function Write-W1fHarnessFailure {
    param([string]$Marker, [string]$Detail = "")
    if ([string]::IsNullOrWhiteSpace($Detail)) {
        Write-Output $Marker
    }
    else {
        Write-Output ("{0}: {1}" -f $Marker, $Detail)
    }
    throw $Marker
}

function Write-W1fProductFailure {
    param([string]$Marker, [string]$Detail = "")
    if ([string]::IsNullOrWhiteSpace($Detail)) {
        Write-Output $Marker
    }
    else {
        Write-Output ("{0}: {1}" -f $Marker, $Detail)
    }
    $script:ProductFailure = $true
    throw $Marker
}

function Get-W1fProcessSnapshot {
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
        Write-W1fHarnessFailure `
            "W1F_HARNESS_PROCESS_ENUM_FAILED" `
            ([string]$_.Exception.Message)
    }
}

function Get-W1fListenerSnapshot {
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
        $listenerRun = Invoke-W1fTimedCommand `
            -FilePath $PowerShellExe `
            -TimeoutSec 20 `
            -TimeoutMarker "W1F_HARNESS_LISTENER_ENUM_TIMEOUT" `
            -ArgumentList @(
                "-NoProfile", "-NonInteractive", "-EncodedCommand", $encodedProbe
            )
        if ([int]$listenerRun.ExitCode -ne 0) {
            Write-W1fCommandEvidence $listenerRun
            Write-W1fHarnessFailure "W1F_HARNESS_LISTENER_ENUM_FAILED" (
                "exit={0}" -f $listenerRun.ExitCode
            )
        }
        $payload = ([string]$listenerRun.Stdout).Trim() | ConvertFrom-Json
        return $payload.Rows
    }
    catch {
        $message = [string]$_.Exception.Message
        if ($message -match "W1F_HARNESS_") {
            throw
        }
        Write-W1fHarnessFailure "W1F_HARNESS_LISTENER_ENUM_FAILED" $message
    }
}

function Get-W1fProcessIdentity {
    param([Parameter(Mandatory = $true)]$ProcessRow)
    if (
        $null -eq $ProcessRow.ProcessId -or
        $null -eq $ProcessRow.CreationDate -or
        [string]::IsNullOrWhiteSpace([string]$ProcessRow.CreationDate)
    ) {
        Write-W1fHarnessFailure "W1F_HARNESS_PROCESS_IDENTITY_INCOMPLETE" (
            "name={0};pid={1}" -f $ProcessRow.Name, $ProcessRow.ProcessId
        )
    }
    return ("{0}|{1}" -f [int]$ProcessRow.ProcessId, [string]$ProcessRow.CreationDate)
}

function Test-W1fResidualPostgresProcess {
    param(
        [Parameter(Mandatory = $true)]$ProcessRow,
        [Parameter(Mandatory = $true)][hashtable]$BaselineSet,
        [Parameter(Mandatory = $true)][string[]]$OwnedPathVariants,
        [Parameter(Mandatory = $true)][int]$OwnedPort
    )
    if ($ProcessRow.Name -notmatch '^(postgres|pg_ctl)\.exe$') {
        return $false
    }
    $identity = Get-W1fProcessIdentity $ProcessRow
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

function Get-W1fDescendantPids {
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

function Stop-W1fProcessTreeFailClosed {
    param(
        [Parameter(Mandatory = $true)][int]$RootPid,
        [string]$Context = "child"
    )
    $snapshot = Get-W1fProcessSnapshot
    $descendants = @(
        Get-W1fDescendantPids -RootPid $RootPid -Snapshot $snapshot
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
    $verificationSnapshot = Get-W1fProcessSnapshot
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
        Write-W1fHarnessFailure "W1F_HARNESS_PROCESS_TREE_RESIDUAL" (
            "context={0};pids={1}" -f $Context, ($residualPids -join ",")
        )
    }
}

function ConvertTo-W1fProcessArgument {
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

function ConvertTo-W1fProcessArguments {
    param([string[]]$ArgumentList = @())
    return (@(
        $ArgumentList | ForEach-Object {
            ConvertTo-W1fProcessArgument ([string]$_)
        }
    ) -join " ")
}

function Invoke-W1fTimedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = "",
        [int]$TimeoutSec = 600,
        [string]$TimeoutMarker = "W1F_HARNESS_CHILD_TIMEOUT"
    )
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = ConvertTo-W1fProcessArguments $ArgumentList
    if (-not [string]::IsNullOrWhiteSpace($WorkingDirectory)) {
        $startInfo.WorkingDirectory = $WorkingDirectory
    }
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    $startInfo.StandardOutputEncoding = $utf8NoBom
    $startInfo.StandardErrorEncoding = $utf8NoBom
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $drainTasks = [System.Threading.Tasks.Task[]]@($stdoutTask, $stderrTask)
    if (-not $process.WaitForExit($TimeoutSec * 1000)) {
        Stop-W1fProcessTreeFailClosed `
            -RootPid ([int]$process.Id) `
            -Context $TimeoutMarker
        try {
            [void][System.Threading.Tasks.Task]::WaitAll($drainTasks, 5000)
        }
        catch {
            Write-W1fHarnessFailure "W1F_HARNESS_STREAM_READ_FAILED" (
                [string]$_.Exception.Message
            )
        }
        Write-W1fHarnessFailure $TimeoutMarker ("timeoutSec={0}" -f $TimeoutSec)
    }
    try {
        $streamsDrained = [System.Threading.Tasks.Task]::WaitAll($drainTasks, 5000)
    }
    catch {
        Write-W1fHarnessFailure "W1F_HARNESS_STREAM_READ_FAILED" (
            [string]$_.Exception.Message
        )
    }
    if (-not $streamsDrained) {
        Stop-W1fProcessTreeFailClosed `
            -RootPid ([int]$process.Id) `
            -Context "W1F_HARNESS_STREAM_DRAIN_TIMEOUT"
        try {
            $streamsDrained = [System.Threading.Tasks.Task]::WaitAll(
                $drainTasks,
                5000
            )
        }
        catch {
            Write-W1fHarnessFailure "W1F_HARNESS_STREAM_READ_FAILED" (
                [string]$_.Exception.Message
            )
        }
        if (-not $streamsDrained) {
            Write-W1fHarnessFailure "W1F_HARNESS_STREAM_DRAIN_TIMEOUT"
        }
    }
    try {
        $stdout = [string]$stdoutTask.GetAwaiter().GetResult()
        $stderr = [string]$stderrTask.GetAwaiter().GetResult()
    }
    catch {
        Write-W1fHarnessFailure "W1F_HARNESS_STREAM_READ_FAILED" (
            [string]$_.Exception.Message
        )
    }
    $result = New-Object psobject -Property @{
        ExitCode = [int]$process.ExitCode
        Stdout   = $stdout
        Stderr   = $stderr
    }
    $process.Dispose()
    return ,$result
}

function Invoke-W1fDetachedPgCtlStart {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [int]$TimeoutSec = 60
    )
    try {
        $process = Start-Process `
            -FilePath $FilePath `
            -ArgumentList (ConvertTo-W1fProcessArguments $ArgumentList) `
            -WorkingDirectory $WorkingDirectory `
            -PassThru `
            -WindowStyle Hidden
    }
    catch {
        Write-W1fHarnessFailure "W1F_HARNESS_POSTGRES_START_LAUNCH_FAILED" (
            [string]$_.Exception.Message
        )
    }
    if (-not $process.WaitForExit($TimeoutSec * 1000)) {
        Stop-W1fProcessTreeFailClosed `
            -RootPid ([int]$process.Id) `
            -Context "W1F_HARNESS_POSTGRES_START_TIMEOUT"
        Write-W1fHarnessFailure "W1F_HARNESS_POSTGRES_START_TIMEOUT" (
            "timeoutSec={0}" -f $TimeoutSec
        )
    }
    return ,(New-Object psobject -Property @{
            ExitCode  = [int]$process.ExitCode
            Stdout    = ""
            Stderr    = ""
            Transport = "detached-hidden"
        })
}

function Write-W1fCommandEvidence {
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

function Get-W1fArtifactSnapshot {
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

function Invoke-W1fPsqlScalar {
    param(
        [Parameter(Mandatory = $true)][string]$User,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Sql,
        [Parameter(Mandatory = $true)][string]$Marker
    )
    $run = Invoke-W1fTimedCommand `
        -FilePath $PsqlExe `
        -TimeoutSec 60 `
        -TimeoutMarker ($Marker + "_TIMEOUT") `
        -ArgumentList @(
            "-X", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1",
            "-p", [string]$Port, "-U", $User, "-d", $Database, "-tAc", $Sql
        )
    if ([int]$run.ExitCode -ne 0) {
        Write-W1fCommandEvidence $run
        Write-W1fHarnessFailure $Marker ("exit={0}" -f $run.ExitCode)
    }
    return ([string]$run.Stdout).Trim()
}

function Invoke-W1fAlembic {
    param(
        [Parameter(Mandatory = $true)][string[]]$AlembicArgs,
        [Parameter(Mandatory = $true)][string]$Marker,
        [int]$TimeoutSec = 600
    )
    $run = Invoke-W1fTimedCommand `
        -FilePath $PythonExe `
        -WorkingDirectory $BackendRoot `
        -TimeoutSec $TimeoutSec `
        -TimeoutMarker ($Marker + "_TIMEOUT") `
        -ArgumentList (@("-m", "alembic", "-c", "alembic.ini") + $AlembicArgs)
    if ([int]$run.ExitCode -ne 0) {
        Write-W1fCommandEvidence $run
        Write-W1fHarnessFailure $Marker ("exit={0}" -f $run.ExitCode)
    }
    return $run
}

function Get-W1fRevision {
    param([Parameter(Mandatory = $true)][string]$Database)
    return Invoke-W1fPsqlScalar `
        -User "erp_owner" `
        -Database $Database `
        -Sql "SELECT version_num FROM erp.alembic_version" `
        -Marker "W1F_HARNESS_REVISION_QUERY_FAILED"
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
        Write-W1fHarnessFailure "W1F_HARNESS_MISSING_EXECUTABLE" $executable
    }
}

if ($ExpectedSha -notmatch '^[0-9a-fA-F]{40}$') {
    Write-W1fHarnessFailure "W1F_HARNESS_EXPECTED_SHA_INVALID" $ExpectedSha
}
$ExpectedSha = $ExpectedSha.ToLowerInvariant()

$GitRootRun = Invoke-W1fTimedCommand `
    -FilePath $GitExe `
    -WorkingDirectory $WorkspaceRoot `
    -TimeoutSec 30 `
    -TimeoutMarker "W1F_HARNESS_GIT_ROOT_TIMEOUT" `
    -ArgumentList @("rev-parse", "--show-toplevel")
if ([int]$GitRootRun.ExitCode -ne 0) {
    Write-W1fCommandEvidence $GitRootRun
    Write-W1fHarnessFailure "W1F_HARNESS_GIT_ROOT_FAILED"
}
$ObservedGitRoot = [System.IO.Path]::GetFullPath(
    ([string]$GitRootRun.Stdout).Trim()
)
if (-not $ObservedGitRoot.Equals($WorkspaceRoot, [StringComparison]::OrdinalIgnoreCase)) {
    Write-W1fHarnessFailure "W1F_HARNESS_GIT_ROOT_MISMATCH" (
        "expected={0};actual={1}" -f $WorkspaceRoot, $ObservedGitRoot
    )
}

$HeadRun = Invoke-W1fTimedCommand `
    -FilePath $GitExe `
    -WorkingDirectory $WorkspaceRoot `
    -TimeoutSec 30 `
    -TimeoutMarker "W1F_HARNESS_GIT_HEAD_TIMEOUT" `
    -ArgumentList @("rev-parse", "HEAD")
if ([int]$HeadRun.ExitCode -ne 0) {
    Write-W1fCommandEvidence $HeadRun
    Write-W1fHarnessFailure "W1F_HARNESS_GIT_HEAD_FAILED"
}
$ObservedSha = ([string]$HeadRun.Stdout).Trim().ToLowerInvariant()
if ($ObservedSha -ne $ExpectedSha) {
    Write-W1fHarnessFailure "W1F_HARNESS_EXACT_SHA_MISMATCH" (
        "expected={0};actual={1}" -f $ExpectedSha, $ObservedSha
    )
}

$GitStatusRun = Invoke-W1fTimedCommand `
    -FilePath $GitExe `
    -WorkingDirectory $WorkspaceRoot `
    -TimeoutSec 30 `
    -TimeoutMarker "W1F_HARNESS_GIT_STATUS_TIMEOUT" `
    -ArgumentList @("status", "--porcelain=v1", "--untracked-files=all")
if ([int]$GitStatusRun.ExitCode -ne 0) {
    Write-W1fCommandEvidence $GitStatusRun
    Write-W1fHarnessFailure "W1F_HARNESS_GIT_STATUS_FAILED"
}
$InitialGitStatus = ([string]$GitStatusRun.Stdout).Trim()
if (-not [string]::IsNullOrWhiteSpace($InitialGitStatus)) {
    Write-W1fHarnessFailure "W1F_HARNESS_GIT_NOT_CLEAN" $InitialGitStatus
}
Write-Output ("W1F_EXACT_SHA_OK={0}" -f $ObservedSha)

$PreflightListeners = Get-W1fListenerSnapshot
$PortUsers = @(
    $PreflightListeners | Where-Object { [int]$_.LocalPort -eq [int]$Port }
)
if ($PortUsers.Count -gt 0) {
    Write-W1fHarnessFailure "W1F_HARNESS_PORT_IN_USE" ([string]$Port)
}

$PreflightProcesses = Get-W1fProcessSnapshot
$BeforePostgresProcessSet = @{}
foreach ($preflightProcess in @(
    $PreflightProcesses |
        Where-Object { $_.Name -match '^(postgres|pg_ctl)\.exe$' }
)) {
    $processIdentity = Get-W1fProcessIdentity $preflightProcess
    $BeforePostgresProcessSet[$processIdentity] = $true
}
Write-Output (
    "W1F_PREFLIGHT_POSTGRES_PROCESS_BASELINE={0}" -f
    $BeforePostgresProcessSet.Count
)

$BeforeArtifacts = @(Get-W1fArtifactSnapshot)
$BeforeArtifactSet = @{}
foreach ($artifactPath in $BeforeArtifacts) {
    $BeforeArtifactSet[[string]$artifactPath] = $true
}

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    Write-W1fHarnessFailure "W1F_HARNESS_LOCALAPPDATA_MISSING"
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
    Write-W1fHarnessFailure "W1F_HARNESS_USER_TEMP_UNAVAILABLE" $TempParent
}
$env:TEMP = $TempParent
$env:TMP = $TempParent
$env:TMPDIR = $TempParent
Write-Output ("W1F_USER_TEMP_OK={0}" -f $TempParent)
$ClusterRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $TempParent ("sswcenter-w1f-pg-" + [Guid]::NewGuid().ToString("N")))
)
$ExpectedTempPrefix = $TempParent + [System.IO.Path]::DirectorySeparatorChar
$ClusterLeaf = Split-Path -Leaf $ClusterRoot
if (
    -not $ClusterRoot.StartsWith(
        $ExpectedTempPrefix,
        [StringComparison]::OrdinalIgnoreCase
    ) -or
    -not $ClusterLeaf.StartsWith("sswcenter-w1f-pg-", [StringComparison]::Ordinal)
) {
    Write-W1fHarnessFailure "W1F_HARNESS_UNSAFE_TEMP_PATH" $ClusterRoot
}

$DataDirectory = Join-Path $ClusterRoot "data"
$RuntimeDataRoot = Join-Path $ClusterRoot "sswcenter-w1f-runtime"
$BackupRoot = Join-Path $ClusterRoot "sswcenter-w1f-backups"
$ReviewDataRoot = Join-Path $ClusterRoot "sswcenter-restore-review-w1f"
$OfflineSqlFile = Join-Path $ClusterRoot "w1f-offline.sql"
$SeedSqlFile = Join-Path $ClusterRoot "w1f-seed.sql"
$LogFile = Join-Path $ClusterRoot "postgres.log"
$DatabaseName = "sswcenter_w1f_review"
$OfflineDatabaseName = "sswcenter_w1f_offline"
$RestoreReviewDatabaseName = "sswcenter_w1f_restore_review"
$OwnerPassword = "w1f_owner_pw"
$AppPassword = "w1f_app_pw"
$BackupPassword = "w1f_backup_pw"
$OwnerDatabaseUrl = "postgresql+psycopg://erp_owner:$OwnerPassword@127.0.0.1:$Port/$DatabaseName"
$AdminDatabaseUrl = "postgresql+psycopg://postgres@127.0.0.1:$Port/postgres"
$ClusterStarted = $false
$ProductFailure = $false
$AllProductStagesOk = $false
$CleanupHarnessFailure = $false
$ScriptExitCode = 0
$ListenerResidual = 0
$ProcessResidual = 0
$TempResidual = 0
$ArtifactResidual = 0
$GitResidual = 0

$SeedSql = @'
DO $$
DECLARE
    account_staff_id bigint;
    account_id bigint;
    care_staff_id bigint;
    employment_id bigint;
    home_care_service_id bigint;
    care_worker_license_type_id bigint;
    social_worker_license_type_id bigint;
    nurse_license_type_id bigint;
    source_license_id bigint;
    recipient_id bigint;
    guardian_id bigint;
    contract_id bigint;
    seq bigint;
BEGIN
    SET CONSTRAINTS ALL DEFERRED;

    SELECT id INTO home_care_service_id
    FROM erp.service_type WHERE code = 'HOME_CARE' AND active IS TRUE;
    SELECT id INTO care_worker_license_type_id
    FROM erp.license_type WHERE code = 'CARE_WORKER';
    SELECT id INTO social_worker_license_type_id
    FROM erp.license_type WHERE code = 'SOCIAL_WORKER';
    SELECT id INTO nurse_license_type_id
    FROM erp.license_type WHERE code = 'NURSE';

    INSERT INTO erp.staff (name, birth_date, sex_code, display_name, memo, row_version)
    VALUES ('W1F ACCOUNT STAFF', DATE '1990-01-01', 'TEST',
            'W1F ACCOUNT DISPLAY', 'W1F ACCOUNT MEMO', 1)
    RETURNING id INTO account_staff_id;

    INSERT INTO erp.user_account
        (staff_id, account_code, display_name, role_code,
         pin_hash, pin_lookup_hmac, pin_key_version, row_version)
    VALUES (account_staff_id, 'W1F_ADMIN', 'W1F ADMIN', 'ADMIN',
            'w1f-synthetic-hash-not-for-login',
            decode(repeat('01', 32), 'hex'), 1, 1)
    RETURNING id INTO account_id;

    INSERT INTO erp.staff (name, birth_date, sex_code, display_name, memo, row_version)
    VALUES ('W1F CARE STAFF', DATE '1990-01-01', 'TEST',
            'W1F CARE DISPLAY', 'W1F CARE MEMO', 1)
    RETURNING id INTO care_staff_id;

    SELECT COALESCE(MAX(staff_no_sequence), 0) + 1 INTO seq FROM erp.staff_employment;
    INSERT INTO erp.staff_employment
        (staff_id, employment_no, staff_no, staff_no_year, staff_no_sequence,
         start_date, end_date, created_by_account_id, updated_by_account_id, row_version)
    VALUES (care_staff_id, 1, 'W1F-CARE', 2099, seq,
            DATE '2030-01-01', DATE '2030-12-31', account_id, account_id, 1)
    RETURNING id INTO employment_id;

    INSERT INTO erp.staff_position_period
        (staff_id, employment_id, position_code, start_date, end_date,
         invalidated_at_utc, replacement_id,
         created_by_account_id, updated_by_account_id, row_version)
    VALUES (care_staff_id, employment_id, 'CARE_WORKER',
            DATE '2030-01-01', DATE '2030-12-31', NULL, NULL,
            account_id, account_id, 1);

    INSERT INTO erp.staff_license
        (staff_id, license_type_id, license_number, issued_date,
         invalidated_at_utc, replacement_license_id,
         created_by_account_id, updated_by_account_id, row_version)
    VALUES (care_staff_id, care_worker_license_type_id, 'W1F-CARE-0001',
            DATE '2026-01-01', NULL, NULL, account_id, account_id, 1)
    RETURNING id INTO source_license_id;
    INSERT INTO erp.staff_license
        (staff_id, license_type_id, license_number, issued_date,
         invalidated_at_utc, replacement_license_id,
         created_by_account_id, updated_by_account_id, row_version)
    VALUES (care_staff_id, social_worker_license_type_id, 'W1F-SOCIAL-0001',
            DATE '2026-01-01', NULL, NULL, account_id, account_id, 1);
    INSERT INTO erp.staff_license
        (staff_id, license_type_id, license_number, issued_date,
         invalidated_at_utc, replacement_license_id,
         created_by_account_id, updated_by_account_id, row_version)
    VALUES (care_staff_id, nurse_license_type_id, 'W1F-NURSE-0001',
            DATE '2026-01-01', NULL, NULL, account_id, account_id, 1);

    INSERT INTO erp.staff_service_qualification_period
        (staff_id, employment_id, service_type_id, start_date, end_date,
         source_license_id, created_by_account_id, updated_by_account_id, row_version)
    VALUES (care_staff_id, employment_id, home_care_service_id,
            DATE '2030-01-01', DATE '2030-12-31', source_license_id,
            account_id, account_id, 1);

    INSERT INTO erp.staff_onboarding_training
        (staff_id, employment_id, course_code, completed,
         created_by_account_id, updated_by_account_id, row_version)
    VALUES (care_staff_id, employment_id, 'NEW_HIRE_ORIENTATION', TRUE,
            account_id, account_id, 1);

    -- 0013 continuing-education fact (catalog course is migration-seeded).
    INSERT INTO erp.staff_periodic_training_status
        (staff_id, course_code, period_key, completed,
         created_by_account_id, updated_by_account_id, row_version)
    VALUES (care_staff_id, 'CONTINUING_EDUCATION', '2026', TRUE,
            account_id, account_id, 1);

    -- recipient_status is the 0015 manual tag; full-row to_jsonb includes it.
    INSERT INTO erp.recipient
        (name, birth_date, sex_code, recipient_status,
         created_by_account_id, updated_by_account_id, row_version)
    VALUES ('W1F RECIPIENT', DATE '1950-01-01', 'TEST', 'ACTIVE',
            account_id, account_id, 1)
    RETURNING id INTO recipient_id;

    -- 0016/0017 guardian: payer_guardian_id composite FK + guardian.email column.
    INSERT INTO erp.recipient_guardian
        (recipient_id, name, phone, address, relationship_text, email,
         created_by_account_id, updated_by_account_id, row_version)
    VALUES (recipient_id, 'W1F GUARDIAN', '010-0000-0000', 'W1F ADDRESS',
            'PARENT', 'w1f-guardian@example.test',
            account_id, account_id, 1)
    RETURNING id INTO guardian_id;

    UPDATE erp.recipient SET payer_guardian_id = guardian_id
    WHERE id = recipient_id;

    INSERT INTO erp.recipient_contract
        (recipient_id, service_type_id, start_date, end_date,
         invalidated_at_utc, replacement_contract_id,
         created_by_account_id, updated_by_account_id, row_version)
    VALUES (recipient_id, home_care_service_id,
            DATE '2030-01-01', DATE '2030-12-31', NULL, NULL,
            account_id, account_id, 1)
    RETURNING id INTO contract_id;

    INSERT INTO erp.care_assignment
        (recipient_contract_id, staff_id, employment_id, assignment_kind,
         family_relationship_text, start_date, end_date, invalidated_at_utc,
         replacement_assignment_id, created_by_account_id,
         updated_by_account_id, row_version)
    VALUES (contract_id, care_staff_id, employment_id, 'GENERAL', NULL,
            DATE '2030-01-01', DATE '2030-12-31', NULL, NULL,
            account_id, account_id, 1);

    -- 0014 recipient plan-notification fact.
    INSERT INTO erp.recipient_plan_notification
        (recipient_id, notified_date,
         created_by_account_id, updated_by_account_id, row_version)
    VALUES (recipient_id, DATE '2026-06-01',
            account_id, account_id, 1);
END $$;
'@

# Canonical count/value hash over every column of every table seeded above. The
# same query runs before backup and after restore so a missing row or any field
# mutation in the recovered database changes the count/hash evidence.
$CanonicalSql = @'
WITH rows AS (
    SELECT 'staff:' || to_jsonb(s)::text AS line
    FROM erp.staff AS s
    UNION ALL
    SELECT 'user_account:' || to_jsonb(ua)::text AS line
    FROM erp.user_account AS ua
    UNION ALL
    SELECT 'staff_employment:' || to_jsonb(se)::text AS line
    FROM erp.staff_employment AS se
    UNION ALL
    SELECT 'staff_position_period:' || to_jsonb(spp)::text AS line
    FROM erp.staff_position_period AS spp
    UNION ALL
    SELECT 'staff_license:' || to_jsonb(sl)::text AS line
    FROM erp.staff_license AS sl
    UNION ALL
    SELECT 'staff_service_qualification_period:' || to_jsonb(ssqp)::text AS line
    FROM erp.staff_service_qualification_period AS ssqp
    UNION ALL
    SELECT 'staff_onboarding_training:' || to_jsonb(sot)::text AS line
    FROM erp.staff_onboarding_training AS sot
    UNION ALL
    SELECT 'staff_periodic_training_status:' || to_jsonb(spts)::text AS line
    FROM erp.staff_periodic_training_status AS spts
    UNION ALL
    SELECT 'recipient:' || to_jsonb(r)::text AS line
    FROM erp.recipient AS r
    UNION ALL
    SELECT 'recipient_guardian:' || to_jsonb(rg)::text AS line
    FROM erp.recipient_guardian AS rg
    UNION ALL
    SELECT 'recipient_contract:' || to_jsonb(rc)::text AS line
    FROM erp.recipient_contract AS rc
    UNION ALL
    SELECT 'care_assignment:' || to_jsonb(ca)::text AS line
    FROM erp.care_assignment AS ca
    UNION ALL
    SELECT 'recipient_plan_notification:' || to_jsonb(rpn)::text AS line
    FROM erp.recipient_plan_notification AS rpn
)
SELECT count(*)::text || '|' ||
       md5(COALESCE(string_agg(line, chr(10) ORDER BY line), '<EMPTY>'))
FROM rows;
'@

try {
    New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $RuntimeDataRoot -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $RuntimeDataRoot "blobs") -Force | Out-Null

    $InitRun = Invoke-W1fTimedCommand `
        -FilePath $InitDbExe `
        -TimeoutSec 120 `
        -TimeoutMarker "W1F_HARNESS_INITDB_TIMEOUT" `
        -ArgumentList @(
            "--pgdata=$DataDirectory", "--username=postgres", "--auth=trust",
            "--encoding=UTF8", "--locale=C"
        )
    Write-Output ("W1F_STAGE_INITDB_EXIT={0}" -f $InitRun.ExitCode)
    if ([int]$InitRun.ExitCode -ne 0) {
        Write-W1fCommandEvidence $InitRun
        Write-W1fHarnessFailure "W1F_HARNESS_INITDB_FAILED"
    }

    $StartRun = Invoke-W1fDetachedPgCtlStart `
        -FilePath $PgCtlExe `
        -WorkingDirectory $WorkspaceRoot `
        -TimeoutSec 60 `
        -ArgumentList @(
            "--pgdata=$DataDirectory", "--log=$LogFile",
            "--options=-h 127.0.0.1 -p $Port", "start", "--wait"
        )
    Write-Output ("W1F_STAGE_POSTGRES_START_EXIT={0}" -f $StartRun.ExitCode)
    if ([int]$StartRun.ExitCode -ne 0) {
        Write-W1fCommandEvidence $StartRun
        Write-W1fHarnessFailure "W1F_HARNESS_POSTGRES_START_FAILED"
    }
    $ClusterStarted = $true

    $ReadyRun = Invoke-W1fTimedCommand `
        -FilePath $PgIsReadyExe `
        -TimeoutSec 30 `
        -TimeoutMarker "W1F_HARNESS_POSTGRES_READY_TIMEOUT" `
        -ArgumentList @(
            "-h", "127.0.0.1", "-p", [string]$Port,
            "-U", "postgres", "-d", "postgres", "-t", "15"
        )
    Write-Output ("W1F_STAGE_POSTGRES_READY_EXIT={0}" -f $ReadyRun.ExitCode)
    if ([int]$ReadyRun.ExitCode -ne 0) {
        Write-W1fCommandEvidence $ReadyRun
        Write-W1fHarnessFailure "W1F_HARNESS_POSTGRES_NOT_READY"
    }

    $RoleSql = (
        "CREATE ROLE erp_owner LOGIN PASSWORD '$OwnerPassword'; " +
        "CREATE ROLE erp_app LOGIN PASSWORD '$AppPassword'; " +
        "CREATE ROLE erp_backup LOGIN PASSWORD '$BackupPassword';"
    )
    $RoleRun = Invoke-W1fTimedCommand `
        -FilePath $PsqlExe `
        -TimeoutSec 30 `
        -TimeoutMarker "W1F_HARNESS_ROLE_CREATE_TIMEOUT" `
        -ArgumentList @(
            "-X", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1",
            "-p", [string]$Port, "-U", "postgres", "-d", "postgres",
            "-c", $RoleSql
        )
    Write-Output ("W1F_STAGE_ROLE_CREATE_EXIT={0}" -f $RoleRun.ExitCode)
    if ([int]$RoleRun.ExitCode -ne 0) {
        Write-W1fCommandEvidence $RoleRun
        Write-W1fHarnessFailure "W1F_HARNESS_ROLE_CREATE_FAILED"
    }

    foreach ($newDatabase in @($DatabaseName, $OfflineDatabaseName)) {
        $CreateDatabaseRun = Invoke-W1fTimedCommand `
            -FilePath $CreateDbExe `
            -TimeoutSec 30 `
            -TimeoutMarker "W1F_HARNESS_DATABASE_CREATE_TIMEOUT" `
            -ArgumentList @(
                "-h", "127.0.0.1", "-p", [string]$Port,
                "-U", "postgres", "-O", "erp_owner", $newDatabase
            )
        if ([int]$CreateDatabaseRun.ExitCode -ne 0) {
            Write-W1fCommandEvidence $CreateDatabaseRun
            Write-W1fHarnessFailure "W1F_HARNESS_DATABASE_CREATE_FAILED" $newDatabase
        }
    }
    Write-Output "W1F_STAGE_DATABASE_CREATE_EXIT=0"

    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
    $env:SSWCENTER_OWNER_DATABASE_URL = $OwnerDatabaseUrl
    $env:SSWCENTER_APP_DATABASE_URL = (
        "postgresql+psycopg://erp_app:$AppPassword@127.0.0.1:$Port/$DatabaseName"
    )
    $env:SSWCENTER_BACKUP_DATABASE_URL = (
        "postgresql+psycopg://erp_backup:$BackupPassword@127.0.0.1:$Port/$DatabaseName"
    )
    $env:SSWCENTER_DATA_ROOT = $RuntimeDataRoot
    $env:SSWCENTER_PIN_PEPPER = "w1f-test-pin-pepper"
    $env:SSWCENTER_PIN_LOOKUP_KEY = "w1f-test-pin-lookup"
    $env:SSWCENTER_CSRF_SIGNING_KEY = "w1f-test-csrf"
    $env:SSWCENTER_RESIDENT_NUMBER_KEY_V1 = (
        "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
    )
    $env:SSWCENTER_RESIDENT_NUMBER_LOOKUP_KEY = (
        "YWJjZGVmMDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODk="
    )
    $env:SSWCENTER_RESIDENT_NUMBER_ACTIVE_KEY_VERSION = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTEST_ADDOPTS = ""

    # Fresh base -> current head (0015) upgrade of the primary review database.
    [void](Invoke-W1fAlembic -AlembicArgs @("upgrade", $CurrentHead) -Marker "W1F_HARNESS_BASE_UPGRADE_FAILED")
    $HeadRevision = Get-W1fRevision -Database $DatabaseName
    Write-Output ("W1F_STAGE_HEAD_REVISION={0}" -f $HeadRevision)
    if ($HeadRevision -ne $CurrentHead) {
        Write-W1fHarnessFailure "W1F_HARNESS_HEAD_REVISION_MISMATCH" (
            "expected={0};actual={1}" -f $CurrentHead, $HeadRevision
        )
    }

    # W1D boundary downgrade and observation of the W1D postcheck marker.
    [void](Invoke-W1fAlembic -AlembicArgs @("downgrade", $W1dHead) -Marker "W1F_HARNESS_DOWNGRADE_FAILED")
    $DowngradeRevision = Get-W1fRevision -Database $DatabaseName
    if ($DowngradeRevision -ne $W1dHead) {
        Write-W1fProductFailure "W1F_MIGRATION_DOWNGRADE_REVISION_MISMATCH" (
            "expected={0};actual={1}" -f $W1dHead, $DowngradeRevision
        )
    }
    $AssignmentAbsent = Invoke-W1fPsqlScalar `
        -User "erp_owner" -Database $DatabaseName `
        -Sql "SELECT to_regclass('erp.care_assignment') IS NULL" `
        -Marker "W1F_HARNESS_DOWNGRADE_TABLE_QUERY_FAILED"
    if ($AssignmentAbsent -ne "t") {
        Write-W1fProductFailure "W1F_MIGRATION_DOWNGRADE_TABLE_RESIDUAL"
    }
    $W1dPostcheckRun = Invoke-W1fTimedCommand `
        -FilePath $PowerShellExe `
        -TimeoutSec 120 `
        -TimeoutMarker "W1F_HARNESS_W1D_POSTCHECK_TIMEOUT" `
        -ArgumentList @(
            "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", (Join-Path $PSScriptRoot "verify-w1a-vs1-db.ps1"),
            "-DatabaseUrl", $OwnerDatabaseUrl
        )
    Write-W1fCommandEvidence $W1dPostcheckRun
    if (
        [int]$W1dPostcheckRun.ExitCode -ne 0 -or
        ([string]$W1dPostcheckRun.Stdout) -notmatch "W1D_DB_POSTCHECK_OK"
    ) {
        Write-W1fProductFailure "W1F_W1D_POSTCHECK_MARKER_MISSING"
    }
    Write-Output "W1F_STAGE_DOWNGRADE=ok"

    # W1E boundary exact-revision observation of the W1E postcheck marker.
    [void](Invoke-W1fAlembic -AlembicArgs @("upgrade", $W1eHead) -Marker "W1F_HARNESS_W1E_UPGRADE_FAILED")
    $W1eRevision = Get-W1fRevision -Database $DatabaseName
    if ($W1eRevision -ne $W1eHead) {
        Write-W1fProductFailure "W1F_MIGRATION_W1E_REVISION_MISMATCH" (
            "expected={0};actual={1}" -f $W1eHead, $W1eRevision
        )
    }
    $W1ePostcheckRun = Invoke-W1fTimedCommand `
        -FilePath $PowerShellExe `
        -TimeoutSec 120 `
        -TimeoutMarker "W1F_HARNESS_W1E_POSTCHECK_TIMEOUT" `
        -ArgumentList @(
            "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", (Join-Path $PSScriptRoot "verify-w1a-vs1-db.ps1"),
            "-DatabaseUrl", $OwnerDatabaseUrl
        )
    Write-W1fCommandEvidence $W1ePostcheckRun
    if (
        [int]$W1ePostcheckRun.ExitCode -ne 0 -or
        ([string]$W1ePostcheckRun.Stdout) -notmatch "W1E_DB_POSTCHECK_OK"
    ) {
        Write-W1fProductFailure "W1F_W1E_POSTCHECK_MARKER_MISSING"
    }
    Write-Output "W1F_STAGE_W1E_OBSERVED=ok"

    # Re-upgrade back to current head (0015).
    [void](Invoke-W1fAlembic -AlembicArgs @("upgrade", $CurrentHead) -Marker "W1F_HARNESS_REUPGRADE_FAILED")
    $ReupgradeRevision = Get-W1fRevision -Database $DatabaseName
    if ($ReupgradeRevision -ne $CurrentHead) {
        Write-W1fProductFailure "W1F_MIGRATION_REUPGRADE_REVISION_MISMATCH" (
            "expected={0};actual={1}" -f $CurrentHead, $ReupgradeRevision
        )
    }
    Write-Output "W1F_STAGE_REUPGRADE=ok"

    # Offline SQL generation applied to an empty database, then postcheck.
    $OfflineRun = Invoke-W1fAlembic `
        -AlembicArgs @("upgrade", "head", "--sql") `
        -Marker "W1F_HARNESS_OFFLINE_SQL_FAILED"
    $OfflineSqlText = (
        ([string]$OfflineRun.Stdout) -join [Environment]::NewLine
    ) + [Environment]::NewLine
    [System.IO.File]::WriteAllText(
        $OfflineSqlFile,
        $OfflineSqlText,
        [System.Text.UTF8Encoding]::new($false)
    )
    $OfflineApplyRun = Invoke-W1fTimedCommand `
        -FilePath $PsqlExe `
        -TimeoutSec 300 `
        -TimeoutMarker "W1F_HARNESS_OFFLINE_APPLY_TIMEOUT" `
        -ArgumentList @(
            "-X", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1",
            "-p", [string]$Port, "-U", "erp_owner", "-d", $OfflineDatabaseName,
            "-f", $OfflineSqlFile
        )
    if ([int]$OfflineApplyRun.ExitCode -ne 0) {
        Write-W1fCommandEvidence $OfflineApplyRun
        Write-W1fHarnessFailure "W1F_HARNESS_OFFLINE_APPLY_FAILED"
    }
    $OfflineRevision = Get-W1fRevision -Database $OfflineDatabaseName
    if ($OfflineRevision -ne $CurrentHead) {
        Write-W1fProductFailure "W1F_OFFLINE_REVISION_MISMATCH" (
            "expected={0};actual={1}" -f $CurrentHead, $OfflineRevision
        )
    }
    Write-Output "W1F_STAGE_OFFLINE=ok"

    # Seed synthetic W1A..0015 business rows into the primary review database.
    [System.IO.File]::WriteAllText(
        $SeedSqlFile,
        $SeedSql,
        [System.Text.UTF8Encoding]::new($false)
    )
    $SeedRun = Invoke-W1fTimedCommand `
        -FilePath $PsqlExe `
        -TimeoutSec 120 `
        -TimeoutMarker "W1F_HARNESS_SEED_TIMEOUT" `
        -ArgumentList @(
            "-X", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1",
            "-p", [string]$Port, "-U", "erp_owner", "-d", $DatabaseName,
            "-f", $SeedSqlFile
        )
    if ([int]$SeedRun.ExitCode -ne 0) {
        Write-W1fCommandEvidence $SeedRun
        Write-W1fProductFailure "W1F_SYNTHETIC_SEED_FAILED"
    }

    # Runtime invariant: the seeded recipient must actually be linked to a
    # guardian with a non-null email, no matter what SQL syntax the seed used
    # to (not) set it. This checks materialized data, not source text, so it
    # cannot be evaded by any INSERT/UPDATE syntax variation.
    $GuardianInvariantSql = @'
SELECT count(*)
FROM erp.recipient AS r
JOIN erp.recipient_guardian AS g
    ON g.id = r.payer_guardian_id AND g.recipient_id = r.id
WHERE r.name = 'W1F RECIPIENT'
  AND g.email IS NOT NULL
  AND btrim(g.email) <> ''
'@
    $GuardianInvariantCount = Invoke-W1fPsqlScalar `
        -User "erp_owner" -Database $DatabaseName `
        -Sql $GuardianInvariantSql -Marker "W1F_HARNESS_GUARDIAN_INVARIANT_QUERY_FAILED"
    if ($GuardianInvariantCount -ne "1") {
        Write-W1fProductFailure "W1F_GUARDIAN_SEED_INVARIANT_FAILED" (
            "expected=1;actual={0}" -f $GuardianInvariantCount
        )
    }
    Write-Output "W1F_STAGE_GUARDIAN_INVARIANT=ok"

    # Synthetic file bundle with a recorded SHA-256 for restore comparison.
    $SyntheticFile = Join-Path (Join-Path $RuntimeDataRoot "blobs") "w1f-synthetic.bin"
    [System.IO.File]::WriteAllText(
        $SyntheticFile,
        "W1F synthetic bundle payload for restore comparison.",
        [System.Text.UTF8Encoding]::new($false)
    )
    $SyntheticFileHash = (
        Get-FileHash -LiteralPath $SyntheticFile -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    Write-Output ("W1F_SYNTHETIC_FILE_SHA256={0}" -f $SyntheticFileHash)

    # Canonical fingerprint before backup.
    $CanonicalBefore = Invoke-W1fPsqlScalar `
        -User "erp_owner" -Database $DatabaseName `
        -Sql $CanonicalSql -Marker "W1F_HARNESS_CANONICAL_QUERY_FAILED"
    if ([string]::IsNullOrWhiteSpace($CanonicalBefore)) {
        Write-W1fHarnessFailure "W1F_HARNESS_CANONICAL_EMPTY"
    }
    Write-Output ("W1F_CANONICAL_BEFORE={0}" -f $CanonicalBefore)

    # Backup the review database and its synthetic file bundle.
    $BackupRun = Invoke-W1fTimedCommand `
        -FilePath $PowerShellExe `
        -TimeoutSec 300 `
        -TimeoutMarker "W1F_HARNESS_BACKUP_TIMEOUT" `
        -ArgumentList @(
            "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", (Join-Path $PSScriptRoot "backup-postgres.ps1"),
            "-DatabaseUrl", $OwnerDatabaseUrl,
            "-DestinationRoot", $BackupRoot,
            "-DataRoot", $RuntimeDataRoot,
            "-AppVersion", "w1f-integration-test"
        )
    Write-W1fCommandEvidence $BackupRun
    if (
        [int]$BackupRun.ExitCode -ne 0 -or
        ([string]$BackupRun.Stdout) -notmatch "BACKUP_OK"
    ) {
        Write-W1fHarnessFailure "W1F_HARNESS_BACKUP_FAILED" (
            "exit={0}" -f $BackupRun.ExitCode
        )
    }
    $BackupDirectory = (
        Get-ChildItem -LiteralPath $BackupRoot -Directory |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
    ).FullName

    # Restore into a fresh review database and data root; restore-drill.ps1
    # enforces the 0017 guardian-email postcheck marker fail-closed.
    $RestoreRun = Invoke-W1fTimedCommand `
        -FilePath $PowerShellExe `
        -TimeoutSec 300 `
        -TimeoutMarker "W1F_HARNESS_RESTORE_TIMEOUT" `
        -ArgumentList @(
            "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", (Join-Path $PSScriptRoot "restore-drill.ps1"),
            "-BackupDirectory", $BackupDirectory,
            "-AdminDatabaseUrl", $AdminDatabaseUrl,
            "-ReviewDatabaseName", $RestoreReviewDatabaseName,
            "-ReviewDataRoot", $ReviewDataRoot,
            "-KeepReviewArtifacts"
        )
    Write-W1fCommandEvidence $RestoreRun
    if (
        [int]$RestoreRun.ExitCode -ne 0 -or
        ([string]$RestoreRun.Stdout) -notmatch "RESTORE_DRILL_OK"
    ) {
        Write-W1fProductFailure "W1F_RESTORE_DRILL_FAILED" (
            "exit={0}" -f $RestoreRun.ExitCode
        )
    }
    if (([string]$RestoreRun.Stdout) -notmatch "RECIPIENT_GUARDIAN_EMAIL_DB_POSTCHECK_OK") {
        Write-W1fProductFailure "W1F_0017_POSTCHECK_MARKER_MISSING"
    }
    Write-Output "W1F_STAGE_RESTORE=ok"

    # Compare canonical fingerprint in the restored database.
    $CanonicalAfter = Invoke-W1fPsqlScalar `
        -User "erp_owner" -Database $RestoreReviewDatabaseName `
        -Sql $CanonicalSql -Marker "W1F_HARNESS_CANONICAL_RESTORE_QUERY_FAILED"
    Write-Output ("W1F_CANONICAL_AFTER={0}" -f $CanonicalAfter)
    if ($CanonicalAfter -ne $CanonicalBefore) {
        Write-W1fProductFailure "W1F_CANONICAL_MISMATCH" (
            "before={0};after={1}" -f $CanonicalBefore, $CanonicalAfter
        )
    }

    # Compare the restored synthetic file hash in the new data root.
    $RestoredFile = Join-Path (Join-Path $ReviewDataRoot "blobs") "w1f-synthetic.bin"
    if (-not (Test-Path -LiteralPath $RestoredFile -PathType Leaf)) {
        Write-W1fProductFailure "W1F_RESTORED_FILE_MISSING"
    }
    $RestoredFileHash = (
        Get-FileHash -LiteralPath $RestoredFile -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if ($RestoredFileHash -ne $SyntheticFileHash) {
        Write-W1fProductFailure "W1F_RESTORED_FILE_HASH_MISMATCH" (
            "expected={0};actual={1}" -f $SyntheticFileHash, $RestoredFileHash
        )
    }

    # Confirm W1D/W1E tables and backup-role ACL in the restored database.
    $TablesPresent = Invoke-W1fPsqlScalar `
        -User "erp_owner" -Database $RestoreReviewDatabaseName `
        -Sql (
            "SELECT to_regclass('erp.recipient_contract') IS NOT NULL " +
            "AND to_regclass('erp.care_assignment') IS NOT NULL"
        ) `
        -Marker "W1F_HARNESS_RESTORED_TABLE_QUERY_FAILED"
    if ($TablesPresent -ne "t") {
        Write-W1fProductFailure "W1F_RESTORED_TABLES_MISSING"
    }
    $BackupAcl = Invoke-W1fPsqlScalar `
        -User "erp_owner" -Database $RestoreReviewDatabaseName `
        -Sql (
            "SELECT has_table_privilege('erp_backup', 'erp.recipient_contract', 'SELECT') " +
            "AND has_table_privilege('erp_backup', 'erp.care_assignment', 'SELECT') " +
            "AND NOT has_table_privilege('erp_backup', 'erp.recipient_contract', 'INSERT') " +
            "AND NOT has_table_privilege('erp_backup', 'erp.care_assignment', 'INSERT')"
        ) `
        -Marker "W1F_HARNESS_RESTORED_ACL_QUERY_FAILED"
    if ($BackupAcl -ne "t") {
        Write-W1fProductFailure "W1F_RESTORED_BACKUP_ACL_INVALID"
    }

    Write-Output ("W1F_CANONICAL={0}" -f $CanonicalAfter)
    $AllProductStagesOk = $true
    Write-Output "W1F_POSTGRES_PRODUCT_GREEN"
}
catch {
    $ScriptExitCode = 1
    $FailureMessage = [string]$_.Exception.Message
    if ($FailureMessage -match "W1F_HARNESS_") {
        Write-Output ("W1F_WRAPPER_HARNESS_FAILURE: {0}" -f $FailureMessage)
    }
    elseif ($ProductFailure) {
        Write-Output ("W1F_WRAPPER_PRODUCT_FAILURE: {0}" -f $FailureMessage)
    }
    else {
        Write-Output ("W1F_WRAPPER_HARNESS_FAILURE: {0}" -f $FailureMessage)
    }
}
finally {
    if ($ClusterStarted) {
        try {
            $StopRun = Invoke-W1fTimedCommand `
                -FilePath $PgCtlExe `
                -TimeoutSec 60 `
                -TimeoutMarker "W1F_HARNESS_POSTGRES_STOP_TIMEOUT" `
                -ArgumentList @(
                    "--pgdata=$DataDirectory", "stop", "--mode=immediate", "--wait"
                )
            Write-Output ("W1F_STAGE_POSTGRES_STOP_EXIT={0}" -f $StopRun.ExitCode)
            if ([int]$StopRun.ExitCode -ne 0) {
                Write-W1fCommandEvidence $StopRun
                $CleanupHarnessFailure = $true
                Write-Output "W1F_HARNESS_POSTGRES_STOP_FAILED"
            }
        }
        catch {
            $CleanupHarnessFailure = $true
            Write-Output ("W1F_HARNESS_POSTGRES_STOP_FAILED: {0}" -f $_.Exception.Message)
        }
        $ClusterStarted = $false
        Start-Sleep -Seconds 2
    }

    try {
        $processSnapshot = Get-W1fProcessSnapshot
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
                    "W1F_HARNESS_PG_CHILD_KILL_FAILED: pid={0}" -f
                    $relatedProcess.ProcessId
                )
            }
        }
    }
    catch {
        $CleanupHarnessFailure = $true
        Write-Output ("W1F_HARNESS_PROCESS_ENUM_FAILED: {0}" -f $_.Exception.Message)
    }
    Start-Sleep -Seconds 1

    try {
        $listenerSnapshot = Get-W1fListenerSnapshot
        $portListeners = @(
            $listenerSnapshot | Where-Object { [int]$_.LocalPort -eq [int]$Port }
        )
        $ListenerResidual = $portListeners.Count
    }
    catch {
        $CleanupHarnessFailure = $true
        $ListenerResidual = 1
        Write-Output ("W1F_HARNESS_LISTENER_ENUM_FAILED: {0}" -f $_.Exception.Message)
    }

    try {
        $verificationProcesses = Get-W1fProcessSnapshot
        $DataDirectoryWindows = $DataDirectory.Replace("/", "\").TrimEnd("\")
        $DataDirectoryPosix = $DataDirectory.Replace("\", "/").TrimEnd("/")
        $remainingProcesses = @(
            $verificationProcesses | Where-Object {
                Test-W1fResidualPostgresProcess `
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
        Write-Output ("W1F_HARNESS_PROCESS_ENUM_FAILED: {0}" -f $_.Exception.Message)
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
                "sswcenter-w1f-pg-",
                [StringComparison]::Ordinal
            )
        ) {
            $CleanupHarnessFailure = $true
            Write-Output "W1F_HARNESS_UNSAFE_CLEANUP_PATH"
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
                        "W1F_HARNESS_CLEANUP_REMOVE_WARNING: attempt={0};detail={1}" -f
                        $attempt, $_.Exception.Message
                    )
                    Start-Sleep -Seconds (2 * $attempt)
                }
            }
            if (-not $removed) {
                $CleanupHarnessFailure = $true
                Write-Output "W1F_HARNESS_CLEANUP_REMOVE_RETRY_FAILED"
            }
        }
    }
    if (Test-Path -LiteralPath $ClusterRoot) {
        $TempResidual = 1
    }

    try {
        $FinalArtifacts = @(Get-W1fArtifactSnapshot)
        $ArtifactResidual = @(
            $FinalArtifacts | Where-Object {
                -not $BeforeArtifactSet.ContainsKey([string]$_)
            }
        ).Count
    }
    catch {
        $CleanupHarnessFailure = $true
        $ArtifactResidual = 1
        Write-Output ("W1F_HARNESS_ARTIFACT_SCAN_FAILED: {0}" -f $_.Exception.Message)
    }

    try {
        $FinalHeadRun = Invoke-W1fTimedCommand `
            -FilePath $GitExe `
            -WorkingDirectory $WorkspaceRoot `
            -TimeoutSec 30 `
            -TimeoutMarker "W1F_HARNESS_FINAL_GIT_HEAD_TIMEOUT" `
            -ArgumentList @("rev-parse", "HEAD")
        $FinalStatusRun = Invoke-W1fTimedCommand `
            -FilePath $GitExe `
            -WorkingDirectory $WorkspaceRoot `
            -TimeoutSec 30 `
            -TimeoutMarker "W1F_HARNESS_FINAL_GIT_STATUS_TIMEOUT" `
            -ArgumentList @("status", "--porcelain=v1", "--untracked-files=all")
        if (
            [int]$FinalHeadRun.ExitCode -ne 0 -or
            [int]$FinalStatusRun.ExitCode -ne 0 -or
            ([string]$FinalHeadRun.Stdout).Trim().ToLowerInvariant() -ne $ExpectedSha -or
            -not [string]::IsNullOrWhiteSpace(([string]$FinalStatusRun.Stdout).Trim())
        ) {
            $GitResidual = 1
            $CleanupHarnessFailure = $true
            Write-Output "W1F_HARNESS_FINAL_GIT_STATE_MISMATCH"
        }
    }
    catch {
        $GitResidual = 1
        $CleanupHarnessFailure = $true
        Write-Output ("W1F_HARNESS_FINAL_GIT_CHECK_FAILED: {0}" -f $_.Exception.Message)
    }

    Write-Output (
        "W1F_CLEANUP listener={0} process={1} temp={2} artifact={3} git={4}" -f
        $ListenerResidual,
        $ProcessResidual,
        $TempResidual,
        $ArtifactResidual,
        $GitResidual
    )
    if (
        $ListenerResidual -gt 0 -or
        $ProcessResidual -gt 0 -or
        $TempResidual -gt 0 -or
        $ArtifactResidual -gt 0 -or
        $GitResidual -gt 0
    ) {
        $CleanupHarnessFailure = $true
        Write-Output "W1F_HARNESS_CLEANUP_RESIDUAL_NONZERO"
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
    Write-Output "W1F_POSTGRES_GREEN"
}
else {
    $ScriptExitCode = 1
    if ($CleanupHarnessFailure) {
        Write-Output "W1F_WRAPPER_HARNESS_FAILURE: W1F_HARNESS_CLEANUP_GATE"
    }
}

if ($ScriptExitCode -ne 0) {
    exit $ScriptExitCode
}
