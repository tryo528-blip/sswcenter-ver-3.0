#requires -Version 7.0
[CmdletBinding(PositionalBinding = $false)]
param(
    [Alias('p')][AllowEmptyString()][string]$Prompt = '',
    [AllowEmptyString()][string]$PromptFile = '',
    [AllowEmptyString()][string]$RepositoryRoot = '',
    [AllowEmptyString()][string]$MachineProfile = '',
    [Alias('AllowPath')][AllowEmptyCollection()][string[]]$WriteAllowPath = @()
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$corePath = Join-Path $PSScriptRoot 'ai-wrapper-core.ps1'
if (-not [System.IO.File]::Exists($corePath)) {
    [Console]::Error.WriteLine('WRAPPER_ERROR=AI_WRAPPER_CORE_NOT_FOUND')
    exit 64
}
. $corePath

function Test-AwJsonHasNoDuplicateProperties {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$FailureCode
    )
    $document = $null
    try { $document = [System.Text.Json.JsonDocument]::Parse($Text) }
    catch { return $false }
    try {
        $pending = [System.Collections.Generic.Stack[System.Text.Json.JsonElement]]::new()
        $pending.Push($document.RootElement)
        while ($pending.Count -gt 0) {
            $element = $pending.Pop()
            if ($element.ValueKind -eq [System.Text.Json.JsonValueKind]::Object) {
                $names = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
                foreach ($property in $element.EnumerateObject()) {
                    if (-not $names.Add([string]$property.Name)) { throw $FailureCode }
                    $pending.Push($property.Value)
                }
            }
            elseif ($element.ValueKind -eq [System.Text.Json.JsonValueKind]::Array) {
                foreach ($item in $element.EnumerateArray()) { $pending.Push($item) }
            }
        }
        return $true
    }
    finally { $document.Dispose() }
}

function ConvertFrom-AwTrailingJsonObject {
    param([Parameter(Mandatory)][string]$Text)

    $trimmed = $Text.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed)) { return $null }

    if (Test-AwJsonHasNoDuplicateProperties -Text $trimmed -FailureCode 'GROK_REPORT_DUPLICATE_PROPERTY') {
        return ($trimmed | ConvertFrom-Json -Depth 30 -ErrorAction Stop -NoEnumerate)
    }

    if (-not $trimmed.EndsWith('}', [System.StringComparison]::Ordinal)) { return $null }
    $depth = 0
    $inString = $false
    for ($index = $trimmed.Length - 1; $index -ge 0; $index--) {
        $character = $trimmed[$index]
        if ($character -eq [char]0x22) {
            $backslashes = 0
            for ($scan = $index - 1; $scan -ge 0 -and $trimmed[$scan] -eq [char]0x5c; $scan--) { $backslashes++ }
            if (($backslashes % 2) -eq 0) { $inString = -not $inString }
            continue
        }
        if ($inString) { continue }
        if ($character -eq '}') {
            $depth++
            continue
        }
        if ($character -eq '{') {
            $depth--
            if ($depth -eq 0) {
                $candidate = $trimmed.Substring($index)
                if (-not (Test-AwJsonHasNoDuplicateProperties -Text $candidate -FailureCode 'GROK_REPORT_DUPLICATE_PROPERTY')) {
                    return $null
                }
                return ($candidate | ConvertFrom-Json -Depth 30 -ErrorAction Stop -NoEnumerate)
            }
            if ($depth -lt 0) { return $null }
        }
    }
    return $null
}

function Assert-AwGrokObjectShape {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory)][string[]]$Fields,
        [Parameter(Mandatory)][string]$Prefix
    )
    if ($null -eq $Value -or $Value -is [System.Array] -or $Value -isnot [pscustomobject]) {
        throw ($Prefix + '_TYPE_INVALID')
    }
    $actual = @($Value.PSObject.Properties.Name)
    foreach ($field in $Fields) {
        if ($actual -cnotcontains $field) {
            throw ($Prefix + '_FIELD_MISSING_' + $field.ToUpperInvariant())
        }
    }
    foreach ($property in $Value.PSObject.Properties) {
        if ($Fields -cnotcontains [string]$property.Name) {
            throw ($Prefix + '_FIELD_UNEXPECTED_' + ([string]$property.Name).ToUpperInvariant())
        }
    }
}

function Read-AwGrokReport {
    param([Parameter(Mandatory)][string]$Text)
    if (-not (Test-AwJsonHasNoDuplicateProperties -Text $Text -FailureCode 'GROK_ENVELOPE_DUPLICATE_PROPERTY')) {
        throw 'GROK_REPORT_INVALID_JSON'
    }
    try { $envelope = $Text | ConvertFrom-Json -Depth 30 -ErrorAction Stop -NoEnumerate }
    catch { throw 'GROK_REPORT_INVALID_JSON' }
    if ($null -eq $envelope) { throw 'GROK_REPORT_MISSING' }
    if ($envelope -is [System.Array] -or $envelope -isnot [pscustomobject]) { throw 'GROK_ENVELOPE_TYPE_INVALID' }
    $stopReasonProperty = $envelope.PSObject.Properties['stopReason']
    if ($null -eq $stopReasonProperty) { $stopReasonProperty = $envelope.PSObject.Properties['stop_reason'] }
    if ($null -eq $stopReasonProperty) { throw 'GROK_STOP_REASON_MISSING' }
    if ($stopReasonProperty.Value -isnot [string]) { throw 'GROK_STOP_REASON_TYPE_INVALID' }
    $stopReason = ([string]$stopReasonProperty.Value).Trim().ToLowerInvariant()
    if ($stopReason -ne 'end_turn') {
        $safeStopReason = ($stopReason -replace '[^a-z0-9]+', '_').Trim('_').ToUpperInvariant()
        if ([string]::IsNullOrWhiteSpace($safeStopReason)) { $safeStopReason = 'UNKNOWN' }
        throw ('GROK_RUN_INCOMPLETE_' + $safeStopReason)
    }
    $report = $null
    foreach ($propertyName in @('structured_output', 'structuredOutput', 'text')) {
        $property = $envelope.PSObject.Properties[$propertyName]
        if ($null -eq $property -or $null -eq $property.Value) { continue }
        $candidate = $property.Value
        if ($candidate -is [string]) {
            if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
            $candidate = ConvertFrom-AwTrailingJsonObject -Text $candidate
            if ($null -eq $candidate) { continue }
        }
        if ($null -ne $candidate) {
            $report = $candidate
            break
        }
    }
    if ($null -eq $report -and $null -ne $envelope.PSObject.Properties['status']) {
        $report = $envelope
    }
    if ($null -eq $report) { throw 'GROK_REPORT_MISSING' }
    Assert-AwGrokObjectShape -Value $report `
        -Fields @('status', 'summary', 'changed_paths', 'tests', 'unverified') -Prefix 'GROK_REPORT'
    if ($report.status -isnot [string]) { throw 'GROK_REPORT_STATUS_TYPE_INVALID' }
    if ($report.summary -isnot [string]) { throw 'GROK_REPORT_SUMMARY_TYPE_INVALID' }
    foreach ($arrayField in @('changed_paths', 'tests', 'unverified')) {
        $arrayValue = $report.PSObject.Properties[$arrayField].Value
        if ($arrayValue -isnot [System.Array]) { throw ('GROK_REPORT_' + $arrayField.ToUpperInvariant() + '_TYPE_INVALID') }
        foreach ($item in $arrayValue) {
            if ($item -isnot [string]) { throw ('GROK_REPORT_' + $arrayField.ToUpperInvariant() + '_ITEM_TYPE_INVALID') }
        }
    }
    $status = [string]$report.status
    if ($status -cnotin @('COMPLETE', 'NO_CHANGE', 'BLOCKED')) { throw 'GROK_REPORT_STATUS_INVALID' }
    $changedCount = @($report.changed_paths).Count
    if ($status -eq 'COMPLETE' -and $changedCount -eq 0) { throw 'GROK_COMPLETE_WITHOUT_CHANGED_PATHS' }
    if ($status -eq 'NO_CHANGE' -and $changedCount -ne 0) { throw 'GROK_NO_CHANGE_WITH_CHANGED_PATHS' }
    return $report
}

function Invoke-AwGrokMain {
    $config = Read-AwConfig -Path (Join-Path $PSScriptRoot 'wrapper-config.json')
    $root = Resolve-AwRepositoryRoot -ConfiguredRoot ([string]$config.repositoryRoot) -RepositoryRoot $RepositoryRoot
    $allowlist = @(Resolve-AwWriteAllowlist -Root $root -Paths $WriteAllowPath)
    $executable = Resolve-AwProviderExecutable -Config $config -Provider Grok -MachineProfile $MachineProfile
    $task = Read-AwPrompt -Prompt $Prompt -PromptFile $PromptFile
    $environment = New-AwProviderEnvironment -Provider Grok -Overrides @{
        'GROK_DISABLE_AUTOUPDATER' = '1'
        'GROK_SUBAGENTS' = '0'
    }
    $tempBase = Get-AwTempBase
    $watcher = $null
    $before = $null
    $temp = $null
    try {
        $before = Assert-AwProviderAuthenticationReadOnly -Provider Grok -Executable $executable `
            -WorkingDirectory $root -Environment $environment `
            -TimeoutSeconds ([int]$config.preflightTimeoutSeconds)
        $watcher = Start-AwRepositoryWatcher -Root $root
        $temp = New-AwTempDirectory -Prefix 'ai-grok-' -Base $tempBase
        $promptPath = Join-Path $temp 'task.txt'
        Write-AwUtf8File -Path $promptPath -Text $task
        $allowlistJson = ConvertTo-Json -InputObject ([object[]]$allowlist) -Compress
        $rules = @"
You are the implementation Writer for exactly one task in this repository:
$root

Hard contract:
- Read as needed, but create, edit, delete, or rename only these pre-authorized repository-relative paths: $allowlistJson
- An entry ending in / is a pre-existing directory and authorizes descendants. Every other entry is exact-only, including a pre-existing file or a path that did not exist at authorization time.
- Do not act as the independent acceptance reviewer. Verify your own work and report what remains unverified.
- Do not modify anything outside the repository. Never stage, commit, push, reset, clean, switch, or alter Git configuration.
- Shell, web, and external MCP tools are unavailable. Do not attempt to bypass that boundary.
- Do not delegate to or spawn any subagent. Complete the Writer task yourself in this one session.
- Complete the task in this single CLI invocation. Do not request a wrapper retry or fallback model.
- Work through the requested task completely before producing the final report. Do not emit COMPLETE or NO_CHANGE as an intermediate progress message.
- Intermediate analysis and tool-call progress are allowed. After all requested edits and verification are finished, make your final assistant message exactly one JSON object with these fields: status, summary, changed_paths, tests, unverified.
- The exact final shape and types are: {"status":"COMPLETE|NO_CHANGE|BLOCKED","summary":"string","changed_paths":["repository-relative path"],"tests":["string"],"unverified":["string"]}.
- changed_paths, tests, and unverified must always be JSON arrays, including when empty. Never return a scalar string for any of them.
- Use status COMPLETE only after the requested edits and verification are finished, NO_CHANGE only when no edit is needed, and BLOCKED only when the task cannot be completed within this contract.
- changed_paths must be the exact repository-relative set whose current bytes differ from the start of this invocation, including partial changes made before BLOCKED.
- Do not wrap the final report in Markdown or add prose before or after it.
"@
        $arguments = @(
            '--cwd', $root,
            '--model', 'grok-4.5',
            '--max-turns', '96',
            '--always-approve',
            '--tools', 'read_file,search_replace,grep,list_dir',
            '--no-subagents',
            '--deny', 'Bash',
            '--deny', 'WebFetch',
            '--deny', 'WebSearch',
            '--deny', 'MCPTool',
            '--disable-web-search',
            '--no-memory',
            '--rules', $rules,
            '--output-format', 'json',
            '--prompt-file', $promptPath
        )
        $nativeFailure = $null
        $run = $null
        try {
            $run = Invoke-AwNativeOnce -Executable $executable `
                -Arguments $arguments -WorkingDirectory $root `
                -TimeoutSeconds ([int]$config.grokTimeoutSeconds) `
                -MaxOutputBytes ([int64]$config.maxOutputBytes) -Environment $environment
        }
        catch { $nativeFailure = $_ }
        $watcherResult = Stop-AwRepositoryWatcher -Watcher $watcher
        $watcher = $null
        $after = Get-AwStableRepositorySnapshot -Root $root
        $delta = Compare-AwRepositorySnapshots -Before $before -After $after
        Assert-AwGrokMutationScope -Delta $delta -Allowlist $allowlist -Root $root -WatcherResult $watcherResult
        if ($null -ne $nativeFailure) {
            if (@($delta.Paths).Count -ne 0) { throw 'GROK_MUTATION_WITHOUT_VALID_REPORT' }
            throw $nativeFailure
        }

        if ($run.ExitCode -ne 0) {
            if (@($delta.Paths).Count -ne 0) { throw 'GROK_MUTATION_WITHOUT_VALID_REPORT' }
            Write-AwChildOutput -Result $run
            return [int]$run.ExitCode
        }
        if (-not [string]::IsNullOrEmpty([string]$run.StdErr)) { [Console]::Error.Write([string]$run.StdErr) }
        try { $report = Read-AwGrokReport -Text ([string]$run.StdOut) }
        catch {
            Write-AwChildOutput -Result $run
            [Console]::Error.WriteLine('WRAPPER_ERROR=' + $_.Exception.Message)
            return 20
        }
        try {
            $reportedPaths = @(Resolve-AwReportedChangedPaths -Root $root -Paths @($report.changed_paths))
            Assert-AwPathSetsEqual -Expected @($delta.Paths) -Actual $reportedPaths `
                -FailureCode 'GROK_REPORTED_CHANGED_PATHS_MISMATCH'
        }
        catch {
            [Console]::Error.WriteLine('WRAPPER_ERROR=' + $_.Exception.Message)
            return 20
        }
        [Console]::Out.WriteLine(($report | ConvertTo-Json -Depth 20 -Compress))
        if ([string]$report.status -eq 'BLOCKED') { return 11 }
        return 0
    }
    finally {
        $guardFailure = $null
        if ($null -ne $watcher) {
            $after = $null
            $watcherResult = $null
            try {
                $watcherResult = Stop-AwRepositoryWatcher -Watcher $watcher
                $watcher = $null
            }
            catch { $guardFailure = $_ }
            if ($null -eq $guardFailure -and $null -ne $before) {
                try { $after = Get-AwStableRepositorySnapshot -Root $root }
                catch { $guardFailure = $_ }
            }
            if ($null -eq $guardFailure -and $null -ne $before -and $null -ne $after) {
                try {
                    $delta = Compare-AwRepositorySnapshots -Before $before -After $after
                    Assert-AwGrokMutationScope -Delta $delta -Allowlist $allowlist -Root $root -WatcherResult $watcherResult
                    if (@($delta.Paths).Count -ne 0 -or @($watcherResult.Paths).Count -ne 0) {
                        throw 'GROK_MUTATION_WITHOUT_VALID_REPORT'
                    }
                }
                catch { $guardFailure = $_ }
            }
        }
        try {
            if ($null -ne $temp) { Remove-AwTempDirectory -Path $temp -Prefix 'ai-grok-' -Base $tempBase }
        }
        catch { if ($null -eq $guardFailure) { $guardFailure = $_ } }
        if ($null -ne $guardFailure) { throw $guardFailure }
    }
}

try { $finalExit = Invoke-AwGrokMain }
catch {
    $message = [string]$_.Exception.Message
    [Console]::Error.WriteLine('WRAPPER_ERROR=' + $message)
    Write-AwAuthGuidance -Message $message
    $finalExit = Get-AwWrapperErrorExitCode -Message $message
}
exit [int]$finalExit
