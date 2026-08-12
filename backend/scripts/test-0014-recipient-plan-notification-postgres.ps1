param(
    # CleanHead is the only supported 2.2 candidate. The LegacyStaged21
    # (2.1 staged compatibility) mode is retired.
    [ValidateSet('CleanHead')]
    [string]$CandidateMode = 'CleanHead',
    # PreflightOnly runs candidate identity, reviewed-byte binding, required
    # executable/file checks, process/artifact baselines, port availability, and
    # postflight cleanup/git invariants; it stops before creating a temp root or
    # starting PostgreSQL/FastAPI/Vite/Playwright.
    [switch]$PreflightOnly,
    # Optional override for the Python interpreter.  If blank, the script uses
    # backend\.venv\Scripts\python.exe relative to itself.
    [string]$PythonExecutable = '',
    # The operator must bind the exact candidate explicitly.  An omitted value
    # fails before any PostgreSQL process or temp root is created.
    [string]$ExpectedSha = "",
    # A script cannot safely embed its own digest.  The independent reviewer
    # supplies the reviewed wrapper SHA-256 at invocation time instead.
    # Required in LegacyStaged21; optional in CleanHead (verified if supplied).
    [string]$ExpectedWrapperSha256 = "",
    [ValidateRange(1024, 65535)][int]$Port = 55445,
    [ValidateRange(1024, 65535)][int]$BackendPort = 18094,
    [ValidateRange(1024, 65535)][int]$FrontendPort = 14194,
    [string]$PostgresBin = "C:\Program Files\PostgreSQL\17\bin"
)

# This is a bounded current-head derivative of the W1E/W1F PostgreSQL process,
# stream-capture, migration-boundary, and postflight patterns.  It is separate
# because the legacy wrappers pin older heads and require a clean worktree;
# invoking or editing them would not validate this dirty staged-21 candidate.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$BackendRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$WorkspaceRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $BackendRoot))
$FrontendRoot = Join-Path $WorkspaceRoot "frontend"
if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $PythonExe = Join-Path $BackendRoot ".venv\Scripts\python.exe"
}
else {
    $PythonExe = [System.IO.Path]::GetFullPath($PythonExecutable)
}
$PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$InitDbExe = Join-Path $PostgresBin "initdb.exe"
$PgCtlExe = Join-Path $PostgresBin "pg_ctl.exe"
$PgIsReadyExe = Join-Path $PostgresBin "pg_isready.exe"
$CreateDbExe = Join-Path $PostgresBin "createdb.exe"
$PsqlExe = Join-Path $PostgresBin "psql.exe"
$GitExe = (Get-Command git.exe -ErrorAction Stop).Source
$NodeExe = (Get-Command node.exe -ErrorAction Stop).Source
$ViteCli = Join-Path $FrontendRoot "node_modules\vite\bin\vite.js"
$PlaywrightCli = Join-Path $FrontendRoot "node_modules\playwright\cli.js"

$BaseRevision = "20260802_0013_staff_continuing_education"
$ExpectedRevision = "20260803_0014_recipient_plan_notification"
$ExpectedBranch = "codex/monthly-editorial-redesign"
$ExpectedWorkspaceRoot = [System.IO.Path]::GetFullPath("C:\sswcenter\2.1")
$ExpectedStagedManifestSha256 = "3EE4BD8A38D2776775BDCAAF6374C136E41772C1F410AA5910155B97B0E4B0B4"
$WrapperRelativePath = "backend/scripts/test-0014-recipient-plan-notification-postgres.ps1"
$MigrationRelativePath = "backend/alembic/versions/20260803_0014_recipient_plan_notification.py"
$ExpectedMigrationWorktreeSha256 = "C76ECA1F6AD9594CC4901C1DD25F0D724F47A451257E61903D3EBB4781D6A3B2"
$ExpectedReviewedFileSha256 = [ordered]@{
    "backend/tests/test_recipient_plan_notification_postgres.py" =
        "E528F4D209634745E87FC420B6A9B08267979A35EE9E2024E6190F6717024E1D"
    "frontend/e2e/recipient-plan-notification-real-pg.spec.ts" =
        "0495950586BA506780A5ABCF1124BD1E66CDB7550A5D86E746E90B731D92E5CB"
    "frontend/e2e/recipient-plan-notification-real-pg.config.ts" =
        "3A483CFAA9A799429661687C3C276F92BE7CCC6659A4D9AD015DEADCF3FF8191"
    "frontend/e2e/recipient-plan-notification-real-pg.vite.config.ts" =
        "0008F5723B89748DDDAE55E44B3E1A9D180BE208E063EA33ADE0B7E147E471FF"
}
$OwnedProcessNamePattern = '^(postgres|pg_ctl|python|pythonw|node|npm|cmd|chrome|chromium|msedge|esbuild)\.exe$'
$ExpectedStagedPaths = @(
    "backend/alembic/versions/20260803_0014_recipient_plan_notification.py",
    "backend/app/api/recipient.py",
    "backend/app/db/models.py",
    "backend/app/domains/recipient/repository.py",
    "backend/app/domains/recipient/schemas.py",
    "backend/app/domains/recipient/service.py",
    "backend/tests/test_recipient_deadlines_contract.py",
    "backend/tests/test_schema_contract.py",
    "backend/tests/test_w1d_contract.py",
    "backend/tests/test_w1e_contract.py",
    "frontend/src/components/dashboard/todoState.ts",
    "frontend/src/components/layout/AppLayout.tsx",
    "frontend/src/generated/sswcenter-api.ts",
    "frontend/src/pages/DashboardPage.tsx",
    "frontend/src/pages/RecipientsPage.tsx",
    "frontend/src/services/recipientApi.ts",
    "frontend/src/services/staffApi.ts",
    "frontend/src/styles/editorial.css",
    "frontend/src/test/DashboardInteractions.test.tsx",
    "frontend/src/test/StaffApi.test.ts",
    "frontend/src/test/TodoState.test.ts"
)

$SavedEnvironment = @{}
$EnvironmentNames = @(
    "TEMP", "TMP", "TMPDIR", "PYTHONDONTWRITEBYTECODE", "PYTEST_ADDOPTS",
    "SSWCENTER_ENVIRONMENT", "SSWCENTER_DATABASE_URL", "SSWCENTER_DATA_ROOT",
    "SSWCENTER_OWNER_DATABASE_URL", "SSWCENTER_APP_DATABASE_URL",
    "SSWCENTER_0014_OWNER_DATABASE_URL", "SSWCENTER_0014_APP_DATABASE_URL",
    "SSWCENTER_0014_REAL_PG", "SSWCENTER_0014_REAL_E2E",
    "SSWCENTER_0014_E2E_PIN", "SSWCENTER_E2E_BACKEND_PORT",
    "SSWCENTER_E2E_FRONTEND_PORT", "SSWCENTER_0014_VITE_CACHE_DIR",
    "SSWCENTER_0014_PLAYWRIGHT_OUTPUT_DIR", "SSWCENTER_PIN_PEPPER",
    "SSWCENTER_PIN_LOOKUP_KEY", "SSWCENTER_CSRF_SIGNING_KEY",
    "SSWCENTER_RESIDENT_NUMBER_KEY_V1", "SSWCENTER_RESIDENT_NUMBER_LOOKUP_KEY",
    "SSWCENTER_RESIDENT_NUMBER_ACTIVE_KEY_VERSION", "SSWCENTER_DEV_LOGIN_BYPASS",
    "VITE_DEV_LOGIN_BYPASS"
)
foreach ($environmentName in $EnvironmentNames) {
    $SavedEnvironment[$environmentName] = [Environment]::GetEnvironmentVariable(
        $environmentName,
        "Process"
    )
}

$script:ProductFailure = $false
$script:HarnessFailure = $false
$ScriptExitCode = 0
$AllStagesAttempted = $false
$ClusterStarted = $false
$BackendProcess = $null
$FrontendProcess = $null
$TempRoot = $null
$DataDirectory = $null
$OutputRoot = $null
$ExpectedTempPrefix = $null
$InitialGitSnapshot = $null
$InitialReviewedManifest = $null
$script:CleanHeadInitialFileHashes = @{}
$script:CleanHeadInitialMigrationHash = $null
$PreflightOnlyCompleted = $false
$PreflightOnlySentinel = "SSWCENTER_0014_INTERNAL_PREFLIGHT_ONLY_COMPLETE"
$BeforeArtifacts = @()
$BeforeProcessSet = @{}
$ArtifactBaselineCaptured = $false
$ProcessBaselineCaptured = $false
$ListenerResidual = 0
$ProcessResidual = 0
$TempResidual = 0
$ArtifactResidual = 0
$GitResidual = 0
$IndexResidual = 0
$BackendStdoutPath = $null
$BackendStderrPath = $null
$FrontendStdoutPath = $null
$FrontendStderrPath = $null
$RuntimeDiagnosticWritten = @{}

function Write-RpnHarnessFailure {
    param([string]$Marker, [string]$Detail = "")
    $script:HarnessFailure = $true
    if ([string]::IsNullOrWhiteSpace($Detail)) {
        Write-Output $Marker
    }
    else {
        Write-Output ("{0}: {1}" -f $Marker, $Detail)
    }
    throw $Marker
}

function Write-RpnProductFailure {
    param([string]$Marker, [string]$Detail = "")
    $script:ProductFailure = $true
    if ([string]::IsNullOrWhiteSpace($Detail)) {
        Write-Output $Marker
    }
    else {
        Write-Output ("{0}: {1}" -f $Marker, $Detail)
    }
    throw $Marker
}

function Restore-RpnEnvironment {
    foreach ($environmentName in $EnvironmentNames) {
        $original = $SavedEnvironment[$environmentName]
        if ($null -eq $original) {
            [Environment]::SetEnvironmentVariable($environmentName, $null, "Process")
        }
        else {
            [Environment]::SetEnvironmentVariable(
                $environmentName,
                [string]$original,
                "Process"
            )
        }
    }
}

function ConvertTo-RpnProcessArgument {
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
                [void]$builder.Append((('\' * (2 * $backslashCount)) -join ''))
            }
            [void]$builder.Append('\')
            [void]$builder.Append('"')
            $backslashCount = 0
            continue
        }
        if ($backslashCount -gt 0) {
            [void]$builder.Append((('\' * $backslashCount) -join ''))
            $backslashCount = 0
        }
        [void]$builder.Append($character)
    }
    if ($backslashCount -gt 0) {
        [void]$builder.Append((('\' * (2 * $backslashCount)) -join ''))
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function ConvertTo-RpnProcessArguments {
    param([string[]]$ArgumentList = @())
    return (@(
        $ArgumentList | ForEach-Object { ConvertTo-RpnProcessArgument ([string]$_) }
    ) -join " ")
}

function Get-RpnProcessSnapshot {
    try {
        return @(
            Get-CimInstance Win32_Process -OperationTimeoutSec 10 -ErrorAction Stop
        )
    }
    catch {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_PROCESS_ENUM_FAILED" (
            [string]$_.Exception.Message
        )
    }
}

function Get-RpnProcessIdentity {
    param([Parameter(Mandatory = $true)]$ProcessRow)
    if ($null -eq $ProcessRow.CreationDate) {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_PROCESS_IDENTITY_INCOMPLETE" (
            "pid={0};name={1}" -f $ProcessRow.ProcessId, $ProcessRow.Name
        )
    }
    return ("{0}|{1}" -f [int]$ProcessRow.ProcessId, [string]$ProcessRow.CreationDate)
}

function Get-RpnDescendantPids {
    param([int]$RootPid, $Snapshot)
    $byParent = @{}
    foreach ($row in @($Snapshot)) {
        $parentPid = [int]$row.ParentProcessId
        if (-not $byParent.ContainsKey($parentPid)) {
            $byParent[$parentPid] = New-Object System.Collections.ArrayList
        }
        [void]$byParent[$parentPid].Add([int]$row.ProcessId)
    }
    $depth = @{}
    $depth[$RootPid] = 0
    $queue = New-Object System.Collections.Queue
    $queue.Enqueue($RootPid)
    while ($queue.Count -gt 0) {
        $current = [int]$queue.Dequeue()
        if (-not $byParent.ContainsKey($current)) { continue }
        foreach ($childValue in @($byParent[$current])) {
            $child = [int]$childValue
            if ($depth.ContainsKey($child)) { continue }
            $depth[$child] = [int]$depth[$current] + 1
            $queue.Enqueue($child)
        }
    }
    return @(
        $depth.Keys |
            Where-Object { [int]$_ -ne $RootPid } |
            Sort-Object { -[int]$depth[[int]$_] } |
            ForEach-Object { [int]$_ }
    )
}

function Stop-RpnProcessTree {
    param([int]$RootPid, [string]$Context)
    $snapshot = Get-RpnProcessSnapshot
    $targets = @(Get-RpnDescendantPids -RootPid $RootPid -Snapshot $snapshot) + @($RootPid)
    foreach ($targetValue in $targets) {
        $target = [int]$targetValue
        if ($target -eq $PID) { continue }
        if (@($snapshot | Where-Object { [int]$_.ProcessId -eq $target }).Count -eq 0) {
            continue
        }
        try {
            Stop-Process -Id $target -Force -ErrorAction Stop
        }
        catch {
            # A race is accepted only if the final process/listener gate proves zero.
        }
    }
    Start-Sleep -Milliseconds 250
    $remaining = @(
        Get-RpnProcessSnapshot | Where-Object { $targets -contains [int]$_.ProcessId }
    )
    if ($remaining.Count -gt 0) {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_PROCESS_TREE_STOP_FAILED" (
            "context={0};pids={1}" -f $Context, (($remaining.ProcessId) -join ",")
        )
    }
}

function Invoke-RpnTimedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = "",
        [int]$TimeoutSec = 600,
        [string]$TimeoutMarker = "SSWCENTER_0014_HARNESS_CHILD_TIMEOUT"
    )
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = ConvertTo-RpnProcessArguments $ArgumentList
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
    $tasks = [System.Threading.Tasks.Task[]]@($stdoutTask, $stderrTask)
    if (-not $process.WaitForExit($TimeoutSec * 1000)) {
        Stop-RpnProcessTree -RootPid ([int]$process.Id) -Context $TimeoutMarker
        try { [void][System.Threading.Tasks.Task]::WaitAll($tasks, 5000) } catch {}
        Write-RpnHarnessFailure $TimeoutMarker ("timeoutSec={0}" -f $TimeoutSec)
    }
    try {
        $drained = [System.Threading.Tasks.Task]::WaitAll($tasks, 10000)
    }
    catch {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_STREAM_READ_FAILED" (
            [string]$_.Exception.Message
        )
    }
    if (-not $drained) {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_STREAM_DRAIN_TIMEOUT"
    }
    return ,([pscustomobject]@{
        ExitCode = [int]$process.ExitCode
        Stdout = [string]$stdoutTask.GetAwaiter().GetResult()
        Stderr = [string]$stderrTask.GetAwaiter().GetResult()
    })
}

function Protect-RpnEvidenceText {
    param([AllowEmptyString()][string]$Text)
    $redacted = [string]$Text
    $redacted = [regex]::Replace(
        $redacted,
        '(?i)(postgresql(?:\+[a-z0-9_]+)?://[^:/\s@]+:)[^@\s]+(@)',
        '$1***$2'
    )
    $redacted = [regex]::Replace(
        $redacted,
        '(?i)((?:password|passwd|secret|token|authorization|cookie|pin)' +
            '\s*[=:]\s*)[^\s,;]+',
        '$1***'
    )
    foreach ($environmentName in @(
        "SSWCENTER_PIN_PEPPER", "SSWCENTER_PIN_LOOKUP_KEY",
        "SSWCENTER_CSRF_SIGNING_KEY", "SSWCENTER_RESIDENT_NUMBER_KEY_V1",
        "SSWCENTER_RESIDENT_NUMBER_LOOKUP_KEY", "SSWCENTER_0014_E2E_PIN"
    )) {
        $secret = [Environment]::GetEnvironmentVariable($environmentName, "Process")
        if (-not [string]::IsNullOrWhiteSpace($secret)) {
            $redacted = $redacted.Replace([string]$secret, "***")
        }
    }
    return $redacted
}

function Write-RpnEvidenceStream {
    param(
        [string]$Stage,
        [string]$Stream,
        [AllowEmptyString()][string]$Text
    )
    Write-Output ("SSWCENTER_0014_DIAGNOSTIC_BEGIN stage={0} stream={1}" -f $Stage, $Stream)
    foreach ($line in ((Protect-RpnEvidenceText $Text) -split "`r?`n")) {
        if (-not [string]::IsNullOrWhiteSpace($line)) {
            Write-Output ("SSWCENTER_0014_DIAGNOSTIC stage={0} stream={1} {2}" -f
                $Stage, $Stream, $line)
        }
    }
    Write-Output ("SSWCENTER_0014_DIAGNOSTIC_END stage={0} stream={1}" -f $Stage, $Stream)
}

function Write-RpnCommandEvidence {
    param($Result, [string]$Stage = "child")
    Write-RpnEvidenceStream -Stage $Stage -Stream "stdout" -Text ([string]$Result.Stdout)
    Write-RpnEvidenceStream -Stage $Stage -Stream "stderr" -Text ([string]$Result.Stderr)
}

function Get-RpnLogTail {
    param([AllowEmptyString()][string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return "<log unavailable>"
    }
    try {
        return (@(Get-Content -LiteralPath $Path -Tail 400 -ErrorAction Stop) -join "`n")
    }
    catch {
        return ("<log read failed: {0}>" -f $_.Exception.Message)
    }
}

function Write-RpnRuntimeLogEvidence {
    param(
        [string]$Stage,
        [AllowEmptyString()][string]$StdoutPath,
        [AllowEmptyString()][string]$StderrPath
    )
    if ($RuntimeDiagnosticWritten.ContainsKey($Stage)) { return }
    $RuntimeDiagnosticWritten[$Stage] = $true
    Write-RpnEvidenceStream -Stage $Stage -Stream "stdout" -Text (Get-RpnLogTail $StdoutPath)
    Write-RpnEvidenceStream -Stage $Stage -Stream "stderr" -Text (Get-RpnLogTail $StderrPath)
}

function Get-RpnRuntimeFailureClass {
    param(
        [AllowEmptyString()][string]$StdoutPath,
        [AllowEmptyString()][string]$StderrPath
    )
    $diagnostic = (Get-RpnLogTail $StdoutPath) + "`n" + (Get-RpnLogTail $StderrPath)
    if ($diagnostic -match (
        '(?i)EADDRINUSE|address already in use|ENOENT|EACCES|' +
        'ERR_MODULE_NOT_FOUND|Cannot find module|Cannot find package|' +
        'ModuleNotFoundError:\s+No module named|' +
        'executable doesn.t exist|not recognized as an internal or external command'
    )) {
        return "HARNESS"
    }
    return "PRODUCT"
}

function Write-RpnEarlyRuntimeFailure {
    param(
        [string]$Stage,
        [string]$Detail,
        [AllowEmptyString()][string]$StdoutPath,
        [AllowEmptyString()][string]$StderrPath
    )
    Write-RpnRuntimeLogEvidence `
        -Stage $Stage `
        -StdoutPath $StdoutPath `
        -StderrPath $StderrPath
    $classification = Get-RpnRuntimeFailureClass `
        -StdoutPath $StdoutPath `
        -StderrPath $StderrPath
    Write-Output (
        "SSWCENTER_0014_EARLY_RUNTIME_CLASS stage={0} class={1}" -f
        $Stage, $classification
    )
    if ($classification -eq "HARNESS") {
        Write-RpnHarnessFailure `
            ("SSWCENTER_0014_HARNESS_{0}_EARLY_FAILURE" -f $Stage.ToUpperInvariant()) `
            $Detail
    }
    Write-RpnProductFailure `
        ("SSWCENTER_0014_{0}_PRODUCT_START_FAILED" -f $Stage.ToUpperInvariant()) `
        $Detail
}

function Get-RpnSha256 {
    param([AllowEmptyString()][string]$Text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Text)
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "")
    }
    finally {
        $sha.Dispose()
    }
}

function Normalize-RpnText {
    param([AllowEmptyString()][string]$Text)
    return (($Text -replace "`r`n", "`n").TrimEnd([char[]]"`r`n"))
}

function Invoke-RpnGit {
    param([string[]]$ArgumentList, [int]$TimeoutSec = 120)
    $result = Invoke-RpnTimedCommand `
        -FilePath $GitExe `
        -WorkingDirectory $WorkspaceRoot `
        -TimeoutSec $TimeoutSec `
        -TimeoutMarker "SSWCENTER_0014_HARNESS_GIT_TIMEOUT" `
        -ArgumentList $ArgumentList
    if ([int]$result.ExitCode -ne 0) {
        Write-RpnCommandEvidence -Result $result -Stage "git"
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_GIT_COMMAND_FAILED" (
            $ArgumentList -join " "
        )
    }
    return (Normalize-RpnText ([string]$result.Stdout))
}

function Get-RpnGitSnapshot {
    $head = Invoke-RpnGit @("rev-parse", "HEAD")
    $status = Invoke-RpnGit @("status", "--porcelain=v2", "--untracked-files=all")
    $stagedText = Invoke-RpnGit @("diff", "--cached", "--name-only")
    $stagedPaths = @(
        $stagedText -split "`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    $stagedSet = @{}
    foreach ($path in $stagedPaths) { $stagedSet[[string]$path] = $true }
    $fullIndex = Invoke-RpnGit @("ls-files", "--stage")
    $stagedManifestLines = @(
        $fullIndex -split "`n" | Where-Object {
            $tab = $_.IndexOf("`t")
            if ($tab -lt 0) { return $false }
            $path = $_.Substring($tab + 1)
            return $stagedSet.ContainsKey($path)
        }
    )
    $stagedManifest = $stagedManifestLines -join "`n"
    $cachedDiff = Invoke-RpnGit @("diff", "--cached", "--binary") 300
    $workingDiff = Invoke-RpnGit @("diff", "--binary") 300
    $untrackedText = Invoke-RpnGit @("ls-files", "--others", "--exclude-standard")
    $untrackedManifest = New-Object System.Collections.ArrayList
    foreach ($relativePath in @(
        $untrackedText -split "`n" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Sort-Object
    )) {
        $absolutePath = Join-Path $WorkspaceRoot $relativePath
        if (Test-Path -LiteralPath $absolutePath -PathType Leaf) {
            $fileHash = (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256).Hash
            [void]$untrackedManifest.Add(("{0} {1}" -f $fileHash, $relativePath))
        }
        else {
            [void]$untrackedManifest.Add(("MISSING {0}" -f $relativePath))
        }
    }
    return [pscustomobject]@{
        Head = $head.Trim().ToLowerInvariant()
        Status = $status
        StatusSha256 = Get-RpnSha256 $status
        StatusCount = @($status -split "`n" | Where-Object { $_ }).Count
        StagedPaths = [string[]]$stagedPaths
        StagedCount = $stagedPaths.Count
        StagedManifestSha256 = Get-RpnSha256 $stagedManifest
        FullIndexSha256 = Get-RpnSha256 $fullIndex
        CachedDiffSha256 = Get-RpnSha256 $cachedDiff
        WorkingDiffSha256 = Get-RpnSha256 $workingDiff
        UntrackedManifestSha256 = Get-RpnSha256 ($untrackedManifest -join "`n")
    }
}

function Get-RpnReviewedManifest {
    param([string]$BindingMode, [string]$WrapperSha256)

    $reviewFilePaths = @(
        $WrapperRelativePath,
        "backend/tests/test_recipient_plan_notification_postgres.py",
        "frontend/e2e/recipient-plan-notification-real-pg.spec.ts",
        "frontend/e2e/recipient-plan-notification-real-pg.config.ts",
        "frontend/e2e/recipient-plan-notification-real-pg.vite.config.ts"
    )

    $trackedPaths = @(
        (Invoke-RpnGit @("ls-files")) -split "`n" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    $trackedSet = @{}
    foreach ($path in $trackedPaths) { $trackedSet[[string]$path] = $true }

    $untrackedPaths = @(
        (Invoke-RpnGit @("ls-files", "--others", "--exclude-standard")) -split "`n" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    $untrackedSet = @{}
    foreach ($path in $untrackedPaths) { $untrackedSet[[string]$path] = $true }

    $reviewNamespacePaths = @(
        $untrackedPaths + $trackedPaths | Where-Object {
            $_ -like "backend/scripts/test-0014-recipient-plan-notification-postgres*" -or
            $_ -like "backend/tests/test_recipient_plan_notification_postgres*" -or
            $_ -like "frontend/e2e/recipient-plan-notification-real-pg*"
        }
    )

    $expectedSet = @{}
    foreach ($path in $reviewFilePaths) { $expectedSet[[string]$path] = $true }
    $actualSet = @{}
    foreach ($path in $reviewNamespacePaths) { $actualSet[[string]$path] = $true }
    $missing = @($reviewFilePaths | Where-Object { -not $actualSet.ContainsKey($_) })
    $extra = @($reviewNamespacePaths | Where-Object { -not $expectedSet.ContainsKey($_) })
    $exactSetMatch = $missing.Count -eq 0 -and $extra.Count -eq 0

    $rows = New-Object System.Collections.ArrayList
    $expectedLines = New-Object System.Collections.ArrayList
    $actualLines = New-Object System.Collections.ArrayList
    $bytesMatch = $true
    $provenanceMatch = $true
    $wrapperMatched = $true

    if ($BindingMode -eq "LegacyStaged21") {
        $expected = [ordered]@{}
        $expected[$WrapperRelativePath] = $WrapperSha256.ToUpperInvariant()
        foreach ($entry in $ExpectedReviewedFileSha256.GetEnumerator()) {
            $expected[[string]$entry.Key] = ([string]$entry.Value).ToUpperInvariant()
        }
        foreach ($path in $expected.Keys) {
            $absolutePath = Join-Path $WorkspaceRoot ([string]$path)
            $actualSha = "MISSING"
            if (Test-Path -LiteralPath $absolutePath -PathType Leaf) {
                $actualSha = (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256).Hash
            }
            $provenance = if ($untrackedSet.ContainsKey([string]$path)) {
                "untracked"
            }
            elseif ($trackedSet.ContainsKey([string]$path)) {
                "tracked"
            }
            else {
                "absent"
            }
            $expectedSha = [string]$expected[$path]
            if ($actualSha -ne $expectedSha) { $bytesMatch = $false }
            if ($provenance -ne "untracked") { $provenanceMatch = $false }
            [void]$expectedLines.Add(("{0}={1}" -f $path, $expectedSha))
            [void]$actualLines.Add(("{0}={1}" -f $path, $actualSha))
            [void]$rows.Add([pscustomobject]@{
                Path = [string]$path
                ExpectedSha256 = $expectedSha
                ActualSha256 = $actualSha
                Provenance = $provenance
            })
        }
    }
    else {
        # CleanHead: no historical fixed hashes; capture actual bytes as baseline.
        foreach ($path in $reviewFilePaths) {
            $absolutePath = Join-Path $WorkspaceRoot ([string]$path)
            $actualSha = "MISSING"
            if (Test-Path -LiteralPath $absolutePath -PathType Leaf) {
                $actualSha = (Get-FileHash -LiteralPath $absolutePath -Algorithm SHA256).Hash
            }
            $provenance = if ($trackedSet.ContainsKey([string]$path)) {
                "tracked"
            }
            elseif ($untrackedSet.ContainsKey([string]$path)) {
                "untracked"
            }
            else {
                "absent"
            }
            if ($provenance -ne "tracked") { $provenanceMatch = $false }
            # Wrapper digest optional; if supplied, must match actual bytes.
            if ($path -eq $WrapperRelativePath) {
                if (-not [string]::IsNullOrWhiteSpace($WrapperSha256)) {
                    if ($actualSha -ne $WrapperSha256.ToUpperInvariant()) {
                        $wrapperMatched = $false
                    }
                }
            }
            if (-not $script:CleanHeadInitialFileHashes.ContainsKey([string]$path)) {
                $script:CleanHeadInitialFileHashes[[string]$path] = $actualSha
            }
            $expectedSha = [string]$script:CleanHeadInitialFileHashes[[string]$path]
            if ($actualSha -ne $expectedSha) { $bytesMatch = $false }
            [void]$expectedLines.Add(("{0}={1}" -f $path, $expectedSha))
            [void]$actualLines.Add(("{0}={1}" -f $path, $actualSha))
            [void]$rows.Add([pscustomobject]@{
                Path = [string]$path
                ExpectedSha256 = $expectedSha
                ActualSha256 = $actualSha
                Provenance = $provenance
            })
        }
        $bytesMatch = $bytesMatch -and $wrapperMatched
    }

    $migrationPath = Join-Path $WorkspaceRoot $MigrationRelativePath
    $migrationActualSha = if (Test-Path -LiteralPath $migrationPath -PathType Leaf) {
        (Get-FileHash -LiteralPath $migrationPath -Algorithm SHA256).Hash
    }
    else { "MISSING" }
    $migrationTracked = $trackedSet.ContainsKey($MigrationRelativePath)
    if ($BindingMode -eq "LegacyStaged21") {
        $migrationExpectedSha = $ExpectedMigrationWorktreeSha256
        $migrationMatch = $migrationActualSha -eq $ExpectedMigrationWorktreeSha256
    }
    else {
        if ($null -eq $script:CleanHeadInitialMigrationHash) {
            $script:CleanHeadInitialMigrationHash = $migrationActualSha
        }
        $migrationExpectedSha = [string]$script:CleanHeadInitialMigrationHash
        $migrationMatch = (
            (-not [string]::IsNullOrWhiteSpace($migrationActualSha)) -and
            $migrationActualSha -ne "MISSING" -and
            $migrationTracked -and
            $migrationActualSha -eq $migrationExpectedSha
        )
    }
    $matchesExpected = if ($BindingMode -eq "LegacyStaged21") {
        $bytesMatch -and $provenanceMatch -and $exactSetMatch -and $migrationMatch
    }
    else {
        $bytesMatch -and $provenanceMatch -and $exactSetMatch -and $migrationMatch
    }

    return [pscustomobject]@{
        Rows = @($rows)
        ExpectedManifestSha256 = Get-RpnSha256 ($expectedLines -join "`n")
        ActualManifestSha256 = Get-RpnSha256 ($actualLines -join "`n")
        BytesMatch = $bytesMatch
        ProvenanceMatch = $provenanceMatch
        ExactSetMatch = $exactSetMatch
        Missing = [string[]]$missing
        Extra = [string[]]$extra
        MigrationExpectedSha256 = $migrationExpectedSha
        MigrationActualSha256 = $migrationActualSha
        MigrationMatch = $migrationMatch
        MatchesExpected = $matchesExpected
    }
}

function Write-RpnReviewedManifest {
    param($Snapshot, [string]$Phase)
    Write-Output (
        "SSWCENTER_0014_REVIEWED_MANIFEST phase={0} count=5 expected={1} actual={2} bytes={3} provenance={4} exact_set={5}" -f
        $Phase,
        $Snapshot.ExpectedManifestSha256,
        $Snapshot.ActualManifestSha256,
        [int]$Snapshot.BytesMatch,
        [int]$Snapshot.ProvenanceMatch,
        [int]$Snapshot.ExactSetMatch
    )
    foreach ($row in $Snapshot.Rows) {
        Write-Output (
            "SSWCENTER_0014_REVIEWED_FILE phase={0} path={1} expected={2} actual={3} provenance={4}" -f
            $Phase, $row.Path, $row.ExpectedSha256, $row.ActualSha256, $row.Provenance
        )
    }
    Write-Output (
        "SSWCENTER_0014_REVIEWED_MIGRATION phase={0} path={1} expected={2} actual={3} match={4}" -f
        $Phase,
        $MigrationRelativePath,
        $Snapshot.MigrationExpectedSha256,
        $Snapshot.MigrationActualSha256,
        [int]$Snapshot.MigrationMatch
    )
    if (-not $Snapshot.ExactSetMatch) {
        Write-Output (
            "SSWCENTER_0014_REVIEWED_SET_MISMATCH phase={0} missing={1} extra={2}" -f
            $Phase, ($Snapshot.Missing -join ","), ($Snapshot.Extra -join ",")
        )
    }
}

function Get-RpnListeners {
    try {
        return @(
            Get-NetTCPConnection -State Listen -ErrorAction Stop |
                Select-Object LocalAddress, LocalPort, OwningProcess
        )
    }
    catch {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_LISTENER_ENUM_FAILED" (
            [string]$_.Exception.Message
        )
    }
}

function Assert-RpnPortAvailable {
    param([int]$ListenPort, [string]$Label)
    $listeners = @(Get-RpnListeners | Where-Object { [int]$_.LocalPort -eq $ListenPort })
    if ($listeners.Count -gt 0) {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_PORT_IN_USE" (
            "label={0};port={1};pids={2}" -f $Label, $ListenPort, (($listeners.OwningProcess) -join ",")
        )
    }
}

function Get-RpnArtifactSnapshot {
    $paths = New-Object System.Collections.ArrayList
    foreach ($scanRoot in @(
        (Join-Path $BackendRoot "app"),
        (Join-Path $BackendRoot "alembic"),
        (Join-Path $BackendRoot "tests")
    )) {
        if (-not (Test-Path -LiteralPath $scanRoot -PathType Container)) { continue }
        foreach ($directory in @(
            Get-ChildItem -LiteralPath $scanRoot -Recurse -Force -Directory |
                Where-Object { $_.Name -in @("__pycache__", ".pytest_cache", ".ruff_cache") }
        )) { [void]$paths.Add([System.IO.Path]::GetFullPath($directory.FullName)) }
        foreach ($file in @(
            Get-ChildItem -LiteralPath $scanRoot -Recurse -Force -File -Filter "*.pyc"
        )) { [void]$paths.Add([System.IO.Path]::GetFullPath($file.FullName)) }
    }
    foreach ($path in @(
        (Join-Path $BackendRoot ".pytest_cache"),
        (Join-Path $BackendRoot ".ruff_cache"),
        (Join-Path $FrontendRoot "test-results"),
        (Join-Path $FrontendRoot "playwright-report")
    )) {
        if (Test-Path -LiteralPath $path) {
            [void]$paths.Add([System.IO.Path]::GetFullPath($path))
        }
    }
    return [string[]]@($paths | Sort-Object -Unique)
}

function Remove-RpnNewArtifacts {
    param([string[]]$Baseline)
    $baselineSet = @{}
    foreach ($path in $Baseline) { $baselineSet[[string]$path] = $true }
    $newPaths = @(
        Get-RpnArtifactSnapshot | Where-Object { -not $baselineSet.ContainsKey([string]$_) } |
            Sort-Object { ([string]$_).Length } -Descending
    )
    $allowedRoots = @(
        ([System.IO.Path]::GetFullPath($BackendRoot).TrimEnd("\") + "\"),
        ([System.IO.Path]::GetFullPath($FrontendRoot).TrimEnd("\") + "\")
    )
    foreach ($pathValue in $newPaths) {
        $path = [System.IO.Path]::GetFullPath([string]$pathValue)
        $underAllowedRoot = @(
            $allowedRoots | Where-Object {
                $path.StartsWith($_, [StringComparison]::OrdinalIgnoreCase)
            }
        ).Count -gt 0
        $leaf = Split-Path -Leaf $path
        $allowedLeaf = (
            $leaf -in @("__pycache__", ".pytest_cache", ".ruff_cache", "test-results", "playwright-report") -or
            [System.IO.Path]::GetExtension($path) -eq ".pyc"
        )
        if (-not $underAllowedRoot -or -not $allowedLeaf) {
            $script:HarnessFailure = $true
            Write-Output ("SSWCENTER_0014_HARNESS_ARTIFACT_PATH_UNSAFE: {0}" -f $path)
            continue
        }
        try {
            if (Test-Path -LiteralPath $path -PathType Container) {
                [System.IO.Directory]::Delete($path, $true)
            }
            elseif (Test-Path -LiteralPath $path -PathType Leaf) {
                [System.IO.File]::Delete($path)
            }
        }
        catch {
            $script:HarnessFailure = $true
            Write-Output ("SSWCENTER_0014_HARNESS_ARTIFACT_CLEANUP_FAILED: {0}" -f $_.Exception.Message)
        }
    }
}

function Invoke-RpnPgStart {
    $arguments = @(
        "--pgdata=$DataDirectory", "--log=$(Join-Path $TempRoot 'postgres.log')",
        "--options=-h 127.0.0.1 -p $Port", "start", "--wait"
    )
    try {
        $process = Start-Process `
            -FilePath $PgCtlExe `
            -ArgumentList (ConvertTo-RpnProcessArguments $arguments) `
            -WorkingDirectory $WorkspaceRoot `
            -PassThru `
            -WindowStyle Hidden
    }
    catch {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_POSTGRES_START_LAUNCH_FAILED" (
            [string]$_.Exception.Message
        )
    }
    if (-not $process.WaitForExit(60000)) {
        Stop-RpnProcessTree -RootPid ([int]$process.Id) -Context "pg_ctl-start"
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_POSTGRES_START_TIMEOUT"
    }
    if ([int]$process.ExitCode -ne 0) {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_POSTGRES_START_FAILED" (
            "exit={0}" -f $process.ExitCode
        )
    }
}

function Invoke-RpnPsqlScalar {
    param([string]$User, [string]$Database, [string]$Sql, [string]$Marker)
    $run = Invoke-RpnTimedCommand `
        -FilePath $PsqlExe `
        -TimeoutSec 60 `
        -TimeoutMarker ("{0}_TIMEOUT" -f $Marker) `
        -ArgumentList @(
            "-X", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1", "-p", [string]$Port,
            "-U", $User, "-d", $Database, "-tAc", $Sql
        )
    if ([int]$run.ExitCode -ne 0) {
        Write-RpnCommandEvidence -Result $run -Stage $Marker
        Write-RpnHarnessFailure $Marker
    }
    return ([string]$run.Stdout).Trim()
}

function Invoke-RpnAlembic {
    param([string]$DatabaseUrl, [string[]]$AlembicArguments, [string]$Marker)
    $previous = [Environment]::GetEnvironmentVariable("SSWCENTER_DATABASE_URL", "Process")
    try {
        $env:SSWCENTER_DATABASE_URL = $DatabaseUrl
        $run = Invoke-RpnTimedCommand `
            -FilePath $PythonExe `
            -WorkingDirectory $BackendRoot `
            -TimeoutSec 900 `
            -TimeoutMarker ("{0}_TIMEOUT" -f $Marker) `
            -ArgumentList (@("-m", "alembic", "-c", "alembic.ini") + $AlembicArguments)
    }
    finally {
        if ($null -eq $previous) { Remove-Item Env:SSWCENTER_DATABASE_URL -ErrorAction SilentlyContinue }
        else { $env:SSWCENTER_DATABASE_URL = $previous }
    }
    Write-RpnCommandEvidence -Result $run -Stage $Marker
    if ([int]$run.ExitCode -ne 0) {
        Write-RpnProductFailure $Marker ("exit={0}" -f $run.ExitCode)
    }
}

function Invoke-RpnAlembicOfflineAclContract {
    param([string]$DatabaseUrl)
    $previous = [Environment]::GetEnvironmentVariable("SSWCENTER_DATABASE_URL", "Process")
    try {
        $env:SSWCENTER_DATABASE_URL = $DatabaseUrl
        $run = Invoke-RpnTimedCommand `
            -FilePath $PythonExe `
            -WorkingDirectory $BackendRoot `
            -TimeoutSec 300 `
            -TimeoutMarker "SSWCENTER_0014_HARNESS_OFFLINE_SQL_TIMEOUT" `
            -ArgumentList @(
                "-m", "alembic", "-c", "alembic.ini", "upgrade",
                ("{0}:{1}" -f $BaseRevision, $ExpectedRevision), "--sql"
            )
    }
    finally {
        if ($null -eq $previous) { Remove-Item Env:SSWCENTER_DATABASE_URL -ErrorAction SilentlyContinue }
        else { $env:SSWCENTER_DATABASE_URL = $previous }
    }
    Write-RpnCommandEvidence -Result $run -Stage "alembic_offline_0014"
    if ([int]$run.ExitCode -ne 0) {
        Write-RpnProductFailure "SSWCENTER_0014_OFFLINE_SQL_GENERATION_FAILED" (
            "exit={0}" -f $run.ExitCode
        )
    }
    $offlineSql = ([string]$run.Stdout) -replace '\s+', ' '
    foreach ($requiredSql in @(
        "GRANT USAGE ON SCHEMA erp TO erp_app",
        "GRANT SELECT, INSERT, UPDATE ON TABLE erp.recipient_plan_notification TO erp_app",
        "REVOKE DELETE, TRUNCATE ON TABLE erp.recipient_plan_notification FROM erp_app",
        "GRANT USAGE, SELECT ON SEQUENCE erp.recipient_plan_notification_id_seq TO erp_app",
        "GRANT USAGE ON SCHEMA erp TO erp_backup",
        "GRANT SELECT ON TABLE erp.recipient_plan_notification TO erp_backup",
        "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE erp.recipient_plan_notification FROM erp_backup",
        "GRANT SELECT ON SEQUENCE erp.recipient_plan_notification_id_seq TO erp_backup",
        "REVOKE USAGE ON SEQUENCE erp.recipient_plan_notification_id_seq FROM erp_backup"
    )) {
        if ($offlineSql.IndexOf($requiredSql, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
            Write-RpnProductFailure "SSWCENTER_0014_OFFLINE_ACL_SQL_MISSING" $requiredSql
        }
    }
    Write-Output "SSWCENTER_0014_OFFLINE_ACL_GREEN"
}

function Get-RpnRevision {
    param([string]$Database)
    return Invoke-RpnPsqlScalar `
        -User "erp_owner" `
        -Database $Database `
        -Sql "SELECT version_num FROM erp.alembic_version" `
        -Marker "SSWCENTER_0014_HARNESS_REVISION_QUERY_FAILED"
}

function Start-RpnBackend {
    param([string]$StdoutPath, [string]$StderrPath)
    try {
        return Start-Process `
            -FilePath $PythonExe `
            -ArgumentList (ConvertTo-RpnProcessArguments @(
                "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                "--port", [string]$BackendPort
            )) `
            -WorkingDirectory $BackendRoot `
            -RedirectStandardOutput $StdoutPath `
            -RedirectStandardError $StderrPath `
            -PassThru `
            -WindowStyle Hidden
    }
    catch {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_BACKEND_START_FAILED" (
            [string]$_.Exception.Message
        )
    }
}

function Start-RpnFrontend {
    param([string]$StdoutPath, [string]$StderrPath)
    try {
        return Start-Process `
            -FilePath $NodeExe `
            -ArgumentList (ConvertTo-RpnProcessArguments @(
                $ViteCli, "--config",
                "e2e/recipient-plan-notification-real-pg.vite.config.ts"
            )) `
            -WorkingDirectory $FrontendRoot `
            -RedirectStandardOutput $StdoutPath `
            -RedirectStandardError $StderrPath `
            -PassThru `
            -WindowStyle Hidden
    }
    catch {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_FRONTEND_START_FAILED" (
            [string]$_.Exception.Message
        )
    }
}

function Wait-RpnBackendReady {
    for ($attempt = 1; $attempt -le 120; $attempt++) {
        if ($null -ne $BackendProcess -and $BackendProcess.HasExited) {
            Write-RpnEarlyRuntimeFailure `
                -Stage "backend" `
                -Detail ("exit={0}" -f $BackendProcess.ExitCode) `
                -StdoutPath $BackendStdoutPath `
                -StderrPath $BackendStderrPath
        }
        try {
            $response = Invoke-WebRequest `
                -UseBasicParsing `
                -Uri ("http://127.0.0.1:{0}/health/ready" -f $BackendPort) `
                -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return }
        }
        catch {}
        Start-Sleep -Milliseconds 250
    }
    Write-RpnEarlyRuntimeFailure `
        -Stage "backend" `
        -Detail "health readiness timeout" `
        -StdoutPath $BackendStdoutPath `
        -StderrPath $BackendStderrPath
}

function Wait-RpnFrontendReady {
    for ($attempt = 1; $attempt -le 120; $attempt++) {
        if ($null -ne $FrontendProcess -and $FrontendProcess.HasExited) {
            Write-RpnEarlyRuntimeFailure `
                -Stage "vite" `
                -Detail ("exit={0}" -f $FrontendProcess.ExitCode) `
                -StdoutPath $FrontendStdoutPath `
                -StderrPath $FrontendStderrPath
        }
        try {
            $response = Invoke-WebRequest `
                -UseBasicParsing `
                -Uri ("http://127.0.0.1:{0}/dashboard" -f $FrontendPort) `
                -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return }
        }
        catch {}
        Start-Sleep -Milliseconds 250
    }
    Write-RpnEarlyRuntimeFailure `
        -Stage "vite" `
        -Detail "frontend readiness timeout" `
        -StdoutPath $FrontendStdoutPath `
        -StderrPath $FrontendStderrPath
}

try {
    foreach ($executable in @(
        $GitExe, $PythonExe, $PowerShellExe, $InitDbExe, $PgCtlExe,
        $PgIsReadyExe, $CreateDbExe, $PsqlExe, $NodeExe
    )) {
        if ([string]::IsNullOrWhiteSpace($executable) -or -not (Test-Path -LiteralPath $executable -PathType Leaf)) {
            Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_MISSING_EXECUTABLE" $executable
        }
    }
    foreach ($requiredPath in @(
        (Join-Path $BackendRoot "tests\test_recipient_plan_notification_postgres.py"),
        (Join-Path $FrontendRoot "e2e\recipient-plan-notification-real-pg.spec.ts"),
        (Join-Path $FrontendRoot "e2e\recipient-plan-notification-real-pg.config.ts"),
        (Join-Path $FrontendRoot "e2e\recipient-plan-notification-real-pg.vite.config.ts"),
        $ViteCli,
        $PlaywrightCli
    )) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_REQUIRED_FILE_MISSING" $requiredPath
        }
    }
    if ($ExpectedSha -notmatch '^[0-9a-fA-F]{40}$') {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_EXPECTED_SHA_INVALID" $ExpectedSha
    }
    $ExpectedSha = $ExpectedSha.ToLowerInvariant()
    if ($CandidateMode -eq "LegacyStaged21") {
        if ($ExpectedWrapperSha256 -notmatch '^[0-9a-fA-F]{64}$') {
            Write-RpnHarnessFailure `
                "SSWCENTER_0014_HARNESS_EXPECTED_WRAPPER_SHA256_INVALID" `
                $ExpectedWrapperSha256
        }
    }
    elseif (
        -not [string]::IsNullOrWhiteSpace($ExpectedWrapperSha256) -and
        $ExpectedWrapperSha256 -notmatch '^[0-9a-fA-F]{64}$'
    ) {
        Write-RpnHarnessFailure `
            "SSWCENTER_0014_HARNESS_EXPECTED_WRAPPER_SHA256_INVALID" `
            $ExpectedWrapperSha256
    }
    $ExpectedWrapperSha256 = $ExpectedWrapperSha256.ToUpperInvariant()
    if (@(@($Port, $BackendPort, $FrontendPort) | Sort-Object -Unique).Count -ne 3) {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_PORTS_NOT_UNIQUE"
    }

    $gitRoot = Invoke-RpnGit @("rev-parse", "--show-toplevel")
    if (-not [System.IO.Path]::GetFullPath($gitRoot).Equals(
        $WorkspaceRoot,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_GIT_ROOT_MISMATCH" $gitRoot
    }
    $observedBranch = (Invoke-RpnGit @("branch", "--show-current")).Trim()
    $InitialGitSnapshot = Get-RpnGitSnapshot
    if ($InitialGitSnapshot.Head -ne $ExpectedSha) {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_EXACT_SHA_MISMATCH" (
            "expected={0};actual={1}" -f $ExpectedSha, $InitialGitSnapshot.Head
        )
    }
    if ($CandidateMode -eq "LegacyStaged21") {
        if (-not $WorkspaceRoot.Equals(
            $ExpectedWorkspaceRoot,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_PRIMARY_ROOT_REQUIRED" $WorkspaceRoot
        }
        if ($observedBranch -ne $ExpectedBranch) {
            Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_BRANCH_MISMATCH" (
                "expected={0};actual={1}" -f $ExpectedBranch, $observedBranch
            )
        }
        $expectedSet = @{}
        foreach ($path in $ExpectedStagedPaths) { $expectedSet[$path] = $true }
        $actualSet = @{}
        foreach ($path in $InitialGitSnapshot.StagedPaths) { $actualSet[$path] = $true }
        $missing = @($ExpectedStagedPaths | Where-Object { -not $actualSet.ContainsKey($_) })
        $extra = @($InitialGitSnapshot.StagedPaths | Where-Object { -not $expectedSet.ContainsKey($_) })
        if (
            $InitialGitSnapshot.StagedCount -ne 21 -or
            $missing.Count -ne 0 -or
            $extra.Count -ne 0 -or
            $InitialGitSnapshot.StagedManifestSha256 -ne $ExpectedStagedManifestSha256
        ) {
            Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_STAGED_21_MISMATCH" (
                "count={0};missing={1};extra={2};manifest={3}" -f
                $InitialGitSnapshot.StagedCount,
                ($missing -join ","),
                ($extra -join ","),
                $InitialGitSnapshot.StagedManifestSha256
            )
        }
    }
    elseif (
        $InitialGitSnapshot.StatusCount -ne 0 -or
        $InitialGitSnapshot.StagedCount -ne 0
    ) {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_CLEAN_HEAD_REQUIRED" (
            "status={0};staged={1}" -f
            $InitialGitSnapshot.StatusCount,
            $InitialGitSnapshot.StagedCount
        )
    }
    $InitialReviewedManifest = Get-RpnReviewedManifest `
        -BindingMode $CandidateMode `
        -WrapperSha256 $ExpectedWrapperSha256
    Write-RpnReviewedManifest -Snapshot $InitialReviewedManifest -Phase "preflight"
    if (-not $InitialReviewedManifest.MatchesExpected) {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_REVIEWED_BYTES_MISMATCH" (
            "expected={0};actual={1};bytes={2};provenance={3};exact_set={4};migration={5}" -f
            $InitialReviewedManifest.ExpectedManifestSha256,
            $InitialReviewedManifest.ActualManifestSha256,
            [int]$InitialReviewedManifest.BytesMatch,
            [int]$InitialReviewedManifest.ProvenanceMatch,
            [int]$InitialReviewedManifest.ExactSetMatch,
            [int]$InitialReviewedManifest.MigrationMatch
        )
    }
    Write-Output (
        "SSWCENTER_0014_PREFLIGHT_GIT mode={0} cwd={1} branch={2} head={3} status={4} staged={5} manifest={6} index={7}" -f
        $CandidateMode,
        $WorkspaceRoot,
        $observedBranch,
        $InitialGitSnapshot.Head,
        $InitialGitSnapshot.StatusCount,
        $InitialGitSnapshot.StagedCount,
        $InitialGitSnapshot.StagedManifestSha256,
        $InitialGitSnapshot.FullIndexSha256
    )

    $preflightProcesses = Get-RpnProcessSnapshot
    foreach ($processRow in @(
        $preflightProcesses |
            Where-Object { $_.Name -match $OwnedProcessNamePattern }
    )) {
        $BeforeProcessSet[(Get-RpnProcessIdentity $processRow)] = $true
    }
    $ProcessBaselineCaptured = $true
    $BeforeArtifacts = @(Get-RpnArtifactSnapshot)
    $ArtifactBaselineCaptured = $true
    Assert-RpnPortAvailable -ListenPort $Port -Label "postgres"
    Assert-RpnPortAvailable -ListenPort $BackendPort -Label "backend"
    Assert-RpnPortAvailable -ListenPort $FrontendPort -Label "frontend"
    Write-Output (
        "SSWCENTER_0014_PREFLIGHT_PORTS postgres={0} backend={1} frontend={2}" -f
        $Port, $BackendPort, $FrontendPort
    )

    if ($PreflightOnly) {
        $PreflightOnlyCompleted = $true
        throw $PreflightOnlySentinel
    }

    if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_LOCALAPPDATA_MISSING"
    }
    $tempParent = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Temp"))
    if (-not (Test-Path -LiteralPath $tempParent -PathType Container)) {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_TEMP_PARENT_MISSING" $tempParent
    }
    $TempRoot = [System.IO.Path]::GetFullPath(
        (Join-Path $tempParent ("sswcenter-0014-pg-" + [Guid]::NewGuid().ToString("N")))
    )
    $ExpectedTempPrefix = $tempParent.TrimEnd("\") + "\"
    if (
        -not $TempRoot.StartsWith($ExpectedTempPrefix, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Split-Path -Leaf $TempRoot).StartsWith("sswcenter-0014-pg-", [StringComparison]::Ordinal)
    ) {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_UNSAFE_TEMP_ROOT" $TempRoot
    }
    $DataDirectory = Join-Path $TempRoot "data"
    $OutputRoot = Join-Path $TempRoot "output"
    $RuntimeDataRoot = Join-Path $TempRoot "sswcenter-0014-runtime"
    New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
    New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $RuntimeDataRoot -Force | Out-Null
    Write-Output ("SSWCENTER_0014_PRIVATE_TEMP_ROOT={0}" -f $TempRoot)

    $env:TEMP = $TempRoot
    $env:TMP = $TempRoot
    $env:TMPDIR = $TempRoot
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTEST_ADDOPTS = ""
    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_DATA_ROOT = $RuntimeDataRoot
    $env:SSWCENTER_0014_REAL_PG = "1"
    $env:SSWCENTER_PIN_PEPPER = "0014-test-pin-pepper"
    $env:SSWCENTER_PIN_LOOKUP_KEY = "0014-test-pin-lookup"
    $env:SSWCENTER_CSRF_SIGNING_KEY = "0014-test-csrf"
    $env:SSWCENTER_RESIDENT_NUMBER_KEY_V1 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
    $env:SSWCENTER_RESIDENT_NUMBER_LOOKUP_KEY = "YWJjZGVmMDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODk="
    $env:SSWCENTER_RESIDENT_NUMBER_ACTIVE_KEY_VERSION = "1"
    $env:SSWCENTER_DEV_LOGIN_BYPASS = "false"
    $env:VITE_DEV_LOGIN_BYPASS = "false"

    $initRun = Invoke-RpnTimedCommand `
        -FilePath $InitDbExe `
        -TimeoutSec 180 `
        -TimeoutMarker "SSWCENTER_0014_HARNESS_INITDB_TIMEOUT" `
        -ArgumentList @(
            "--pgdata=$DataDirectory", "--username=postgres", "--auth=trust",
            "--encoding=UTF8", "--locale=C"
        )
    Write-Output ("SSWCENTER_0014_STAGE_INITDB_EXIT={0}" -f $initRun.ExitCode)
    if ([int]$initRun.ExitCode -ne 0) {
        Write-RpnCommandEvidence -Result $initRun -Stage "initdb"
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_INITDB_FAILED"
    }
    Invoke-RpnPgStart
    $ClusterStarted = $true

    $readyRun = Invoke-RpnTimedCommand `
        -FilePath $PgIsReadyExe `
        -TimeoutSec 30 `
        -TimeoutMarker "SSWCENTER_0014_HARNESS_PG_READY_TIMEOUT" `
        -ArgumentList @(
            "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres",
            "-d", "postgres", "-t", "15"
        )
    if ([int]$readyRun.ExitCode -ne 0) {
        Write-RpnCommandEvidence -Result $readyRun -Stage "pg_ready"
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_POSTGRES_NOT_READY"
    }

    $runId = [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $OwnerPassword = "rpnOwner$runId"
    $AppPassword = "rpnApp$runId"
    $BackupPassword = "rpnBackup$runId"
    $DatabaseName = "sswcenter_0014_${runId}_test"
    $E2EDatabaseName = "sswcenter_0014_e2e_${runId}_test"
    $roleSql = (
        "CREATE ROLE erp_owner LOGIN PASSWORD '$OwnerPassword'; " +
        "CREATE ROLE erp_app LOGIN PASSWORD '$AppPassword'; " +
        "CREATE ROLE erp_backup LOGIN PASSWORD '$BackupPassword';"
    )
    $roleRun = Invoke-RpnTimedCommand `
        -FilePath $PsqlExe `
        -TimeoutSec 30 `
        -TimeoutMarker "SSWCENTER_0014_HARNESS_ROLE_CREATE_TIMEOUT" `
        -ArgumentList @(
            "-X", "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1", "-p", [string]$Port,
            "-U", "postgres", "-d", "postgres", "-c", $roleSql
        )
    if ([int]$roleRun.ExitCode -ne 0) {
        Write-RpnCommandEvidence -Result $roleRun -Stage "role_setup"
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_ROLE_CREATE_FAILED"
    }
    foreach ($database in @($DatabaseName, $E2EDatabaseName)) {
        $createRun = Invoke-RpnTimedCommand `
            -FilePath $CreateDbExe `
            -TimeoutSec 30 `
            -TimeoutMarker "SSWCENTER_0014_HARNESS_DATABASE_CREATE_TIMEOUT" `
            -ArgumentList @(
                "-h", "127.0.0.1", "-p", [string]$Port, "-U", "postgres",
                "-O", "erp_owner", $database
            )
        if ([int]$createRun.ExitCode -ne 0) {
            Write-RpnCommandEvidence -Result $createRun -Stage "database_create"
            Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_DATABASE_CREATE_FAILED" $database
        }
    }

    $OwnerDatabaseUrl = "postgresql+psycopg://erp_owner:$OwnerPassword@127.0.0.1:$Port/$DatabaseName"
    $AppDatabaseUrl = "postgresql+psycopg://erp_app:$AppPassword@127.0.0.1:$Port/$DatabaseName"
    $E2EOwnerDatabaseUrl = "postgresql+psycopg://erp_owner:$OwnerPassword@127.0.0.1:$Port/$E2EDatabaseName"
    $E2EAppDatabaseUrl = "postgresql+psycopg://erp_app:$AppPassword@127.0.0.1:$Port/$E2EDatabaseName"

    $previousDatabaseUrl = [Environment]::GetEnvironmentVariable(
        "SSWCENTER_DATABASE_URL",
        "Process"
    )
    try {
        $env:SSWCENTER_DATABASE_URL = $OwnerDatabaseUrl
        $headsRun = Invoke-RpnTimedCommand `
            -FilePath $PythonExe `
            -WorkingDirectory $BackendRoot `
            -TimeoutSec 60 `
            -TimeoutMarker "SSWCENTER_0014_HARNESS_ALEMBIC_HEADS_TIMEOUT" `
            -ArgumentList @("-m", "alembic", "-c", "alembic.ini", "heads")
    }
    finally {
        if ($null -eq $previousDatabaseUrl) {
            Remove-Item Env:SSWCENTER_DATABASE_URL -ErrorAction SilentlyContinue
        }
        else {
            $env:SSWCENTER_DATABASE_URL = $previousDatabaseUrl
        }
    }
    if ([int]$headsRun.ExitCode -ne 0) {
        Write-RpnCommandEvidence -Result $headsRun -Stage "alembic_heads"
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_ALEMBIC_HEADS_FAILED"
    }
    $headMatches = [regex]::Matches(
        ([string]$headsRun.Stdout),
        '(?m)^([0-9A-Za-z_]+)\s+\(head\)\s*$'
    )
    $headIds = @($headMatches | ForEach-Object { $_.Groups[1].Value })
    if ($headIds.Count -ne 1 -or $headIds[0] -ne $ExpectedRevision) {
        Write-RpnProductFailure "SSWCENTER_0014_ALEMBIC_HEAD_MISMATCH" (
            "expected={0};actual={1}" -f $ExpectedRevision, ($headIds -join ",")
        )
    }
    Write-Output ("SSWCENTER_0014_ALEMBIC_HEAD={0}" -f $headIds[0])
    Invoke-RpnAlembicOfflineAclContract -DatabaseUrl $OwnerDatabaseUrl

    Invoke-RpnAlembic `
        -DatabaseUrl $OwnerDatabaseUrl `
        -AlembicArguments @("upgrade", $BaseRevision) `
        -Marker "SSWCENTER_0014_MIGRATION_BASE_UPGRADE_FAILED"
    $baseObserved = Get-RpnRevision -Database $DatabaseName
    if ($baseObserved -ne $BaseRevision) {
        Write-RpnProductFailure "SSWCENTER_0014_MIGRATION_BASE_REVISION_MISMATCH" $baseObserved
    }
    $baseTableAbsent = Invoke-RpnPsqlScalar `
        -User "erp_owner" -Database $DatabaseName `
        -Sql "SELECT to_regclass('erp.recipient_plan_notification') IS NULL" `
        -Marker "SSWCENTER_0014_HARNESS_BASE_TABLE_QUERY_FAILED"
    if ($baseTableAbsent -ne "t") {
        Write-RpnProductFailure "SSWCENTER_0014_MIGRATION_BASE_TABLE_PRESENT"
    }
    Write-Output ("SSWCENTER_0014_STAGE_BASE revision={0} table_absent=1" -f $baseObserved)

    Invoke-RpnAlembic `
        -DatabaseUrl $OwnerDatabaseUrl `
        -AlembicArguments @("upgrade", $ExpectedRevision) `
        -Marker "SSWCENTER_0014_MIGRATION_UPGRADE_FAILED"
    $upgradeObserved = Get-RpnRevision -Database $DatabaseName
    if ($upgradeObserved -ne $ExpectedRevision) {
        Write-RpnProductFailure "SSWCENTER_0014_MIGRATION_UPGRADE_REVISION_MISMATCH" $upgradeObserved
    }
    Write-Output ("SSWCENTER_0014_STAGE_UPGRADE revision={0}" -f $upgradeObserved)

    Invoke-RpnAlembic `
        -DatabaseUrl $OwnerDatabaseUrl `
        -AlembicArguments @("downgrade", $BaseRevision) `
        -Marker "SSWCENTER_0014_MIGRATION_DOWNGRADE_FAILED"
    $downgradeObserved = Get-RpnRevision -Database $DatabaseName
    $downgradeTableAbsent = Invoke-RpnPsqlScalar `
        -User "erp_owner" -Database $DatabaseName `
        -Sql "SELECT to_regclass('erp.recipient_plan_notification') IS NULL" `
        -Marker "SSWCENTER_0014_HARNESS_DOWNGRADE_TABLE_QUERY_FAILED"
    if ($downgradeObserved -ne $BaseRevision -or $downgradeTableAbsent -ne "t") {
        Write-RpnProductFailure "SSWCENTER_0014_MIGRATION_DOWNGRADE_CONTRACT_FAILED" (
            "revision={0};table_absent={1}" -f $downgradeObserved, $downgradeTableAbsent
        )
    }
    Write-Output ("SSWCENTER_0014_STAGE_DOWNGRADE revision={0} table_absent=1" -f $downgradeObserved)

    Invoke-RpnAlembic `
        -DatabaseUrl $OwnerDatabaseUrl `
        -AlembicArguments @("upgrade", $ExpectedRevision) `
        -Marker "SSWCENTER_0014_MIGRATION_REUPGRADE_FAILED"
    $reupgradeObserved = Get-RpnRevision -Database $DatabaseName
    if ($reupgradeObserved -ne $ExpectedRevision) {
        Write-RpnProductFailure "SSWCENTER_0014_MIGRATION_REUPGRADE_REVISION_MISMATCH" $reupgradeObserved
    }
    Write-Output ("SSWCENTER_0014_STAGE_REUPGRADE revision={0}" -f $reupgradeObserved)

    $env:SSWCENTER_DATABASE_URL = $AppDatabaseUrl
    $env:SSWCENTER_OWNER_DATABASE_URL = $OwnerDatabaseUrl
    $env:SSWCENTER_APP_DATABASE_URL = $AppDatabaseUrl
    $env:SSWCENTER_0014_OWNER_DATABASE_URL = $OwnerDatabaseUrl
    $env:SSWCENTER_0014_APP_DATABASE_URL = $AppDatabaseUrl
    $pytestRun = Invoke-RpnTimedCommand `
        -FilePath $PythonExe `
        -WorkingDirectory $BackendRoot `
        -TimeoutSec 1200 `
        -TimeoutMarker "SSWCENTER_0014_HARNESS_PYTEST_TIMEOUT" `
        -ArgumentList @(
            "-m", "pytest", "-vv", "-s", "--tb=line", "--color=no",
            "-p", "no:cacheprovider", "tests/test_recipient_plan_notification_postgres.py"
        )
    Write-RpnCommandEvidence -Result $pytestRun -Stage "backend_pytest"
    $pytestText = ([string]$pytestRun.Stdout) + "`n" + ([string]$pytestRun.Stderr)
    $backendPassedMatches = [regex]::Matches($pytestText, '(?m)(\d+)\s+passed')
    $backendFailedMatches = [regex]::Matches($pytestText, '(?m)(\d+)\s+failed')
    $backendPassed = if ($backendPassedMatches.Count -gt 0) {
        [int]$backendPassedMatches[$backendPassedMatches.Count - 1].Groups[1].Value
    }
    else { 0 }
    $backendFailed = if ($backendFailedMatches.Count -gt 0) {
        [int]$backendFailedMatches[$backendFailedMatches.Count - 1].Groups[1].Value
    }
    else { 0 }
    Write-Output ("SSWCENTER_0014_STAGE_BACKEND_EXIT={0}" -f $pytestRun.ExitCode)
    Write-Output (
        "SSWCENTER_0014_BACKEND_COUNTS passed={0} failed={1} expected=6" -f
        $backendPassed, $backendFailed
    )
    if ([int]$pytestRun.ExitCode -eq 0) {
        if ($backendPassed -ne 6 -or $backendFailed -ne 0) {
            Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_BACKEND_COUNT_MISMATCH" (
                "passed={0};failed={1}" -f $backendPassed, $backendFailed
            )
        }
        foreach ($marker in @(
            "SSWCENTER_0014_CATALOG_ACL_GREEN",
            "SSWCENTER_0014_BACKEND_API_GREEN",
            "SSWCENTER_0014_AUTH_ERROR_GREEN"
        )) {
            if ([regex]::Matches($pytestText, [regex]::Escape($marker)).Count -ne 1) {
                Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_BACKEND_MARKER_COUNT" $marker
            }
        }
    }
    elseif ($pytestText -match 'collected\s+6\s+items?') {
        $script:ProductFailure = $true
        Write-Output "SSWCENTER_0014_STAGE_BACKEND_PRODUCT_RED"
    }
    else {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_BACKEND_COLLECTION_FAILED" (
            "exit={0}" -f $pytestRun.ExitCode
        )
    }

    Invoke-RpnAlembic `
        -DatabaseUrl $E2EOwnerDatabaseUrl `
        -AlembicArguments @("upgrade", $ExpectedRevision) `
        -Marker "SSWCENTER_0014_E2E_MIGRATION_UPGRADE_FAILED"
    $e2eRevision = Get-RpnRevision -Database $E2EDatabaseName
    if ($e2eRevision -ne $ExpectedRevision) {
        Write-RpnProductFailure "SSWCENTER_0014_E2E_MIGRATION_REVISION_MISMATCH" $e2eRevision
    }

    $env:SSWCENTER_DATABASE_URL = $E2EAppDatabaseUrl
    $env:SSWCENTER_OWNER_DATABASE_URL = $E2EOwnerDatabaseUrl
    $env:SSWCENTER_APP_DATABASE_URL = $E2EAppDatabaseUrl
    $env:SSWCENTER_0014_OWNER_DATABASE_URL = $E2EOwnerDatabaseUrl
    $env:SSWCENTER_0014_APP_DATABASE_URL = $E2EAppDatabaseUrl
    $env:SSWCENTER_0014_REAL_E2E = "1"
    $env:SSWCENTER_0014_E2E_PIN = "314159"
    $env:SSWCENTER_E2E_BACKEND_PORT = [string]$BackendPort
    $env:SSWCENTER_E2E_FRONTEND_PORT = [string]$FrontendPort
    $env:SSWCENTER_0014_VITE_CACHE_DIR = Join-Path $OutputRoot "vite-cache"
    $env:SSWCENTER_0014_PLAYWRIGHT_OUTPUT_DIR = Join-Path $OutputRoot "playwright"

    $BackendStdoutPath = Join-Path $OutputRoot "backend.stdout.log"
    $BackendStderrPath = Join-Path $OutputRoot "backend.stderr.log"
    $BackendProcess = Start-RpnBackend `
        -StdoutPath $BackendStdoutPath `
        -StderrPath $BackendStderrPath
    Wait-RpnBackendReady
    Write-Output "SSWCENTER_0014_STAGE_BACKEND_READY=1"

    $FrontendStdoutPath = Join-Path $OutputRoot "frontend.stdout.log"
    $FrontendStderrPath = Join-Path $OutputRoot "frontend.stderr.log"
    $FrontendProcess = Start-RpnFrontend `
        -StdoutPath $FrontendStdoutPath `
        -StderrPath $FrontendStderrPath
    Wait-RpnFrontendReady
    Write-Output "SSWCENTER_0014_STAGE_FRONTEND_READY=1"

    New-Item `
        -ItemType Directory `
        -Path $env:SSWCENTER_0014_PLAYWRIGHT_OUTPUT_DIR `
        -Force | Out-Null
    $e2eRun = Invoke-RpnTimedCommand `
        -FilePath $NodeExe `
        -WorkingDirectory $FrontendRoot `
        -TimeoutSec 1200 `
        -TimeoutMarker "SSWCENTER_0014_HARNESS_PLAYWRIGHT_TIMEOUT" `
        -ArgumentList @(
            $PlaywrightCli, "test",
            "--config=e2e/recipient-plan-notification-real-pg.config.ts",
            "recipient-plan-notification-real-pg.spec.ts",
            "--project=chromium-1440x1000", "--workers=1", "--reporter=line"
        )
    Write-RpnCommandEvidence -Result $e2eRun -Stage "playwright"
    $e2eText = ([string]$e2eRun.Stdout) + "`n" + ([string]$e2eRun.Stderr)
    $e2eGreenCount = [regex]::Matches(
        $e2eText,
        "SSWCENTER_0014_E2E_GREEN"
    ).Count
    $e2ePassedMatches = [regex]::Matches($e2eText, '(?m)(\d+)\s+passed')
    $e2ePassed = if ($e2ePassedMatches.Count -gt 0) {
        [int]$e2ePassedMatches[$e2ePassedMatches.Count - 1].Groups[1].Value
    }
    else { 0 }
    Write-Output (
        "SSWCENTER_0014_STAGE_E2E exit={0} passed={1} green_markers={2} workers=1" -f
        $e2eRun.ExitCode, $e2ePassed, $e2eGreenCount
    )
    if (
        [int]$e2eRun.ExitCode -eq 0 -and
        $e2ePassed -eq 1 -and
        $e2eGreenCount -eq 1
    ) {
        Write-Output "SSWCENTER_0014_STAGE_E2E_OK=1"
    }
    elseif (
        $e2eText -match "Executable doesn't exist|browserType\.launch|ECONNREFUSED|net::ERR_|Cannot find module"
    ) {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_E2E_INFRASTRUCTURE_FAILED" (
            "exit={0}" -f $e2eRun.ExitCode
        )
    }
    elseif ([int]$e2eRun.ExitCode -ne 0) {
        $script:ProductFailure = $true
        Write-Output "SSWCENTER_0014_STAGE_E2E_PRODUCT_RED"
    }
    else {
        Write-RpnHarnessFailure "SSWCENTER_0014_HARNESS_E2E_MARKER_COUNT" (
            "expected=1;actual={0}" -f $e2eGreenCount
        )
    }
    $AllStagesAttempted = $true
}
catch {
    $ScriptExitCode = 1
    $message = [string]$_.Exception.Message
    if (
        $PreflightOnly -and
        $PreflightOnlyCompleted -and
        $message -eq $PreflightOnlySentinel
    ) {
        $ScriptExitCode = 0
    }
    else {
        try {
            if ($null -ne $BackendStdoutPath -or $null -ne $BackendStderrPath) {
                Write-RpnRuntimeLogEvidence `
                    -Stage "backend" `
                    -StdoutPath $BackendStdoutPath `
                    -StderrPath $BackendStderrPath
            }
            if ($null -ne $FrontendStdoutPath -or $null -ne $FrontendStderrPath) {
                Write-RpnRuntimeLogEvidence `
                    -Stage "vite" `
                    -StdoutPath $FrontendStdoutPath `
                    -StderrPath $FrontendStderrPath
            }
        }
        catch {
            $script:HarnessFailure = $true
            Write-Output (
                "SSWCENTER_0014_HARNESS_RUNTIME_DIAGNOSTIC_FAILED: {0}" -f
                (Protect-RpnEvidenceText ([string]$_.Exception.Message))
            )
        }
        if ($script:HarnessFailure -or $message -match "SSWCENTER_0014_HARNESS_") {
            Write-Output ("SSWCENTER_0014_WRAPPER_HARNESS_FAILURE: {0}" -f $message)
        }
        elseif ($script:ProductFailure) {
            Write-Output ("SSWCENTER_0014_WRAPPER_PRODUCT_FAILURE: {0}" -f $message)
        }
        else {
            $script:HarnessFailure = $true
            Write-Output ("SSWCENTER_0014_WRAPPER_HARNESS_FAILURE: {0}" -f $message)
        }
    }
}
finally {
    if ($null -ne $FrontendProcess) {
        try {
            if (-not $FrontendProcess.HasExited) {
                Stop-RpnProcessTree -RootPid ([int]$FrontendProcess.Id) -Context "vite"
            }
        }
        catch {
            $script:HarnessFailure = $true
            Write-Output ("SSWCENTER_0014_HARNESS_FRONTEND_CLEANUP_FAILED: {0}" -f $_.Exception.Message)
        }
    }
    if ($null -ne $BackendProcess) {
        try {
            if (-not $BackendProcess.HasExited) {
                Stop-RpnProcessTree -RootPid ([int]$BackendProcess.Id) -Context "uvicorn"
            }
        }
        catch {
            $script:HarnessFailure = $true
            Write-Output ("SSWCENTER_0014_HARNESS_BACKEND_CLEANUP_FAILED: {0}" -f $_.Exception.Message)
        }
    }
    if ($ClusterStarted -and $null -ne $DataDirectory) {
        try {
            $stopRun = Invoke-RpnTimedCommand `
                -FilePath $PgCtlExe `
                -TimeoutSec 60 `
                -TimeoutMarker "SSWCENTER_0014_HARNESS_POSTGRES_STOP_TIMEOUT" `
                -ArgumentList @(
                    "--pgdata=$DataDirectory", "stop", "--mode=immediate", "--wait"
                )
            Write-Output ("SSWCENTER_0014_STAGE_POSTGRES_STOP_EXIT={0}" -f $stopRun.ExitCode)
            if ([int]$stopRun.ExitCode -ne 0) {
                $script:HarnessFailure = $true
                Write-RpnCommandEvidence -Result $stopRun -Stage "postgres_stop"
                Write-Output "SSWCENTER_0014_HARNESS_POSTGRES_STOP_FAILED"
            }
        }
        catch {
            $script:HarnessFailure = $true
            Write-Output ("SSWCENTER_0014_HARNESS_POSTGRES_STOP_FAILED: {0}" -f $_.Exception.Message)
        }
        $ClusterStarted = $false
    }
    Start-Sleep -Milliseconds 500

    if ($ProcessBaselineCaptured) {
        try {
            $cleanupSnapshot = Get-RpnProcessSnapshot
            $ownedProcesses = @(
                $cleanupSnapshot | Where-Object {
                    if ($_.Name -notmatch $OwnedProcessNamePattern) {
                        return $false
                    }
                    $identity = Get-RpnProcessIdentity $_
                    $isNew = -not $BeforeProcessSet.ContainsKey($identity)
                    $commandLine = [string]$_.CommandLine
                    $ownedSignature = (
                        (
                            $null -ne $TempRoot -and
                            $commandLine.IndexOf(
                                $TempRoot,
                                [StringComparison]::OrdinalIgnoreCase
                            ) -ge 0
                        ) -or
                        $commandLine -match ("--port\s+{0}\b" -f $BackendPort) -or
                        $commandLine -match ("--port\s+{0}\b" -f $FrontendPort) -or
                        $commandLine -match "recipient-plan-notification-real-pg"
                    )
                    $isNew -and $ownedSignature
                }
            )
            foreach ($ownedProcess in $ownedProcesses) {
                if ([int]$ownedProcess.ProcessId -ne $PID) {
                    try {
                        Stop-RpnProcessTree `
                            -RootPid ([int]$ownedProcess.ProcessId) `
                            -Context "owned-residual"
                    }
                    catch {
                        $script:HarnessFailure = $true
                        Write-Output ("SSWCENTER_0014_HARNESS_OWNED_PROCESS_CLEANUP_FAILED: {0}" -f $_.Exception.Message)
                    }
                }
            }
        }
        catch {
            $script:HarnessFailure = $true
            Write-Output ("SSWCENTER_0014_HARNESS_PROCESS_CLEANUP_FAILED: {0}" -f $_.Exception.Message)
        }
    }
    Start-Sleep -Milliseconds 500

    try {
        $listeners = Get-RpnListeners
        $ListenerResidual = @(
            $listeners | Where-Object {
                [int]$_.LocalPort -in @($Port, $BackendPort, $FrontendPort)
            }
        ).Count
    }
    catch {
        $script:HarnessFailure = $true
        $ListenerResidual = 1
    }
    if ($ProcessBaselineCaptured) {
        try {
            $verificationSnapshot = Get-RpnProcessSnapshot
            $ProcessResidual = @(
                $verificationSnapshot | Where-Object {
                    if ($_.Name -notmatch $OwnedProcessNamePattern) {
                        return $false
                    }
                    $identity = Get-RpnProcessIdentity $_
                    $isNew = -not $BeforeProcessSet.ContainsKey($identity)
                    $commandLine = [string]$_.CommandLine
                    $ownedSignature = (
                        (
                            $null -ne $TempRoot -and
                            $commandLine.IndexOf(
                                $TempRoot,
                                [StringComparison]::OrdinalIgnoreCase
                            ) -ge 0
                        ) -or
                        $commandLine -match ("--port\s+{0}\b" -f $BackendPort) -or
                        $commandLine -match ("--port\s+{0}\b" -f $FrontendPort) -or
                        $commandLine -match "recipient-plan-notification-real-pg"
                    )
                    $isNew -and $ownedSignature
                }
            ).Count
        }
        catch {
            $script:HarnessFailure = $true
            $ProcessResidual = 1
        }
    }
    else {
        $script:HarnessFailure = $true
        $ProcessResidual = 1
        Write-Output "SSWCENTER_0014_HARNESS_PROCESS_BASELINE_UNAVAILABLE"
    }

    if ($ArtifactBaselineCaptured) {
        try {
            Remove-RpnNewArtifacts -Baseline $BeforeArtifacts
            $baselineArtifactSet = @{}
            foreach ($path in $BeforeArtifacts) { $baselineArtifactSet[[string]$path] = $true }
            $ArtifactResidual = @(
                Get-RpnArtifactSnapshot | Where-Object {
                    -not $baselineArtifactSet.ContainsKey([string]$_)
                }
            ).Count
        }
        catch {
            $script:HarnessFailure = $true
            $ArtifactResidual = 1
            Write-Output ("SSWCENTER_0014_HARNESS_ARTIFACT_POSTCHECK_FAILED: {0}" -f $_.Exception.Message)
        }
    }
    else {
        $script:HarnessFailure = $true
        $ArtifactResidual = 1
        Write-Output "SSWCENTER_0014_HARNESS_ARTIFACT_BASELINE_UNAVAILABLE"
    }

    if ($null -ne $TempRoot -and (Test-Path -LiteralPath $TempRoot)) {
        try {
            $resolved = [System.IO.Path]::GetFullPath($TempRoot)
            $leaf = Split-Path -Leaf $resolved
            if (
                -not $resolved.StartsWith($ExpectedTempPrefix, [StringComparison]::OrdinalIgnoreCase) -or
                -not $leaf.StartsWith("sswcenter-0014-pg-", [StringComparison]::Ordinal)
            ) {
                $script:HarnessFailure = $true
                Write-Output "SSWCENTER_0014_HARNESS_UNSAFE_TEMP_CLEANUP_PATH"
            }
            else {
                $removed = $false
                for ($attempt = 1; $attempt -le 3 -and -not $removed; $attempt++) {
                    try {
                        [System.IO.Directory]::Delete($resolved, $true)
                        $removed = $true
                    }
                    catch {
                        Start-Sleep -Seconds $attempt
                    }
                }
                if (-not $removed) {
                    $script:HarnessFailure = $true
                    Write-Output "SSWCENTER_0014_HARNESS_TEMP_CLEANUP_FAILED"
                }
            }
        }
        catch {
            $script:HarnessFailure = $true
            Write-Output ("SSWCENTER_0014_HARNESS_TEMP_CLEANUP_FAILED: {0}" -f $_.Exception.Message)
        }
    }
    if ($null -ne $TempRoot -and (Test-Path -LiteralPath $TempRoot)) { $TempResidual = 1 }

    if ($null -ne $InitialGitSnapshot) {
        try {
            $finalGit = Get-RpnGitSnapshot
            if ($null -ne $InitialReviewedManifest) {
                $finalReviewedManifest = Get-RpnReviewedManifest `
                    -BindingMode $CandidateMode `
                    -WrapperSha256 $ExpectedWrapperSha256
                Write-RpnReviewedManifest `
                    -Snapshot $finalReviewedManifest `
                    -Phase "postflight"
                if (
                    -not $finalReviewedManifest.MatchesExpected -or
                    $finalReviewedManifest.ActualManifestSha256 -ne
                        $InitialReviewedManifest.ActualManifestSha256 -or
                    $finalReviewedManifest.MigrationActualSha256 -ne
                        $InitialReviewedManifest.MigrationActualSha256
                ) {
                    $script:HarnessFailure = $true
                    $GitResidual = 1
                    Write-Output "SSWCENTER_0014_HARNESS_REVIEWED_BYTES_POSTFLIGHT_MISMATCH"
                }
            }
            if (
                $finalGit.Head -ne $InitialGitSnapshot.Head -or
                $finalGit.StatusSha256 -ne $InitialGitSnapshot.StatusSha256 -or
                $finalGit.WorkingDiffSha256 -ne $InitialGitSnapshot.WorkingDiffSha256 -or
                $finalGit.UntrackedManifestSha256 -ne $InitialGitSnapshot.UntrackedManifestSha256
            ) { $GitResidual = 1 }
            if (
                $finalGit.FullIndexSha256 -ne $InitialGitSnapshot.FullIndexSha256 -or
                $finalGit.StagedManifestSha256 -ne $InitialGitSnapshot.StagedManifestSha256 -or
                $finalGit.CachedDiffSha256 -ne $InitialGitSnapshot.CachedDiffSha256 -or
                (
                    $CandidateMode -eq "LegacyStaged21" -and
                    $finalGit.StagedCount -ne 21
                ) -or
                (
                    $CandidateMode -eq "CleanHead" -and
                    $finalGit.StagedCount -ne 0
                )
            ) { $IndexResidual = 1 }
            Write-Output (
                "SSWCENTER_0014_POST_GIT head={0} status={1} staged={2} manifest={3} index={4}" -f
                $finalGit.Head,
                $finalGit.StatusCount,
                $finalGit.StagedCount,
                $finalGit.StagedManifestSha256,
                $finalGit.FullIndexSha256
            )
        }
        catch {
            $script:HarnessFailure = $true
            $GitResidual = 1
            $IndexResidual = 1
            Write-Output ("SSWCENTER_0014_HARNESS_FINAL_GIT_CHECK_FAILED: {0}" -f $_.Exception.Message)
        }
    }

    Restore-RpnEnvironment
    Write-Output (
        "SSWCENTER_0014_POSTFLIGHT listener={0} process={1} temp={2} artifact={3} git={4} index={5}" -f
        $ListenerResidual,
        $ProcessResidual,
        $TempResidual,
        $ArtifactResidual,
        $GitResidual,
        $IndexResidual
    )
    if (
        $ListenerResidual -gt 0 -or $ProcessResidual -gt 0 -or
        $TempResidual -gt 0 -or $ArtifactResidual -gt 0 -or
        $GitResidual -gt 0 -or $IndexResidual -gt 0
    ) {
        $script:HarnessFailure = $true
        Write-Output "SSWCENTER_0014_HARNESS_CLEANUP_RESIDUAL_NONZERO"
    }
}

if ($PreflightOnly) {
    if (
        $PreflightOnlyCompleted -and
        -not $script:ProductFailure -and
        -not $script:HarnessFailure -and
        $ScriptExitCode -eq 0 -and
        $ListenerResidual -eq 0 -and $ProcessResidual -eq 0 -and
        $TempResidual -eq 0 -and $ArtifactResidual -eq 0 -and
        $GitResidual -eq 0 -and $IndexResidual -eq 0
    ) {
        Write-Output "SSWCENTER_0014_PREFLIGHT_ONLY_GREEN"
        exit 0
    }
    if (-not $script:HarnessFailure) {
        $script:HarnessFailure = $true
    }
    Write-Output "SSWCENTER_0014_WRAPPER_HARNESS_FAILURE: SSWCENTER_0014_PREFLIGHT_ONLY_GATE"
    exit 1
}

if (
    $AllStagesAttempted -and
    -not $script:ProductFailure -and
    -not $script:HarnessFailure -and
    $ScriptExitCode -eq 0 -and
    $ListenerResidual -eq 0 -and $ProcessResidual -eq 0 -and
    $TempResidual -eq 0 -and $ArtifactResidual -eq 0 -and
    $GitResidual -eq 0 -and $IndexResidual -eq 0
) {
    Write-Output "SSWCENTER_0014_POSTGRES_GREEN"
    exit 0
}

if ($script:HarnessFailure) {
    Write-Output "SSWCENTER_0014_WRAPPER_HARNESS_FAILURE: SSWCENTER_0014_POSTFLIGHT_GATE"
}
elseif ($script:ProductFailure) {
    Write-Output "SSWCENTER_0014_POSTGRES_PRODUCT_RED"
}
else {
    Write-Output "SSWCENTER_0014_WRAPPER_HARNESS_FAILURE: SSWCENTER_0014_INCOMPLETE_STAGE_SET"
}
exit 1
