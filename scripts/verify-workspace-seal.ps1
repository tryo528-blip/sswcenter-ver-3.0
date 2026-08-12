<#
.SYNOPSIS
    Read-only canonical workspace seal observer.
.DESCRIPTION
    Verifies workspace integrity by hashing frozen paths with SHA-256,
    checking Git diff status, and comparing against expected values.
    Never mutates any file, Git state, or environment.
.PARAMETER RepositoryRoot
    Path to the repository root. Defaults to the current directory.
.PARAMETER FrozenPath
    Array of repository-relative paths that constitute the frozen seal.
    Defaults to @('frontend/src', 'frontend/public', 'frontend/index.html').
.PARAMETER ExpectedHead
    Optional expected HEAD commit SHA. If supplied and mismatched, REJECT.
.PARAMETER ExpectedFrozenAggregate
    Optional expected SHA-256 of the frozen manifest. If supplied and mismatched, REJECT.
.PARAMETER JsonOutput
    Emit the result object as JSON (depth 20) instead of a single-line summary.
#>

[CmdletBinding()]
param(
    [string]$RepositoryRoot = '',
    [string[]]$FrozenPath = @('frontend/src', 'frontend/public', 'frontend/index.html'),
    [string]$ExpectedHead = '',
    [string]$ExpectedFrozenAggregate = '',
    [switch]$JsonOutput,
    [switch]$TestMode,
    [ValidateRange(0, 10000)]
    [int]$TestPauseAfterStartMilliseconds = 0,
    [string]$TestPauseStartedEventName = ''
)

# --------------------------------------------------------------------
# Helper: format a single argument for Windows CommandLineToArgvW
# --------------------------------------------------------------------
function Format-NativeArgument {
    param([string]$Arg)
    if ($Arg.Length -eq 0) { return '""' }
    # Only quote when the argument contains whitespace or a double-quote
    if ($Arg -match '[\s\t"]') {
        $sb = New-Object System.Text.StringBuilder
        [void]$sb.Append('"')
        $backslashes = 0
        foreach ($ch in $Arg.ToCharArray()) {
            if ($ch -eq '\') {
                $backslashes++
            } elseif ($ch -eq '"') {
                [void]$sb.Append('\', ($backslashes * 2))
                [void]$sb.Append('\"')
                $backslashes = 0
            } else {
                if ($backslashes -gt 0) {
                    [void]$sb.Append('\', $backslashes)
                    $backslashes = 0
                }
                [void]$sb.Append($ch)
            }
        }
        # double trailing backslashes so they don't escape the closing quote
        if ($backslashes -gt 0) {
            [void]$sb.Append('\', ($backslashes * 2))
        }
        [void]$sb.Append('"')
        return $sb.ToString()
    }
    return $Arg
}

# --------------------------------------------------------------------
# Invoke-NativeObserverProcess
# Uses System.Diagnostics.Process with redirected stdout/stderr.
# Captures stdout, stderr, and exit code independently.
# stderr with exit 0 is treated as a warning, not process failure.
# --------------------------------------------------------------------
function Invoke-NativeObserverProcess {
    param(
        [Parameter(Mandatory=$true)]
        [string]$FileName,
        [string[]]$ArgumentList = @(),
        [hashtable]$ExtraEnvironment = @{}
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $FileName
    $psi.Arguments = ($ArgumentList | ForEach-Object { Format-NativeArgument $_ }) -join ' '
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    # Use UTF-8 encoding when supported (.NET Framework 4.x+)
    try {
        $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    } catch {
        # Fall back to default encoding if UTF-8 not settable
    }

    if ($ExtraEnvironment.Count -gt 0) {
        foreach ($kvp in $ExtraEnvironment.GetEnumerator()) {
            $psi.EnvironmentVariables[$kvp.Key] = [string]$kvp.Value
        }
    }

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi

    try {
        $process.Start() | Out-Null
    } catch {
        # Build a synthetic result on start failure
        return [PSCustomObject]@{
            StdOut   = ''
            StdErr   = "Failed to start process '$FileName': $_"
            ExitCode = -1
        }
    }

    # Read both streams asynchronously to avoid deadlocks
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()

    $process.WaitForExit()

    $stdoutStr = ''
    $stderrStr = ''
    try { $stdoutStr = $stdoutTask.Result } catch { }
    try { $stderrStr = $stderrTask.Result } catch { }

    $exitCode = $process.ExitCode
    $process.Dispose()

    return [PSCustomObject]@{
        StdOut   = $stdoutStr
        StdErr   = $stderrStr
        ExitCode = $exitCode
    }
}

# --------------------------------------------------------------------
# Invoke-GitObserver
# Wraps git.exe with optional locks disabled and `core.quotePath=false`.
# Mutating commands are never issued.
# --------------------------------------------------------------------
function Invoke-GitObserver {
    param(
        [Parameter(Mandatory=$true)]
        [string[]]$Arguments,
        [string]$RepositoryPath = ''
    )

    $preArgs = @('--no-optional-locks', '-c', 'core.quotePath=false')
    $allArgs = $preArgs + $Arguments
    if ($RepositoryPath) {
        $allArgs = @('-C', $RepositoryPath) + $allArgs
    }

    return Invoke-NativeObserverProcess -FileName 'git.exe' -ArgumentList $allArgs -ExtraEnvironment @{ GIT_OPTIONAL_LOCKS = '0' }
}

# --------------------------------------------------------------------
# Test-IsFrozenPath
# Returns $true when $Path is equal to or a descendant of any $FrozenPaths entry.
# --------------------------------------------------------------------
function Test-IsFrozenPath {
    param(
        [string]$Path,
        [string[]]$FrozenPaths
    )
    $normalizedPath = $Path -replace '\\', '/'
    foreach ($fp in $FrozenPaths) {
        $normalizedFp = $fp -replace '\\', '/'
        if ($normalizedPath -eq $normalizedFp) { return $true }
        if ($normalizedPath.StartsWith($normalizedFp + '/', [System.StringComparison]::Ordinal)) { return $true }
    }
    return $false
}

# --------------------------------------------------------------------
# Get-FrozenManifestSha256
# Hashes every tracked file within the frozen paths (worktree bytes)
# and returns the SHA-256 of the sorted manifest string.
# --------------------------------------------------------------------
function Get-FrozenManifestSha256 {
    param(
        [string]$RepoRoot,
        [string[]]$FrozenPaths
    )

    $lsArgs = @('ls-files', '-z', '--') + $FrozenPaths
    $lsResult = Invoke-GitObserver -Arguments $lsArgs -RepositoryPath $RepoRoot

    if ($lsResult.ExitCode -ne 0) {
        throw "git ls-files exited $($lsResult.ExitCode): $($lsResult.StdErr)"
    }

    $trackedFiles = $lsResult.StdOut.Split([char[]]@([char]0), [System.StringSplitOptions]::RemoveEmptyEntries)

    if ($trackedFiles.Count -eq 0) {
        # Empty manifest → hash of empty UTF-8 byte sequence
        $sha = $null
        try {
            $sha = [System.Security.Cryptography.SHA256]::Create()
            $hashBytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes(''))
            return ([System.BitConverter]::ToString($hashBytes) -replace '-', '').ToLowerInvariant()
        } finally {
            if ($sha) { $sha.Dispose() }
        }
    }

    $records = New-Object 'System.Collections.Generic.List[string]'

    foreach ($relativePath in $trackedFiles) {
        $fullPath = Join-Path $RepoRoot $relativePath
        if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
            throw "Tracked file not found on disk: $fullPath"
        }

        $fileBytes = [System.IO.File]::ReadAllBytes($fullPath)
        $fileSha = $null
        try {
            $fileSha = [System.Security.Cryptography.SHA256]::Create()
            $hashBytes = $fileSha.ComputeHash($fileBytes)
            $hexHash = ([System.BitConverter]::ToString($hashBytes) -replace '-', '').ToLowerInvariant()
        } finally {
            if ($fileSha) { $fileSha.Dispose() }
        }

        $normalizedPath = $relativePath -replace '\\', '/'
        $records.Add("$normalizedPath|$hexHash")
    }

    # Sort with ordinal comparer
    $records.Sort([System.StringComparer]::Ordinal)

    # Join with CRLF, no final newline
    $manifestStr = $records -join "`r`n"

    $manifestSha = $null
    try {
        $manifestSha = [System.Security.Cryptography.SHA256]::Create()
        $manifestBytes = [System.Text.Encoding]::UTF8.GetBytes($manifestStr)
        $hashBytes = $manifestSha.ComputeHash($manifestBytes)
        return ([System.BitConverter]::ToString($hashBytes) -replace '-', '').ToLowerInvariant()
    } finally {
        if ($manifestSha) { $manifestSha.Dispose() }
    }
}

# --------------------------------------------------------------------
# --------------------------------------------------------------------
# Get-Sha256HexForBytes
# SHA-256 lowercase hex for a byte array. Disposes the algorithm.
# --------------------------------------------------------------------
function Get-Sha256HexForBytes {
    param([byte[]]$Bytes)
    $alg = $null
    try {
        $alg = [System.Security.Cryptography.SHA256]::Create()
        $hashBytes = $alg.ComputeHash($Bytes)
        return ([System.BitConverter]::ToString($hashBytes) -replace '-', '').ToLowerInvariant()
    } finally {
        if ($alg) { $alg.Dispose() }
    }
}

# --------------------------------------------------------------------
# Get-Sha256HexForText
# SHA-256 lowercase hex of the UTF-8 representation of a string.
# --------------------------------------------------------------------
function Get-Sha256HexForText {
    param([AllowEmptyString()][string]$Text)
    $utf8Bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    return Get-Sha256HexForBytes -Bytes $utf8Bytes
}

# --------------------------------------------------------------------
# Get-Sha256HexForFile
# SHA-256 lowercase hex of a file's bytes. Requires the path to be a leaf.
# --------------------------------------------------------------------
function Get-Sha256HexForFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Path is not a leaf file: $Path"
    }
    $fileBytes = [System.IO.File]::ReadAllBytes($Path)
    return Get-Sha256HexForBytes -Bytes $fileBytes
}

# --------------------------------------------------------------------
# Get-FrozenUntrackedManifestSha256
# Hashes every untracked file within the frozen paths and returns the
# SHA-256 of the sorted manifest string (CRLF join, no final newline).
# --------------------------------------------------------------------
function Get-FrozenUntrackedManifestSha256 {
    param(
        [string]$RepoRoot,
        [string[]]$FrozenPaths
    )

    $lsArgs = @('ls-files', '--others', '--exclude-standard', '-z', '--') + $FrozenPaths
    $lsResult = Invoke-GitObserver -Arguments $lsArgs -RepositoryPath $RepoRoot

    if ($lsResult.ExitCode -ne 0) {
        throw "git ls-files --others exited $($lsResult.ExitCode): $($lsResult.StdErr)"
    }

    $untrackedFiles = $lsResult.StdOut.Split([char[]]@([char]0), [System.StringSplitOptions]::RemoveEmptyEntries)

    if ($untrackedFiles.Count -eq 0) {
        return Get-Sha256HexForText -Text ''
    }

    $records = New-Object 'System.Collections.Generic.List[string]'

    foreach ($relativePath in $untrackedFiles) {
        $normalizedPath = $relativePath -replace '\\', '/'
        $fullPath = Join-Path $RepoRoot $relativePath
        if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
            throw "Untracked file not found on disk: $fullPath"
        }
        $hexHash = Get-Sha256HexForFile -Path $fullPath
        $records.Add("$normalizedPath|$hexHash")
    }

    $records.Sort([System.StringComparer]::Ordinal)

    $manifestStr = $records -join "`r`n"
    return Get-Sha256HexForText -Text $manifestStr
}

# --------------------------------------------------------------------
# Get-ObserverSnapshotSeal
# Returns a PSCustomObject with HEAD plus full-worktree and frozen-scope
# tracked/untracked manifests and a composite seal_sha256.
# --------------------------------------------------------------------
function Get-ObserverSnapshotSeal {
    param(
        [string]$RepoRoot,
        [string[]]$FrozenPaths
    )

    $revResult = Invoke-GitObserver -Arguments @('rev-parse', 'HEAD') -RepositoryPath $RepoRoot
    if ($revResult.ExitCode -ne 0) {
        throw "git rev-parse HEAD exited $($revResult.ExitCode): $($revResult.StdErr)"
    }
    $headSha = $revResult.StdOut.Trim()

    $tracked = Get-FrozenManifestSha256 -RepoRoot $RepoRoot -FrozenPaths @('.')
    $untracked = Get-FrozenUntrackedManifestSha256 -RepoRoot $RepoRoot -FrozenPaths @('.')
    $frozenTracked = Get-FrozenManifestSha256 -RepoRoot $RepoRoot -FrozenPaths $FrozenPaths
    $frozenUntracked = Get-FrozenUntrackedManifestSha256 -RepoRoot $RepoRoot -FrozenPaths $FrozenPaths

    $indexResult = Invoke-GitObserver -Arguments @('ls-files', '--stage', '-z', '--') -RepositoryPath $RepoRoot
    if ($indexResult.ExitCode -ne 0) {
        throw "git ls-files --stage exited $($indexResult.ExitCode): $($indexResult.StdErr)"
    }
    $indexManifest = Get-Sha256HexForText -Text $indexResult.StdOut

    $cachedDiffResult = Invoke-GitObserver -Arguments @(
        'diff', '--cached', '--binary', '--no-ext-diff', '--no-textconv', '--'
    ) -RepositoryPath $RepoRoot
    if ($cachedDiffResult.ExitCode -ne 0) {
        throw "git diff --cached --binary exited $($cachedDiffResult.ExitCode): $($cachedDiffResult.StdErr)"
    }
    $cachedDiff = Get-Sha256HexForText -Text $cachedDiffResult.StdOut

    $statusResult = Invoke-GitObserver -Arguments @(
        'status', '--porcelain=v2', '-z', '--untracked-files=all'
    ) -RepositoryPath $RepoRoot
    if ($statusResult.ExitCode -ne 0) {
        throw "git status --porcelain=v2 exited $($statusResult.ExitCode): $($statusResult.StdErr)"
    }
    $statusFingerprint = Get-Sha256HexForText -Text $statusResult.StdOut

    $composite = @(
        "head|$headSha"
        "tracked|$tracked"
        "untracked|$untracked"
        "frozen_tracked|$frozenTracked"
        "frozen_untracked|$frozenUntracked"
        "index|$indexManifest"
        "cached_diff|$cachedDiff"
        "status|$statusFingerprint"
    ) -join "`r`n"
    $seal = Get-Sha256HexForText -Text $composite

    return [PSCustomObject]@{
        head                               = $headSha
        tracked_manifest_sha256            = $tracked
        untracked_manifest_sha256          = $untracked
        frozen_manifest_sha256             = $frozenTracked
        frozen_untracked_manifest_sha256   = $frozenUntracked
        index_manifest_sha256              = $indexManifest
        cached_diff_sha256                 = $cachedDiff
        status_fingerprint_sha256          = $statusFingerprint
        seal_sha256                        = $seal
    }
}

# --------------------------------------------------------------------
# Test-ObserverSnapshotEqual
# Compares every seal component with ordinal string semantics.
# --------------------------------------------------------------------
function Test-ObserverSnapshotEqual {
    param(
        [object]$StartSnapshot,
        [object]$EndSnapshot
    )

    if ($null -eq $StartSnapshot -or $null -eq $EndSnapshot) {
        return $false
    }

    foreach ($propertyName in @(
        'head',
        'tracked_manifest_sha256',
        'untracked_manifest_sha256',
        'frozen_manifest_sha256',
        'frozen_untracked_manifest_sha256',
        'index_manifest_sha256',
        'cached_diff_sha256',
        'status_fingerprint_sha256',
        'seal_sha256'
    )) {
        $startValue = [string]$StartSnapshot.$propertyName
        $endValue = [string]$EndSnapshot.$propertyName
        if (-not [string]::Equals($startValue, $endValue, [System.StringComparison]::Ordinal)) {
            return $false
        }
    }

    return $true
}

# --------------------------------------------------------------------
# Add-ObserverSnapshotProperties
# Gives PASS and every REJECT/catch result the same stable JSON contract.
# --------------------------------------------------------------------
function Add-ObserverSnapshotProperties {
    param(
        [Parameter(Mandatory=$true)]
        [object]$Result,
        [object]$StartSnapshot,
        [object]$EndSnapshot,
        [string]$StartSealSha256,
        [string]$EndSealSha256,
        [bool]$SnapshotStable
    )

    Add-Member -InputObject $Result -NotePropertyName observer_start_snapshot -NotePropertyValue $StartSnapshot
    Add-Member -InputObject $Result -NotePropertyName observer_end_snapshot -NotePropertyValue $EndSnapshot
    Add-Member -InputObject $Result -NotePropertyName observer_start_seal_sha256 -NotePropertyValue $StartSealSha256
    Add-Member -InputObject $Result -NotePropertyName observer_end_seal_sha256 -NotePropertyValue $EndSealSha256
    Add-Member -InputObject $Result -NotePropertyName observer_snapshot_stable -NotePropertyValue $SnapshotStable
}

# Dot-source guard: return without running main logic when dot-sourced
# --------------------------------------------------------------------
if ($MyInvocation.InvocationName -eq '.') {
    return
}

# ====================================================================
# Main
# ====================================================================
$ErrorActionPreference = 'Stop'
try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
} catch {
    # Preserve read-only observation even if the host does not expose a mutable console encoding.
}
$errors = New-Object 'System.Collections.Generic.List[string]'
$warnings = New-Object 'System.Collections.Generic.List[string]'

function Record-Error {
    param([string]$Msg)
    # Do not Write-Error under $ErrorActionPreference=Stop (would terminate before callers finish).
    # Collect for structured result output only.
    $errors.Add($Msg)
}

# Result variables (populated progressively)
$status              = 'REJECT'
$repository_root     = ''
$head                = ''
$branch              = ''
$expected_head       = $ExpectedHead
$head_matches        = $false
$status_count        = 0
$staged_count        = 0
$staged_paths        = @()
$frozen_paths        = $FrozenPath
$frozen_file_count   = 0
$frozen_manifest     = ''
$expected_aggregate  = $ExpectedFrozenAggregate
$aggregate_matches   = $false
$frozen_diff_clean   = $false
$frozen_untracked_count = 0
$frozen_untracked_paths = @()
$diff_check_exit     = -1
$git_warnings_arr    = @()
$exit_code           = 1
$start_observer_snapshot = $null
$end_observer_snapshot = $null
$start_observer_seal = ''
$end_observer_seal = ''
$snapshot_stable = $false

try {
    # ----------------------------------------------------------------
    # 1. Resolve repository root
    # ----------------------------------------------------------------
    $candidateRoot = if ($RepositoryRoot) { $RepositoryRoot } else { (Get-Location).Path }
    $candidateFull = [System.IO.Path]::GetFullPath($candidateRoot)

    $revParseResult = Invoke-GitObserver -Arguments @('rev-parse', '--show-toplevel') -RepositoryPath $candidateFull
    if ($revParseResult.ExitCode -ne 0) {
        Record-Error "Not a Git repository or missing root: $candidateFull"
        throw "git rev-parse failed"
    }
    if ($revParseResult.StdErr) {
        $revParseResult.StdErr -split "`r?`n" | Where-Object { $_ } | ForEach-Object { $warnings.Add($_) }
    }

    $gitRoot = $revParseResult.StdOut.Trim()
    $gitRootFull = [System.IO.Path]::GetFullPath($gitRoot)
    $separatorChars = [char[]]@([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $candidatePathRoot = [System.IO.Path]::GetPathRoot($candidateFull)
    if (-not [string]::Equals($candidateFull, $candidatePathRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        $candidateFull = $candidateFull.TrimEnd($separatorChars)
    }
    $gitPathRoot = [System.IO.Path]::GetPathRoot($gitRootFull)
    if (-not [string]::Equals($gitRootFull, $gitPathRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        $gitRootFull = $gitRootFull.TrimEnd($separatorChars)
    }

    # Case-insensitive comparison of canonical paths
    if (-not [string]::Equals($candidateFull, $gitRootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        Record-Error "Repository root mismatch: supplied '$candidateFull', Git reports '$gitRootFull'"
        throw "Root mismatch"
    }
    $repository_root = $gitRootFull
    if (($TestPauseAfterStartMilliseconds -gt 0 -or $TestPauseStartedEventName) -and -not $TestMode) {
        throw 'OBSERVER_TEST_PAUSE_REQUIRES_TEST_MODE'
    }
    if ($TestPauseStartedEventName -and $TestPauseAfterStartMilliseconds -le 0) {
        throw 'OBSERVER_TEST_PAUSE_SIGNAL_REQUIRES_PAUSE'
    }
    $start_observer_snapshot = Get-ObserverSnapshotSeal -RepoRoot $repository_root -FrozenPaths $FrozenPath
    $start_observer_seal = $start_observer_snapshot.seal_sha256
    if ($TestMode -and $TestPauseAfterStartMilliseconds -gt 0) {
        if ($TestPauseStartedEventName) {
            $pauseStartedEvent = $null
            try {
                $pauseStartedEvent = [System.Threading.EventWaitHandle]::OpenExisting($TestPauseStartedEventName)
                [void]$pauseStartedEvent.Set()
            } catch {
                throw "OBSERVER_TEST_PAUSE_SIGNAL_FAILED: $($_.Exception.Message)"
            } finally {
                if ($pauseStartedEvent) { $pauseStartedEvent.Dispose() }
            }
        }
        Start-Sleep -Milliseconds $TestPauseAfterStartMilliseconds
    }

    # ----------------------------------------------------------------
    # 2. Obtain HEAD
    # ----------------------------------------------------------------
    $headResult = Invoke-GitObserver -Arguments @('rev-parse', 'HEAD') -RepositoryPath $repository_root
    if ($headResult.ExitCode -ne 0) {
        Record-Error "git rev-parse HEAD exited $($headResult.ExitCode): $($headResult.StdErr)"
        throw "HEAD resolution failed"
    }
    if ($headResult.StdErr) {
        $headResult.StdErr -split "`r?`n" | Where-Object { $_ } | ForEach-Object { $warnings.Add($_) }
    }
    $head = $headResult.StdOut.Trim()

    # ----------------------------------------------------------------
    # 3. Obtain branch
    # ----------------------------------------------------------------
    $branchResult = Invoke-GitObserver -Arguments @('rev-parse', '--abbrev-ref', 'HEAD') -RepositoryPath $repository_root
    if ($branchResult.ExitCode -ne 0) {
        Record-Error "git rev-parse --abbrev-ref HEAD exited $($branchResult.ExitCode)"
        throw "Branch resolution failed"
    }
    if ($branchResult.StdErr) {
        $branchResult.StdErr -split "`r?`n" | Where-Object { $_ } | ForEach-Object { $warnings.Add($_) }
    }
    $branch = $branchResult.StdOut.Trim()

    # ----------------------------------------------------------------
    # 4. Porcelain-v2 status with untracked files (NUL-delimited)
    # ----------------------------------------------------------------
    $statusResult = Invoke-GitObserver -Arguments @(
        'status', '--porcelain=v2', '--branch', '-z', '--untracked-files=all'
    ) -RepositoryPath $repository_root

    if ($statusResult.ExitCode -ne 0) {
        Record-Error "git status exited $($statusResult.ExitCode): $($statusResult.StdErr)"
        throw "Status failed"
    }
    if ($statusResult.StdErr) {
        $statusResult.StdErr -split "`r?`n" | Where-Object { $_ } | ForEach-Object { $warnings.Add($_) }
    }

    # Parse NUL-delimited porcelain v2 records
    $rawRecords = $statusResult.StdOut.Split([char[]]@([char]0), [System.StringSplitOptions]::RemoveEmptyEntries)
    $allStatusPaths = New-Object 'System.Collections.Generic.List[string]'
    $stagedPathsList = New-Object 'System.Collections.Generic.List[string]'

    foreach ($rec in $rawRecords) {
        if ($rec.StartsWith('# branch.')) { continue }

        if ($rec.StartsWith('? ')) {
            # Untracked
            $p = $rec.Substring(2)
            $allStatusPaths.Add($p)
            if (Test-IsFrozenPath -Path $p -FrozenPaths $FrozenPath) {
                $frozen_untracked_paths += $p
            }
        } elseif ($rec.StartsWith('! ')) {
            # Ignored
            $p = $rec.Substring(2)
            $allStatusPaths.Add($p)
        } elseif ($rec[0] -match '^[12u]$') {
            # Tracked file entry: 1/2/u + space + XY + sub + mH + mI + mW + hH + hI + path
            # Split into at most 9 tokens
            $tokens = $rec -split ' ', 9
            if ($tokens.Count -lt 9) { continue }
            $p = $tokens[8]
            $xy = $tokens[1]
            $allStatusPaths.Add($p)
            # Staged when X (first char of XY) is not '.'
            if ($xy.Length -ge 1 -and $xy[0] -ne '.') {
                $stagedPathsList.Add($p)
            }
        }
    }

    $status_count = $allStatusPaths.Count
    $stagedResult = Invoke-GitObserver -Arguments @('diff', '--cached', '--name-only', '-z') -RepositoryPath $repository_root
    if ($stagedResult.ExitCode -ne 0) {
        Record-Error "git diff --cached --name-only exited $($stagedResult.ExitCode): $($stagedResult.StdErr)"
        throw 'Staged path observation failed'
    }
    if ($stagedResult.StdErr) {
        $stagedResult.StdErr -split "`r?`n" | Where-Object { $_ } | ForEach-Object { $warnings.Add($_) }
    }
    $staged_paths = @(
        $stagedResult.StdOut.Split([char[]]@([char]0), [System.StringSplitOptions]::RemoveEmptyEntries) |
            ForEach-Object { $_ -replace '\\', '/' }
    )
    $staged_count = $staged_paths.Count
    # Canonical staged paths were populated by git diff --cached above.
    $frozenUntrackedResult = Invoke-GitObserver -Arguments (@('ls-files', '--others', '--exclude-standard', '-z', '--') + $FrozenPath) -RepositoryPath $repository_root
    if ($frozenUntrackedResult.ExitCode -ne 0) {
        Record-Error "git ls-files --others exited $($frozenUntrackedResult.ExitCode): $($frozenUntrackedResult.StdErr)"
        throw 'Frozen untracked observation failed'
    }
    if ($frozenUntrackedResult.StdErr) {
        $frozenUntrackedResult.StdErr -split "`r?`n" | Where-Object { $_ } | ForEach-Object { $warnings.Add($_) }
    }
    $frozen_untracked_paths = @(
        $frozenUntrackedResult.StdOut.Split([char[]]@([char]0), [System.StringSplitOptions]::RemoveEmptyEntries) |
            ForEach-Object { $_ -replace '\\', '/' }
    )
    $frozen_untracked_count = $frozen_untracked_paths.Count

    # ----------------------------------------------------------------
    # 5. Frozen manifest SHA-256
    # ----------------------------------------------------------------
    $frozen_file_count = 0
    try {
        $lsCountResult = Invoke-GitObserver -Arguments (@('ls-files', '-z', '--') + $FrozenPath) -RepositoryPath $repository_root
        if ($lsCountResult.ExitCode -eq 0) {
            $trackedFrozen = $lsCountResult.StdOut.Split([char[]]@([char]0), [System.StringSplitOptions]::RemoveEmptyEntries)
            $frozen_file_count = $trackedFrozen.Count
        }
        if ($lsCountResult.StdErr) {
            $lsCountResult.StdErr -split "`r?`n" | Where-Object { $_ } | ForEach-Object { $warnings.Add($_) }
        }
    } catch { }

    $frozen_manifest = Get-FrozenManifestSha256 -RepoRoot $repository_root -FrozenPaths $FrozenPath

    # ----------------------------------------------------------------
    # 6. Frozen diff: git diff --quiet HEAD -- <FrozenPath>
    #    Respect repository conversion settings; stderr warnings are collected separately.
    # ----------------------------------------------------------------
    $diffResult = Invoke-GitObserver -Arguments (@(
        'diff', '--quiet', 'HEAD', '--'
    ) + $FrozenPath) -RepositoryPath $repository_root

    if ($diffResult.StdErr) {
        $diffResult.StdErr -split "`r?`n" | Where-Object { $_ } | ForEach-Object { $warnings.Add($_) }
    }

    if ($diffResult.ExitCode -eq 0) {
        $frozen_diff_clean = $true
    } elseif ($diffResult.ExitCode -eq 1) {
        $frozen_diff_clean = $false
    } else {
        # Unexpected exit code → Git error
        Record-Error "git diff --quiet exited unexpectedly ($($diffResult.ExitCode)): $($diffResult.StdErr)"
    }

    # ----------------------------------------------------------------
    # 7. Whole-worktree diff check using repository conversion settings
    # ----------------------------------------------------------------
    $diffCheckResult = Invoke-GitObserver -Arguments (@(
        'diff', '--check', '--', '.'
    ) + $FrozenPath) -RepositoryPath $repository_root

    if ($diffCheckResult.StdErr) {
        $diffCheckResult.StdErr -split "`r?`n" | Where-Object { $_ } | ForEach-Object { $warnings.Add($_) }
    }

    $diff_check_exit = $diffCheckResult.ExitCode
    # --check exit 0 = clean, non-zero = whitespace errors (or git error; treat as fail-closed)

    # ----------------------------------------------------------------
    # 8. Collect warnings from any prior git commands with exit-0 stderr
    #    (already done inline above)
    # ----------------------------------------------------------------
    $git_warnings_arr = $warnings.ToArray()

    # ----------------------------------------------------------------
    $end_observer_snapshot = Get-ObserverSnapshotSeal -RepoRoot $repository_root -FrozenPaths $FrozenPath
    $end_observer_seal = $end_observer_snapshot.seal_sha256
    $snapshot_stable = Test-ObserverSnapshotEqual -StartSnapshot $start_observer_snapshot -EndSnapshot $end_observer_snapshot
    if (-not $snapshot_stable) {
        $errors.Add('OBSERVER_SNAPSHOT_CHANGED')
    }

    # 9. Determine PASS / REJECT
    # ----------------------------------------------------------------
    $pass = $true

    # Errors accumulated?
    if ($errors.Count -gt 0) {
        $pass = $false
    }

    # Frozen diff must be clean
    if (-not $frozen_diff_clean) {
        $pass = $false
    }

    # No frozen untracked files allowed
    if ($frozen_untracked_count -gt 0) {
        $pass = $false
    }

    # diff-check must succeed (exit 0)
    if ($diff_check_exit -ne 0) {
        $pass = $false
    }

    # ExpectedHead match (if supplied)
    if ($ExpectedHead) {
        $head_matches = [string]::Equals($head, $ExpectedHead, [System.StringComparison]::OrdinalIgnoreCase)
        if (-not $head_matches) {
            $pass = $false
        }
    } else {
        $head_matches = $true
    }

    # ExpectedFrozenAggregate match (if supplied)
    if ($ExpectedFrozenAggregate) {
        $aggregate_matches = [string]::Equals($frozen_manifest, $ExpectedFrozenAggregate, [System.StringComparison]::OrdinalIgnoreCase)
        if (-not $aggregate_matches) {
            $pass = $false
        }
    } else {
        $aggregate_matches = $true
    }

    $status = if ($pass) { 'PASS' } else { 'REJECT' }
    $exit_code = if ($pass) { 0 } else { 1 }

    # ----------------------------------------------------------------
    # 10. Build result object
    # ----------------------------------------------------------------
    $result = [PSCustomObject]@{
        status                    = $status
        repository_root           = $repository_root
        head                      = $head
        branch                    = $branch
        expected_head             = $expected_head
        head_matches              = $head_matches
        status_count              = $status_count
        staged_count              = $staged_count
        staged_paths              = $staged_paths
        frozen_paths              = $frozen_paths
        frozen_file_count         = $frozen_file_count
        frozen_manifest_sha256    = $frozen_manifest
        expected_frozen_aggregate = $expected_aggregate
        frozen_aggregate_matches  = $aggregate_matches
        frozen_diff_clean         = $frozen_diff_clean
        frozen_untracked_count    = $frozen_untracked_count
        frozen_untracked_paths    = $frozen_untracked_paths
        diff_check_exit_code      = $diff_check_exit
        git_warnings              = $git_warnings_arr
        errors                    = $errors.ToArray()
        exit_code                 = $exit_code
    }

    # ----------------------------------------------------------------
    Add-ObserverSnapshotProperties -Result $result `
        -StartSnapshot $start_observer_snapshot `
        -EndSnapshot $end_observer_snapshot `
        -StartSealSha256 $start_observer_seal `
        -EndSealSha256 $end_observer_seal `
        -SnapshotStable ([bool]$snapshot_stable)
    # 11. Emit output
    # ----------------------------------------------------------------
    if ($JsonOutput) {
        $result | ConvertTo-Json -Depth 20
    } else {
        $line = "$status | root=$repository_root head=$head branch=$branch frozen_files=$frozen_file_count"
        $line += " sha256=$frozen_manifest diff_clean=$frozen_diff_clean untracked=$frozen_untracked_count"
        $line += " diff_check=$diff_check_exit staged=$staged_count statuses=$status_count"
        if ($ExpectedHead) { $line += " head_match=$head_matches" }
        if ($ExpectedFrozenAggregate) { $line += " aggregate_match=$aggregate_matches" }
        Write-Output $line
    }

} catch {
    $status = 'REJECT'
    $exit_code = 1
    $caughtErrorMessage = $_.Exception.Message

    if ($start_observer_snapshot -and -not $end_observer_snapshot -and $repository_root) {
        try {
            $end_observer_snapshot = Get-ObserverSnapshotSeal -RepoRoot $repository_root -FrozenPaths $FrozenPath
            $end_observer_seal = $end_observer_snapshot.seal_sha256
            $snapshot_stable = Test-ObserverSnapshotEqual -StartSnapshot $start_observer_snapshot -EndSnapshot $end_observer_snapshot
            if (-not $snapshot_stable -and -not $errors.Contains('OBSERVER_SNAPSHOT_CHANGED')) {
                $errors.Add('OBSERVER_SNAPSHOT_CHANGED')
            }
        } catch {
            $snapshot_stable = $false
        }
    }

    # Ensure the exception is recorded if not already
    $errMsg = $caughtErrorMessage
    if ($errMsg -and ($errors.Count -eq 0 -or $errors[-1] -ne $errMsg)) {
        $errors.Add($errMsg)
    }

    $result = [PSCustomObject]@{
        status                    = $status
        repository_root           = $repository_root
        head                      = $head
        branch                    = $branch
        expected_head             = $expected_head
        head_matches              = $head_matches
        status_count              = $status_count
        staged_count              = $staged_count
        staged_paths              = $staged_paths
        frozen_paths              = $frozen_paths
        frozen_file_count         = $frozen_file_count
        frozen_manifest_sha256    = $frozen_manifest
        expected_frozen_aggregate = $expected_aggregate
        frozen_aggregate_matches  = $aggregate_matches
        frozen_diff_clean         = $frozen_diff_clean
        frozen_untracked_count    = $frozen_untracked_count
        frozen_untracked_paths    = $frozen_untracked_paths
        diff_check_exit_code      = $diff_check_exit
        git_warnings              = $git_warnings_arr
        errors                    = $errors.ToArray()
        exit_code                 = $exit_code
    }

    Add-ObserverSnapshotProperties -Result $result `
        -StartSnapshot $start_observer_snapshot `
        -EndSnapshot $end_observer_snapshot `
        -StartSealSha256 $start_observer_seal `
        -EndSealSha256 $end_observer_seal `
        -SnapshotStable ([bool]$snapshot_stable)

    if ($JsonOutput) {
        $result | ConvertTo-Json -Depth 20
    } else {
        Write-Output "REJECT | errors=$($errors.Count) $($errors -join '; ')"
    }
}

exit $exit_code
