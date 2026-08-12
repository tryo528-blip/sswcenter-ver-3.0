#requires -Version 7.0
[CmdletBinding(PositionalBinding = $false)]
param(
    [Alias('p')][AllowEmptyString()][string]$Prompt = '',
    [AllowEmptyString()][string]$PromptFile = '',
    [switch]$SimpleTest,
    [ValidateRange(0, 5)][int]$TestGrade = 0,
    [ValidateRange(0, 5)][int]$ReviewGrade = 0,
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

function Get-AwCodexSessionSettings {
    param(
        [switch]$SimpleTest,
        [ValidateRange(0, 5)][int]$TestGrade = 0,
        [ValidateRange(0, 5)][int]$ReviewGrade = 0
    )

    if ($SimpleTest -and ($TestGrade -gt 0 -or $ReviewGrade -gt 0)) { throw 'CODEX_GRADE_CONFLICT' }
    if ($TestGrade -gt 0 -and $ReviewGrade -gt 0) { throw 'CODEX_GRADE_CONFLICT' }
    if (-not $SimpleTest -and $TestGrade -eq 0 -and $ReviewGrade -eq 0) { throw 'CODEX_GRADE_REQUIRED' }

    if ($SimpleTest) {
        return [pscustomobject]@{
            Mode = 'simple_test'
            TaskKind = 'test'
            TestGrade = 1
            ReviewGrade = 0
            Model = 'gpt-5.3-codex-spark'
            ReasoningEffort = 'xhigh'
            FastMode = 'off'
            SandboxMode = 'read-only'
            NetworkAccess = $false
        }
    }

    if ($TestGrade -gt 0) {
        $model = switch ($TestGrade) {
            { $_ -le 2 } { 'gpt-5.3-codex-spark'; break }
            { $_ -le 4 } { 'gpt-5.6-luna'; break }
            default { 'gpt-5.6-sol' }
        }
        $isSparkGrade = $TestGrade -le 2
        return [pscustomobject]@{
            Mode = ('test_grade_{0}' -f $TestGrade)
            TaskKind = 'test'
            TestGrade = $TestGrade
            ReviewGrade = 0
            Model = $model
            ReasoningEffort = if ($isSparkGrade) { 'xhigh' } else { 'max' }
            FastMode = if ($isSparkGrade -or $TestGrade -eq 5) { 'off' } else { 'on' }
            SandboxMode = if ($TestGrade -le 2) { 'read-only' } else { 'workspace-write' }
            NetworkAccess = ($TestGrade -ge 3)
        }
    }

    $isLunaReview = $ReviewGrade -le 2
    $isFinalReview = $ReviewGrade -eq 5
    return [pscustomobject]@{
        Mode = 'review'
        TaskKind = 'review'
        TestGrade = 0
        ReviewGrade = $ReviewGrade
        Model = if ($isLunaReview) { 'gpt-5.6-luna' } else { 'gpt-5.6-sol' }
        ReasoningEffort = if ($isLunaReview) { 'max' } elseif ($isFinalReview) { 'ultra' } else { 'xhigh' }
        FastMode = if ($isFinalReview -or $ReviewGrade -ge 3) { 'off' } else { 'on' }
        SandboxMode = 'read-only'
        NetworkAccess = $false
    }
}

function New-AwCodexSchema {
    $finding = [ordered]@{
        type = 'object'
        properties = [ordered]@{
            severity = @{ type = 'string'; enum = @('CRITICAL', 'HIGH', 'MEDIUM', 'LOW') }
            file = @{ type = 'string' }
            line = @{ type = 'integer'; minimum = 1 }
            title = @{ type = 'string' }
            detail = @{ type = 'string' }
        }
        required = @('severity', 'file', 'line', 'title', 'detail')
        additionalProperties = $false
    }
    $schema = [ordered]@{
        type = 'object'
        properties = [ordered]@{
            mode = @{ type = 'string'; enum = @('review', 'simple_test', 'test_grade_1', 'test_grade_2', 'test_grade_3', 'test_grade_4', 'test_grade_5') }
            status = @{ type = 'string'; enum = @('COMPLETE', 'BLOCKED') }
            verdict = @{ type = 'string'; enum = @('PASS', 'FAIL', 'NOT_APPLICABLE') }
            summary = @{ type = 'string' }
            findings = @{ type = 'array'; items = $finding }
            changed_paths = @{ type = 'array'; items = @{ type = 'string' } }
            tests = @{ type = 'array'; items = @{ type = 'string' } }
            unverified = @{ type = 'array'; items = @{ type = 'string' } }
        }
        required = @('mode', 'status', 'verdict', 'summary', 'findings', 'changed_paths', 'tests', 'unverified')
        additionalProperties = $false
    }
    return ($schema | ConvertTo-Json -Depth 30)
}

function Assert-AwCodexObjectShape {
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

function Assert-AwCodexStringArray {
    param([AllowNull()][object]$Value, [Parameter(Mandatory)][string]$Prefix)
    if ($Value -isnot [System.Array]) { throw ($Prefix + '_TYPE_INVALID') }
    foreach ($item in $Value) {
        if ($item -isnot [string]) { throw ($Prefix + '_ITEM_TYPE_INVALID') }
    }
}

function Assert-AwCodexFindings {
    param([AllowNull()][object]$Value)
    if ($Value -isnot [System.Array]) { throw 'CODEX_REPORT_FINDINGS_TYPE_INVALID' }
    $fields = @('severity', 'file', 'line', 'title', 'detail')
    $integerTypes = @([byte], [sbyte], [int16], [uint16], [int32], [uint32], [int64], [uint64])
    foreach ($finding in $Value) {
        Assert-AwCodexObjectShape -Value $finding -Fields $fields -Prefix 'CODEX_FINDING'
        if ($finding.severity -isnot [string] -or $finding.severity -notin @('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')) {
            throw 'CODEX_FINDING_SEVERITY_INVALID'
        }
        foreach ($field in @('file', 'title', 'detail')) {
            if ($finding.$field -isnot [string]) { throw ('CODEX_FINDING_' + $field.ToUpperInvariant() + '_TYPE_INVALID') }
        }
        if ($null -eq $finding.line -or $finding.line.GetType() -notin $integerTypes -or [decimal]$finding.line -lt 1) {
            throw 'CODEX_FINDING_LINE_INVALID'
        }
    }
}

function Read-AwCodexReport {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$ExpectedMode)
    if (-not [System.IO.File]::Exists($Path)) { throw 'CODEX_REPORT_MISSING' }
    try { $text = [System.IO.File]::ReadAllText($Path, (Get-AwUtf8)) }
    catch { throw 'CODEX_REPORT_INVALID_UTF8' }
    try { $report = $text | ConvertFrom-Json -Depth 40 -ErrorAction Stop -NoEnumerate }
    catch { throw 'CODEX_REPORT_INVALID_JSON' }
    Assert-AwCodexObjectShape -Value $report `
        -Fields @('mode', 'status', 'verdict', 'summary', 'findings', 'changed_paths', 'tests', 'unverified') `
        -Prefix 'CODEX_REPORT'
    if ($report.mode -isnot [string] -or $report.mode -cnotin @('review', 'simple_test', 'test_grade_1', 'test_grade_2', 'test_grade_3', 'test_grade_4', 'test_grade_5')) { throw 'CODEX_REPORT_MODE_INVALID' }
    if ($report.status -isnot [string] -or $report.status -cnotin @('COMPLETE', 'BLOCKED')) { throw 'CODEX_REPORT_STATUS_INVALID' }
    if ($report.verdict -isnot [string] -or $report.verdict -cnotin @('PASS', 'FAIL', 'NOT_APPLICABLE')) { throw 'CODEX_REPORT_VERDICT_INVALID' }
    if ($report.summary -isnot [string]) { throw 'CODEX_REPORT_SUMMARY_TYPE_INVALID' }
    Assert-AwCodexFindings -Value $report.findings
    Assert-AwCodexStringArray -Value $report.changed_paths -Prefix 'CODEX_REPORT_CHANGED_PATHS'
    Assert-AwCodexStringArray -Value $report.tests -Prefix 'CODEX_REPORT_TESTS'
    Assert-AwCodexStringArray -Value $report.unverified -Prefix 'CODEX_REPORT_UNVERIFIED'
    $mode = [string]$report.mode
    $status = [string]$report.status
    $verdict = [string]$report.verdict
    if ($mode -ne $ExpectedMode) { throw 'CODEX_REPORT_MODE_MISMATCH' }
    if ($status -eq 'COMPLETE' -and $verdict -notin @('PASS', 'FAIL')) { throw 'CODEX_VERDICT_INVALID' }
    if ($status -eq 'BLOCKED' -and $verdict -ne 'NOT_APPLICABLE') { throw 'CODEX_BLOCKED_VERDICT_INVALID' }
    if (@($report.changed_paths).Count -ne 0) { throw 'CODEX_READ_ONLY_REPORTED_CHANGES' }
    $findingCount = @($report.findings).Count
    if ($status -eq 'COMPLETE' -and $verdict -eq 'PASS' -and $findingCount -ne 0) { throw 'CODEX_PASS_WITH_FINDINGS' }
    if ($status -eq 'COMPLETE' -and $verdict -eq 'FAIL' -and $findingCount -eq 0) { throw 'CODEX_FAIL_WITHOUT_FINDINGS' }
    return $report
}

function Write-AwCodexFailureDiagnostics {
    param(
        [AllowNull()]$Result,
        [AllowEmptyString()][string]$FinalPath = ''
    )

    try {
        [Console]::Error.WriteLine('CODEX_CHILD_DIAGNOSTICS_BEGIN')
        if ($null -ne $Result) {
            [Console]::Error.WriteLine('CODEX_CHILD_EXIT_CODE=' + [int]$Result.ExitCode)
            if (-not [string]::IsNullOrEmpty([string]$Result.StdOut)) {
                [Console]::Error.WriteLine('CODEX_CHILD_STDOUT_BEGIN')
                [Console]::Error.WriteLine([string]$Result.StdOut)
                [Console]::Error.WriteLine('CODEX_CHILD_STDOUT_END')
            }
            if (-not [string]::IsNullOrEmpty([string]$Result.StdErr)) {
                [Console]::Error.WriteLine('CODEX_CHILD_STDERR_BEGIN')
                [Console]::Error.WriteLine([string]$Result.StdErr)
                [Console]::Error.WriteLine('CODEX_CHILD_STDERR_END')
            }
        }
        if (-not [string]::IsNullOrWhiteSpace($FinalPath) -and [System.IO.File]::Exists($FinalPath)) {
            [Console]::Error.WriteLine('CODEX_CHILD_FINAL_JSON_BEGIN')
            [Console]::Error.WriteLine([System.IO.File]::ReadAllText($FinalPath, (Get-AwUtf8)))
            [Console]::Error.WriteLine('CODEX_CHILD_FINAL_JSON_END')
        }
        [Console]::Error.WriteLine('CODEX_CHILD_DIAGNOSTICS_END')
    }
    catch {
        [Console]::Error.WriteLine('CODEX_CHILD_DIAGNOSTICS_UNAVAILABLE')
    }
}

function Invoke-AwCodexMain {
    $config = Read-AwConfig -Path (Join-Path $PSScriptRoot 'wrapper-config.json')
    $root = Resolve-AwRepositoryRoot -ConfiguredRoot ([string]$config.repositoryRoot) -RepositoryRoot $RepositoryRoot
    $executable = Resolve-AwProviderExecutable -Config $config -Provider Codex -MachineProfile $MachineProfile
    $task = Read-AwPrompt -Prompt $Prompt -PromptFile $PromptFile
    $session = Get-AwCodexSessionSettings `
        -SimpleTest:$SimpleTest `
        -TestGrade $TestGrade `
        -ReviewGrade $ReviewGrade
    $grade = if ([string]$session.TaskKind -eq 'test') { [int]$session.TestGrade } else { [int]$session.ReviewGrade }
    [Console]::Error.WriteLine((
        'CODEX_SESSION_SETTINGS kind={0} grade={1} model={2} effort={3} fast={4} sandbox={5} network={6}' -f
        $session.TaskKind, $grade, $session.Model, $session.ReasoningEffort, $session.FastMode,
        $session.SandboxMode, ([bool]$session.NetworkAccess).ToString().ToLowerInvariant()
    ))
    $environment = New-AwProviderEnvironment -Provider Codex
    $watcher = $null
    $before = $null
    $run = $null
    $finalPath = ''
    $diagnosticsWritten = $false
    try {
        $before = Assert-AwProviderAuthenticationReadOnly -Provider Codex -Executable $executable `
            -WorkingDirectory $root -Environment $environment `
            -TimeoutSeconds ([int]$config.preflightTimeoutSeconds)
        $watcher = Start-AwRepositoryWatcher -Root $root
        $tempBase = Get-AwTempBase
        $temp = New-AwTempDirectory -Prefix 'ai-codex-' -Base $tempBase
        try {
        $schemaPath = Join-Path $temp 'final.schema.json'
        $finalPath = Join-Path $temp 'final.json'
        Write-AwUtf8File -Path $schemaPath -Text (New-AwCodexSchema)
        $mode = [string]$session.Mode
        $model = [string]$session.Model
        $roleRules = if ([string]$session.TaskKind -eq 'test') {
            $testGrade = [int]$session.TestGrade
            $agentName = switch ($model) {
                'gpt-5.3-codex-spark' { 'Codex Spark' }
                'gpt-5.6-luna' { 'Codex Luna' }
                default { 'Codex Sol' }
            }
            $scope = switch ($testGrade) {
                1 { 'Run only static, syntax, import, compile, or one narrowly named smoke check.' }
                2 { 'Run the bounded local unit, component, and contract checks in the requested scope.' }
                3 { 'Run the requested isolated PostgreSQL or database-integration checks.' }
                4 { 'Run the requested cross-layer API, frontend, service, and end-to-end checks.' }
                5 { 'Run the requested operational, recovery, migration-lifecycle, security, and final acceptance checks.' }
            }
            $resourceRules = if ($testGrade -le 2) {
@"
- The repository and Git state are read-only. Do not use network access. Keep all permitted test scratch data outside the repository.
- If the requested test requires repository writes, a database, a local service, network access, installation, or expanded scope, report BLOCKED instead of escalating.
- Do not report BLOCKED while an in-scope read-only method remains.
"@
            }
            else {
@"
- Repository files and Git state remain immutable. You may use isolated temporary directories, disposable test databases, and explicitly requested local test services only.
- Never target production, shared, or unidentified databases. Do not access the public internet, download packages, install software, or expand scope.
- Remove isolated test resources you created when cleanup is safe. Report cleanup failures and every resource left behind.
"@
            }
@"
You are $agentName, the independent test executor used when Claude Code is the operator.
- This is test grade $testGrade. $scope
$resourceRules
- Do not delegate to or spawn any subagent. Complete the test in this one session.
- If one permitted command is denied, use another in-scope method when it can complete the same test without weakening isolation. Do not report BLOCKED while an in-scope method remains.
- PASS means the requested test completed successfully. FAIL means it completed and exposed a material defect. BLOCKED means the requested grade cannot be completed within these boundaries.
- Report exact commands and results in tests, exact evidence in findings, and every unverified claim.
- Complete this task in this single CLI invocation. Do not request a wrapper retry or fallback model.
- Set mode=$mode, changed_paths=[], and status/verdict consistently.
"@
        }
        else {
            $reviewGrade = [int]$session.ReviewGrade
            $agentName = if ($model -eq 'gpt-5.6-luna') { 'Codex Luna' } else { 'Codex Sol' }
            $scope = switch ($reviewGrade) {
                1 { 'Perform a fast, focused review of the explicitly requested change and its immediate contracts.' }
                2 { 'Perform a normal repository review covering correctness, regressions, and test adequacy in scope.' }
                3 { 'Perform a deep cross-layer review covering data flow, integration behavior, and edge cases.' }
                4 { 'Perform a critical architecture, security, concurrency, recovery, and operational review in scope.' }
                5 { 'Perform the final adversarial acceptance review; exhaust all safe read-only evidence paths before concluding.' }
            }
@"
You are $agentName, a read-only repository reviewer used when Claude Code is the operator.
  - This is review grade $reviewGrade. $scope
  - Never create, edit, delete, rename, install, or change repository or Git state.
  - Do not delegate to or spawn any subagent. Complete the review yourself in this one session.
  - If one read-only inspection command is denied, use another permitted read-only method such as rg or Get-Content when it can complete the same review without writes, network access, or scope expansion. Do not report BLOCKED while an in-scope read-only method remains.
  - Give exact file and line evidence for every finding. List every unverified claim.
- PASS means no material defect was found in the requested scope. FAIL means at least one material defect was found. BLOCKED means the review could not be completed.
- Do not confuse process success with a PASS verdict.
- Complete the review in this single CLI invocation. Do not request a wrapper retry or fallback model.
- Set mode=review, changed_paths=[], and status/verdict consistently.
"@
        }
        $stdin = $roleRules + [Environment]::NewLine + 'TASK:' + [Environment]::NewLine + $task
        $arguments = @(
            'exec',
            '--ephemeral',
            '--ignore-user-config',
            '--strict-config',
            '--sandbox', ([string]$session.SandboxMode),
            '--cd', $root,
            '--model', $model,
            '--color', 'never',
            '-c', 'approval_policy="never"',
            '-c', ('model_reasoning_effort="{0}"' -f $session.ReasoningEffort),
            '-c', 'web_search="disabled"',
            '-c', ('sandbox_workspace_write.network_access={0}' -f ([bool]$session.NetworkAccess).ToString().ToLowerInvariant()),
            '-c', 'windows.sandbox="elevated"',
            '-c', 'features.hooks=false',
            '-c', 'features.multi_agent=false',
            '-c', 'apps._default.enabled=false',
            '-c', 'features.skill_mcp_dependency_install=false',
            '-c', 'shell_environment_policy.ignore_default_excludes=false'
        )
        if ([string]$session.FastMode -eq 'on') {
            $arguments += @('-c', 'service_tier="fast"', '--enable', 'fast_mode')
        }
        $arguments += @(
            '--output-schema', $schemaPath,
            '--output-last-message', $finalPath,
            '-'
        )
        $run = Invoke-AwNativeOnce -Executable $executable `
            -Arguments $arguments -WorkingDirectory $root -StdinText $stdin `
            -TimeoutSeconds ([int]$config.codexTimeoutSeconds) `
            -MaxOutputBytes ([int64]$config.maxOutputBytes) -Environment $environment
        try {
            try { $watcherResult = Stop-AwRepositoryWatcher -Watcher $watcher }
            finally { $watcher = $null }
            $after = Get-AwStableRepositorySnapshot -Root $root
            Assert-AwReadOnlyRepositoryUnchanged -Before $before -After $after -Provider CODEX -WatcherResult $watcherResult
        }
        catch {
            Write-AwCodexFailureDiagnostics -Result $run -FinalPath $finalPath
            $diagnosticsWritten = $true
            throw
        }

        if ($run.ExitCode -ne 0) {
            Write-AwChildOutput -Result $run
            return [int]$run.ExitCode
        }
        try { $report = Read-AwCodexReport -Path $finalPath -ExpectedMode $mode }
        catch {
            if (-not $diagnosticsWritten) {
                Write-AwCodexFailureDiagnostics -Result $run -FinalPath $finalPath
                $diagnosticsWritten = $true
            }
            [Console]::Error.WriteLine('WRAPPER_ERROR=' + $_.Exception.Message)
            return 20
        }
        if (-not [string]::IsNullOrEmpty([string]$run.StdErr)) { [Console]::Error.Write([string]$run.StdErr) }
        [Console]::Out.WriteLine(($report | ConvertTo-Json -Depth 30 -Compress))
        if ([string]$report.status -eq 'BLOCKED') { return 11 }
        if ([string]$report.verdict -eq 'FAIL') { return 10 }
        return 0
        }
        finally { Remove-AwTempDirectory -Path $temp -Prefix 'ai-codex-' -Base $tempBase }
    }
    finally {
        if ($null -ne $watcher) {
            $after = $null
            $watcherResult = $null
            try { $watcherResult = Stop-AwRepositoryWatcher -Watcher $watcher }
            finally { $watcher = $null }
            if ($null -ne $before) { $after = Get-AwStableRepositorySnapshot -Root $root }
            if ($null -ne $before -and $null -ne $after) {
                try {
                    Assert-AwReadOnlyRepositoryUnchanged -Before $before -After $after -Provider CODEX -WatcherResult $watcherResult
                }
                catch {
                    if ($null -ne $run -and -not $diagnosticsWritten) {
                        Write-AwCodexFailureDiagnostics -Result $run -FinalPath $finalPath
                        $diagnosticsWritten = $true
                    }
                    throw
                }
            }
        }
    }
}

try { $finalExit = Invoke-AwCodexMain }
catch {
    $message = [string]$_.Exception.Message
    [Console]::Error.WriteLine('WRAPPER_ERROR=' + $message)
    Write-AwAuthGuidance -Message $message
    $finalExit = Get-AwWrapperErrorExitCode -Message $message
}
exit [int]$finalExit
