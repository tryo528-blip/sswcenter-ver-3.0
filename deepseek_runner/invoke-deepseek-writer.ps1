#!/usr/bin/env pwsh
# invoke-deepseek-writer.ps1
# DeepSeek Writer Runner v0.2 — implementation of the integrated design
# PowerShell 7.x only. UTF-8 no BOM + LF.

<#
.SYNOPSIS
    DeepSeek Writer Runner — reliable multi-file code implementation agent.

.PARAMETER RepoRoot
    Absolute or relative path to the target repository root. REQUIRED.

.PARAMETER EnvFile
    Fixed authentication file. The only accepted path is
    C:\sswcenter\api-keys.local.env. No credential search or environment
    variable fallback is performed.

.PARAMETER Model
    Model id (default: deepseek-v4-pro).

.PARAMETER MaxTurns
    Soft segment size. Reaching it starts another in-memory segment when the
    Writer has made real progress (default 80). Persistent checkpoints and
    run-history files are disabled by policy.

.PARAMETER MaxReadCalls
    Safety fuse (default 60).

.PARAMETER MaxBatchBytes
    Memory preimage limit per edit batch (default 8MB).

.PARAMETER Thinking
    Enable thinking / reasoning_content (default $true).

.PARAMETER WriteAllowList
    Relative paths allowed for writes. Writer execution requires a non-empty,
    explicit scope (a deliberate "." means the repository root).

.PARAMETER ReadAllowList
    Relative paths allowed for reads. Empty means all non-sensitive paths under RepoRoot.

.PARAMETER MaxTokens
    Maximum provider output tokens per request.

.PARAMETER TaskPacketPath
    JSON Task Packet. It names the task, read/write scope, delete policy,
    required changes, prohibitions, completion criteria, and report contract.
    Exactly one of TaskPacketPath or TaskPacketJson is required.  Writer runs
    never accept an unstructured natural-language task.

.EXAMPLE
    ./invoke-deepseek-writer.ps1 -RepoRoot /path/to/repo -TaskPacketPath ./task-packet.json
#>

[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [string]$TaskPacketPath = '',
    [string]$TaskPacketJson = '',
    [string]$EnvFile = 'C:\sswcenter\api-keys.local.env',
    [string]$Model = 'deepseek-v4-pro',
    [int]$MaxTurns = 80,
    [int]$MaxReadCalls = 60,
    [int]$MaxNoProgressSegments = 3,
    [int]$MaxTransportRetries = 8,
    [int]$MaxRateLimitRetries = 8,
    [long]$MaxBatchBytes = 8MB,
    [ValidateRange(128, 32768)][int]$MaxTokens = 32768,
    [ValidateSet('low', 'high', 'max')][string]$ReasoningEffort = 'high',
    [bool]$Thinking = $true,
    [int]$RequestTimeoutSec = 300,
    [string]$SystemPromptExtra = '',
    [string[]]$WriteAllowList = @(),
    [string[]]$ReadAllowList = @(),
    [string]$RunId = '',
    [switch]$Resume,
    [string]$MockResponsesPath = '',
    [int]$MockCrashAfterResponses = 0
)

# PowerShell 5.1 bootstrap must run before StrictMode, module imports, or any
# PowerShell 7/.NET-only API. Bound non-secret arguments are forwarded to the
# same-volume portable pwsh. The PS7 child reads only the fixed EnvFile path.
$script:BootstrapMarkerVariable = 'DSW_WRITER_BOOTSTRAP_SCRIPT'
$script:BootstrapArraysVariable = 'DSW_WRITER_BOOTSTRAP_ARRAYS_B64'

function Write-BootstrapFailureAndExit {
    param([Parameter(Mandatory)][string]$Message)
    $bootstrapFailureRunId = if ([string]::IsNullOrWhiteSpace($RunId)) { [guid]::NewGuid().ToString('N') } else { $RunId }
    [ordered]@{
        status = 'FAIL'
        run_id = $bootstrapFailureRunId
        stop_reason = 'POWERSHELL7_BOOTSTRAP_FAILED'
        final_response = $Message
        final_summary = $Message
        tests = @{ status = 'NOT_RUN'; reason = 'Runner bootstrap did not reach the Writer.' }
        resume_available = $false
    } | ConvertTo-Json -Depth 6
    exit 2
}

if ($PSVersionTable.PSVersion.Major -lt 7) {
    $bootstrapRunnerCandidates = @($PSScriptRoot, 'C:\sswcenter\3.0\deepseek_runner')
    $bootstrapRunnerRoot = ''
    foreach ($candidate in @($bootstrapRunnerCandidates | Select-Object -Unique)) {
        if ([string]::IsNullOrWhiteSpace([string]$candidate)) { continue }
        $marker = Join-Path $candidate '.dsw-root'
        if ((Test-Path -LiteralPath $candidate -PathType Container) -and
            (Test-Path -LiteralPath $marker -PathType Leaf) -and
            ((Get-Content -LiteralPath $marker -Raw -ErrorAction SilentlyContinue).Trim() -eq 'dsw-runner-v0.2')) {
            $bootstrapRunnerRoot = [System.IO.Path]::GetFullPath($candidate)
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($bootstrapRunnerRoot)) {
        Write-BootstrapFailureAndExit -Message 'POWERSHELL7_BOOTSTRAP_FAILED: no valid runner root was found before module import'
    }

    $bootstrapRunnerParent = Split-Path -Parent $bootstrapRunnerRoot
    $bootstrapBundleRoot = if ((Split-Path -Leaf $bootstrapRunnerParent).Equals('runner', [System.StringComparison]::OrdinalIgnoreCase)) {
        Split-Path -Parent $bootstrapRunnerParent
    } else {
        $bootstrapRunnerParent
    }
    $bootstrapVolumeRoot = [System.IO.Path]::GetPathRoot($bootstrapRunnerRoot)
    $bootstrapPwshCandidates = @(
        [System.IO.Path]::Combine($bootstrapVolumeRoot, 'tools\PowerShell7\pwsh.exe'),
        [System.IO.Path]::Combine($bootstrapBundleRoot, 'tools\PowerShell7\pwsh.exe')
    ) | Select-Object -Unique | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf }
    if (@($bootstrapPwshCandidates).Count -eq 0) {
        Write-BootstrapFailureAndExit -Message 'POWERSHELL7_REQUIRED: same-volume tools\PowerShell7\pwsh.exe was not found'
    }
    if (@($bootstrapPwshCandidates).Count -gt 1) {
        Write-BootstrapFailureAndExit -Message 'PORTABLE_PWSH_AMBIGUOUS: more than one same-volume PowerShell 7 executable was found'
    }

    $bootstrapPwshPath = [string]@($bootstrapPwshCandidates)[0]
    $relaunchArgs = New-Object System.Collections.ArrayList
    $null = $relaunchArgs.Add('-NoProfile')
    $null = $relaunchArgs.Add('-File')
    $null = $relaunchArgs.Add($PSCommandPath)
    $bootstrapArrayParameters = [ordered]@{}
    foreach ($entry in $PSBoundParameters.GetEnumerator()) {
        if ($entry.Value -is [System.Management.Automation.SwitchParameter]) {
            if ([bool]$entry.Value) { $null = $relaunchArgs.Add("-$($entry.Key)") }
            continue
        }
        if ($entry.Value -is [bool]) {
            $bootstrapBooleanLiteral = if ([bool]$entry.Value) { '$true' } else { '$false' }
            $null = $relaunchArgs.Add("-$($entry.Key):$bootstrapBooleanLiteral")
            continue
        }
        if ($entry.Value -is [System.Array]) {
            # Native PowerShell -File argument binding cannot preserve a
            # string[] element boundary when an element itself contains a
            # comma. Carry bound arrays in an encoded inherited environment
            # payload and restore them in the PS7 child instead.
            $bootstrapArrayParameters[$entry.Key] = [string[]]@($entry.Value | ForEach-Object { [string]$_ })
            continue
        }
        $null = $relaunchArgs.Add("-$($entry.Key)")
        $null = $relaunchArgs.Add([string]$entry.Value)
    }
    $bootstrapArraysJson = $bootstrapArrayParameters | ConvertTo-Json -Depth 4 -Compress
    $bootstrapArraysEncoded = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($bootstrapArraysJson))

    $priorBootstrapMarker = [Environment]::GetEnvironmentVariable($script:BootstrapMarkerVariable, 'Process')
    $priorBootstrapArrays = [Environment]::GetEnvironmentVariable($script:BootstrapArraysVariable, 'Process')
    $bootstrapExitCode = 2
    try {
        [Environment]::SetEnvironmentVariable($script:BootstrapMarkerVariable, [System.IO.Path]::GetFullPath($PSCommandPath), 'Process')
        [Environment]::SetEnvironmentVariable($script:BootstrapArraysVariable, $bootstrapArraysEncoded, 'Process')
        & $bootstrapPwshPath @($relaunchArgs)
        $bootstrapExitCode = $LASTEXITCODE
    } finally {
        [Environment]::SetEnvironmentVariable($script:BootstrapMarkerVariable, $priorBootstrapMarker, 'Process')
        [Environment]::SetEnvironmentVariable($script:BootstrapArraysVariable, $priorBootstrapArrays, 'Process')
    }
    exit $bootstrapExitCode
}

$bootstrapReadAllowListRestored = $false
$bootstrapWriteAllowListRestored = $false
$bootstrapMarker = [Environment]::GetEnvironmentVariable($script:BootstrapMarkerVariable, 'Process')
if (-not [string]::IsNullOrWhiteSpace($bootstrapMarker) -and
    [System.IO.Path]::GetFullPath($bootstrapMarker).Equals([System.IO.Path]::GetFullPath($PSCommandPath), [System.StringComparison]::OrdinalIgnoreCase)) {
    $bootstrapArraysEncoded = [Environment]::GetEnvironmentVariable($script:BootstrapArraysVariable, 'Process')
    [Environment]::SetEnvironmentVariable($script:BootstrapArraysVariable, $null, 'Process')
    [Environment]::SetEnvironmentVariable($script:BootstrapMarkerVariable, $null, 'Process')
    if (-not [string]::IsNullOrWhiteSpace($bootstrapArraysEncoded)) {
        try {
            $bootstrapArraysJson = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($bootstrapArraysEncoded))
            $bootstrapArrayParameters = $bootstrapArraysJson | ConvertFrom-Json
            foreach ($arrayProperty in @($bootstrapArrayParameters.PSObject.Properties)) {
                if ($arrayProperty.Value -isnot [System.Array]) {
                    throw "array parameter '$($arrayProperty.Name)' was not encoded as an array"
                }
                switch -CaseSensitive ($arrayProperty.Name) {
                    'ReadAllowList' {
                        $ReadAllowList = [string[]]@($arrayProperty.Value)
                        $bootstrapReadAllowListRestored = $true
                    }
                    'WriteAllowList' {
                        $WriteAllowList = [string[]]@($arrayProperty.Value)
                        $bootstrapWriteAllowListRestored = $true
                    }
                    default { throw "unsupported array parameter '$($arrayProperty.Name)'" }
                }
            }
        } catch {
            Write-BootstrapFailureAndExit -Message "POWERSHELL7_BOOTSTRAP_FAILED: array parameter payload is invalid: $($_.Exception.Message)"
        }
    }
}

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# A runner failure must still hand the caller a machine-readable, non-empty
# report.  The normal loop writes a richer envelope below; this trap covers
# malformed startup input and unexpected host failures without exposing keys.
$script:BootstrapRunId = if ([string]::IsNullOrWhiteSpace($RunId)) { [guid]::NewGuid().ToString('N') } else { $RunId }
trap {
    $safeMessage = [string]$_.Exception.Message
    if ([string]::IsNullOrWhiteSpace($safeMessage)) { $safeMessage = 'Unexpected runner failure.' }
    [ordered]@{
        status = 'FAIL'
        run_id = $script:BootstrapRunId
        stop_reason = 'RUNNER_STARTUP_OR_UNHANDLED_FAILURE'
        final_response = "Runner failed safely: $safeMessage"
        final_summary = "Runner failed safely: $safeMessage"
        error_location = [string]$_.ScriptStackTrace
        tests = @{ status = 'NOT_RUN'; reason = 'DeepSeek Writer is not given test execution tools.' }
        resume_available = $false
    } | ConvertTo-Json -Depth 6
    exit 2
}

if ($RequestTimeoutSec -lt 30 -or $RequestTimeoutSec -gt 3600) {
    throw "REQUEST_TIMEOUT_INVALID: RequestTimeoutSec must be between 30 and 3600 (got $RequestTimeoutSec)"
}
if ($MaxTurns -lt 1) { throw "MAX_TURNS_INVALID: MaxTurns must be greater than zero" }
if ($MaxReadCalls -lt 1) { throw "MAX_READ_CALLS_INVALID: MaxReadCalls must be greater than zero" }
if ($MaxNoProgressSegments -lt 1) { throw "MAX_NO_PROGRESS_SEGMENTS_INVALID: value must be greater than zero" }
if ($MaxTransportRetries -lt 0 -or $MaxRateLimitRetries -lt 0) { throw "RETRY_LIMIT_INVALID: retry limits cannot be negative" }
if ($MockCrashAfterResponses -lt 0) { throw 'MOCK_CRASH_AFTER_RESPONSES_INVALID: value cannot be negative' }

# ---------------------------------------------------------------------------
# Resolve runner location (4-slot design adapted for cross-platform)
# ---------------------------------------------------------------------------
$script:CandidateRoots = @(
    @{ Label = 'SSWCenter 3.0 fixed runner'; Path = 'C:\sswcenter\3.0\deepseek_runner' }
)

function Test-RunnerRootValid {
    param([string]$Path)
    if (-not $Path) { return $false }
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return $false }
    $marker = Join-Path $Path '.dsw-root'
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { return $false }
    $ver = (Get-Content -LiteralPath $marker -Raw -ErrorAction SilentlyContinue).Trim()
    if ($ver -ne 'dsw-runner-v0.2') { return $false }
    foreach ($mod in @('Workspace.psm1','EditBatch.psm1','DeepSeekClient.psm1')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Path $mod) -PathType Leaf)) { return $false }
    }
    return $true
}

function Find-RunnerRoot {
    # 1) Always prefer the directory of the running script when valid
    if ($PSScriptRoot -and (Test-RunnerRootValid -Path $PSScriptRoot)) {
        return $PSScriptRoot
    }
    # 2) Candidate roots (must have correct marker + modules)
    foreach ($c in $script:CandidateRoots) {
        if (Test-RunnerRootValid -Path $c.Path) {
            return $c.Path
        }
    }
    $tried = @()
    if ($PSScriptRoot) { $tried += "PSScriptRoot=$PSScriptRoot" }
    foreach ($c in $script:CandidateRoots) { $tried += "$($c.Label)=$($c.Path)" }
    throw "RUNNER_ROOT_INVALID: no valid runner root (need .dsw-root=dsw-runner-v0.2 + modules). Tried: $($tried -join '; ')"
}

$RunnerRoot = Find-RunnerRoot

function ConvertTo-PathList {
    param([string[]]$Values, [switch]$PreserveElements)
    $expandedValues = if ($PreserveElements) {
        @($Values)
    } else {
        @($Values | ForEach-Object { $_ -split ',' })
    }
    return @($expandedValues |
        ForEach-Object { ([string]$_).Trim() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Get-InputMember {
    param($Object, [string]$Name, $Default = $null)
    if ($null -eq $Object) { return $Default }
    if ($Object -is [System.Collections.IDictionary]) {
        if ($Object.Contains($Name)) { return $Object[$Name] }
        return $Default
    }
    $prop = $Object.PSObject.Properties[$Name]
    if ($prop) { return $prop.Value }
    return $Default
}

function Test-InputHasMember {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $false }
    if ($Object -is [System.Collections.IDictionary]) { return $Object.Contains($Name) }
    return $null -ne $Object.PSObject.Properties[$Name]
}

function Get-RequiredPacketStrings {
    param($Packet, [string]$Name, [switch]$AllowEmpty)
    if (-not (Test-InputHasMember -Object $Packet -Name $Name)) { throw "TASK_PACKET_INVALID: missing '$Name'" }
    $values = @((Get-InputMember -Object $Packet -Name $Name) | ForEach-Object { [string]$_ } | ForEach-Object { $_.Trim() } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if (-not $AllowEmpty -and $values.Count -eq 0) { throw "TASK_PACKET_INVALID: '$Name' must not be empty" }
    return [string[]]$values
}

function Get-CanonicalJsonHash {
    param($Object)
    $json = $Object | ConvertTo-Json -Depth 30 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $hash = [System.Security.Cryptography.SHA256]::HashData($bytes)
    return ([BitConverter]::ToString($hash) -replace '-','').ToLowerInvariant()
}

function ConvertTo-TaskPacket {
    param([Parameter(Mandatory)]$RawPacket)
    foreach ($required in @('task_id','objective','read_paths','write_paths','allow_delete','required_changes','prohibited','completion_criteria','report_format')) {
        if (-not (Test-InputHasMember -Object $RawPacket -Name $required)) { throw "TASK_PACKET_INVALID: missing '$required'" }
    }
    $taskId = [string](Get-InputMember -Object $RawPacket -Name 'task_id')
    $objective = [string](Get-InputMember -Object $RawPacket -Name 'objective')
    if ([string]::IsNullOrWhiteSpace($taskId) -or $taskId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') { throw 'TASK_PACKET_INVALID: task_id must be a safe non-empty identifier' }
    if ([string]::IsNullOrWhiteSpace($objective)) { throw 'TASK_PACKET_INVALID: objective must not be empty' }
    $readPaths = @(Get-RequiredPacketStrings -Packet $RawPacket -Name 'read_paths')
    $writePaths = @(Get-RequiredPacketStrings -Packet $RawPacket -Name 'write_paths')
    $requiredChanges = @(Get-RequiredPacketStrings -Packet $RawPacket -Name 'required_changes')
    $prohibited = @(Get-RequiredPacketStrings -Packet $RawPacket -Name 'prohibited' -AllowEmpty)
    $allowDeleteRaw = Get-InputMember -Object $RawPacket -Name 'allow_delete'
    if ($allowDeleteRaw -isnot [bool]) { throw 'TASK_PACKET_INVALID: allow_delete must be boolean' }
    $format = [string](Get-InputMember -Object $RawPacket -Name 'report_format')
    if ($format -ne 'completion_evidence_json_v1') { throw 'TASK_PACKET_INVALID: report_format must be completion_evidence_json_v1' }
    $criteria = [System.Collections.Generic.List[object]]::new()
    $criterionIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    foreach ($criterion in @(Get-InputMember -Object $RawPacket -Name 'completion_criteria')) {
        $id = [string](Get-InputMember -Object $criterion -Name 'id')
        $description = [string](Get-InputMember -Object $criterion -Name 'description')
        if ([string]::IsNullOrWhiteSpace($id) -or [string]::IsNullOrWhiteSpace($description)) { throw 'TASK_PACKET_INVALID: every completion_criteria item needs id and description' }
        if (-not $criterionIds.Add($id)) { throw "TASK_PACKET_INVALID: duplicate completion criterion id '$id'" }
        $criteria.Add([ordered]@{ id = $id; description = $description })
    }
    if ($criteria.Count -eq 0) { throw 'TASK_PACKET_INVALID: completion_criteria must not be empty' }
    return [ordered]@{
        task_id = $taskId
        objective = $objective.Trim()
        read_paths = [string[]]$readPaths
        write_paths = [string[]]$writePaths
        allow_delete = [bool]$allowDeleteRaw
        required_changes = [string[]]$requiredChanges
        prohibited = [string[]]$prohibited
        completion_criteria = @($criteria)
        report_format = $format
    }
}

function Test-SameVolume {
    param([string[]]$Paths)
    $roots = @($Paths | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { [System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($_)) } | Select-Object -Unique)
    return $roots.Count -eq 1
}

function Get-PortableBundleRoot {
    param([Parameter(Mandatory)][string]$ValidatedRunnerRoot)
    $runnerFull = [System.IO.Path]::GetFullPath($ValidatedRunnerRoot).TrimEnd([char[]]@('/','\'))
    $runnerParent = Split-Path -Parent $runnerFull
    if ((Split-Path -Leaf $runnerParent).Equals('runner', [System.StringComparison]::OrdinalIgnoreCase)) {
        return [System.IO.Path]::GetFullPath((Split-Path -Parent $runnerParent))
    }
    return [System.IO.Path]::GetFullPath($runnerParent)
}

function Get-ExistingPortableCandidates {
    param([string[]]$CandidatePaths)
    # PowerShell unwraps a one-item pipeline result into a scalar.  Every
    # portable discovery consumer needs Count/index semantics, so preserve a
    # real array both before and after filtering.
    $normalized = @($CandidatePaths |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { [System.IO.Path]::GetFullPath([string]$_) } |
        Select-Object -Unique)
    return @($normalized | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
}

function Select-PortableCandidate {
    param(
        [string[]]$Candidates,
        [string]$AmbiguousCode
    )
    $safeCandidates = @($Candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($safeCandidates.Count -gt 1) { throw $AmbiguousCode }
    if ($safeCandidates.Count -eq 0) { return '' }
    return [string]$safeCandidates[0]
}

function Find-PortablePowerShell7 {
    param([string]$ValidatedRunnerRoot, [string]$TargetRepoRoot = '')
    $volumeRoot = [System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($ValidatedRunnerRoot))
    $bundleRoot = Get-PortableBundleRoot -ValidatedRunnerRoot $ValidatedRunnerRoot
    $candidatePaths = @(@(
        ([System.IO.Path]::Combine($volumeRoot, 'tools\PowerShell7\pwsh.exe')),
        ([System.IO.Path]::Combine($bundleRoot, 'tools\PowerShell7\pwsh.exe'))
    ) | Select-Object -Unique)
    $candidates = @(Get-ExistingPortableCandidates -CandidatePaths $candidatePaths | Where-Object { Test-SameVolume -Paths @($ValidatedRunnerRoot, $_) })
    return (Select-PortableCandidate -Candidates $candidates -AmbiguousCode 'PORTABLE_PWSH_AMBIGUOUS: more than one same-volume PowerShell 7 executable was found')
}

function Get-FixedApiKey {
    param(
        [Parameter(Mandatory)][string]$EnvFile,
        [Parameter(Mandatory)][string]$ValidatedRunnerRoot,
        [Parameter(Mandatory)][string]$TargetRepoRoot
    )
    $expectedPath = [System.IO.Path]::GetFullPath('C:\sswcenter\api-keys.local.env')
    $requestedPath = [System.IO.Path]::GetFullPath($EnvFile)
    if (-not $requestedPath.Equals($expectedPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'AUTH_PATH_INVALID: EnvFile must be C:\sswcenter\api-keys.local.env'
    }
    if (-not (Test-SameVolume -Paths @($ValidatedRunnerRoot, $TargetRepoRoot, $requestedPath))) {
        throw 'AUTH_PATH_CROSS_VOLUME: fixed authentication file must share the runner and repository volume'
    }
    if (-not (Test-Path -LiteralPath $requestedPath -PathType Leaf)) {
        return @{ key = ''; source = 'fixed-api-keys.local.env'; path = $requestedPath }
    }
    $keyLines = @([System.IO.File]::ReadAllLines($requestedPath) | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '^DEEPSEEK_API_KEY\s*=' })
    if ($keyLines.Count -ne 1) { throw 'FIXED_KEY_INVALID: exactly one DEEPSEEK_API_KEY entry is required' }
    $value = ($keyLines[0] -replace '^DEEPSEEK_API_KEY\s*=\s*','').Trim().Trim('"').Trim("'")
    if ([string]::IsNullOrWhiteSpace($value)) { throw 'FIXED_KEY_INVALID: DEEPSEEK_API_KEY is empty' }
    return @{ key = $value; source = 'fixed-api-keys.local.env'; path = $requestedPath }
}

function Test-ScopeEquivalent {
    param([string[]]$Left, [string[]]$Right)
    $l = @($Left | ForEach-Object { ([string]$_).Trim().TrimEnd([char[]]@('/','\')) } | Sort-Object -Unique)
    $r = @($Right | ForEach-Object { ([string]$_).Trim().TrimEnd([char[]]@('/','\')) } | Sort-Object -Unique)
    if ($l.Count -ne $r.Count) { return $false }
    for ($i = 0; $i -lt $l.Count; $i++) { if (-not $l[$i].Equals($r[$i], [System.StringComparison]::OrdinalIgnoreCase)) { return $false } }
    return $true
}

$WriteAllowList = @(ConvertTo-PathList -Values $WriteAllowList -PreserveElements:$bootstrapWriteAllowListRestored)
$ReadAllowList = @(ConvertTo-PathList -Values $ReadAllowList -PreserveElements:$bootstrapReadAllowListRestored)

# Import modules from the validated root only
Import-Module (Join-Path $RunnerRoot 'Workspace.psm1') -Force
Import-Module (Join-Path $RunnerRoot 'EditBatch.psm1') -Force
Import-Module (Join-Path $RunnerRoot 'DeepSeekClient.psm1') -Force

function Assert-TaskPacketReadDirectories {
    param(
        [Parameter(Mandatory)]$Workspace,
        [Parameter(Mandatory)][string[]]$Paths
    )
    foreach ($path in @($Paths)) {
        try {
            $resolved = Resolve-WorkspacePath -Workspace $Workspace -RelativePath $path -Mode Read
        } catch {
            throw "TASK_PACKET_READ_PATH_INVALID: '$path' failed repository path validation: $($_.Exception.Message)"
        }
        if (-not (Test-Path -LiteralPath $resolved.Full -PathType Container)) {
            throw "TASK_PACKET_READ_PATH_MUST_BE_DIRECTORY: '$path' must name an existing repository directory"
        }
    }
}

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    # Git-distributed fixed layout shared by HOME and OFFICE.
    # An explicit RepoRoot may still select an approved same-volume room worktree.
    $RepoRoot = 'C:\sswcenter\3.0'
}
$RepoRootFull = [System.IO.Path]::GetFullPath($RepoRoot)
if (-not (Test-Path -LiteralPath $RepoRootFull -PathType Container)) {
    throw "REPO_ROOT_NOT_FOUND: $RepoRootFull"
}
if (-not (Test-SameVolume -Paths @($RunnerRoot, $RepoRootFull))) {
    throw 'PORTABLE_LAYOUT_CROSS_VOLUME: runner and repository must be on the same volume'
}
if (-not [string]::IsNullOrWhiteSpace($TaskPacketPath) -and -not [string]::IsNullOrWhiteSpace($TaskPacketJson)) {
    throw 'TASK_PACKET_AMBIGUOUS: use TaskPacketPath or TaskPacketJson, not both'
}
if (-not [string]::IsNullOrWhiteSpace($TaskPacketPath)) {
    $packetFullPath = [System.IO.Path]::GetFullPath($TaskPacketPath)
    if (-not (Test-Path -LiteralPath $packetFullPath -PathType Leaf)) { throw 'TASK_PACKET_NOT_FOUND' }
    $rawPacket = [System.IO.File]::ReadAllText($packetFullPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
} elseif (-not [string]::IsNullOrWhiteSpace($TaskPacketJson)) {
    try { $rawPacket = $TaskPacketJson | ConvertFrom-Json } catch { throw 'TASK_PACKET_INVALID_JSON' }
} else {
    throw 'TASK_PACKET_REQUIRED: pass exactly one of -TaskPacketPath or -TaskPacketJson'
}
$taskPacket = ConvertTo-TaskPacket -RawPacket $rawPacket
$TaskObjective = [string]$taskPacket.objective
if ($WriteAllowList.Count -eq 0) { $WriteAllowList = @($taskPacket.write_paths) }
if ($ReadAllowList.Count -eq 0) { $ReadAllowList = @($taskPacket.read_paths) }
if ($WriteAllowList.Count -eq 0) { throw 'WRITER_ALLOWLIST_REQUIRED: a Writer call cannot use an empty write allowlist' }
if (-not (Test-ScopeEquivalent -Left $WriteAllowList -Right @($taskPacket.write_paths))) { throw 'TASK_PACKET_WRITE_SCOPE_MISMATCH' }
if (-not (Test-ScopeEquivalent -Left $ReadAllowList -Right @($taskPacket.read_paths))) { throw 'TASK_PACKET_READ_SCOPE_MISMATCH' }

if ([string]::IsNullOrWhiteSpace($RunId)) { $RunId = $script:BootstrapRunId }
if ($RunId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') { throw 'RUN_ID_INVALID: RunId must be a safe identifier' }
$taskHash = Get-CanonicalJsonHash -Object $taskPacket
$portablePwshPath = Find-PortablePowerShell7 -ValidatedRunnerRoot $RunnerRoot -TargetRepoRoot $RepoRootFull
$ws = New-Workspace -RepoRoot $RepoRootFull -WriteAllowList $WriteAllowList -ReadAllowList $ReadAllowList
Assert-TaskPacketReadDirectories -Workspace $ws -Paths @($taskPacket.read_paths)

$usingMockProvider = -not [string]::IsNullOrWhiteSpace($MockResponsesPath)
$mockResponses = @()
$mockResponseIndex = 0
$mockResponsesHash = ''
$ApiKey = ''
if ($usingMockProvider) {
    $mockFullPath = [System.IO.Path]::GetFullPath($MockResponsesPath)
    if (-not (Test-Path -LiteralPath $mockFullPath -PathType Leaf)) { throw 'MOCK_RESPONSES_NOT_FOUND' }
    $mockRaw = [System.IO.File]::ReadAllText($mockFullPath, [System.Text.Encoding]::UTF8)
    try { $mockDoc = $mockRaw | ConvertFrom-Json } catch { throw 'MOCK_RESPONSES_INVALID_JSON' }
    $mockResponses = @(Get-InputMember -Object $mockDoc -Name 'responses' -Default @())
    if ($mockResponses.Count -eq 0) { throw 'MOCK_RESPONSES_EMPTY' }
    $mockResponsesHash = Get-CanonicalJsonHash -Object $mockRaw
    $ApiKey = 'offline-mock-key'
    $credentialSource = 'offline-mock'
} else {
    $fixedCredential = Get-FixedApiKey -EnvFile $EnvFile -ValidatedRunnerRoot $RunnerRoot -TargetRepoRoot $RepoRootFull
    if (-not [string]::IsNullOrWhiteSpace($fixedCredential.key)) {
        $ApiKey = $fixedCredential.key
        $credentialSource = $fixedCredential.source
    }
}
if (-not $usingMockProvider -and [string]::IsNullOrWhiteSpace($ApiKey)) {
    throw 'DEEPSEEK_API_KEY_MISSING: fixed auth file C:\sswcenter\api-keys.local.env was not found or did not contain a usable key'
}

# ---------------------------------------------------------------------------
# State (minimal set per design §18)
# ---------------------------------------------------------------------------
$messages = [System.Collections.Generic.List[object]]::new()
$failureFingerprints = [System.Collections.Generic.List[string]]::new()  # recent history for consecutive detection
$requestCount = 0
$turnCount = 0
$readCalls = 0
$readBudgetExhaustionCount = 0
$recoverableErrorCount = 0
$repeatedErrorCount = 0
$transportRetryCount = 0
$rateLimitRetryCount = 0
$mutatedPaths = [System.Collections.Generic.HashSet[string]]::new()
$editRecords = [System.Collections.Generic.List[object]]::new()
$progressEventKeys = [System.Collections.Generic.HashSet[string]]::new()
$progressCount = 0
$segmentNumber = 1
$segmentTurnStart = 0
$segmentProgressStart = 0
$autoExtensionCount = 0
$noProgressSegmentCount = 0
$lastCheckpointEvent = ''
$usageAccum = @{
    prompt_tokens = 0
    completion_tokens = 0
    cache_hit_tokens = 0
    cache_miss_tokens = 0
}
$status = 'RUNNING'
$stopReason = ''
$finalResponse = ''
# Keep a UTC instant, not a local DateTime wall clock, for every persisted
# duration.  Resume runs may execute after a different local time-zone
# conversion has been applied, so DateTime/LocalDateTime round-trips are not
# safe here.
$startTime = [datetimeoffset]::UtcNow
$apiElapsedMs = 0L

$client = New-DeepSeekClient -ApiKey $ApiKey -Model $Model -ThinkingEnabled $Thinking `
    -ReasoningEffort $ReasoningEffort -MaxTokens $MaxTokens -TimeoutSec $RequestTimeoutSec
$tools = Get-WriterToolsDefinition -AllowDelete ([bool]$taskPacket.allow_delete)

# ---------------------------------------------------------------------------
# System prompt — Writer role only
# ---------------------------------------------------------------------------
$systemPrompt = @"
You are DeepSeek Writer. Your sole job is to implement the requested code changes by reading files and applying precise edits.

Rules you must follow:
1. You only use the provided tools: read_file, search_text, list_files, edit_files.
2. Prefer batching related changes into a single edit_files call.
3. For replace operations the "context" argument must be an EXACT unique substring of the current file (no whitespace or newline normalization). Prefer short unique contexts that still make the intent clear.
4. For rewrite/delete/replace on an EXISTING file you MUST supply expected_sha from a prior read_file. The runner rejects mutations without it. For large files use read_file offset/max_bytes to page through content.
5. After you have made the required net changes, reply with ONLY one JSON object in the required completion report format below. Do not call tools any more.
6. If you truly cannot proceed because of a missing external secret, permission, or out-of-repo requirement, say BLOCKED: <clear reason>.
7. Do not claim "already done" or "no change needed" unless you have verified the current file content. The runner will reject premature completion.
8. Progress is measured by actual file state change, not by number of tool calls. Keep working as long as you are making forward progress.
9. Never invent file contents. Always read first when unsure.
10. You do not have a shell, Git, test runner, network, or process execution capability. Tests are always NOT_RUN.

Task Packet (enforced by the runner):
$($taskPacket | ConvertTo-Json -Depth 12)

Required final completion report (JSON only):
{
  "summary": "non-empty description of completed work",
  "completion_evidence": [
    { "id": "criterion id from Task Packet", "status": "PASS", "evidence": "specific file/path evidence" }
  ],
  "remaining_work": [],
  "blocked": [],
  "tests": "NOT_RUN"
}

Current repository root: $RepoRootFull
"@

 $systemPrompt += "`n`nWrite scope (enforced by the runner): $($WriteAllowList -join ', ')"
if ($ReadAllowList.Count -gt 0) {
    $systemPrompt += "`nRead scope (enforced by the runner): $($ReadAllowList -join ', ')"
}
if ($SystemPromptExtra) {
    $systemPrompt += "`n`nAdditional instructions:`n$SystemPromptExtra"
}

$messages.Add([PSCustomObject]@{ role = 'system'; content = $systemPrompt })
$messages.Add([PSCustomObject]@{ role = 'user'; content = "Task ID: $($taskPacket.task_id)`nObjective: $TaskObjective" })

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Get-FailureFingerprint {
    param($ErrorCode, $Path, $Operation, $ArgHash)
    return "$ErrorCode|$Path|$Operation|$ArgHash"
}

function Get-ArgHash {
    param($Obj)
    $json = ($Obj | ConvertTo-Json -Depth 10 -Compress)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $hash = [System.Security.Cryptography.SHA256]::HashData($bytes)
    return ([BitConverter]::ToString($hash) -replace '-','').Substring(0,16).ToLowerInvariant()
}

function Convert-FileStateForCheckpoint {
    param($State)
    return [ordered]@{
        path = [string]$State.Path
        exists = [bool]$State.Exists
        sha256 = $State.Sha256
        size = [long]$State.Size
    }
}

function ConvertTo-RunnerUtcTimestamp {
    param([datetimeoffset]$Value)
    return $Value.ToUniversalTime().UtcDateTime.ToString('o', [System.Globalization.CultureInfo]::InvariantCulture)
}

function ConvertFrom-RunnerUtcTimestamp {
    param(
        [string]$Value,
        [string]$FieldName
    )
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "CHECKPOINT_TIMESTAMP_INVALID: $FieldName is empty"
    }
    $parsed = [datetimeoffset]::MinValue
    try {
        $parsed = [datetimeoffset]::Parse(
            $Value,
            [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::RoundtripKind
        )
    } catch {
        throw "CHECKPOINT_TIMESTAMP_INVALID: $FieldName is not a round-trip timestamp"
    }
    if ($parsed.Offset -ne [timespan]::Zero) {
        throw "CHECKPOINT_TIMESTAMP_INVALID: $FieldName must be UTC"
    }
    return $parsed.ToUniversalTime()
}

function Get-CheckpointPayload {
    $initialStates = @($ws.InitialStates.Values | ForEach-Object { Convert-FileStateForCheckpoint $_ })
    $knownStates = @($ws.KnownStates.Values | ForEach-Object { Convert-FileStateForCheckpoint $_ })
    return [ordered]@{
        checkpoint_schema = 1
        run_id = $RunId
        task_hash = $taskHash
        task_packet = $taskPacket
        repo_root = $RepoRootFull
        runner_root = $RunnerRoot
        write_allow_list = @($WriteAllowList)
        read_allow_list = @($ReadAllowList)
        messages = @($messages)
        initial_states = $initialStates
        known_states = $knownStates
        mutated_paths = @($mutatedPaths)
        edit_records = @($editRecords)
        progress_event_keys = @($progressEventKeys)
        progress_count = $progressCount
        segment_number = $segmentNumber
        segment_turn_start = $segmentTurnStart
        segment_progress_start = $segmentProgressStart
        auto_extension_count = $autoExtensionCount
        no_progress_segment_count = $noProgressSegmentCount
        request_count = $requestCount
        turn_count = $turnCount
        read_calls = $readCalls
        read_budget_exhaustion_count = $readBudgetExhaustionCount
        recoverable_error_count = $recoverableErrorCount
        repeated_error_count = $repeatedErrorCount
        transport_retry_count = $transportRetryCount
        rate_limit_retry_count = $rateLimitRetryCount
        usage = $usageAccum
        start_time_utc = ConvertTo-RunnerUtcTimestamp -Value $startTime
        api_elapsed_ms = $apiElapsedMs
        status = $status
        stop_reason = $stopReason
        final_response = $finalResponse
        force_non_thinking_once = $forceNonThinkingOnce
        premature_reconfirm_done = $prematureReconfirmDone
        blocked_bounce_done = $blockedBounceDone
        using_mock_provider = $usingMockProvider
        mock_responses_hash = $mockResponsesHash
        mock_response_index = $mockResponseIndex
        event = $script:lastCheckpointEvent
        saved_at_utc = ConvertTo-RunnerUtcTimestamp -Value ([datetimeoffset]::UtcNow)
    }
}

$checkpointDirectory = ''
$checkpointPath = ''

function Save-RunnerCheckpoint {
    param([string]$Event)
    $script:lastCheckpointEvent = $Event
}

function Restore-RunnerCheckpoint {
    throw 'CHECKPOINT_PERSISTENCE_DISABLED_BY_POLICY'
}

function Register-Progress {
    param([string]$Kind, [string]$Evidence)
    $fingerprint = "$Kind|$(Get-CanonicalJsonHash -Object $Evidence)"
    if ($progressEventKeys.Add($fingerprint)) {
        $script:progressCount++
        return $true
    }
    return $false
}

function Get-RetryDelaySeconds {
    param([int]$Attempt)
    return [Math]::Min(30, [Math]::Max(1, [int][Math]::Pow(2, [Math]::Min(5, $Attempt))))
}

function Invoke-WriterProvider {
    param([bool]$ForceNonThinking = $false)
    if ($usingMockProvider) {
        if ($script:mockResponseIndex -ge $mockResponses.Count) {
            return @{ ok = $false; error = 'MOCK_RESPONSES_EXHAUSTED'; message = 'Offline mock response queue is exhausted' }
        }
        $response = $mockResponses[$script:mockResponseIndex]
        $script:mockResponseIndex++
        return $response
    }
    return Invoke-DeepSeekChat -Client $client -Messages $messages -Tools $tools -ForceNonThinking:$ForceNonThinking
}

function ConvertFrom-CompletionReportObject {
    param([string]$JsonText)
    $jsonDocument = $null
    try {
        $jsonDocument = [System.Text.Json.JsonDocument]::Parse($JsonText)
    } catch {
        return @{ ok = $false; was_json = $false; error = 'completion report JSON is malformed' }
    }
    try {
        if ($jsonDocument.RootElement.ValueKind -ne [System.Text.Json.JsonValueKind]::Object) {
            return @{ ok = $false; was_json = $true; error = 'completion report JSON must be one object' }
        }
        $topLevelNames = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
        foreach ($property in $jsonDocument.RootElement.EnumerateObject()) {
            if (-not $topLevelNames.Add($property.Name)) {
                return @{ ok = $false; was_json = $true; error = "completion report JSON has duplicate top-level property '$($property.Name)'" }
            }
            if ($property.Name -ceq 'completion_evidence' -and
                $property.Value.ValueKind -eq [System.Text.Json.JsonValueKind]::Array) {
                $evidenceIndex = 0
                foreach ($evidenceItem in $property.Value.EnumerateArray()) {
                    if ($evidenceItem.ValueKind -eq [System.Text.Json.JsonValueKind]::Object) {
                        $evidencePropertyNames = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
                        foreach ($evidenceProperty in $evidenceItem.EnumerateObject()) {
                            if (-not $evidencePropertyNames.Add($evidenceProperty.Name)) {
                                return @{ ok = $false; was_json = $true; error = "completion report JSON has duplicate completion_evidence[$evidenceIndex] property '$($evidenceProperty.Name)'" }
                            }
                        }
                    }
                    $evidenceIndex++
                }
            }
        }
    } finally {
        $jsonDocument.Dispose()
    }
    try {
        $value = ConvertFrom-Json -InputObject $JsonText -NoEnumerate
    } catch {
        return @{ ok = $false; was_json = $true; error = 'completion report JSON could not be converted without property loss' }
    }
    if ($null -eq $value -or $value -is [string] -or $value -is [System.Array] -or $value -is [ValueType]) {
        return @{ ok = $false; was_json = $true; error = 'completion report JSON must be one object' }
    }
    return @{ ok = $true; was_json = $true; value = $value }
}

function Get-CompletionPropertyNames {
    param([AllowNull()]$Object)
    if ($null -eq $Object) { return @() }
    if ($Object -is [System.Collections.IDictionary]) {
        return @($Object.Keys | ForEach-Object { [string]$_ })
    }
    return @($Object.PSObject.Properties | ForEach-Object { [string]$_.Name })
}

function Get-CompletionPropertyValue {
    param(
        [Parameter(Mandatory)]$Object,
        [Parameter(Mandatory)][string]$Name
    )
    if ($Object -is [System.Collections.IDictionary]) {
        if (-not $Object.Contains($Name)) { return $null }
        return ,$Object[$Name]
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    # Unary comma prevents a one-item array from becoming a scalar and an
    # empty JSON array from disappearing as no pipeline output.
    return ,$property.Value
}

function Test-CompletionArrayValue {
    param([AllowNull()]$Value)
    return ($null -ne $Value -and $Value -isnot [string] -and $Value -is [System.Collections.IList])
}

function Get-BalancedTopLevelJsonObjects {
    param([string]$Text)
    $objects = [System.Collections.Generic.List[string]]::new()
    $stack = [System.Collections.Generic.List[char]]::new()
    $start = -1
    $inString = $false
    $escaped = $false
    for ($i = 0; $i -lt $Text.Length; $i++) {
        $ch = $Text[$i]
        if ($inString) {
            if ($escaped) { $escaped = $false; continue }
            if ($ch -eq '\') { $escaped = $true; continue }
            if ($ch -eq '"') { $inString = $false }
            continue
        }
        if ($ch -eq '"') { $inString = $true; continue }
        if ($ch -eq '{' -or $ch -eq '[') {
            if ($stack.Count -eq 0 -and $ch -eq '{') { $start = $i }
            $stack.Add($ch)
            continue
        }
        if ($ch -eq '}' -or $ch -eq ']') {
            if ($stack.Count -eq 0) {
                return @{ objects = @($objects); error = 'unmatched JSON closing delimiter' }
            }
            $open = $stack[$stack.Count - 1]
            if (($ch -eq '}' -and $open -ne '{') -or ($ch -eq ']' -and $open -ne '[')) {
                return @{ objects = @($objects); error = 'mismatched JSON delimiter' }
            }
            $stack.RemoveAt($stack.Count - 1)
            if ($stack.Count -eq 0 -and $ch -eq '}' -and $start -ge 0) {
                $objects.Add($Text.Substring($start, $i - $start + 1))
                $start = -1
            }
        }
    }
    if ($inString -or $stack.Count -gt 0) {
        return @{ objects = @($objects); error = 'unterminated JSON string or delimiter' }
    }
    return @{ objects = @($objects); error = '' }
}

function Get-CompletionReportObject {
    param([string]$ModelReport)
    $text = if ($null -eq $ModelReport) { '' } else { $ModelReport.Trim() }
    if ([string]::IsNullOrWhiteSpace($text)) {
        return @{ parsed = $null; extraction = 'none'; parse_error = 'model report is empty' }
    }

    # Exact JSON remains the preferred and least-ambiguous contract.
    $direct = ConvertFrom-CompletionReportObject -JsonText $text
    if ($direct.ok) {
        return @{ parsed = $direct.value; extraction = 'direct'; parse_error = '' }
    }
    if ($direct.was_json) {
        return @{ parsed = $null; extraction = 'direct'; parse_error = $direct.error }
    }

    # A prose introduction followed by exactly one fenced JSON object is
    # accepted. Any other fence, malformed fence, or JSON object outside the
    # selected fence makes the report ambiguous and therefore invalid.
    # Consume the physical line ending as part of the marker. With a CRLF
    # response, a multiline '$' before LF otherwise leaves CR behind and a
    # perfectly ordinary closing fence is falsely considered malformed.
    $fenceTokens = @([regex]::Matches($text, '(?m)^[ \t]*```[^\r\n]*(?:\r?\n|\z)'))
    if ($fenceTokens.Count -gt 0) {
        $fenceMatches = @([regex]::Matches($text, '(?ms)^[ \t]*```(?<language>[^\r\n`]*)\r?\n(?<body>.*?)^[ \t]*```[ \t]*(?:\r?\n|\z)'))
        if ($fenceTokens.Count -ne 2 -or $fenceMatches.Count -ne 1) {
            return @{ parsed = $null; extraction = 'fenced'; parse_error = 'completion report has ambiguous or malformed fenced blocks' }
        }
        $fence = $fenceMatches[0]
        if (-not $fence.Groups['language'].Value.Trim().Equals('json', [System.StringComparison]::OrdinalIgnoreCase)) {
            return @{ parsed = $null; extraction = 'fenced'; parse_error = 'completion report fenced block must be labelled json' }
        }
        $outside = $text.Remove($fence.Index, $fence.Length)
        $outsideObjects = Get-BalancedTopLevelJsonObjects -Text $outside
        if ($outsideObjects.error -or @($outsideObjects.objects).Count -gt 0) {
            return @{ parsed = $null; extraction = 'fenced'; parse_error = 'completion report has JSON outside its fenced json object' }
        }
        $fenced = ConvertFrom-CompletionReportObject -JsonText $fence.Groups['body'].Value.Trim()
        if (-not $fenced.ok) {
            return @{ parsed = $null; extraction = 'fenced'; parse_error = $fenced.error }
        }
        return @{ parsed = $fenced.value; extraction = 'fenced'; parse_error = '' }
    }

    # Last resort for providers that prepend/append prose without a fence:
    # accept exactly one balanced top-level object, never an array, multiple
    # objects, or an unterminated/mismatched JSON-like fragment.
    $balanced = Get-BalancedTopLevelJsonObjects -Text $text
    if ($balanced.error) {
        return @{ parsed = $null; extraction = 'balanced'; parse_error = "completion report balanced JSON extraction failed: $($balanced.error)" }
    }
    $objects = @($balanced.objects)
    if ($objects.Count -ne 1) {
        $reason = if ($objects.Count -eq 0) { 'no balanced top-level JSON object' } else { 'multiple balanced top-level JSON objects' }
        return @{ parsed = $null; extraction = 'balanced'; parse_error = "completion report is ambiguous: $reason" }
    }
    $single = ConvertFrom-CompletionReportObject -JsonText $objects[0]
    if (-not $single.ok) {
        return @{ parsed = $null; extraction = 'balanced'; parse_error = $single.error }
    }
    return @{ parsed = $single.value; extraction = 'balanced'; parse_error = '' }
}

function Get-CompletionAssessment {
    param([string]$ModelReport)
    $results = [System.Collections.Generic.List[object]]::new()
    $remaining = [System.Collections.Generic.List[string]]::new()
    $shapeErrors = [System.Collections.Generic.List[string]]::new()
    $parsed = $null
    $parseError = ''
    $reportObject = Get-CompletionReportObject -ModelReport $ModelReport
    $parsed = $reportObject.parsed
    $parseError = [string]$reportObject.parse_error

    $summary = ''
    $reportedRemaining = @()
    $reportedBlocked = @()
    $evidenceItems = @()
    $testsIsNotRun = $false
    $validEvidenceItems = [System.Collections.Generic.List[object]]::new()

    if ($null -ne $parsed) {
        $requiredProperties = @('summary','completion_evidence','remaining_work','blocked','tests')
        $actualProperties = @(Get-CompletionPropertyNames -Object $parsed)
        foreach ($requiredProperty in $requiredProperties) {
            if (-not ($actualProperties -ccontains $requiredProperty)) {
                $shapeErrors.Add("missing top-level property '$requiredProperty'")
            }
        }
        foreach ($actualProperty in $actualProperties) {
            if (-not ($requiredProperties -ccontains $actualProperty)) {
                $shapeErrors.Add("unexpected top-level property '$actualProperty'")
            }
        }

        $summaryRaw = Get-CompletionPropertyValue -Object $parsed -Name 'summary'
        if ($summaryRaw -isnot [string] -or [string]::IsNullOrWhiteSpace([string]$summaryRaw)) {
            $shapeErrors.Add('summary must be a non-empty string')
        } else {
            $summary = [string]$summaryRaw
        }

        $evidenceRaw = Get-CompletionPropertyValue -Object $parsed -Name 'completion_evidence'
        if (-not (Test-CompletionArrayValue -Value $evidenceRaw)) {
            $shapeErrors.Add('completion_evidence must be an array')
        } else {
            $evidenceItems = @($evidenceRaw)
        }

        $remainingRaw = Get-CompletionPropertyValue -Object $parsed -Name 'remaining_work'
        if (-not (Test-CompletionArrayValue -Value $remainingRaw)) {
            $shapeErrors.Add('remaining_work must be an array')
        } else {
            $reportedRemaining = @($remainingRaw)
        }

        $blockedRaw = Get-CompletionPropertyValue -Object $parsed -Name 'blocked'
        if (-not (Test-CompletionArrayValue -Value $blockedRaw)) {
            $shapeErrors.Add('blocked must be an array')
        } else {
            $reportedBlocked = @($blockedRaw)
        }

        $testsRaw = Get-CompletionPropertyValue -Object $parsed -Name 'tests'
        $testsIsNotRun = ($testsRaw -is [string] -and ([string]$testsRaw -ceq 'NOT_RUN'))
        if (-not $testsIsNotRun) { $shapeErrors.Add('tests must be exactly NOT_RUN') }

        $seenEvidenceIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
        $criterionIds = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
        foreach ($criterion in @($taskPacket.completion_criteria)) {
            $null = $criterionIds.Add([string](Get-InputMember -Object $criterion -Name 'id'))
        }
        for ($evidenceIndex = 0; $evidenceIndex -lt $evidenceItems.Count; $evidenceIndex++) {
            $item = $evidenceItems[$evidenceIndex]
            if ($null -eq $item -or $item -is [string] -or $item -is [System.Array] -or $item -is [ValueType]) {
                $shapeErrors.Add("completion_evidence[$evidenceIndex] must be an object")
                continue
            }
            $requiredItemProperties = @('id','status','evidence')
            $itemProperties = @(Get-CompletionPropertyNames -Object $item)
            $itemShapeValid = $true
            foreach ($requiredItemProperty in $requiredItemProperties) {
                if (-not ($itemProperties -ccontains $requiredItemProperty)) {
                    $shapeErrors.Add("completion_evidence[$evidenceIndex] is missing '$requiredItemProperty'")
                    $itemShapeValid = $false
                }
            }
            foreach ($itemProperty in $itemProperties) {
                if (-not ($requiredItemProperties -ccontains $itemProperty)) {
                    $shapeErrors.Add("completion_evidence[$evidenceIndex] has unexpected property '$itemProperty'")
                    $itemShapeValid = $false
                }
            }
            if (-not $itemShapeValid) { continue }

            $itemIdRaw = $item.PSObject.Properties['id'].Value
            $itemStatusRaw = $item.PSObject.Properties['status'].Value
            $itemEvidenceRaw = $item.PSObject.Properties['evidence'].Value
            if ($itemIdRaw -isnot [string] -or [string]::IsNullOrWhiteSpace([string]$itemIdRaw)) {
                $shapeErrors.Add("completion_evidence[$evidenceIndex].id must be a non-empty string")
                continue
            }
            $itemId = [string]$itemIdRaw
            if (-not $seenEvidenceIds.Add($itemId)) {
                $shapeErrors.Add("duplicate completion evidence id '$itemId'")
                continue
            }
            if (-not $criterionIds.Contains($itemId)) {
                $shapeErrors.Add("unknown completion evidence id '$itemId'")
                continue
            }
            if ($itemStatusRaw -isnot [string]) {
                $shapeErrors.Add("completion evidence '$itemId' status must be a string")
                continue
            }
            if ($itemEvidenceRaw -isnot [string]) {
                $shapeErrors.Add("completion evidence '$itemId' evidence must be a string")
                continue
            }
            $validEvidenceItems.Add($item)
        }
    }

    foreach ($criterion in @($taskPacket.completion_criteria)) {
        $criterionId = [string](Get-InputMember -Object $criterion -Name 'id')
        $match = $null
        foreach ($item in $validEvidenceItems) {
            if ([string](Get-InputMember -Object $item -Name 'id') -ceq $criterionId) { $match = $item; break }
        }
        $evidence = if ($match) { [string](Get-InputMember -Object $match -Name 'evidence') } else { '' }
        $itemStatus = if ($match) { [string](Get-InputMember -Object $match -Name 'status') } else { 'MISSING' }
        $passed = $itemStatus -ceq 'PASS' -and -not [string]::IsNullOrWhiteSpace($evidence)
        $results.Add([ordered]@{
            id = $criterionId
            description = [string](Get-InputMember -Object $criterion -Name 'description')
            status = if ($passed) { 'PASS' } else { 'FAIL' }
            evidence = $evidence
            reason = if ($passed) { '' } elseif ($match) { 'status must be PASS and evidence must be non-empty' } else { 'completion evidence is missing' }
        })
        if (-not $passed) { $remaining.Add($criterionId) }
    }
    if ([string]::IsNullOrWhiteSpace($parseError) -and $shapeErrors.Count -gt 0) {
        $parseError = 'completion report shape invalid: ' + ($shapeErrors -join '; ')
    }
    return [ordered]@{
        complete = ($null -ne $parsed -and
            $shapeErrors.Count -eq 0 -and
            -not [string]::IsNullOrWhiteSpace($summary) -and
            $remaining.Count -eq 0 -and
            $reportedRemaining.Count -eq 0 -and
            $reportedBlocked.Count -eq 0 -and
            $testsIsNotRun)
        parse_error = $parseError
        extraction = [string]$reportObject.extraction
        summary = $summary
        criteria = @($results)
        unmet_criteria = @($remaining)
        remaining_work = @($reportedRemaining)
        blocked = @($reportedBlocked)
    }
}

function New-NonEmptyFinalSummary {
    param($Assessment)
    $changed = @($editRecords | ForEach-Object { "$($_.operation) $($_.path)" })
    $base = if ($Assessment -and -not [string]::IsNullOrWhiteSpace([string]$Assessment.summary)) { [string]$Assessment.summary } elseif (-not [string]::IsNullOrWhiteSpace($finalResponse)) { $finalResponse.Trim() } else { "Run $RunId ended with status $status and no model final report." }
    $pending = if ($Assessment) { @(@($Assessment.unmet_criteria) + @($Assessment.remaining_work)) } else { @() }
    $changedItems = @($changed)
    $pendingItems = @($pending)
    $changedText = if ($changedItems.Count -gt 0) { $changedItems -join ', ' } else { 'none' }
    $pendingText = if ($pendingItems.Count -gt 0) { $pendingItems -join ', ' } else { 'none' }
    return "RunId=$RunId; status=$status; changes=$changedText; summary=$base; pending=$pendingText; tests=NOT_RUN; checkpoint=$checkpointPath"
}

function Add-FingerprintAndCheck {
    param([string]$Fp)
    $script:failureFingerprints.Add($Fp)
    # count consecutive identical from the end
    $consec = 0
    for ($i = $script:failureFingerprints.Count - 1; $i -ge 0; $i--) {
        if ($script:failureFingerprints[$i] -eq $Fp) { $consec++ } else { break }
    }
    return $consec
}

function Get-OptionalToolInt {
    param(
        [Parameter(Mandatory)]
        [AllowNull()]
        $Arguments,
        [Parameter(Mandatory)][string]$Name
    )

    if ($null -eq $Arguments) { return 0 }

    $value = $null
    if ($Arguments -is [System.Collections.IDictionary]) {
        if ($Arguments.Contains($Name)) {
            $value = $Arguments[$Name]
        }
    } else {
        $property = $Arguments.PSObject.Properties[$Name]
        if ($null -ne $property) {
            $value = $property.Value
        }
    }

    if ($null -eq $value -or [string]::IsNullOrWhiteSpace([string]$value)) {
        return 0
    }
    return [int]$value
}

# StrictMode-safe read of optional members on hashtables / PSCustomObject (DSW-RUNNER-002)
function Get-OptionalMember {
    param(
        [Parameter(Mandatory)]
        [AllowNull()]
        $Object,
        [Parameter(Mandatory)][string]$Name,
        [AllowNull()]
        $Default = $null
    )

    if ($null -eq $Object) { return $Default }
    if ($Object -is [System.Collections.IDictionary]) {
        if ($Object.Contains($Name)) {
            return $Object[$Name]
        }
        return $Default
    }
    # Primitives / arrays are not member maps — avoid StrictMode property traps
    if ($Object -is [string] -or $Object -is [System.ValueType]) { return $Default }
    if ($Object -is [System.Array]) { return $Default }

    $property = $Object.PSObject.Properties[$Name]
    if ($null -ne $property) {
        return $property.Value
    }
    return $Default
}

# True when value is a JSON-object analogue (dictionary or PSCustomObject), not null/string/number/array.
function Test-IsMapObject {
    param(
        [Parameter(Mandatory)]
        [AllowNull()]
        $Value
    )
    if ($null -eq $Value) { return $false }
    if ($Value -is [string]) { return $false }
    if ($Value -is [System.ValueType]) { return $false }
    if ($Value -is [System.Collections.IDictionary]) { return $true }
    if ($Value -is [System.Array]) { return $false }
    if ($Value -is [System.Collections.IList]) { return $false }
    # PSCustomObject / other property bags
    if ($null -ne $Value.PSObject -and $null -ne $Value.PSObject.Properties) {
        return $true
    }
    return $false
}

# Single entry: raw provider tool_call → internal normalized ToolCall (or explicit tool/protocol error).
function Normalize-ToolCall {
    param(
        [Parameter(Mandatory)]
        [AllowNull()]
        $RawToolCall
    )

    if ($null -eq $RawToolCall) {
        return @{
            ok = $false
            error = 'TOOL_CALL_INVALID'
            content = 'ERROR: TOOL_CALL_INVALID — null tool_call'
            tool_call = $null
        }
    }

    if (-not (Test-IsMapObject -Value $RawToolCall)) {
        return @{
            ok = $false
            error = 'TOOL_CALL_INVALID'
            content = 'ERROR: TOOL_CALL_INVALID — tool_call must be an object'
            tool_call = $null
        }
    }

    $id = Get-OptionalMember -Object $RawToolCall -Name 'id'
    $function = Get-OptionalMember -Object $RawToolCall -Name 'function'

    if ($null -eq $function) {
        return @{
            ok = $false
            error = 'TOOL_CALL_INVALID'
            content = 'ERROR: TOOL_CALL_INVALID — missing function'
            tool_call = $null
            partial_id = $id
        }
    }
    if (-not (Test-IsMapObject -Value $function)) {
        return @{
            ok = $false
            error = 'TOOL_CALL_INVALID'
            content = 'ERROR: TOOL_CALL_INVALID — function must be an object'
            tool_call = $null
            partial_id = $id
        }
    }

    $name = Get-OptionalMember -Object $function -Name 'name'
    $rawArgs = Get-OptionalMember -Object $function -Name 'arguments'

    if ($null -eq $id -or [string]::IsNullOrWhiteSpace([string]$id)) {
        return @{
            ok = $false
            error = 'TOOL_CALL_INVALID'
            content = 'ERROR: TOOL_CALL_INVALID — missing or empty id'
            tool_call = $null
        }
    }
    if ($null -eq $name -or [string]::IsNullOrWhiteSpace([string]$name)) {
        return @{
            ok = $false
            error = 'TOOL_CALL_INVALID'
            content = 'ERROR: TOOL_CALL_INVALID — missing or empty function.name'
            tool_call = $null
            partial_id = $id
        }
    }

    # arguments: wire may be JSON string; internal form must be object/dictionary
    if ($null -eq $rawArgs) {
        return @{
            ok = $false
            error = 'TOOL_ARGUMENTS_INVALID'
            content = 'ERROR: TOOL_ARGUMENTS_INVALID — arguments is null'
            tool_call = $null
            partial_id = $id
        }
    }

    $parsedArgs = $null
    if ($rawArgs -is [string]) {
        try {
            $parsedArgs = $rawArgs | ConvertFrom-Json -AsHashtable
        } catch {
            return @{
                ok = $false
                error = 'TOOL_ARGUMENTS_INVALID_JSON'
                content = "ERROR: TOOL_ARGUMENTS_INVALID_JSON — $($_.Exception.Message)"
                tool_call = $null
                partial_id = $id
            }
        }
    } elseif (Test-IsMapObject -Value $rawArgs) {
        if ($rawArgs -is [System.Collections.IDictionary]) {
            $parsedArgs = $rawArgs
        } else {
            # PSCustomObject → hashtable for uniform Get-OptionalMember / Get-OptionalToolInt use
            $parsedArgs = [ordered]@{}
            foreach ($p in $rawArgs.PSObject.Properties) {
                $parsedArgs[$p.Name] = $p.Value
            }
        }
    } else {
        # number, array, bool, etc.
        return @{
            ok = $false
            error = 'TOOL_ARGUMENTS_INVALID'
            content = 'ERROR: TOOL_ARGUMENTS_INVALID — arguments must be an object'
            tool_call = $null
            partial_id = $id
        }
    }

    if (-not (Test-IsMapObject -Value $parsedArgs)) {
        # e.g. JSON string "hello", number, or array after parse
        return @{
            ok = $false
            error = 'TOOL_ARGUMENTS_INVALID'
            content = 'ERROR: TOOL_ARGUMENTS_INVALID — arguments must be an object'
            tool_call = $null
            partial_id = $id
        }
    }

    return @{
        ok = $true
        tool_call = @{
            id = [string]$id
            name = [string]$name
            arguments = $parsedArgs
        }
    }
}

# Production result normalization / state transition for tool results (main loop + tests).
function Resolve-ToolResultOutcome {
    param(
        [Parameter(Mandatory)]
        [AllowNull()]
        $ToolResult,
        [Parameter(Mandatory)]
        [AllowNull()]
        [string]$ToolCallId
    )

    $toolFatal = [bool](Get-OptionalMember -Object $ToolResult -Name 'fatal' -Default $false)
    $toolOk = [bool](Get-OptionalMember -Object $ToolResult -Name 'ok' -Default $false)
    $toolContent = Get-OptionalMember -Object $ToolResult -Name 'content' -Default ''
    if ($null -eq $toolContent) { $toolContent = '' }
    $errCode = Get-OptionalMember -Object $ToolResult -Name 'error' -Default $null

    $branch = 'SUCCESS'
    $stopReason = $null
    if ($toolFatal) {
        $branch = 'FAIL'
        $stopReason = if ($errCode) { [string]$errCode } else { 'TOOL_FATAL' }
    } elseif (-not $toolOk) {
        $branch = 'RECOVERABLE'
        $stopReason = if ($errCode) { [string]$errCode } else { 'TOOL_ERROR' }
    }

    $callId = if ($null -eq $ToolCallId) { '' } else { [string]$ToolCallId }
    $toolMessage = [PSCustomObject]@{
        role         = 'tool'
        tool_call_id = $callId
        content      = $toolContent
    }

    return @{
        ok           = $toolOk
        fatal        = $toolFatal
        branch       = $branch
        content      = $toolContent
        error        = $errCode
        stop_reason  = $stopReason
        tool_message = $toolMessage
    }
}

function Invoke-ToolCall {
    param($ToolCall)

    # Expects Normalize-ToolCall output: { id, name, arguments } — never raw provider shape.
    $name = Get-OptionalMember -Object $ToolCall -Name 'name'
    $args = Get-OptionalMember -Object $ToolCall -Name 'arguments'

    if ($null -eq $args -or -not (Test-IsMapObject -Value $args)) {
        return @{
            ok = $false
            error = 'TOOL_ARGUMENTS_INVALID'
            content = 'ERROR: TOOL_ARGUMENTS_INVALID — arguments must be an object'
        }
    }

    try {
    switch ($name) {
        'read_file' {
            if ($script:readCalls -ge $MaxReadCalls) {
                return @{ ok = $false; error = 'MAX_READ_CALLS'; content = 'ERROR: MAX_READ_CALLS exceeded' }
            }
            $script:readCalls++
            $path = Get-OptionalMember -Object $args -Name 'path'
            $offset = Get-OptionalToolInt -Arguments $args -Name 'offset'
            $maxBytes = Get-OptionalToolInt -Arguments $args -Name 'max_bytes'
            $r = Read-WorkspaceFile -Workspace $ws -Path $path -Offset $offset -MaxBytes $maxBytes
            if (-not $r.ok) {
                return @{
                    ok = $false
                    error = $r.error
                    content = "ERROR: $($r.error) path=$($r.path)"
                }
            }
            $header = @"
path: $($r.path)
sha256: $($r.sha)
size: $($r.size)
offset: $($r.offset)
bytes_returned: $($r.bytes_returned)
next_offset: $($r.next_offset)
truncated: $($r.truncated)
"@
            $hint = Get-OptionalMember -Object $r -Name 'hint'
            if ($r.truncated -and $hint) {
                $header += "`nhint: $hint"
            }
            return @{
                ok = $true
                content = "$header`n---`n$($r.content)"
            }
        }
        'search_text' {
            if ($script:readCalls -ge $MaxReadCalls) {
                return @{ ok = $false; error = 'MAX_READ_CALLS'; content = 'ERROR: MAX_READ_CALLS exceeded' }
            }
            $script:readCalls++
            $q = Get-OptionalMember -Object $args -Name 'query'
            $prefix = Get-OptionalMember -Object $args -Name 'path_prefix' -Default ''
            if (-not $prefix) { $prefix = '' }
            $maxRaw = Get-OptionalMember -Object $args -Name 'max_results'
            $max = if ($maxRaw) { [int]$maxRaw } else { 50 }
            $hits = @(Search-WorkspaceText -Workspace $ws -Query $q -PathPrefix $prefix -MaxResults $max)
            if ($hits.Count -eq 0) {
                return @{ ok = $true; content = "No matches for '$q'" }
            }
            $sb = [System.Text.StringBuilder]::new()
            foreach ($h in $hits) {
                [void]$sb.AppendLine("$($h.path):$($h.line): $($h.text)")
            }
            return @{ ok = $true; content = $sb.ToString() }
        }
        'list_files' {
            if ($script:readCalls -ge $MaxReadCalls) {
                return @{ ok = $false; error = 'MAX_READ_CALLS'; content = 'ERROR: MAX_READ_CALLS exceeded' }
            }
            $script:readCalls++
            $p = Get-OptionalMember -Object $args -Name 'path' -Default ''
            if (-not $p) { $p = '' }
            $depthRaw = Get-OptionalMember -Object $args -Name 'max_depth'
            $depth = if ($depthRaw) { [int]$depthRaw } else { 4 }
            $items = @(Get-WorkspaceFileList -Workspace $ws -Path $p -MaxDepth $depth)
            $lines = $items | ForEach-Object {
                if ($_.type -eq 'dir') { "DIR  $($_.path)" } else { "FILE $($_.path) ($($_.size) bytes)" }
            }
            return @{ ok = $true; content = ($lines -join "`n") }
        }
        'edit_files' {
            $ops = Get-OptionalMember -Object $args -Name 'operations'
            if (-not $ops) {
                return @{ ok = $false; error = 'TOOL_ARGUMENTS_INVALID'; content = 'ERROR: operations array required' }
            }
            $batch = New-EditBatch -Workspace $ws -MaxBatchBytes $MaxBatchBytes
            foreach ($o in $ops) {
                $requestedOp = [string](Get-OptionalMember -Object $o -Name 'op')
                if ($requestedOp -eq 'delete' -and -not [bool]$taskPacket.allow_delete) {
                    return @{ ok = $false; fatal = $true; error = 'DELETE_NOT_AUTHORIZED'; content = 'FATAL: DELETE_NOT_AUTHORIZED — Task Packet allow_delete is false' }
                }
                Add-EditOp -Batch $batch `
                    -Path (Get-OptionalMember -Object $o -Name 'path') `
                    -Op $requestedOp `
                    -Context (Get-OptionalMember -Object $o -Name 'context' -Default '') `
                    -OldText (Get-OptionalMember -Object $o -Name 'old_text' -Default '') `
                    -NewText (Get-OptionalMember -Object $o -Name 'new_text' -Default '') `
                    -Content (Get-OptionalMember -Object $o -Name 'content' -Default '') `
                    -ExpectedSha (Get-OptionalMember -Object $o -Name 'expected_sha' -Default '')
            }
            $result = Invoke-EditBatch -Batch $batch
            if (-not $result.ok) {
                # §8 safety boundary errors → escalate (not recoverable by model)
                $fatalCodes = @('BATCH_ROLLBACK_FAILED','SENSITIVE_PATH','PATH_OUTSIDE_REPOSITORY','PATH_NOT_WRITE_ALLOWLISTED','REPARSE_POINT_FORBIDDEN','HARDLINK_COUNT_UNAVAILABLE')
                if ($fatalCodes -contains $result.error) {
                    return @{
                        ok = $false
                        error = $result.error
                        fatal = $true
                        content = "FATAL: $($result.error) — $($result.message)"
                    }
                }
                $msg = "ERROR: $($result.error) — $($result.message)"
                $divergent = Get-OptionalMember -Object $result -Name 'divergent'
                if ($divergent -and @($divergent).Count -gt 0) {
                    $msg += "`nDIVERGENT PATHS (rollback incomplete): $($divergent -join ', ')"
                }
                return @{
                    ok = $false
                    error = $result.error
                    content = $msg
                }
            }
            foreach ($rr in $result.results) {
                if ($rr.ok -and $rr.path) {
                    $null = $script:mutatedPaths.Add([string]$rr.path)
                    $script:editRecords.Add([ordered]@{
                        path = [string]$rr.path
                        operation = [string]$rr.op
                        before_sha = Get-OptionalMember -Object $rr -Name 'before_sha'
                        after_sha = Get-OptionalMember -Object $rr -Name 'after_sha'
                    })
                }
            }
            $summary = ($result.results | ForEach-Object {
                $warn = Get-OptionalMember -Object $_ -Name 'warning'
                $w = if ($warn) { " ($warn)" } else { '' }
                "$($_.op) $($_.path) → sha=$($_.sha)$w"
            }) -join "`n"
            return @{
                ok = $true
                content = "OK — batch applied:`n$summary"
            }
        }
        default {
            return @{ ok = $false; error = 'UNKNOWN_TOOL'; content = "ERROR: unknown tool $name" }
        }
    }
    }
    catch {
        $rawError = [string]$_.Exception.Message
        $errorCode = (($rawError -split ':', 2)[0]).Trim()
        if ($errorCode -notmatch '^[A-Z][A-Z0-9_]+$') {
            $errorCode = 'TOOL_EXECUTION_ERROR'
        }
        $fatalCodes = @(
            'BATCH_ROLLBACK_FAILED',
            'SENSITIVE_PATH',
            'PATH_OUTSIDE_REPOSITORY',
            'PATH_NOT_WRITE_ALLOWLISTED',
            'PATH_NOT_READ_ALLOWLISTED',
            'REPARSE_POINT_FORBIDDEN',
            'HARDLINK_COUNT_UNAVAILABLE'
        )
        $isFatal = $fatalCodes -contains $errorCode
        $prefix = if ($isFatal) { 'FATAL' } else { 'ERROR' }
        return @{
            ok = $false
            error = $errorCode
            fatal = $isFatal
            content = ('{0}: {1}' -f $prefix, $rawError)
        }
    }
}

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
$forceNonThinkingOnce = $false
$prematureReconfirmDone = $false
$blockedBounceDone = $false
$completionAssessment = $null

if ($Resume) {
    Restore-RunnerCheckpoint
    # A checkpoint can legitimately be taken after a provider tool-call reply
    # but before its complete tool-result batch. Drop that incomplete protocol
    # turn and require fresh reads instead of replaying an unknown edit.
    while ($messages.Count -gt 0 -and (Get-InputMember -Object $messages[$messages.Count - 1] -Name 'role' -Default '') -eq 'tool') {
        $messages.RemoveAt($messages.Count - 1)
    }
    if ($messages.Count -gt 0) {
        $lastMessage = $messages[$messages.Count - 1]
        if ((Get-InputMember -Object $lastMessage -Name 'role' -Default '') -eq 'assistant' -and (Get-InputMember -Object $lastMessage -Name 'tool_calls')) {
            $messages.RemoveAt($messages.Count - 1)
            $messages.Add([PSCustomObject]@{ role = 'user'; content = '[RUNNER] The previous provider response was interrupted before its complete tool batch was safely checkpointed. Re-read current files before any edit; do not replay an assumed operation.' })
        }
    }
    $messages.Add([PSCustomObject]@{ role = 'user'; content = "[RUNNER] RESUMING RunId=$RunId from a verified checkpoint. Continue the Task Packet; preserve existing changes and report completion evidence." })
    Save-RunnerCheckpoint -Event 'resume_verified'
} else {
    Save-RunnerCheckpoint -Event 'run_started'
}

while ($true) {
    if (($turnCount - $segmentTurnStart) -ge $MaxTurns) {
        $segmentProgress = $progressCount - $segmentProgressStart
        if ($segmentProgress -gt 0) {
            $noProgressSegmentCount = 0
        } else {
            $noProgressSegmentCount++
        }
        if ($segmentProgress -eq 0 -and $noProgressSegmentCount -gt $MaxNoProgressSegments) {
            $status = 'PARTIAL'
            $stopReason = 'NO_PROGRESS_SEGMENTS_EXHAUSTED'
            $finalResponse = "Writer stopped after $noProgressSegmentCount consecutive segments without new file evidence. Resume is available after providing direction."
            Save-RunnerCheckpoint -Event 'no_progress_segments_exhausted'
            break
        }
        $autoExtensionCount++
        $segmentNumber++
        $segmentTurnStart = $turnCount
        $segmentProgressStart = $progressCount
        $messages.Clear()
        $messages.Add([PSCustomObject]@{ role = 'system'; content = $systemPrompt })
        $messages.Add([PSCustomObject]@{ role = 'user'; content = "Task ID: $($taskPacket.task_id)`nObjective: $TaskObjective" })
        $messages.Add([PSCustomObject]@{ role = 'user'; content = "[RUNNER] Starting segment $segmentNumber for RunId=$RunId after $turnCount turns. New evidence in prior segment: $segmentProgress. Changed paths so far: $((@($mutatedPaths) -join ', ')). Re-read current files as needed, continue the Task Packet, and do not finish until every completion criterion has evidence." })
        Save-RunnerCheckpoint -Event 'segment_extended'
        continue
    }
    $turnCount++
    $requestCount++

    $apiStart = [datetimeoffset]::UtcNow
    $resp = Invoke-WriterProvider -ForceNonThinking:$forceNonThinkingOnce
    $apiElapsedMs += [long]((([datetimeoffset]::UtcNow) - $apiStart).TotalMilliseconds)

    if (-not $resp.ok) {
        if ($resp.error -eq 'REASONING_PROTOCOL_ERROR' -and -not $forceNonThinkingOnce) {
            # design §11: exactly one non-thinking retry after history sanitization
            Write-Host "[runner] reasoning 400 → sanitizing history and retrying once without thinking" -ForegroundColor Yellow
            # strip reasoning_content from all assistant messages for the retry
            $clean = [System.Collections.Generic.List[object]]::new()
            foreach ($m in $messages) {
                if ($m.role -eq 'assistant') {
                    $cleanItem = [ordered]@{
                        role = 'assistant'
                        content = Get-OptionalMember -Object $m -Name 'content'
                    }
                    # omit tool_calls when absent (StrictMode-safe; ConvertTo-DeepSeekMessage treats missing same as null)
                    $priorToolCalls = Get-OptionalMember -Object $m -Name 'tool_calls'
                    if ($null -ne $priorToolCalls) {
                        $cleanItem['tool_calls'] = $priorToolCalls
                    }
                    $clean.Add([PSCustomObject]$cleanItem)
                } else {
                    $clean.Add($m)
                }
            }
            $messages.Clear()
            $messages.AddRange($clean)
            $forceNonThinkingOnce = $true
            Save-RunnerCheckpoint -Event 'reasoning_protocol_retry'
            $turnCount--  # do not count the failed protocol attempt as a work turn
            continue
        }
        if ($resp.error -eq 'TRANSPORT_ERROR') {
            $transportRetryCount++
            if ($transportRetryCount -gt $MaxTransportRetries) {
                $status = 'FAIL'
                $stopReason = 'TRANSPORT_ERROR_EXHAUSTED'
                $finalResponse = "Transport retries exhausted: $($resp.message)"
                Save-RunnerCheckpoint -Event 'transport_retry_exhausted'
                break
            }
            Save-RunnerCheckpoint -Event 'transport_retry'
            Start-Sleep -Seconds (Get-RetryDelaySeconds -Attempt $transportRetryCount)
            $turnCount--  # protocol/transport does not consume work turn
            continue
        }
        if ($resp.error -eq 'RATE_LIMIT') {
            $rateLimitRetryCount++
            if ($rateLimitRetryCount -gt $MaxRateLimitRetries) {
                $status = 'FAIL'
                $stopReason = 'RATE_LIMIT_EXHAUSTED'
                $finalResponse = "Rate-limit retries exhausted: $($resp.message)"
                Save-RunnerCheckpoint -Event 'rate_limit_retry_exhausted'
                break
            }
            Save-RunnerCheckpoint -Event 'rate_limit_retry'
            Start-Sleep -Seconds (Get-RetryDelaySeconds -Attempt $rateLimitRetryCount)
            $turnCount--
            continue
        }
        $status = 'FAIL'
        $stopReason = $resp.error
        $finalResponse = "Provider error ($($resp.error)): $($resp.message)"
        Save-RunnerCheckpoint -Event 'provider_error'
        break
    }

    # successful provider request → reset consecutive transport/rate streaks
    $transportRetryCount = 0
    $rateLimitRetryCount = 0
    # A non-thinking retry is one retry for the immediately preceding
    # reasoning-protocol error. A successful response returns to normal mode.
    if ($forceNonThinkingOnce) { $forceNonThinkingOnce = $false }

    # accumulate usage (cache fields optional under StrictMode)
    $usageObj = Get-OptionalMember -Object $resp -Name 'usage'
    if ($usageObj) {
        $pt = Get-OptionalMember -Object $usageObj -Name 'prompt_tokens'
        $ct = Get-OptionalMember -Object $usageObj -Name 'completion_tokens'
        $hit = Get-OptionalMember -Object $usageObj -Name 'prompt_cache_hit_tokens'
        $miss = Get-OptionalMember -Object $usageObj -Name 'prompt_cache_miss_tokens'
        if ($pt) { $usageAccum.prompt_tokens += [int]$pt }
        if ($ct) { $usageAccum.completion_tokens += [int]$ct }
        if ($hit) { $usageAccum.cache_hit_tokens += [int]$hit }
        if ($miss) { $usageAccum.cache_miss_tokens += [int]$miss }
    }

    $asst = Get-OptionalMember -Object $resp -Name 'message'
    $finishReason = Get-OptionalMember -Object $resp -Name 'finish_reason'

    # Success provider response with missing/null message → explicit stop, never store null
    if ($null -eq $asst) {
        $status = 'FAIL'
        $stopReason = 'MODEL_MESSAGE_MISSING'
        $finalResponse = 'ERROR: MODEL_MESSAGE_MISSING — provider response has no message'
        break
    }

    # truncated tool-call → do NOT store incomplete assistant message (avoids orphan tool_calls)
    $hasTools = $false
    $asstToolCalls = Get-OptionalMember -Object $asst -Name 'tool_calls'
    if ($asstToolCalls) { $hasTools = $true }
    if ($finishReason -eq 'length' -and $hasTools) {
        $messages.Add([PSCustomObject]@{
            role = 'user'
            content = '[RUNNER] Your previous response was truncated (finish_reason=length). It was NOT saved and tool calls were NOT executed. Please continue with a shorter or split action.'
        })
        continue
    }

    # always preserve reasoning_content when present on $asst (design); do not require the field
    $messages.Add($asst)

    if ($asstToolCalls -and @($asstToolCalls).Count -gt 0) {
        foreach ($tc in $asstToolCalls) {
            $norm = Normalize-ToolCall -RawToolCall $tc
            if (-not $norm.ok) {
                $toolCallId = Get-OptionalMember -Object $norm -Name 'partial_id' -Default ''
                if (-not $toolCallId) { $toolCallId = '' }
                $toolResult = @{
                    ok = $false
                    error = $norm.error
                    content = $norm.content
                }
                $normTool = $null
            } else {
                $normTool = $norm.tool_call
                $toolCallId = $normTool.id
                $toolResult = Invoke-ToolCall -ToolCall $normTool
            }

            # fatal/ok/content via production helper (StrictMode-safe; no direct .fatal/.ok)
            $outcome = Resolve-ToolResultOutcome -ToolResult $toolResult -ToolCallId $toolCallId
            $toolContent = $outcome.content

            if ($outcome.branch -eq 'FAIL') {
                $status = 'FAIL'
                $stopReason = $outcome.stop_reason
                $finalResponse = $toolContent
                $messages.Add($outcome.tool_message)
                Save-RunnerCheckpoint -Event 'fatal_tool_result'
                break
            }

            # P1: common fingerprint for all recoverable tool failures
            if ($outcome.branch -eq 'RECOVERABLE') {
                $errCode = $outcome.error
                if (-not $errCode) { $errCode = 'TOOL_ERROR' }
                $pathOrQ = ''
                $opName = ''
                $argHashSrc = $null
                if ($null -ne $normTool) {
                    $opName = [string](Get-OptionalMember -Object $normTool -Name 'name' -Default '')
                    $a = Get-OptionalMember -Object $normTool -Name 'arguments'
                    if ($null -ne $a) {
                        $pathOrQVal = Get-OptionalMember -Object $a -Name 'path'
                        if (-not $pathOrQVal) { $pathOrQVal = Get-OptionalMember -Object $a -Name 'query' }
                        if ($pathOrQVal) { $pathOrQ = [string]$pathOrQVal }
                        $argHashSrc = $a
                    }
                }
                $argForHash = if ($null -ne $argHashSrc) { $argHashSrc } else { @{} }
                $fp = Get-FailureFingerprint -ErrorCode $errCode -Path $pathOrQ -Operation $opName -ArgHash (Get-ArgHash $argForHash)
                $consec = Add-FingerprintAndCheck -Fp $fp
                $recoverableErrorCount++
                if ($consec -ge 2) { $repeatedErrorCount++ }
                if ($consec -eq 2) {
                    $toolContent += "`n[RUNNER] Same failure fingerprint repeated twice. Do NOT retry the identical request. Change approach."
                } elseif ($consec -ge 3) {
                    $toolContent += "`n[RUNNER] Same failure fingerprint 3 times. Abandon this specific approach; try a different file or method."
                }
                if ($errCode -eq 'MAX_READ_CALLS') {
                    $readBudgetExhaustionCount++
                    if ($readBudgetExhaustionCount -eq 1) {
                        $toolContent += "`n[RUNNER] Read/search/list budget is exhausted. Use the evidence already returned, perform any safe edit, then send the required completion report. Do not request another read tool."
                    } else {
                        $status = 'PARTIAL'
                        $stopReason = 'MAX_READ_CALLS_REPEATED'
                        $finalResponse = 'Read/search/list budget was exhausted repeatedly; checkpoint preserved for a resumed run with a larger explicit read budget.'
                    }
                }
                $messages.Add([PSCustomObject]@{
                    role = 'tool'
                    tool_call_id = $toolCallId
                    content = $toolContent
                })
            } else {
                $messages.Add($outcome.tool_message)
                if ($null -ne $normTool) {
                    $null = Register-Progress -Kind ([string]$normTool.name) -Evidence $toolContent
                }
            }
            Save-RunnerCheckpoint -Event 'tool_result'
            if ($usingMockProvider -and $MockCrashAfterResponses -gt 0 -and $requestCount -ge $MockCrashAfterResponses) {
                throw 'MOCK_FORCED_TERMINATION: checkpoint was written before simulated process termination'
            }
            if ($status -in @('FAIL','BLOCKED','PARTIAL')) { break }
        }
        if ($status -in @('FAIL','BLOCKED','PARTIAL')) { break }
        # continue loop for next model turn
        continue
    }

    # No tool calls → model is giving final answer
    $asstContent = Get-OptionalMember -Object $asst -Name 'content'
    $finalResponse = if ($asstContent) { $asstContent } else { '' }

    # Check for BLOCKED claim
    if ($finalResponse -match '(?i)^\s*BLOCKED\s*:') {
        # Design §10: distinguish obvious external vs exploratable
        $obvious = $finalResponse -match '(?i)(secret|api.?key|permission|outside|권한|비밀|키 없|외부 스펙)'
        if ($obvious) {
            $status = 'BLOCKED'
            $stopReason = 'model_reported_blocked_external'
            Save-RunnerCheckpoint -Event 'model_reported_blocked'
            break
        }
        # §10: bounce back exactly ONCE. A second BLOCKED claim after the model
        # has had the chance to search is accepted as a genuine blocker, so the
        # runner does not burn the remaining MaxTurns re-asking the same thing.
        if (-not $blockedBounceDone) {
            $blockedBounceDone = $true
            $messages.Add([PSCustomObject]@{
                role = 'user'
                content = '[RUNNER] You claimed BLOCKED, but the reason looks solvable with the available read/search tools. Please use list_files / search_text / read_file first. Only re-issue BLOCKED if you still cannot proceed after searching.'
            })
            continue
        }
        $status = 'BLOCKED'
        $stopReason = 'model_reported_blocked_after_bounce'
        Save-RunnerCheckpoint -Event 'model_reported_blocked'
        break
    }

    # Net change check
    $net = Get-NetChangedPaths -Workspace $ws
    if (@($net).Count -gt 0) {
        $completionAssessment = Get-CompletionAssessment -ModelReport $finalResponse
        if ($completionAssessment.complete) {
            $status = 'DONE'
            $stopReason = 'completed_with_all_completion_evidence'
        } else {
            $status = 'PARTIAL'
            $stopReason = 'COMPLETION_EVIDENCE_MISSING_OR_FAILED'
        }
        Save-RunnerCheckpoint -Event 'model_final_report'
        break
    }

    # No net change — premature completion guard
    if (-not $prematureReconfirmDone) {
        $prematureReconfirmDone = $true
        $messages.Add([PSCustomObject]@{
            role = 'user'
            content = '[RUNNER] PREMATURE_COMPLETION detected: no files have a net change from the session start state. Please re-verify the current contents against the original request and perform any missing edits. If after inspection you still believe zero changes are required, reply with a short justification.'
        })
        continue
    }

    # After one reconfirm still no change
    $status = 'PARTIAL'
    $stopReason = 'model_reported_no_change_after_reconfirm'
    Save-RunnerCheckpoint -Event 'model_reported_no_change'
    break
}

$elapsedMs = [long]((([datetimeoffset]::UtcNow) - $startTime).TotalMilliseconds)
$netPaths = @(Get-NetChangedPaths -Workspace $ws)
$allTouched = @($mutatedPaths)

# Final status refinement
if ($status -eq 'RUNNING') { $status = 'PARTIAL'; $stopReason = 'loop_exit' }
$completionAssessment = if ($null -ne $completionAssessment) { $completionAssessment } else { Get-CompletionAssessment -ModelReport $finalResponse }
$finalSummary = New-NonEmptyFinalSummary -Assessment $completionAssessment
if ([string]::IsNullOrWhiteSpace($finalResponse)) { $finalResponse = $finalSummary }
Save-RunnerCheckpoint -Event 'terminal_report'

$result = [ordered]@{
    status                 = $status
    run_id                 = $RunId
    task_id                = $taskPacket.task_id
    task_hash              = $taskHash
    model                  = $Model
    started_at_utc         = ConvertTo-RunnerUtcTimestamp -Value $startTime
    finished_at_utc        = ConvertTo-RunnerUtcTimestamp -Value ([datetimeoffset]::UtcNow)
    turns_used             = $turnCount
    request_count          = $requestCount
    read_calls             = $readCalls
    read_budget_exhaustion_count = $readBudgetExhaustionCount
    segment_count          = $segmentNumber
    auto_extension_count   = $autoExtensionCount
    limits                 = @{ soft_segment_turns = $MaxTurns; max_read_calls = $MaxReadCalls; max_no_progress_segments = $MaxNoProgressSegments; max_transport_retries = $MaxTransportRetries; max_rate_limit_retries = $MaxRateLimitRetries }
    changed_paths          = $allTouched
    net_changed_paths      = $netPaths
    file_changes           = @($editRecords)
    recoverable_error_count = $recoverableErrorCount
    repeated_error_count   = $repeatedErrorCount
    stop_reason            = $stopReason
    elapsed_ms             = $elapsedMs
    api_elapsed_ms         = $apiElapsedMs
    prompt_tokens          = $usageAccum.prompt_tokens
    completion_tokens      = $usageAccum.completion_tokens
    cache_hit_tokens       = $usageAccum.cache_hit_tokens
    cache_miss_tokens      = $usageAccum.cache_miss_tokens
    final_response         = $finalResponse
    final_summary          = $finalSummary
    completion_criteria    = @($completionAssessment.criteria)
    completion_complete    = [bool]$completionAssessment.complete
    unmet_completion_criteria = @($completionAssessment.unmet_criteria)
    remaining_work         = @($completionAssessment.remaining_work)
    blocked_items          = @($completionAssessment.blocked)
    completion_report_parse_error = $completionAssessment.parse_error
    completion_report_extraction = $completionAssessment.extraction
    tests                  = @{ status = 'NOT_RUN'; reason = 'DeepSeek Writer has no shell, Git, or test execution tool.' }
    repo_root              = $RepoRootFull
    write_allow_list       = @($WriteAllowList)
    read_allow_list        = @($ReadAllowList)
    max_tokens             = $MaxTokens
    reasoning_effort       = $ReasoningEffort
    credential_source      = $credentialSource
    portable_pwsh          = $portablePwshPath
    checkpoint_path        = $checkpointPath
    resume_available       = $false
}

# Output
$result | ConvertTo-Json -Depth 6

if ($status -eq 'FAIL') { exit 2 }
if ($status -eq 'BLOCKED') { exit 3 }
if ($status -eq 'PARTIAL') { exit 1 }
exit 0
