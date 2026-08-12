<#
.SYNOPSIS
    Self-contained contract test for verify-workspace-seal.ps1.
.DESCRIPTION
    Windows PowerShell 5.1. AST-parses and dot-sources the helper, then
    exercises every observable contract through a GUID-named temp Git
    repository.  No network, no canonical repo mutation, no package installs.
.NOTES
    Invoke from the scripts directory or via an absolute path so $PSScriptRoot
    resolves correctly.
#>

[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

# =========================================================================
# Counters and assertion helpers
# =========================================================================
$script:Total   = 0
$script:Passed  = 0
$script:Failed  = 0
$script:Failures = New-Object 'System.Collections.Generic.List[string]'

function Fail {
    param([string]$Msg)
    $script:Failed++
    $script:Failures.Add($Msg)
    Write-Host "FAIL  $Msg" -ForegroundColor Red
}

function Pass {
    $script:Passed++
}

function Assert-Equal {
    param($Expected, $Actual, [string]$Label)
    $script:Total++
    if ($Expected -eq $Actual) { Pass } else { Fail "$Label : expected '$Expected', got '$Actual'" }
}

function Assert-NotEqual {
    param($NotExpected, $Actual, [string]$Label)
    $script:Total++
    if ($NotExpected -ne $Actual) { Pass } else { Fail "$Label : should NOT equal '$NotExpected'" }
}

function Assert-True {
    param($Condition, [string]$Label)
    $script:Total++
    if ($Condition) { Pass } else { Fail "$Label : expected true, got false" }
}

function Assert-NotNullOrEmpty {
    param([string]$Value, [string]$Label)
    $script:Total++
    if ($Value) { Pass } else { Fail "$Label : expected non-empty string" }
}

function Assert-GreaterThan {
    param($Value, [int]$Threshold, [string]$Label)
    $script:Total++
    if ($Value -gt $Threshold) { Pass } else { Fail "$Label : expected > $Threshold, got $Value" }
}

# =========================================================================
# 1. AST-parse the helper and assert zero errors
# =========================================================================
$helperPath = Join-Path $PSScriptRoot 'verify-workspace-seal.ps1'
Assert-True (Test-Path -LiteralPath $helperPath -PathType Leaf) "Helper script exists at $helperPath"

$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($helperPath, [ref]$null, [ref]$parseErrors)
Assert-Equal 0 $parseErrors.Count "AST parse: zero errors"
if ($parseErrors.Count -gt 0) {
    foreach ($e in $parseErrors) { Write-Host "  Parse error: $($e.Message)" -ForegroundColor Red }
}
Write-Host "[*] AST parse OK" -ForegroundColor Green

$helperSource = [System.IO.File]::ReadAllText($helperPath)
Assert-True ($helperSource.Contains("@('--no-optional-locks', '-c', 'core.quotePath=false')")) "Git observer source includes --no-optional-locks"
Assert-True ($helperSource.Contains("GIT_OPTIONAL_LOCKS = '0'")) "Git observer source sets process-local GIT_OPTIONAL_LOCKS=0"
$directGitProcessCalls = [regex]::Matches(
    $helperSource,
    "Invoke-NativeObserverProcess\s+-FileName\s+'git\.exe'",
    [System.Text.RegularExpressions.RegexOptions]::CultureInvariant
).Count
Assert-Equal 1 $directGitProcessCalls "Only Invoke-GitObserver launches git.exe directly"

# =========================================================================
# 2. Dot-source the helper (guard prevents main from running)
# =========================================================================
. $helperPath
Assert-True (Get-Command Invoke-NativeObserverProcess -ErrorAction SilentlyContinue) "Function Invoke-NativeObserverProcess available after dot-source"
Assert-True (Get-Command Invoke-GitObserver -ErrorAction SilentlyContinue) "Function Invoke-GitObserver available after dot-source"
Assert-True (Get-Command Format-NativeArgument -ErrorAction SilentlyContinue) "Function Format-NativeArgument available after dot-source"
Write-Host "[*] Dot-source OK" -ForegroundColor Green

# =========================================================================
# 3. Create GUID-named temp directory under [System.IO.Path]::GetTempPath()
# =========================================================================
$tempRoot = [System.IO.Path]::GetTempPath()
$tempDirName = 'sswcenter-seal-contract-' + ([System.Guid]::NewGuid().ToString('N'))
$tempDir = Join-Path $tempRoot $tempDirName
$null = New-Item -ItemType Directory -Path $tempDir -Force
Write-Host "[*] Temp dir: $tempDir" -ForegroundColor Green

try {

# =========================================================================
# 4. Native process separation contract
# =========================================================================
Write-Host "`n=== Native process separation tests ===" -ForegroundColor Cyan

# Probe 1: stdout OUT_OK, stderr WARNING_ONLY, exit 0
$probe1Path = Join-Path $tempDir 'probe1.ps1'
@'
Write-Output 'OUT_OK'
[Console]::Error.WriteLine('WARNING_ONLY')
exit 0
'@ | Set-Content -LiteralPath $probe1Path -Encoding UTF8

$r1 = Invoke-NativeObserverProcess -FileName 'powershell.exe' -ArgumentList @('-NoProfile', '-File', $probe1Path)
Assert-Equal 0 $r1.ExitCode "Probe1 exit code"
Assert-Equal 'OUT_OK' $r1.StdOut.Trim() "Probe1 stdout independent of stderr"
Assert-NotNullOrEmpty $r1.StdErr "Probe1 stderr captured"
Assert-True ($r1.StdErr.Contains('WARNING_ONLY')) "Probe1 stderr contains WARNING_ONLY"
# Contract: exit-0 stderr is NOT process failure
Assert-True ($r1.ExitCode -eq 0 -and $r1.StdErr) "Probe1: exit-0 with stderr is not process failure"

# Probe 2: stderr output, exit 7
$probe2Path = Join-Path $tempDir 'probe2.ps1'
@'
[Console]::Error.WriteLine('ERROR_FATAL')
exit 7
'@ | Set-Content -LiteralPath $probe2Path -Encoding UTF8

$r2 = Invoke-NativeObserverProcess -FileName 'powershell.exe' -ArgumentList @('-NoProfile', '-File', $probe2Path)
Assert-Equal 7 $r2.ExitCode "Probe2 exact nonzero exit code"
Assert-NotNullOrEmpty $r2.StdErr "Probe2 stderr captured"
Assert-True ($r2.StdErr.Contains('ERROR_FATAL')) "Probe2 stderr contains ERROR_FATAL"
Write-Host "[*] Native process separation OK" -ForegroundColor Green

# =========================================================================
# 5. Initialize a temp Git repository with Unicode files
# =========================================================================
Write-Host "`n=== Temp Git repository setup ===" -ForegroundColor Cyan

$repoRoot = Join-Path $tempDir 'repo'
$null = New-Item -ItemType Directory -Path $repoRoot -Force

# git init
$initResult = Invoke-NativeObserverProcess -FileName 'git.exe' -ArgumentList @('-C', $repoRoot, 'init')
Assert-Equal 0 $initResult.ExitCode "git init exit 0"

# Configure local user.name / user.email
$cfgName = Invoke-NativeObserverProcess -FileName 'git.exe' -ArgumentList @('-C', $repoRoot, 'config', 'user.name', 'Seal Contract Test')
Assert-Equal 0 $cfgName.ExitCode "git config user.name"
$cfgEmail = Invoke-NativeObserverProcess -FileName 'git.exe' -ArgumentList @('-C', $repoRoot, 'config', 'user.email', 'seal@contract.test')
Assert-Equal 0 $cfgEmail.ExitCode "git config user.email"

# Create Unicode paths from code points so PowerShell 5.1 is independent of source encoding.
$hangulName = -join ([char[]]@(0xD55C, 0xAE00))
$targetName = -join ([char[]]@(0xB300, 0xC0C1))
$outsideName = -join ([char[]]@(0xC678, 0xBD80))
$fileName = -join ([char[]]@(0xD30C, 0xC77C))
$intruderName = -join ([char[]]@(0xCE68, 0xC785, 0xC790))
$frozenRelativePath = "frozen/${hangulName}/${targetName}.txt"
$outsideRelativePath = "${outsideName}/${fileName}.txt"
$intruderRelativePath = "frozen/${hangulName}/${intruderName}.txt"
$frozenDir = Join-Path $repoRoot 'frozen'
$frozenHangulDir = Join-Path $frozenDir $hangulName
$null = New-Item -ItemType Directory -Path $frozenHangulDir -Force
$frozenFilePath = Join-Path $frozenHangulDir ($targetName + '.txt')
$frozenContent = "Frozen seal content line 1`r`nLine 2 한글 Unicode`r`n"
[System.IO.File]::WriteAllText($frozenFilePath, $frozenContent, [System.Text.Encoding]::UTF8)

# Create outside Unicode file: 외부/파일.txt (NOT under frozen)
$outsideDir = Join-Path $repoRoot $outsideName
$null = New-Item -ItemType Directory -Path $outsideDir -Force
$outsideFilePath = Join-Path $outsideDir ($fileName + '.txt')
$outsideContent = "Outside content 한글`r`n"
[System.IO.File]::WriteAllText($outsideFilePath, $outsideContent, [System.Text.Encoding]::UTF8)

# git add all
$addResult = Invoke-NativeObserverProcess -FileName 'git.exe' -ArgumentList @('-C', $repoRoot, 'add', '.')
Assert-Equal 0 $addResult.ExitCode "git add ."

# git commit
$commitResult = Invoke-NativeObserverProcess -FileName 'git.exe' -ArgumentList @('-C', $repoRoot, 'commit', '-m', 'Initial commit with Unicode files')
Assert-Equal 0 $commitResult.ExitCode "git commit"

# Obtain HEAD
$headResult = Invoke-NativeObserverProcess -FileName 'git.exe' -ArgumentList @('-C', $repoRoot, 'rev-parse', 'HEAD')
Assert-Equal 0 $headResult.ExitCode "git rev-parse HEAD"
$head = $headResult.StdOut.Trim()
Assert-NotNullOrEmpty $head "HEAD is non-empty"
Write-Host "  HEAD = $head" -ForegroundColor Gray

Write-Host "[*] Temp Git repo setup OK" -ForegroundColor Green

# =========================================================================
# 6. Independently calculate expected frozen aggregate
#    One record: frozen/한글/대상.txt|<lowercase_file_sha256>
#    No CRLF separator (single record), UTF-8, then SHA-256
# =========================================================================
Write-Host "`n=== Independent aggregate calculation ===" -ForegroundColor Cyan

$frozenBytes = [System.IO.File]::ReadAllBytes($frozenFilePath)
$fileShaProvider = [System.Security.Cryptography.SHA256]::Create()
try {
    $fileHashBytes = $fileShaProvider.ComputeHash($frozenBytes)
} finally { $fileShaProvider.Dispose() }
$fileShaLower = ([System.BitConverter]::ToString($fileHashBytes) -replace '-', '').ToLowerInvariant()

# Manifest: exactly one record, no trailing CRLF
$manifestRecord = "$frozenRelativePath|$fileShaLower"
$manifestBytes = [System.Text.Encoding]::UTF8.GetBytes($manifestRecord)

$manifestShaProvider = [System.Security.Cryptography.SHA256]::Create()
try {
    $manifestHashBytes = $manifestShaProvider.ComputeHash($manifestBytes)
} finally { $manifestShaProvider.Dispose() }
$expectedAggregate = ([System.BitConverter]::ToString($manifestHashBytes) -replace '-', '').ToLowerInvariant()

Write-Host "  File SHA-256  = $fileShaLower" -ForegroundColor Gray
Write-Host "  Expected agg  = $expectedAggregate" -ForegroundColor Gray
Write-Host "[*] Independent aggregate OK" -ForegroundColor Green

# =========================================================================
# Helper: invoke verify-workspace-seal.ps1 in child powershell.exe
# =========================================================================
function Invoke-SealObserver {
    param(
        [string]$RepositoryRootParam,
        [string[]]$FrozenPathParam,
        [string]$ExpectedHeadParam = '',
        [string]$ExpectedFrozenAggregateParam = '',
        [switch]$TestModeParam,
        [int]$TestPauseAfterStartMillisecondsParam = 0,
        [string]$TestPauseStartedEventNameParam = ''
    )
    $argsList = @('-NoProfile', '-File', $helperPath,
                  '-RepositoryRoot', $RepositoryRootParam,
                  '-FrozenPath')
    $argsList += $FrozenPathParam
    if ($ExpectedHeadParam) {
        $argsList += @('-ExpectedHead', $ExpectedHeadParam)
    }
    if ($ExpectedFrozenAggregateParam) {
        $argsList += @('-ExpectedFrozenAggregate', $ExpectedFrozenAggregateParam)
    }
    if ($TestModeParam) {
        $argsList += '-TestMode'
    }
    if ($TestPauseAfterStartMillisecondsParam -gt 0) {
        $argsList += @('-TestPauseAfterStartMilliseconds', [string]$TestPauseAfterStartMillisecondsParam)
    }
    if ($TestPauseStartedEventNameParam) {
        $argsList += @('-TestPauseStartedEventName', $TestPauseStartedEventNameParam)
    }
    $argsList += '-JsonOutput'

    return Invoke-NativeObserverProcess -FileName 'powershell.exe' -ArgumentList $argsList
}

function Start-SealObserverProcess {
    param([string[]]$ArgumentList)

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'powershell.exe'
    $psi.Arguments = ($ArgumentList | ForEach-Object { Format-NativeArgument $_ }) -join ' '
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    if (-not $process.Start()) {
        $process.Dispose()
        throw 'Failed to start observer child process'
    }

    return [PSCustomObject]@{
        Process = $process
        StdOutTask = $process.StandardOutput.ReadToEndAsync()
        StdErrTask = $process.StandardError.ReadToEndAsync()
    }
}

function Complete-SealObserverProcess {
    param(
        [object]$Capture,
        [int]$TimeoutMilliseconds = 15000
    )

    $finished = $Capture.Process.WaitForExit($TimeoutMilliseconds)
    if (-not $finished) {
        $Capture.Process.Kill()
    }
    $Capture.Process.WaitForExit()

    return [PSCustomObject]@{
        Finished = $finished
        StdOut = $Capture.StdOutTask.Result
        StdErr = $Capture.StdErrTask.Result
        ExitCode = $Capture.Process.ExitCode
    }
}

# =========================================================================
# 7. Baseline: clean workspace → PASS
# =========================================================================
Write-Host "`n=== Baseline clean workspace test ===" -ForegroundColor Cyan

$repoRootTrailing = $repoRoot.TrimEnd(@([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)) + [System.IO.Path]::DirectorySeparatorChar
$indexPath = Join-Path (Join-Path $repoRoot '.git') 'index'
$indexLockPath = Join-Path (Join-Path $repoRoot '.git') 'index.lock'
Assert-True (Test-Path -LiteralPath $indexPath -PathType Leaf) "Temp repo index exists before observer"
Assert-True (-not (Test-Path -LiteralPath $indexLockPath)) "Temp repo index.lock absent before observer"
$indexHashBefore = (Get-FileHash -Algorithm SHA256 -LiteralPath $indexPath).Hash
$indexMtimeBefore = (Get-Item -LiteralPath $indexPath).LastWriteTimeUtc.Ticks
Start-Sleep -Milliseconds 1100

$baselineResult = Invoke-SealObserver -RepositoryRootParam $repoRootTrailing `
                                      -FrozenPathParam @('frozen') `
                                      -ExpectedHeadParam $head `
                                      -ExpectedFrozenAggregateParam $expectedAggregate

Assert-Equal 0 $baselineResult.ExitCode "Baseline child exit code 0"

# Parse JSON even when stderr contains warnings
try {
    $baselineJson = $baselineResult.StdOut | ConvertFrom-Json
} catch {
    Fail "Baseline JSON parse failed: $_"
    $baselineJson = $null
}

if ($baselineJson) {
    Assert-Equal 'PASS' $baselineJson.status "Baseline status PASS"
    Assert-Equal $head $baselineJson.head "Baseline head matches"
    Assert-True $baselineJson.head_matches "Baseline head_matches true"
    Assert-Equal 1 $baselineJson.frozen_file_count "Baseline frozen_file_count 1"
    Assert-Equal $expectedAggregate $baselineJson.frozen_manifest_sha256 "Baseline frozen_manifest_sha256 matches expected"
    Assert-True $baselineJson.frozen_aggregate_matches "Baseline frozen_aggregate_matches true"
    Assert-True $baselineJson.frozen_diff_clean "Baseline frozen_diff_clean true"
    Assert-Equal 0 $baselineJson.frozen_untracked_count "Baseline frozen_untracked_count 0"
    Assert-Equal 0 $baselineJson.diff_check_exit_code "Baseline diff_check_exit_code 0"
    Assert-Equal 0 $baselineJson.staged_count "Baseline staged_count 0"
    Assert-True ($baselineJson.PSObject.Properties.Name -contains 'observer_start_snapshot') "Baseline JSON includes observer_start_snapshot"
    Assert-True ($baselineJson.PSObject.Properties.Name -contains 'observer_end_snapshot') "Baseline JSON includes observer_end_snapshot"
    Assert-True ($baselineJson.PSObject.Properties.Name -contains 'observer_start_seal_sha256') "Baseline JSON includes observer_start_seal_sha256"
    Assert-True ($baselineJson.PSObject.Properties.Name -contains 'observer_end_seal_sha256') "Baseline JSON includes observer_end_seal_sha256"
    Assert-True ($baselineJson.PSObject.Properties.Name -contains 'observer_snapshot_stable') "Baseline JSON includes observer_snapshot_stable"
    Assert-True $baselineJson.observer_snapshot_stable "Baseline observer_snapshot_stable true"
    Assert-NotNullOrEmpty $baselineJson.observer_start_seal_sha256 "Baseline start seal non-empty"
    Assert-Equal $baselineJson.observer_start_seal_sha256 $baselineJson.observer_end_seal_sha256 "Baseline start/end seal equal"
    Assert-Equal $baselineJson.observer_start_snapshot.head $baselineJson.observer_end_snapshot.head "Baseline snapshot HEAD stable"
    Assert-Equal $baselineJson.observer_start_snapshot.tracked_manifest_sha256 $baselineJson.observer_end_snapshot.tracked_manifest_sha256 "Baseline tracked manifest stable"
    Assert-Equal $baselineJson.observer_start_snapshot.untracked_manifest_sha256 $baselineJson.observer_end_snapshot.untracked_manifest_sha256 "Baseline untracked manifest stable"
    Assert-Equal $baselineJson.observer_start_snapshot.frozen_manifest_sha256 $baselineJson.observer_end_snapshot.frozen_manifest_sha256 "Baseline frozen tracked manifest stable"
    Assert-Equal $baselineJson.observer_start_snapshot.frozen_untracked_manifest_sha256 $baselineJson.observer_end_snapshot.frozen_untracked_manifest_sha256 "Baseline frozen untracked manifest stable"
    Assert-Equal $baselineJson.observer_start_snapshot.index_manifest_sha256 $baselineJson.observer_end_snapshot.index_manifest_sha256 "Baseline index manifest stable"
    Assert-Equal $baselineJson.observer_start_snapshot.cached_diff_sha256 $baselineJson.observer_end_snapshot.cached_diff_sha256 "Baseline cached diff stable"
    Assert-Equal $baselineJson.observer_start_snapshot.status_fingerprint_sha256 $baselineJson.observer_end_snapshot.status_fingerprint_sha256 "Baseline status fingerprint stable"
}
$indexHashAfter = (Get-FileHash -Algorithm SHA256 -LiteralPath $indexPath).Hash
$indexMtimeAfter = (Get-Item -LiteralPath $indexPath).LastWriteTimeUtc.Ticks
Assert-Equal $indexHashBefore $indexHashAfter "Observer leaves .git/index SHA-256 unchanged"
Assert-Equal $indexMtimeBefore $indexMtimeAfter "Observer leaves .git/index LastWriteTimeUtc unchanged"
Assert-True (-not (Test-Path -LiteralPath $indexLockPath)) "Observer leaves no .git/index.lock"
Write-Host "[*] Baseline test OK" -ForegroundColor Green

# =========================================================================
# Test-only pause requires TestMode and catch JSON keeps seal fields
# =========================================================================
Write-Host "`n=== Pause authorization test ===" -ForegroundColor Cyan

$unauthorizedPauseResult = Invoke-SealObserver -RepositoryRootParam $repoRootTrailing `
                                                -FrozenPathParam @('frozen') `
                                                -ExpectedHeadParam $head `
                                                -ExpectedFrozenAggregateParam $expectedAggregate `
                                                -TestPauseAfterStartMillisecondsParam 10
Assert-Equal 1 $unauthorizedPauseResult.ExitCode "Pause without TestMode exits 1"
try {
    $unauthorizedPauseJson = $unauthorizedPauseResult.StdOut | ConvertFrom-Json
} catch {
    Fail "Pause-without-TestMode JSON parse failed: $_"
    $unauthorizedPauseJson = $null
}
if ($unauthorizedPauseJson) {
    Assert-Equal 'REJECT' $unauthorizedPauseJson.status "Pause without TestMode status REJECT"
    Assert-True ($unauthorizedPauseJson.errors -contains 'OBSERVER_TEST_PAUSE_REQUIRES_TEST_MODE') "Pause without TestMode records fail-closed error"
    Assert-True ($unauthorizedPauseJson.PSObject.Properties.Name -contains 'observer_start_snapshot') "Catch JSON includes observer_start_snapshot"
    Assert-True ($unauthorizedPauseJson.PSObject.Properties.Name -contains 'observer_end_snapshot') "Catch JSON includes observer_end_snapshot"
    Assert-True ($unauthorizedPauseJson.PSObject.Properties.Name -contains 'observer_start_seal_sha256') "Catch JSON includes observer_start_seal_sha256"
    Assert-True ($unauthorizedPauseJson.PSObject.Properties.Name -contains 'observer_end_seal_sha256') "Catch JSON includes observer_end_seal_sha256"
    Assert-True ($unauthorizedPauseJson.PSObject.Properties.Name -contains 'observer_snapshot_stable') "Catch JSON includes observer_snapshot_stable"
    Assert-True (-not $unauthorizedPauseJson.observer_snapshot_stable) "Catch observer_snapshot_stable false"
}
Write-Host "[*] Pause authorization test OK" -ForegroundColor Green

# =========================================================================
# Concurrent frozen worktree mutation changes the start/end snapshot seal
# =========================================================================
Write-Host "`n=== Concurrent worktree mutation test ===" -ForegroundColor Cyan

$worktreePauseEventName = 'SSWCenterObserverPause-' + ([System.Guid]::NewGuid().ToString('N'))
$worktreePauseEvent = $null
$worktreeCapture = $null
$originalConcurrentBytes = [System.IO.File]::ReadAllBytes($frozenFilePath)
try {
    $worktreePauseEvent = New-Object System.Threading.EventWaitHandle -ArgumentList @(
        $false,
        [System.Threading.EventResetMode]::ManualReset,
        $worktreePauseEventName
    )
    $worktreeArgs = @(
        '-NoProfile', '-File', $helperPath,
        '-RepositoryRoot', $repoRootTrailing,
        '-FrozenPath', 'frozen',
        '-ExpectedHead', $head,
        '-ExpectedFrozenAggregate', $expectedAggregate,
        '-TestMode',
        '-TestPauseAfterStartMilliseconds', '4000',
        '-TestPauseStartedEventName', $worktreePauseEventName,
        '-JsonOutput'
    )
    $worktreeCapture = Start-SealObserverProcess -ArgumentList $worktreeArgs
    $worktreePauseWasSignaled = $worktreePauseEvent.WaitOne(10000)
    Assert-True $worktreePauseWasSignaled "Observer signals after start snapshot before worktree mutation"
    if ($worktreePauseWasSignaled) {
        [System.IO.File]::WriteAllText(
            $frozenFilePath,
            "Concurrent worktree mutation after start snapshot`r`n",
            [System.Text.Encoding]::UTF8
        )
    }

    $worktreeConcurrentResult = Complete-SealObserverProcess -Capture $worktreeCapture
    Assert-True $worktreeConcurrentResult.Finished "Concurrent worktree observer exits within timeout"
    Assert-Equal 1 $worktreeConcurrentResult.ExitCode "Concurrent worktree mutation child exit 1"
    try {
        $worktreeConcurrentJson = $worktreeConcurrentResult.StdOut | ConvertFrom-Json
    } catch {
        Fail "Concurrent worktree mutation JSON parse failed: $_ stderr=$($worktreeConcurrentResult.StdErr)"
        $worktreeConcurrentJson = $null
    }
    if ($worktreeConcurrentJson) {
        Assert-Equal 'REJECT' $worktreeConcurrentJson.status "Concurrent worktree mutation status REJECT"
        Assert-True ($worktreeConcurrentJson.errors -contains 'OBSERVER_SNAPSHOT_CHANGED') "Concurrent worktree mutation records OBSERVER_SNAPSHOT_CHANGED"
        Assert-True (-not $worktreeConcurrentJson.observer_snapshot_stable) "Concurrent worktree snapshot_stable false"
        Assert-NotNullOrEmpty $worktreeConcurrentJson.observer_start_seal_sha256 "Concurrent worktree start seal non-empty"
        Assert-NotNullOrEmpty $worktreeConcurrentJson.observer_end_seal_sha256 "Concurrent worktree end seal non-empty"
        Assert-NotEqual $worktreeConcurrentJson.observer_start_seal_sha256 $worktreeConcurrentJson.observer_end_seal_sha256 "Concurrent worktree start/end seal differ"
        Assert-NotEqual $worktreeConcurrentJson.observer_start_snapshot.frozen_manifest_sha256 $worktreeConcurrentJson.observer_end_snapshot.frozen_manifest_sha256 "Concurrent worktree frozen manifest differs"
    }
} finally {
    [System.IO.File]::WriteAllBytes($frozenFilePath, $originalConcurrentBytes)
    if ($worktreeCapture -and $worktreeCapture.Process) {
        if (-not $worktreeCapture.Process.HasExited) {
            $worktreeCapture.Process.Kill()
            $worktreeCapture.Process.WaitForExit()
        }
        $worktreeCapture.Process.Dispose()
    }
    if ($worktreePauseEvent) { $worktreePauseEvent.Dispose() }
}

$postWorktreeConcurrentResult = Invoke-SealObserver -RepositoryRootParam $repoRootTrailing `
                                                       -FrozenPathParam @('frozen') `
                                                       -ExpectedHeadParam $head `
                                                       -ExpectedFrozenAggregateParam $expectedAggregate
Assert-Equal 0 $postWorktreeConcurrentResult.ExitCode "After worktree concurrent restore: child exit 0"
Write-Host "[*] Concurrent worktree mutation test OK" -ForegroundColor Green

# =========================================================================
# Concurrent index-only mutation is sealed even after worktree byte restore
# =========================================================================
Write-Host "`n=== Concurrent index-only mutation test ===" -ForegroundColor Cyan

$indexPauseEventName = 'SSWCenterObserverPause-' + ([System.Guid]::NewGuid().ToString('N'))
$indexPauseEvent = $null
$indexCapture = $null
$originalIndexTestBytes = [System.IO.File]::ReadAllBytes($frozenFilePath)
try {
    $indexPauseEvent = New-Object System.Threading.EventWaitHandle -ArgumentList @(
        $false,
        [System.Threading.EventResetMode]::ManualReset,
        $indexPauseEventName
    )
    $indexArgs = @(
        '-NoProfile', '-File', $helperPath,
        '-RepositoryRoot', $repoRootTrailing,
        '-FrozenPath', 'frozen',
        '-ExpectedHead', $head,
        '-ExpectedFrozenAggregate', $expectedAggregate,
        '-TestMode',
        '-TestPauseAfterStartMilliseconds', '4000',
        '-TestPauseStartedEventName', $indexPauseEventName,
        '-JsonOutput'
    )
    $indexCapture = Start-SealObserverProcess -ArgumentList $indexArgs
    $indexPauseWasSignaled = $indexPauseEvent.WaitOne(10000)
    Assert-True $indexPauseWasSignaled "Observer signals after start snapshot before index-only mutation"
    if ($indexPauseWasSignaled) {
        [System.IO.File]::WriteAllText(
            $frozenFilePath,
            "Content staged only after start snapshot`r`n",
            [System.Text.Encoding]::UTF8
        )
        $stageIndexOnly = Invoke-NativeObserverProcess -FileName 'git.exe' -ArgumentList @(
            '-C', $repoRoot, 'add', '--', $frozenRelativePath
        )
        Assert-Equal 0 $stageIndexOnly.ExitCode "Index-only test git add succeeds in temp repo"
        [System.IO.File]::WriteAllBytes($frozenFilePath, $originalIndexTestBytes)
    }

    $indexConcurrentResult = Complete-SealObserverProcess -Capture $indexCapture
    Assert-True $indexConcurrentResult.Finished "Concurrent index observer exits within timeout"
    Assert-Equal 1 $indexConcurrentResult.ExitCode "Concurrent index-only mutation child exit 1"
    try {
        $indexConcurrentJson = $indexConcurrentResult.StdOut | ConvertFrom-Json
    } catch {
        Fail "Concurrent index-only mutation JSON parse failed: $_ stderr=$($indexConcurrentResult.StdErr)"
        $indexConcurrentJson = $null
    }
    if ($indexConcurrentJson) {
        Assert-Equal 'REJECT' $indexConcurrentJson.status "Concurrent index-only mutation status REJECT"
        Assert-True ($indexConcurrentJson.errors -contains 'OBSERVER_SNAPSHOT_CHANGED') "Concurrent index-only mutation records OBSERVER_SNAPSHOT_CHANGED"
        Assert-True (-not $indexConcurrentJson.observer_snapshot_stable) "Concurrent index-only snapshot_stable false"
        Assert-Equal $indexConcurrentJson.observer_start_snapshot.tracked_manifest_sha256 $indexConcurrentJson.observer_end_snapshot.tracked_manifest_sha256 "Index-only test restores full tracked worktree manifest"
        Assert-Equal $indexConcurrentJson.observer_start_snapshot.frozen_manifest_sha256 $indexConcurrentJson.observer_end_snapshot.frozen_manifest_sha256 "Index-only test restores frozen worktree manifest"
        Assert-NotEqual $indexConcurrentJson.observer_start_snapshot.index_manifest_sha256 $indexConcurrentJson.observer_end_snapshot.index_manifest_sha256 "Index-only mutation changes index manifest"
        Assert-NotEqual $indexConcurrentJson.observer_start_snapshot.cached_diff_sha256 $indexConcurrentJson.observer_end_snapshot.cached_diff_sha256 "Index-only mutation changes cached diff"
        Assert-NotEqual $indexConcurrentJson.observer_start_snapshot.status_fingerprint_sha256 $indexConcurrentJson.observer_end_snapshot.status_fingerprint_sha256 "Index-only mutation changes status fingerprint"
        Assert-NotEqual $indexConcurrentJson.observer_start_seal_sha256 $indexConcurrentJson.observer_end_seal_sha256 "Index-only mutation changes composite seal"
    }
} finally {
    [System.IO.File]::WriteAllBytes($frozenFilePath, $originalIndexTestBytes)
    $restoreTempIndex = Invoke-NativeObserverProcess -FileName 'git.exe' -ArgumentList @(
        '-C', $repoRoot, 'add', '--', $frozenRelativePath
    )
    Assert-Equal 0 $restoreTempIndex.ExitCode "Index-only test restores temp index"
    if ($indexCapture -and $indexCapture.Process) {
        if (-not $indexCapture.Process.HasExited) {
            $indexCapture.Process.Kill()
            $indexCapture.Process.WaitForExit()
        }
        $indexCapture.Process.Dispose()
    }
    if ($indexPauseEvent) { $indexPauseEvent.Dispose() }
}

$postIndexCachedDiff = Invoke-GitObserver -Arguments @('diff', '--cached', '--quiet', '--') -RepositoryPath $repoRoot
Assert-Equal 0 $postIndexCachedDiff.ExitCode "After index-only test restore: cached diff clean"
$postIndexConcurrentResult = Invoke-SealObserver -RepositoryRootParam $repoRootTrailing `
                                                    -FrozenPathParam @('frozen') `
                                                    -ExpectedHeadParam $head `
                                                    -ExpectedFrozenAggregateParam $expectedAggregate
Assert-Equal 0 $postIndexConcurrentResult.ExitCode "After index-only restore: child exit 0"
Write-Host "[*] Concurrent index-only mutation test OK" -ForegroundColor Green

# =========================================================================
# 8. Modify and stage only the outside Unicode file → still PASS
# =========================================================================
Write-Host "`n=== Staged outside file test ===" -ForegroundColor Cyan

$modifiedOutside = "Outside content 한글 MODIFIED`r`n"
[System.IO.File]::WriteAllText($outsideFilePath, $modifiedOutside, [System.Text.Encoding]::UTF8)

$stageOutside = Invoke-NativeObserverProcess -FileName 'git.exe' -ArgumentList @('-C', $repoRoot, 'add', $outsideRelativePath)
Assert-Equal 0 $stageOutside.ExitCode "git add outside file"

$stagedResult = Invoke-SealObserver -RepositoryRootParam $repoRootTrailing `
                                    -FrozenPathParam @('frozen') `
                                    -ExpectedHeadParam $head `
                                    -ExpectedFrozenAggregateParam $expectedAggregate

Assert-Equal 0 $stagedResult.ExitCode "Staged-outside child exit 0"
try {
    $stagedJson = $stagedResult.StdOut | ConvertFrom-Json
} catch {
    Fail "Staged-outside JSON parse failed: $_"
    $stagedJson = $null
}
if ($stagedJson) {
    Assert-Equal 'PASS' $stagedJson.status "Staged-outside status PASS"
    Assert-Equal 1 $stagedJson.staged_count "Staged-outside staged_count 1"
    $stagedPaths = $stagedJson.staged_paths
    Assert-True ($stagedPaths -contains $outsideRelativePath) "Staged-outside staged_paths contains 외부/파일.txt (normalized)"
    Assert-True $stagedJson.frozen_diff_clean "Staged-outside frozen_diff_clean still true"
    Assert-Equal $expectedAggregate $stagedJson.frozen_manifest_sha256 "Staged-outside aggregate unchanged"
}
Write-Host "[*] Staged outside file test OK" -ForegroundColor Green

# =========================================================================
# 9. Modify the tracked frozen file → REJECT, then restore bytes
# =========================================================================
Write-Host "`n=== Frozen file modification test ===" -ForegroundColor Cyan

# Save original bytes
$originalFrozenBytes = [System.IO.File]::ReadAllBytes($frozenFilePath)

# Modify
$modifiedFrozen = "Frozen seal content line 1`r`nLine 2 한글 Unicode TAMPERED`r`n"
[System.IO.File]::WriteAllText($frozenFilePath, $modifiedFrozen, [System.Text.Encoding]::UTF8)

$dirtyResult = Invoke-SealObserver -RepositoryRootParam $repoRootTrailing `
                                   -FrozenPathParam @('frozen') `
                                   -ExpectedHeadParam $head `
                                   -ExpectedFrozenAggregateParam $expectedAggregate

Assert-Equal 1 $dirtyResult.ExitCode "Frozen-modified child exit 1"
try {
    $dirtyJson = $dirtyResult.StdOut | ConvertFrom-Json
} catch {
    Fail "Frozen-modified JSON parse failed: $_"
    $dirtyJson = $null
}
if ($dirtyJson) {
    Assert-Equal 'REJECT' $dirtyJson.status "Frozen-modified status REJECT"
    Assert-True (-not $dirtyJson.frozen_diff_clean) "Frozen-modified frozen_diff_clean false"
    Assert-True (-not $dirtyJson.frozen_aggregate_matches) "Frozen-modified aggregate mismatch"
    Assert-NotEqual $expectedAggregate $dirtyJson.frozen_manifest_sha256 "Frozen-modified manifest differs from expected"
}

# Restore original bytes directly – no git checkout/reset
[System.IO.File]::WriteAllBytes($frozenFilePath, $originalFrozenBytes)

# Verify restoration
$verifyResult = Invoke-SealObserver -RepositoryRootParam $repoRootTrailing `
                                    -FrozenPathParam @('frozen') `
                                    -ExpectedHeadParam $head `
                                    -ExpectedFrozenAggregateParam $expectedAggregate
Assert-Equal 0 $verifyResult.ExitCode "After restore: child exit 0"
try {
    $verifyJson = $verifyResult.StdOut | ConvertFrom-Json
    Assert-Equal 'PASS' $verifyJson.status "After restore: status PASS"
    Assert-Equal $expectedAggregate $verifyJson.frozen_manifest_sha256 "After restore: aggregate matches"
    Assert-True $verifyJson.frozen_diff_clean "After restore: frozen_diff_clean true"
} catch {
    Fail "After-restore JSON parse failed: $_"
}
Write-Host "[*] Frozen file modification + restore test OK" -ForegroundColor Green

# =========================================================================
# 10. Untracked Unicode file under frozen → REJECT
# =========================================================================
Write-Host "`n=== Frozen untracked file test ===" -ForegroundColor Cyan

$untrackedPath = Join-Path $frozenHangulDir ($intruderName + '.txt')
[System.IO.File]::WriteAllText($untrackedPath, "I should not be here`r`n", [System.Text.Encoding]::UTF8)

$untrackedResult = Invoke-SealObserver -RepositoryRootParam $repoRootTrailing `
                                       -FrozenPathParam @('frozen') `
                                       -ExpectedHeadParam $head `
                                       -ExpectedFrozenAggregateParam $expectedAggregate

Assert-Equal 1 $untrackedResult.ExitCode "Frozen-untracked child exit 1"
try {
    $untrackedJson = $untrackedResult.StdOut | ConvertFrom-Json
} catch {
    Fail "Frozen-untracked JSON parse failed: $_"
    $untrackedJson = $null
}
if ($untrackedJson) {
    Assert-Equal 'REJECT' $untrackedJson.status "Frozen-untracked status REJECT"
    Assert-Equal 1 $untrackedJson.frozen_untracked_count "Frozen-untracked frozen_untracked_count 1"
    $untrackedPaths = $untrackedJson.frozen_untracked_paths
    Assert-True ($untrackedPaths -contains $intruderRelativePath) "Frozen-untracked path preserved: frozen/한글/침입자.txt"
}

# Delete the untracked file directly
[System.IO.File]::Delete($untrackedPath)
Assert-True (-not (Test-Path -LiteralPath $untrackedPath)) "Untracked file deleted"
Write-Host "[*] Frozen untracked file test OK" -ForegroundColor Green

# =========================================================================
# 11. Fail-closed mismatches: wrong ExpectedHead and 64-zero aggregate
# =========================================================================
Write-Host "`n=== Fail-closed mismatch tests ===" -ForegroundColor Cyan

# 11a. Wrong ExpectedHead
$wrongHead = '0000000000000000000000000000000000000000'
$wrongHeadResult = Invoke-SealObserver -RepositoryRootParam $repoRootTrailing `
                                       -FrozenPathParam @('frozen') `
                                       -ExpectedHeadParam $wrongHead `
                                       -ExpectedFrozenAggregateParam $expectedAggregate
Assert-Equal 1 $wrongHeadResult.ExitCode "Wrong-head child exit 1"
try {
    $wrongHeadJson = $wrongHeadResult.StdOut | ConvertFrom-Json
    Assert-Equal 'REJECT' $wrongHeadJson.status "Wrong-head status REJECT"
    Assert-True (-not $wrongHeadJson.head_matches) "Wrong-head head_matches false"
} catch {
    Fail "Wrong-head JSON parse failed: $_"
}

# 11b. 64-zero ExpectedFrozenAggregate
$zeroAggregate = '0000000000000000000000000000000000000000000000000000000000000000'
$zeroAggResult = Invoke-SealObserver -RepositoryRootParam $repoRootTrailing `
                                     -FrozenPathParam @('frozen') `
                                     -ExpectedHeadParam $head `
                                     -ExpectedFrozenAggregateParam $zeroAggregate
Assert-Equal 1 $zeroAggResult.ExitCode "Zero-aggregate child exit 1"
try {
    $zeroAggJson = $zeroAggResult.StdOut | ConvertFrom-Json
    Assert-Equal 'REJECT' $zeroAggJson.status "Zero-aggregate status REJECT"
    Assert-True (-not $zeroAggJson.frozen_aggregate_matches) "Zero-aggregate frozen_aggregate_matches false"
} catch {
    Fail "Zero-aggregate JSON parse failed: $_"
}
Write-Host "[*] Fail-closed mismatch tests OK" -ForegroundColor Green

# =========================================================================
# 12. Invoke-GitObserver with deliberately invalid read-only subcommand
# =========================================================================
Write-Host "`n=== Invalid Git subcommand test ===" -ForegroundColor Cyan

$badGit = Invoke-GitObserver -Arguments @('nonexistent-git-subcommand-xyz') -RepositoryPath $repoRoot
Assert-True ($badGit.ExitCode -ne 0) "Invalid git subcommand: nonzero exit code (got $($badGit.ExitCode))"
Assert-True ([string]::IsNullOrEmpty($badGit.StdErr) -eq $false) "Invalid git subcommand: nonempty stderr"
Write-Host "[*] Invalid Git subcommand test OK" -ForegroundColor Green

} finally {
    # =====================================================================
    # Safe cleanup: verify path before recursive delete
    # =====================================================================
    if ($tempDir) {
        $fullPath = [System.IO.Path]::GetFullPath($tempDir)
        $fullTempRoot = [System.IO.Path]::GetFullPath($tempRoot)
        $leaf = Split-Path $fullPath -Leaf
        if ($fullPath.StartsWith($fullTempRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
            $leaf.StartsWith('sswcenter-seal-contract-')) {
            [System.IO.Directory]::EnumerateFiles($fullPath, '*', [System.IO.SearchOption]::AllDirectories) | ForEach-Object {
                [System.IO.File]::SetAttributes($_, [System.IO.FileAttributes]::Normal)
            }
            [System.IO.Directory]::Delete($fullPath, $true)
            Write-Host "[*] Cleaned up temp dir: $fullPath" -ForegroundColor Green
        } else {
            Write-Host "[!] SKIPPED cleanup – path verification failed: full=$fullPath root=$fullTempRoot leaf=$leaf" -ForegroundColor Yellow
        }
    }
}

# =========================================================================
# Emit final summary and exit
# =========================================================================
if ($Failed -eq 0) {
    Write-Output "WORKSPACE_SEAL_CONTRACT total=$Total passed=$Passed failed=0"
    exit 0
} else {
    foreach ($f in $Failures) {
        Write-Output "FAILURE: $f"
    }
    Write-Output "WORKSPACE_SEAL_CONTRACT total=$Total passed=$Passed failed=$Failed"
    exit 1
}
