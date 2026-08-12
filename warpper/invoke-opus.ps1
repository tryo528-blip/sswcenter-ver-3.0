#requires -Version 7.0
[CmdletBinding(PositionalBinding = $false)]
param(
    [Alias('p')][AllowEmptyString()][string]$Prompt = '',
    [AllowEmptyString()][string]$PromptFile = '',
    [AllowEmptyString()][string]$RepositoryRoot = '',
    [AllowEmptyString()][string]$MachineProfile = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$corePath = Join-Path $PSScriptRoot 'ai-wrapper-core.ps1'
if (-not [System.IO.File]::Exists($corePath)) {
    [Console]::Error.WriteLine('WRAPPER_ERROR=AI_WRAPPER_CORE_NOT_FOUND')
    exit 64
}
. $corePath

function Assert-AwOpusObjectShape {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory)][string[]]$Fields,
        [Parameter(Mandatory)][string]$Prefix
    )
    if ($null -eq $Value -or $Value -isnot [pscustomobject]) { throw ($Prefix + '_TYPE_INVALID') }
    $actual = @($Value.PSObject.Properties.Name)
    foreach ($field in $Fields) {
        if ($null -eq $Value.PSObject.Properties[$field]) { throw ($Prefix + '_FIELD_MISSING_' + $field.ToUpperInvariant()) }
    }
    foreach ($field in $actual) {
        if ($field -notin $Fields) { throw ($Prefix + '_FIELD_UNEXPECTED_' + $field.ToUpperInvariant()) }
    }
}

function Assert-AwOpusStringArray {
    param([AllowNull()][object]$Value, [Parameter(Mandatory)][string]$Prefix)
    if ($Value -isnot [System.Array]) { throw ($Prefix + '_TYPE_INVALID') }
    foreach ($item in $Value) {
        if ($item -isnot [string]) { throw ($Prefix + '_ITEM_TYPE_INVALID') }
    }
}

function Assert-AwOpusFindings {
    param([AllowNull()][object]$Value)
    if ($Value -isnot [System.Array]) { throw 'OPUS_REPORT_FINDINGS_TYPE_INVALID' }
    $fields = @('severity', 'file', 'line', 'title', 'detail')
    $integerTypes = @([byte], [sbyte], [int16], [uint16], [int32], [uint32], [int64], [uint64])
    foreach ($finding in $Value) {
        Assert-AwOpusObjectShape -Value $finding -Fields $fields -Prefix 'OPUS_FINDING'
        if ($finding.severity -isnot [string] -or $finding.severity -notin @('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')) {
            throw 'OPUS_FINDING_SEVERITY_INVALID'
        }
        foreach ($field in @('file', 'title', 'detail')) {
            if ($finding.$field -isnot [string]) { throw ('OPUS_FINDING_' + $field.ToUpperInvariant() + '_TYPE_INVALID') }
        }
        if ($null -eq $finding.line -or $finding.line.GetType() -notin $integerTypes -or [decimal]$finding.line -lt 1) {
            throw 'OPUS_FINDING_LINE_INVALID'
        }
    }
}

function Read-AwOpusReport {
    param([Parameter(Mandatory)][string]$Text)
    try { $envelope = $Text | ConvertFrom-Json -Depth 40 -ErrorAction Stop -NoEnumerate }
    catch { throw 'OPUS_ENVELOPE_INVALID_JSON' }
    if ($null -eq $envelope -or $envelope -isnot [pscustomobject]) { throw 'OPUS_ENVELOPE_TYPE_INVALID' }
    foreach ($field in @('type', 'subtype', 'is_error', 'result')) {
        if ($null -eq $envelope.PSObject.Properties[$field]) { throw ('OPUS_ENVELOPE_FIELD_MISSING_' + $field.ToUpperInvariant()) }
    }
    if ($envelope.type -isnot [string] -or $envelope.type -cne 'result') { throw 'OPUS_ENVELOPE_TYPE_INVALID' }
    if ($envelope.subtype -isnot [string] -or $envelope.subtype -cne 'success') { throw 'OPUS_RUN_INCOMPLETE' }
    if ($envelope.is_error -isnot [bool] -or $envelope.is_error) { throw 'OPUS_RUN_ERROR' }
    if ($null -ne $envelope.PSObject.Properties['terminal_reason'] -and
        $null -ne $envelope.terminal_reason -and
        ($envelope.terminal_reason -isnot [string] -or $envelope.terminal_reason -cne 'completed')) {
        throw 'OPUS_RUN_INCOMPLETE_TERMINAL_REASON'
    }
    if ($envelope.result -isnot [string]) { throw 'OPUS_REPORT_TYPE_INVALID' }
    try { $report = $envelope.result | ConvertFrom-Json -Depth 40 -ErrorAction Stop -NoEnumerate }
    catch { throw 'OPUS_REPORT_INVALID_JSON' }
    Assert-AwOpusObjectShape -Value $report -Fields @('verdict', 'summary', 'findings', 'unverified') -Prefix 'OPUS_REPORT'
    if ($report.verdict -isnot [string] -or $report.verdict -cnotin @('PASS', 'FAIL', 'BLOCKED')) { throw 'OPUS_REPORT_VERDICT_INVALID' }
    if ($report.summary -isnot [string]) { throw 'OPUS_REPORT_SUMMARY_TYPE_INVALID' }
    Assert-AwOpusFindings -Value $report.findings
    Assert-AwOpusStringArray -Value $report.unverified -Prefix 'OPUS_REPORT_UNVERIFIED'
    $verdict = [string]$report.verdict
    $findingCount = @($report.findings).Count
    if ($verdict -eq 'PASS' -and $findingCount -ne 0) { throw 'OPUS_PASS_WITH_FINDINGS' }
    if ($verdict -eq 'FAIL' -and $findingCount -eq 0) { throw 'OPUS_FAIL_WITHOUT_FINDINGS' }
    return $report
}

function Invoke-AwOpusMain {
    $config = Read-AwConfig -Path (Join-Path $PSScriptRoot 'wrapper-config.json')
    $root = Resolve-AwRepositoryRoot -ConfiguredRoot ([string]$config.repositoryRoot) -RepositoryRoot $RepositoryRoot
    $executable = Resolve-AwProviderExecutable -Config $config -Provider Opus -MachineProfile $MachineProfile
    $task = Read-AwPrompt -Prompt $Prompt -PromptFile $PromptFile
    $environment = New-AwProviderEnvironment -Provider Opus -Overrides @{
        'DISABLE_AUTOUPDATER' = '1'
        'CLAUDE_CODE_SKIP_PROMPT_HISTORY' = '1'
        'CLAUDE_CODE_DISABLE_1M_CONTEXT' = '1'
        'CLAUDE_CODE_DISABLE_THINKING' = '1'
    }
    $watcher = $null
    $before = $null
    try {
        $before = Assert-AwProviderAuthenticationReadOnly -Provider Opus -Executable $executable `
            -WorkingDirectory $root -Environment $environment `
            -TimeoutSeconds ([int]$config.preflightTimeoutSeconds)
        $watcher = Start-AwRepositoryWatcher -Root $root
        $reviewRules = @"
You are Opus, the final independent review-only reviewer used when Codex is the operator.
Target repository: $root

Hard contract:
- Never create, edit, delete, rename, install, execute shell commands, or change the environment or Git state.
- Use only Read, Glob, and Grep. Do not delegate to or spawn any subagent.
- Base findings on current repository bytes. Give exact file and line evidence for every finding.
- PASS means no material defect was found in the requested scope. FAIL means at least one material defect was found. BLOCKED means the review could not be completed.
- List every unverified claim explicitly. Do not confuse process success with a PASS verdict.
- Complete this review in this single CLI invocation. Do not request a wrapper retry or fallback model.
  - Return exactly one JSON object with no Markdown fence or surrounding prose.
  - The exact shape is: {"verdict":"PASS|FAIL|BLOCKED","summary":"string","findings":[{"severity":"CRITICAL|HIGH|MEDIUM|LOW","file":"string","line":1,"title":"string","detail":"string"}],"unverified":["string"]}
"@
    $arguments = @(
        '--print',
        '--model', 'claude-opus-4-6',
        '--effort', 'max',
        '--permission-mode', 'plan',
        '--safe-mode',
        '--no-chrome',
        '--no-session-persistence',
        '--tools', 'Read,Glob,Grep',
        '--disallowedTools', 'Agent,Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch',
        '--append-system-prompt', $reviewRules,
        '--output-format', 'json'
    )
    $run = Invoke-AwNativeOnce -Executable $executable `
        -Arguments $arguments -WorkingDirectory $root -StdinText $task `
        -TimeoutSeconds ([int]$config.opusTimeoutSeconds) `
        -MaxOutputBytes ([int64]$config.maxOutputBytes) -Environment $environment
    $watcherResult = Stop-AwRepositoryWatcher -Watcher $watcher
    $watcher = $null
    $after = Get-AwStableRepositorySnapshot -Root $root
    Assert-AwReadOnlyRepositoryUnchanged -Before $before -After $after -Provider OPUS -WatcherResult $watcherResult

    if ($run.ExitCode -ne 0) {
        Write-AwChildOutput -Result $run
        return [int]$run.ExitCode
    }
    if (-not [string]::IsNullOrEmpty([string]$run.StdErr)) { [Console]::Error.Write([string]$run.StdErr) }
    try { $report = Read-AwOpusReport -Text ([string]$run.StdOut) }
    catch {
        [Console]::Error.WriteLine('WRAPPER_ERROR=' + $_.Exception.Message)
        return 20
    }
    [Console]::Out.WriteLine(($report | ConvertTo-Json -Depth 30 -Compress))
    switch ([string]$report.verdict) {
        'PASS' { return 0 }
        'FAIL' { return 10 }
        default { return 11 }
    }
    }
    finally {
        if ($null -ne $watcher) {
            $after = $null
            $watcherResult = $null
            $watcherResult = Stop-AwRepositoryWatcher -Watcher $watcher
            $watcher = $null
            if ($null -ne $before) { $after = Get-AwStableRepositorySnapshot -Root $root }
            if ($null -ne $before -and $null -ne $after) {
                Assert-AwReadOnlyRepositoryUnchanged -Before $before -After $after -Provider OPUS -WatcherResult $watcherResult
            }
        }
    }
}

try { $finalExit = Invoke-AwOpusMain }
catch {
    $message = [string]$_.Exception.Message
    [Console]::Error.WriteLine('WRAPPER_ERROR=' + $message)
    Write-AwAuthGuidance -Message $message
    $finalExit = Get-AwWrapperErrorExitCode -Message $message
}
exit [int]$finalExit
