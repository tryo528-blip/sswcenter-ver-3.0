[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$script:Total = 0
$script:Passed = 0
$script:Failed = 0
$script:Failures = New-Object System.Collections.Generic.List[string]
$runner = Join-Path $PSScriptRoot 'invoke-deepseek-workspace.ps1'
$workspaceParent = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$testRoot = Join-Path $workspaceParent ('.sswcenter-runner-contract-' + [guid]::NewGuid().ToString('N'))
$checkpoint = ''
$script:ExternalCheckpoints = New-Object System.Collections.Generic.List[string]

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Name
    )
    $script:Total++
    if ($Condition) {
        $script:Passed++
    }
    else {
        $script:Failed++
        [void]$script:Failures.Add($Name)
    }
}

function Assert-Equal {
    param(
        [object]$Actual,
        [object]$Expected,
        [string]$Name
    )
    Assert-True ([string]$Actual -eq [string]$Expected) ($Name + ' expected=' + $Expected + ' actual=' + $Actual)
}

function Write-TestText {
    param(
        [string]$Path,
        [string]$Text
    )
    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory)) {
        [System.IO.Directory]::CreateDirectory($directory) | Out-Null
    }
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $encoding)
}

function Read-TestText {
    param([string]$Path)
    return [System.IO.File]::ReadAllText($Path)
}

function New-ExternalCheckpoint {
    param([string]$Label)
    $path = Join-Path $workspaceParent ('.sswcenter-runner-' + $Label + '-' + [guid]::NewGuid().ToString('N') + '.json')
    [void]$script:ExternalCheckpoints.Add($path)
    return $path
}

function New-ToolCall {
    param(
        [string]$Id,
        [string]$Name,
        [object]$Arguments
    )
    $fn = [ordered]@{
        name = $Name
        arguments = (ConvertTo-Json $Arguments -Depth 20 -Compress)
    }
    return [ordered]@{
        id = $Id
        type = 'function'
        function = $fn
    }
}

function New-Response {
    param(
        [object]$Message,
        [int]$PromptTokens = 100,
        [int]$CompletionTokens = 10,
        [switch]$WithoutUsage,
        [string]$FinishReason = 'tool_calls'
    )
    $response = [ordered]@{
        choices = @([ordered]@{
            message = $Message
            finish_reason = $FinishReason
        })
    }
    if (-not $WithoutUsage) {
        $response.usage = [ordered]@{
            prompt_tokens = $PromptTokens
            completion_tokens = $CompletionTokens
        }
    }
    return $response
}

function Save-Responses {
    param(
        [string]$Path,
        [object[]]$Responses
    )
    Write-TestText $Path (($Responses | ConvertTo-Json -Depth 50))
}

function Invoke-Runner {
    param(
        [string]$Root,
        [ValidateSet('ReadOnly', 'Writer')]
        [string]$RunMode = 'ReadOnly',
        [string[]]$Allow = @(),
        [string[]]$Read = @(),
        [string]$PromptText = 'contract test',
        [string]$ResponsesPath = '',
        [string]$Checkpoint = '',
        [string]$Resume = '',
        [string]$Task = '',
        [int]$Turns = 48,
        [int]$Tokens = 0,
        [ValidateSet('Auto', 'ReplaceText', 'ApplyPatch')]
        [string]$Strategy = 'Auto',
        [switch]$Offline,
        [switch]$WithoutJson,
        [switch]$Dry,
        [switch]$Direct,
        [int]$ExpectedBytes = -1,
        [int]$MaxReadToolCalls = 0
    )
    $processArgs = @(
        '-NoProfile',
        '-NonInteractive',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        $runner,
        '-RepositoryRoot',
        $Root,
        '-Mode',
        $RunMode,
        '-Prompt',
        $PromptText,
        '-MaxTurns',
        [string]$Turns
    )
    if ($MaxReadToolCalls -gt 0) {
        $processArgs += '-MaxReadToolCalls'
        $processArgs += [string]$MaxReadToolCalls
    }
    # Pass multi-path allow/read lists as a single comma-joined argument so external
    # powershell.exe -File binding forms a string[] without positional spill.
    if ($Allow.Count -gt 0) {
        $processArgs += '-AllowPath'
        $processArgs += ($Allow -join ',')
    }
    if ($Read.Count -gt 0) {
        $processArgs += '-ReadPath'
        $processArgs += ($Read -join ',')
    }
    if ($Tokens -gt 0) {
        $processArgs += '-MaxTokens'
        $processArgs += [string]$Tokens
    }
    $processArgs += '-WriteStrategy'
    $processArgs += $Strategy
    if (-not $WithoutJson) {
        $processArgs += '-JsonOutput'
    }
    if ($Offline) {
        $processArgs += '-OfflineConfig'
    }
    if ($Dry) {
        $processArgs += '-DryRun'
    }
    if ($Direct) {
        $processArgs += '-DirectResponse'
    }
    if (-not [string]::IsNullOrWhiteSpace($ResponsesPath)) {
        $processArgs += '-TestMode'
        $processArgs += '-MockResponsesPath'
        $processArgs += $ResponsesPath
    }
    if (-not [string]::IsNullOrWhiteSpace($Checkpoint)) {
        $processArgs += '-CheckpointPath'
        $processArgs += $Checkpoint
    }
    if (-not [string]::IsNullOrWhiteSpace($Resume)) {
        $processArgs += '-Resume'
        $processArgs += $Resume
    }
    if (-not [string]::IsNullOrWhiteSpace($Task)) {
        $processArgs += '-TaskId'
        $processArgs += $Task
    }
    if ($RunMode -eq 'Writer') {
        $effectiveExpectedBytes = if ($ExpectedBytes -ge 0) { $ExpectedBytes } else { 16384 }
        $processArgs += '-ExpectedWriteBytes'
        $processArgs += [string]$effectiveExpectedBytes
    }
    $output = @(& powershell.exe @processArgs)
    $rc = $LASTEXITCODE
    $raw = ($output | ForEach-Object { [string]$_ }) -join ([Environment]::NewLine)
    $json = $null
    if (-not $WithoutJson) {
        try {
            $json = $raw | ConvertFrom-Json
        }
        catch {
            $json = $null
        }
    }
    return [pscustomobject]@{
        rc = $rc
        raw = $raw
        json = $json
    }
}

try {
    [System.IO.Directory]::CreateDirectory($testRoot) | Out-Null
    $runnerSource = Read-TestText $runner
    Assert-True (
        $runnerSource.Contains("`$response.PSObject.Properties['__runner_error']") -and
        $runnerSource.Contains("`$response.PSObject.Properties['__runner_detail']")
    ) 'optional model error properties are guarded under StrictMode'
    Assert-True (
        $runnerSource.Contains("`$Message.PSObject.Properties['tool_calls']") -and
        -not $runnerSource.Contains('assistant.tool_calls = @($Message.tool_calls)')
    ) 'assistant tool calls are normalized before replay to provider'
    Assert-True (
        $runnerSource.Contains('$ErrorRecord.ErrorDetails.Message') -and
        $runnerSource.Contains('API_MESSAGE=')
    ) 'structured provider error body is retained without exposing raw body'
    Assert-True (
        $runnerSource.Contains('System.Net.Http.HttpClient') -and
        $runnerSource.Contains('ReadAsStringAsync()') -and
        $runnerSource.Contains('Get-ProviderHttpErrorDetail')
    ) 'provider HTTP errors retain a structured response body on Windows PowerShell'
    Assert-True (
        $runnerSource.Contains("`$message.PSObject.Properties['tool_calls']") -and
        -not $runnerSource.Contains('if ($null -ne $message.tool_calls)')
    ) 'final response optional tool_calls is guarded under StrictMode'
    Assert-True (
        $runnerSource.Contains('Never send diff --git format') -and
        $runnerSource.Contains('apply_patch accepts one file only') -and
        $runnerSource.Contains('Readable paths are:') -and
        $runnerSource.Contains('Writable paths are:') -and
        $runnerSource.Contains('literal leading plus is encoded as ++')
    ) 'apply patch custom single-file format is explicit to model'
    $allowedFile = Join-Path $testRoot 'allowed.txt'
    $leadFile = Join-Path $testRoot 'leading.txt'
    $usageFile = Join-Path $testRoot 'usage.txt'
    $resumeFile = Join-Path $testRoot 'resume.txt'
    $patchFile = Join-Path $testRoot 'patch.txt'
    $readOnlyFile = Join-Path $testRoot 'read-only.txt'
    $checkpoint = Join-Path $workspaceParent ('.sswcenter-runner-checkpoint-' + [guid]::NewGuid().ToString('N') + '.json')
    [void]$script:ExternalCheckpoints.Add($checkpoint)
    $seqResponses = Join-Path $testRoot 'seq-responses.json'
    $extensionResponses = Join-Path $testRoot 'extension-responses.json'
    $leadingResponses = Join-Path $testRoot 'leading-responses.json'
    $usageResponses = Join-Path $testRoot 'usage-responses.json'
    $progressResponses = Join-Path $testRoot 'progress-responses.json'
    $resumeResponses = Join-Path $testRoot 'resume-responses.json'
    $contextResponses = Join-Path $testRoot 'context-responses.json'
    $duplicateResponses = Join-Path $testRoot 'duplicate-responses.json'
    $patchResponses = Join-Path $testRoot 'patch-responses.json'
    $missingAddResponses = Join-Path $testRoot 'missing-add-responses.json'
    $readOnlyReplaceResponses = Join-Path $testRoot 'read-only-replace-responses.json'
    $readOnlyPatchResponses = Join-Path $testRoot 'read-only-patch-responses.json'
    $plusAddResponses = Join-Path $testRoot 'plus-add-responses.json'
    $rawAddResponses = Join-Path $testRoot 'raw-add-responses.json'
    $markerPatchResponses = Join-Path $testRoot 'marker-patch-responses.json'
    $directResponses = Join-Path $testRoot 'direct-responses.json'
    $defaultTaskId = 'contract-default-checkpoint'
    $defaultCheckpointRoot = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::LocalApplicationData)
    $defaultCheckpoint = Join-Path $defaultCheckpointRoot ('SSWCenter\deepseek-runner\' + $defaultTaskId + '.checkpoint.json')
    [void]$script:ExternalCheckpoints.Add($defaultCheckpoint)

    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($runner, [ref]$tokens, [ref]$parseErrors) | Out-Null
    Assert-Equal $parseErrors.Count 0 'runner PowerShell AST'
    $runnerSource = Read-TestText $runner
    Assert-True (-not $runnerSource.Contains('run_commands')) 'no arbitrary shell tool'
    Assert-True (-not $runnerSource.Contains('Invoke-Expression')) 'no dynamic shell evaluation'
    Assert-True (-not $runnerSource.Contains('final_sha')) 'no commit-style final sha'
    Assert-True (-not $runnerSource.Contains("name = 'workspace_status'")) 'workspace status tool not exposed to new requests'

    $offline = Invoke-Runner -Root $testRoot -Offline
    Assert-Equal $offline.rc 0 'offline exit'
    Assert-True ($null -ne $offline.json) 'offline JSON'
    Assert-Equal $offline.json.status 'OFFLINE_CONFIG' 'offline status'
    Assert-Equal $offline.json.max_turns 48 'default 48 turns'
    Assert-Equal $offline.json.extension_size 8 'extension size'
    Assert-Equal $offline.json.checkpoint_turn 64 'checkpoint turn'
    Assert-Equal $offline.json.soft_turn 80 'soft turn'
    Assert-Equal $offline.json.hard_turn_limit 96 'hard turn'
    Assert-Equal $offline.json.provider_context_limit 1000000 'provider one million context'
    Assert-Equal $offline.json.context_soft_limit 850000 'context soft limit'
    Assert-Equal $offline.json.context_hard_limit 950000 'context hard limit'
    Assert-Equal $offline.json.output_reserve_tokens 32768 'default output reserve follows max tokens'
    Assert-Equal $offline.json.usable_context_tokens 917232 'default usable context'
    Assert-Equal $offline.json.base_head 'GIT_METADATA_UNAVAILABLE' 'git metadata unavailable marker'
    Assert-True ($null -eq $offline.json.workspace_diff_sha256) 'git diff unavailable is null'
    Assert-True ($offline.json.PSObject.Properties.Name -contains 'extensions_used') 'offline extensions field'
    Assert-True ($offline.json.PSObject.Properties.Name -contains 'no_progress_rounds') 'offline no progress field'
    Assert-True ($offline.json.PSObject.Properties.Name -contains 'latest_prompt_tokens') 'offline latest usage field'
    Assert-True ($offline.json.PSObject.Properties.Name -contains 'checkpoint_round') 'offline checkpoint field'
    Assert-True ($offline.json.PSObject.Properties.Name -contains 'elapsed_ms') 'offline elapsed field'
    Assert-True ($offline.json.PSObject.Properties.Name -contains 'request_durations_ms') 'offline request durations field'
    Assert-Equal $offline.json.committed $false 'offline committed false'

    Assert-True ($offline.json.PSObject.Properties.Name -contains 'expected_write_bytes') 'offline expected_write_bytes field'
    Assert-True ($offline.json.PSObject.Properties.Name -contains 'effective_expected_write_bytes') 'offline effective_expected_write_bytes field'
    Assert-True ($offline.json.PSObject.Properties.Name -contains 'writer_budget_source') 'offline writer_budget_source field'

    $offlineMaxOutput = Invoke-Runner -Root $testRoot -Offline -Tokens 32768
    Assert-Equal $offlineMaxOutput.json.output_reserve_tokens 32768 'maximum output reserve follows max tokens'
    Assert-Equal $offlineMaxOutput.json.usable_context_tokens 917232 'maximum-output usable context'

    $gitHashRoot = Join-Path $testRoot 'git-diff-hash'
    [System.IO.Directory]::CreateDirectory($gitHashRoot) | Out-Null
    & git -C $gitHashRoot init --quiet
    if ($LASTEXITCODE -ne 0) { throw 'git init failed for runner contract' }
    Write-TestText (Join-Path $gitHashRoot 'tracked.txt') 'tracked'
    & git -C $gitHashRoot add -- tracked.txt
    if ($LASTEXITCODE -ne 0) { throw 'git add failed for runner contract' }
    $gitHashBefore = Invoke-Runner `
        -Root $gitHashRoot `
        -RunMode Writer `
        -Allow @('new.txt') `
        -Offline
    Assert-True ($null -ne $gitHashBefore.json.workspace_diff_sha256) 'git diff hash available'
    Write-TestText (Join-Path $gitHashRoot 'new.txt') 'first-untracked-content'
    $gitHashAfterAdd = Invoke-Runner `
        -Root $gitHashRoot `
        -RunMode Writer `
        -Allow @('new.txt') `
        -Offline
    Assert-True (
        $gitHashBefore.json.workspace_diff_sha256 -ne
            $gitHashAfterAdd.json.workspace_diff_sha256
    ) 'untracked add changes workspace diff hash'
    Write-TestText (Join-Path $gitHashRoot 'new.txt') 'second-untracked-content'
    $gitHashAfterEdit = Invoke-Runner `
        -Root $gitHashRoot `
        -RunMode Writer `
        -Allow @('new.txt') `
        -Offline
    Assert-True (
        $gitHashAfterAdd.json.workspace_diff_sha256 -ne
            $gitHashAfterEdit.json.workspace_diff_sha256
    ) 'untracked content changes workspace diff hash'

    $directCheckpoint = New-ExternalCheckpoint 'direct'
    Save-Responses $directResponses @(
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'DIRECT_OK'; tool_calls = @() }) -FinishReason 'stop')
    )
    $directRun = Invoke-Runner -Root $testRoot -ResponsesPath $directResponses -Checkpoint $directCheckpoint -Turns 1 -Direct
    Assert-Equal $directRun.rc 0 'direct response exit'
    Assert-Equal $directRun.json.status 'PASS' 'direct response status'
    Assert-Equal $directRun.json.response 'DIRECT_OK' 'direct response body'
    Assert-Equal $directRun.json.direct_response $true 'direct response marker'
    Assert-Equal $directRun.json.thinking_mode 'disabled' 'direct response thinking disabled'
    Assert-Equal $directRun.json.tools_enabled $false 'direct response tools disabled'
    Assert-Equal $directRun.json.checkpoint_saved $false 'direct response checkpoint skipped'
    Assert-True (-not (Test-Path -LiteralPath $directCheckpoint)) 'direct response checkpoint absent'

    $directWriter = Invoke-Runner -Root $testRoot -RunMode Writer -ResponsesPath $directResponses -Turns 1 -Direct
    Assert-Equal $directWriter.rc 1 'direct writer rejected'
    Assert-True ($directWriter.json.errors.code -contains 'DIRECT_RESPONSE_READONLY_ONLY') 'direct writer error'

    $directAllow = Invoke-Runner -Root $testRoot -Allow @('allowed.txt') -ResponsesPath $directResponses -Turns 1 -Direct
    Assert-Equal $directAllow.rc 1 'direct allowlist rejected'
    Assert-True ($directAllow.json.errors.code -contains 'DIRECT_RESPONSE_ALLOWLIST_NOT_ALLOWED') 'direct allowlist error'

    $directRead = Invoke-Runner `
        -Root $testRoot `
        -Read @('allowed.txt') `
        -ResponsesPath $directResponses `
        -Turns 1 `
        -Direct
    Assert-Equal $directRead.rc 1 'direct read path rejected'
    Assert-True (
        $directRead.json.errors.code -contains 'DIRECT_RESPONSE_ALLOWLIST_NOT_ALLOWED'
    ) 'direct read path error'

    $missingEnv = Invoke-Runner -Root $testRoot -Allow @('allowed.txt') -PromptText 'pre-network' -Turns 1
    Assert-Equal $missingEnv.rc 1 'missing env exit'
    Assert-Equal $missingEnv.json.status 'FAIL' 'missing env status'
    Assert-True ($missingEnv.json.errors.code -contains 'DEEPSEEK_API_KEY_MISSING') 'missing env no network'
    Assert-Equal $missingEnv.json.request_count 0 'missing env request count'

    $writerNoAllow = Invoke-Runner -Root $testRoot -RunMode Writer -PromptText 'writer allowlist'
    Assert-Equal $writerNoAllow.rc 1 'writer allowlist exit'
    Assert-True ($writerNoAllow.json.errors.code -contains 'WRITER_ALLOWLIST_REQUIRED') 'writer allowlist required'

    $sensitive = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('.env') -Offline
    Assert-Equal $sensitive.rc 1 'sensitive allowlist exit'
    Assert-True ($sensitive.json.errors.code -contains 'ALLOWLIST_SENSITIVE_PATH') 'sensitive allowlist denied'

    $exampleEnv = Join-Path $testRoot '.env.example'
    Write-TestText $exampleEnv 'PUBLIC_PLACEHOLDER=CHANGE_ME'
    $publicExample = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('.env.example') -Offline
    Assert-Equal $publicExample.rc 0 'root env example allowlist exit'
    Assert-Equal $publicExample.json.status 'OFFLINE_CONFIG' 'root env example allowlisted'

    $reparseRepo = Join-Path $testRoot 'reparse-repo'
    $reparseTarget = Join-Path $testRoot 'reparse-target'
    [System.IO.Directory]::CreateDirectory($reparseRepo) | Out-Null
    [System.IO.Directory]::CreateDirectory($reparseTarget) | Out-Null
    Write-TestText (Join-Path $reparseTarget 'reference.txt') 'outside-repository-root'
    $junctionPath = Join-Path $reparseRepo 'escape'
    New-Item -ItemType Junction -Path $junctionPath -Target $reparseTarget -Force | Out-Null
    try {
        $reparseRun = Invoke-Runner `
            -Root $reparseRepo `
            -RunMode Writer `
            -Allow @('escape\new.txt') `
            -Offline
        Assert-Equal $reparseRun.rc 1 'junction path rejected'
        Assert-True (
            $reparseRun.json.errors.code -contains 'PATH_REPARSE_POINT_FORBIDDEN'
        ) 'junction error code'
        Assert-True (
            -not (Test-Path -LiteralPath (Join-Path $reparseTarget 'new.txt'))
        ) 'junction target not written'
    }
    finally {
        if (Test-Path -LiteralPath $junctionPath) {
            [System.IO.Directory]::Delete($junctionPath)
        }
    }

    Write-TestText $allowedFile 'alpha'
    Write-TestText $readOnlyFile 'reference-only'
    $readOnlyReplace = @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'ro-read' 'read_file' ([ordered]@{
                path = 'read-only.txt'
            })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'ro-write' 'replace_text' ([ordered]@{
                path = 'read-only.txt'
                old_text = 'reference-only'
                new_text = 'forbidden'
            })))
        }))
    )
    Save-Responses $readOnlyReplaceResponses $readOnlyReplace
    $readOnlyCheckpoint = New-ExternalCheckpoint 'read-only-replace'
    $readOnlyRun = Invoke-Runner `
        -Root $testRoot `
        -RunMode Writer `
        -Allow @('allowed.txt') `
        -Read @('read-only.txt') `
        -ResponsesPath $readOnlyReplaceResponses `
        -Checkpoint $readOnlyCheckpoint `
        -Turns 4
    Assert-Equal $readOnlyRun.rc 2 'read-only replace rejected'
    Assert-True (
        $readOnlyRun.json.errors.code -contains 'PATH_NOT_WRITE_ALLOWLISTED'
    ) 'read-only replace error code'
    Assert-Equal (Read-TestText $readOnlyFile) 'reference-only' 'read-only replace preserves file'
    Assert-True ($readOnlyRun.json.read_paths -contains 'read-only.txt') 'read path reported'
    Assert-True ($readOnlyRun.json.read_paths -contains 'allowed.txt') 'write path is readable'
    Assert-True ($readOnlyRun.json.write_paths -contains 'allowed.txt') 'write path reported'
    Assert-True (-not ($readOnlyRun.json.write_paths -contains 'read-only.txt')) 'read-only excluded from writes'
    $readOnlyCheckpointRaw = Read-TestText $readOnlyCheckpoint
    Assert-True ($readOnlyCheckpointRaw.Contains('"read_paths"')) 'checkpoint seals read paths'
    Assert-True ($readOnlyCheckpointRaw.Contains('"write_paths"')) 'checkpoint seals write paths'

    $readOnlyPatchText = [string]::Join([Environment]::NewLine, @(
        '*** Begin Patch'
        '*** Update File: read-only.txt'
        '@@'
        '-reference-only'
        '+forbidden'
        '*** End Patch'
    ))
    Save-Responses $readOnlyPatchResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'ro-patch' 'apply_patch' ([ordered]@{
                patch = $readOnlyPatchText
            })))
        }))
    )
    $readOnlyPatchRun = Invoke-Runner `
        -Root $testRoot `
        -RunMode Writer `
        -Allow @('allowed.txt') `
        -Read @('read-only.txt') `
        -ResponsesPath $readOnlyPatchResponses `
        -Checkpoint (New-ExternalCheckpoint 'read-only-patch') `
        -Turns 2 -Strategy ApplyPatch
    Assert-Equal $readOnlyPatchRun.rc 2 'read-only apply patch rejected'
    Assert-True (
        $readOnlyPatchRun.json.errors.code -contains 'PATH_NOT_WRITE_ALLOWLISTED'
    ) 'read-only patch error code'
    Assert-Equal (Read-TestText $readOnlyFile) 'reference-only' 'read-only patch preserves file'

    Write-TestText $allowedFile 'alpha'
    $seq = @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            reasoning_content = 'reasoning stays in history'
            tool_calls = @((New-ToolCall 'r1' 'read_file' ([ordered]@{ path = 'allowed.txt' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'w1' 'replace_text' ([ordered]@{ path = 'allowed.txt'; old_text = 'alpha'; new_text = 'beta' })))
        })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'completed'; tool_calls = @() }) -PromptTokens 200 -FinishReason 'stop')
    )
    Save-Responses $seqResponses $seq
    $seqRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('allowed.txt') -ResponsesPath $seqResponses -Checkpoint $checkpoint -Turns 4
    Assert-Equal $seqRun.rc 0 'sequential exit'
    Assert-Equal $seqRun.json.status 'PASS' 'sequential status'
    Assert-Equal (Read-TestText $allowedFile) 'beta' 'sequential write'
    Assert-Equal $seqRun.json.tool_calls 2 'sequential tool count'
    Assert-Equal $seqRun.json.tool_calls_by_name.read_file 1 'read tool count'
    Assert-Equal $seqRun.json.tool_calls_by_name.replace_text 1 'write tool count'
    Assert-Equal $seqRun.json.tool_call_sequence[0].name 'read_file' 'first tool order'
    Assert-Equal $seqRun.json.tool_call_sequence[1].name 'replace_text' 'second tool order'
    Assert-Equal $seqRun.json.edit_count 1 'edit count'
    Assert-Equal $seqRun.json.latest_prompt_tokens 200 'latest usage is latest response'
    Assert-Equal $seqRun.json.cumulative_prompt_tokens 400 'cumulative usage is reporting only'
    Assert-True ($seqRun.json.changed_paths -contains 'allowed.txt') 'changed path'
    Assert-True $seqRun.json.checkpoint_saved 'write checkpoint'
    $checkpointRaw = Read-TestText $checkpoint
    Assert-True (
        $checkpointRaw.Contains('Readable paths are: allowed.txt.') -and
        $checkpointRaw.Contains('Writable paths are: allowed.txt.')
    ) 'separate path policies included in initial system message'
    Assert-True ($checkpointRaw.Contains('reasoning stays in history')) 'reasoning checkpoint preservation'
    Assert-True (-not $checkpointRaw.Contains('sk-secret-token')) 'checkpoint secret redaction'
    $tempCheckpointFiles = @(Get-ChildItem -LiteralPath ([System.IO.Path]::GetDirectoryName($checkpoint)) -Filter '*.tmp' -ErrorAction SilentlyContinue)
    Assert-Equal $tempCheckpointFiles.Count 0 'checkpoint temp cleanup'

    Write-TestText $allowedFile 'alpha'
    $defaultRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('allowed.txt') -ResponsesPath $seqResponses -Task $defaultTaskId -Turns 4
    Assert-Equal $defaultRun.rc 0 'default checkpoint exit'
    Assert-True $defaultRun.json.checkpoint_saved 'default checkpoint saved'
    Assert-True (Test-Path -LiteralPath $defaultCheckpoint -PathType Leaf) 'default checkpoint location'

    Write-TestText $patchFile 'one'
    $patchText = [string]::Join([Environment]::NewLine, @(
        '*** Begin Patch'
        '*** Update File: patch.txt'
        '@@'
        '-one'
        '+two'
        '*** End Patch'
    ))
    $patchResponsesValue = @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'p-read' 'read_file' ([ordered]@{ path = 'patch.txt' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'p1' 'apply_patch' ([ordered]@{ patch = $patchText })))
        })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'patch complete'; tool_calls = @() }) -FinishReason 'stop')
    )
    Save-Responses $patchResponses $patchResponsesValue
    $patchRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('patch.txt') -ResponsesPath $patchResponses -Checkpoint (New-ExternalCheckpoint 'patch') -Turns 4 -Strategy ApplyPatch
    Assert-Equal $patchRun.rc 0 'apply patch exit'
    Assert-Equal (Read-TestText $patchFile) 'two' 'apply patch write'
    Assert-Equal $patchRun.json.patch_count 1 'apply patch count'

    $missingAddText = [string]::Join([Environment]::NewLine, @(
        '*** Begin Patch'
        '*** Add File: new-file.txt'
        '+created'
        '*** End Patch'
    ))
    $missingAddResponsesValue = @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'missing-read' 'read_file' ([ordered]@{ path = 'new-file.txt' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'missing-add' 'apply_patch' ([ordered]@{ patch = $missingAddText })))
        })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'add complete'; tool_calls = @() }) -FinishReason 'stop')
    )
    Save-Responses $missingAddResponses $missingAddResponsesValue
    $missingAddRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('new-file.txt') -ResponsesPath $missingAddResponses -Checkpoint (New-ExternalCheckpoint 'missing-add') -Turns 5 -Strategy ApplyPatch
    Assert-Equal $missingAddRun.rc 0 'missing allowlisted file can be created'
    Assert-Equal (Read-TestText (Join-Path $testRoot 'new-file.txt')) 'created' 'missing file add content'
    Assert-Equal $missingAddRun.json.patch_count 1 'missing file add patch count'

    $plusAddText = [string]::Join([Environment]::NewLine, @(
        '*** Begin Patch'
        '*** Add File: plus-file.txt'
        '++literal-plus'
        '+plain'
        '*** End Patch'
    ))
    Save-Responses $plusAddResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'plus-add-read' 'read_file' ([ordered]@{
                path = 'plus-file.txt'
            })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'plus-add-write' 'apply_patch' ([ordered]@{
                patch = $plusAddText
            })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = 'plus add complete'
            tool_calls = @()
        }) -FinishReason 'stop')
    )
    $plusAddRun = Invoke-Runner `
        -Root $testRoot `
        -RunMode Writer `
        -Allow @('plus-file.txt') `
        -ResponsesPath $plusAddResponses `
        -Checkpoint (New-ExternalCheckpoint 'plus-add') `
        -Turns 5 -Strategy ApplyPatch
    Assert-Equal $plusAddRun.rc 0 'literal plus add exit'
    Assert-Equal (
        Read-TestText (Join-Path $testRoot 'plus-file.txt')
    ) ('+literal-plus' + [Environment]::NewLine + 'plain') 'literal plus add round trip'

    $rawAddText = [string]::Join([Environment]::NewLine, @(
        '*** Begin Patch'
        '*** Add File: raw-file.txt'
        'raw-without-prefix'
        '*** End Patch'
    ))
    Save-Responses $rawAddResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'raw-add' 'apply_patch' ([ordered]@{
                patch = $rawAddText
            })))
        }))
    )
    $rawAddRun = Invoke-Runner `
        -Root $testRoot `
        -RunMode Writer `
        -Allow @('raw-file.txt') `
        -ResponsesPath $rawAddResponses `
        -Checkpoint (New-ExternalCheckpoint 'raw-add') `
        -Turns 2 -Strategy ApplyPatch
    Assert-Equal $rawAddRun.rc 2 'raw add line rejected'
    Assert-True (
        $rawAddRun.json.errors.code -contains 'PATCH_ADD_LINE_PREFIX_REQUIRED'
    ) 'raw add error code'
    Assert-True (-not (Test-Path -LiteralPath (Join-Path $testRoot 'raw-file.txt'))) 'raw add absent'

    $markerPatchText = [string]::Join([Environment]::NewLine, @(
        '*** Begin Patch'
        '*** Update File: patch.txt'
        '@@'
        '-two'
        '+three'
        '*** Bogus Marker'
        '*** End Patch'
    ))
    Save-Responses $markerPatchResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'marker-patch' 'apply_patch' ([ordered]@{
                patch = $markerPatchText
            })))
        }))
    )
    $markerPatchRun = Invoke-Runner `
        -Root $testRoot `
        -RunMode Writer `
        -Allow @('patch.txt') `
        -ResponsesPath $markerPatchResponses `
        -Checkpoint (New-ExternalCheckpoint 'marker-patch') `
        -Turns 2 -Strategy ApplyPatch
    Assert-Equal $markerPatchRun.rc 2 'marker-like update line rejected'
    Assert-True (
        $markerPatchRun.json.errors.code -contains 'PATCH_UPDATE_MARKER_INVALID'
    ) 'marker-like update error code'
    Assert-Equal (Read-TestText $patchFile) 'two' 'marker-like update preserves file'

    Write-TestText $allowedFile 'alpha'
    $extension = @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'e-read' 'read_file' ([ordered]@{ path = 'allowed.txt' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'e1' 'replace_text' ([ordered]@{ path = 'allowed.txt'; old_text = 'alpha'; new_text = 'extended' })))
        })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'extended complete'; tool_calls = @() }) -FinishReason 'stop')
    )
    Save-Responses $extensionResponses $extension
    $extensionRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('allowed.txt') -ResponsesPath $extensionResponses -Checkpoint (New-ExternalCheckpoint 'extension') -Turns 2
    Assert-Equal $extensionRun.rc 0 'extension exit'
    Assert-Equal $extensionRun.json.extensions_used 1 'eight turn extension'
    Assert-Equal $extensionRun.json.effective_max_turns 10 'extended effective limit'

    Write-TestText $leadFile 'original'
    $leading = @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @(
                (New-ToolCall 'bad' 'read_file' ([ordered]@{ path = 'missing.txt' })),
                (New-ToolCall 'must-not-write' 'replace_text' ([ordered]@{ path = 'leading.txt'; old_text = 'original'; new_text = 'changed' }))
            )
        }))
    )
    Save-Responses $leadingResponses $leading
    $leadingRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('leading.txt') -ResponsesPath $leadingResponses -Checkpoint (New-ExternalCheckpoint 'leading') -Turns 2
    Assert-Equal $leadingRun.rc 2 'leading failure exit'
    Assert-Equal $leadingRun.json.status 'PARTIAL' 'leading failure status'
    Assert-True $leadingRun.json.leading_tool_failure 'leading failure marker'
    Assert-Equal $leadingRun.json.tool_calls 1 'leading failure stops later tool'
    Assert-True ($null -eq $leadingRun.json.tool_calls_by_name.replace_text) 'leading failure no write call'
    Assert-Equal (Read-TestText $leadFile) 'original' 'leading failure preserves file'

    Write-TestText $usageFile 'unchanged'
    $usage = @(
        (New-Response -WithoutUsage -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'u1' 'replace_text' ([ordered]@{ path = 'usage.txt'; old_text = 'unchanged'; new_text = 'changed' })))
        }))
    )
    Save-Responses $usageResponses $usage
    $usageRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('usage.txt') -ResponsesPath $usageResponses -Checkpoint (New-ExternalCheckpoint 'usage') -Turns 2
    Assert-Equal $usageRun.rc 1 'unknown usage exit'
    Assert-True ($usageRun.json.errors.code -contains 'CONTEXT_USAGE_UNKNOWN') 'unknown usage fail closed'
    Assert-Equal $usageRun.json.edit_count 0 'unknown usage no write'
    Assert-Equal (Read-TestText $usageFile) 'unchanged' 'unknown usage preserves file'

    Write-TestText $usageFile 'context-safe'
    $context = @(
        (New-Response -PromptTokens 940000 -CompletionTokens 0 -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'c1' 'replace_text' ([ordered]@{ path = 'usage.txt'; old_text = 'context-safe'; new_text = 'must-not-write' })))
        }))
    )
    Save-Responses $contextResponses $context
    $contextRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('usage.txt') -ResponsesPath $contextResponses -Checkpoint (New-ExternalCheckpoint 'context') -Turns 2
    Assert-Equal $contextRun.rc 1 'context hard exit'
    Assert-True ($contextRun.json.errors.code -contains 'CONTEXT_HARD_LIMIT_REACHED') 'context hard fail closed'
    Assert-Equal $contextRun.json.edit_count 0 'context hard no write'
    Assert-Equal (Read-TestText $usageFile) 'context-safe' 'context hard preserves file'

    # --- output budget / limit contracts (runner 2.4) ---

    Assert-Equal $offline.json.minimum_writer_output_tokens 8192 'offline minimum writer output tokens'

    $outputBudgetRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('allowed.txt') -Offline -Tokens 8191
    Assert-Equal $outputBudgetRun.rc 1 'writer output budget too low exit'
    Assert-True ($outputBudgetRun.json.errors.code -contains 'WRITER_OUTPUT_BUDGET_TOO_LOW') 'writer output budget error code'
    Assert-Equal $outputBudgetRun.json.request_count 0 'writer output budget no requests'
    Assert-Equal $outputBudgetRun.json.edit_count 0 'writer output budget no edits'

    $outputBudgetReadOnly = Invoke-Runner -Root $testRoot -Offline -Tokens 3000
    Assert-Equal $outputBudgetReadOnly.rc 0 'readonly low output exit'
    Assert-Equal $outputBudgetReadOnly.json.status 'OFFLINE_CONFIG' 'readonly low output status'

    $outputLimitBeforeResponses = Join-Path $testRoot 'output-limit-before-responses.json'
    Save-Responses $outputLimitBeforeResponses @(
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'ok'; tool_calls = @() }) -FinishReason 'length')
    )
    $outputLimitBeforeRun = Invoke-Runner -Root $testRoot -ResponsesPath $outputLimitBeforeResponses -Checkpoint (New-ExternalCheckpoint 'output-limit-before') -Turns 2
    Assert-Equal $outputLimitBeforeRun.rc 1 'output limit before edit exit'
    Assert-True ($outputLimitBeforeRun.json.errors.code -contains 'OUTPUT_LIMIT_BEFORE_EDIT') 'output limit before edit error code'
    Assert-Equal $outputLimitBeforeRun.json.stop_reason 'OUTPUT_LIMIT_BEFORE_EDIT' 'output limit before edit stop reason'
    Assert-Equal $outputLimitBeforeRun.json.edit_count 0 'output limit before edit no edits'

    $outputLimitFile = Join-Path $testRoot 'output-limit.txt'
    Write-TestText $outputLimitFile 'before'
    $outputLimitAfterResponses = Join-Path $testRoot 'output-limit-after-responses.json'
    Save-Responses $outputLimitAfterResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'ola-read' 'read_file' ([ordered]@{ path = 'output-limit.txt' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'ola-edit' 'replace_text' ([ordered]@{ path = 'output-limit.txt'; old_text = 'before'; new_text = 'after' })))
        })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'done'; tool_calls = @() }) -FinishReason 'length')
    )
    $outputLimitAfterRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('output-limit.txt') -ResponsesPath $outputLimitAfterResponses -Checkpoint (New-ExternalCheckpoint 'output-limit-after') -Turns 4
    Assert-Equal $outputLimitAfterRun.rc 2 'output limit after edit exit'
    Assert-Equal $outputLimitAfterRun.json.status 'PARTIAL_AFTER_EDIT' 'output limit after edit status'
    Assert-True ($outputLimitAfterRun.json.errors.code -contains 'OUTPUT_LIMIT_AFTER_EDIT') 'output limit after edit error code'
    Assert-Equal $outputLimitAfterRun.json.stop_reason 'OUTPUT_LIMIT_AFTER_EDIT' 'output limit after edit stop reason'
    Assert-Equal $outputLimitAfterRun.json.edit_count 1 'output limit after edit count'
    Assert-Equal (Read-TestText $outputLimitFile) 'after' 'output limit after edit preserves file'

    Write-TestText $allowedFile 'before-malformed'
    $outputLimitMalformedResponses = Join-Path $testRoot 'output-limit-malformed-responses.json'
    $malformedToolCall = [ordered]@{
        id = 'malformed-1'
        type = 'function'
        function = [ordered]@{
            name = 'replace_text'
            arguments = '{bad'
        }
    }
    Save-Responses $outputLimitMalformedResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @($malformedToolCall)
        }) -FinishReason 'length')
    )
    $outputLimitMalformedCheckpoint = New-ExternalCheckpoint 'output-limit-malformed'
    $outputLimitMalformedRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('allowed.txt') -ResponsesPath $outputLimitMalformedResponses -Checkpoint $outputLimitMalformedCheckpoint -Turns 2
    Assert-Equal $outputLimitMalformedRun.rc 1 'output limit during tool call exit'
    Assert-Equal $outputLimitMalformedRun.json.status 'FAIL' 'output limit during tool call status'
    Assert-True ($outputLimitMalformedRun.json.errors.code -contains 'OUTPUT_LIMIT_DURING_TOOL_CALL') 'output limit during tool call error code'
    Assert-Equal $outputLimitMalformedRun.json.stop_reason 'OUTPUT_LIMIT_DURING_TOOL_CALL' 'output limit during tool call stop reason'
    Assert-Equal $outputLimitMalformedRun.json.tool_calls 0 'output limit during tool call tool count'
    Assert-Equal $outputLimitMalformedRun.json.read_tool_calls 0 'output limit during tool call read count'
    Assert-Equal $outputLimitMalformedRun.json.tool_call_sequence.Count 0 'output limit during tool call sequence count'
    Assert-Equal $outputLimitMalformedRun.json.edit_count 0 'output limit during tool call no edits'
    Assert-Equal $outputLimitMalformedRun.json.patch_count 0 'output limit during tool call no patches'
    Assert-Equal (Read-TestText $allowedFile) 'before-malformed' 'output limit during tool call preserves file'
    Assert-True (-not (Read-TestText $outputLimitMalformedCheckpoint).Contains('malformed-1')) 'output limit during tool call omits rejected assistant batch'

    # A. A valid replace_text in a length-truncated turn is rejected before batch accounting or execution.
    $outputLimitAtomicFile = Join-Path $testRoot 'output-limit-atomic.txt'
    Write-TestText $outputLimitAtomicFile 'atomic-before'
    $outputLimitAtomicResponses = Join-Path $testRoot 'output-limit-atomic-responses.json'
    Save-Responses $outputLimitAtomicResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'ola-safe-read' 'read_file' ([ordered]@{ path = 'output-limit-atomic.txt' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'ola-length-edit' 'replace_text' ([ordered]@{ path = 'output-limit-atomic.txt'; old_text = 'atomic-before'; new_text = 'atomic-after' })))
        }) -FinishReason 'length')
    )
    $outputLimitAtomicCheckpoint = New-ExternalCheckpoint 'output-limit-atomic'
    $outputLimitAtomicRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('output-limit-atomic.txt') -ResponsesPath $outputLimitAtomicResponses -Checkpoint $outputLimitAtomicCheckpoint -Turns 3 -Strategy ReplaceText
    Assert-Equal $outputLimitAtomicRun.rc 1 'valid replace length batch exit'
    Assert-Equal $outputLimitAtomicRun.json.status 'FAIL' 'valid replace length batch status'
    Assert-True ($outputLimitAtomicRun.json.errors.code -contains 'OUTPUT_LIMIT_DURING_TOOL_CALL') 'valid replace length batch error code'
    Assert-Equal $outputLimitAtomicRun.json.stop_reason 'OUTPUT_LIMIT_DURING_TOOL_CALL' 'valid replace length batch stop reason'
    Assert-Equal $outputLimitAtomicRun.json.tool_calls 1 'valid replace length batch preserves prior tool count only'
    Assert-Equal $outputLimitAtomicRun.json.read_tool_calls 1 'valid replace length batch preserves prior read count only'
    Assert-Equal $outputLimitAtomicRun.json.tool_call_sequence.Count 1 'valid replace length batch preserves prior sequence only'
    Assert-Equal $outputLimitAtomicRun.json.tool_call_sequence[0].name 'read_file' 'valid replace length batch prior read remains'
    Assert-True ($null -eq $outputLimitAtomicRun.json.tool_calls_by_name.replace_text) 'valid replace length batch write not counted'
    Assert-Equal $outputLimitAtomicRun.json.edit_count 0 'valid replace length batch no edits'
    Assert-Equal $outputLimitAtomicRun.json.patch_count 0 'valid replace length batch no patches'
    Assert-Equal (Read-TestText $outputLimitAtomicFile) 'atomic-before' 'valid replace length batch preserves file'
    Assert-True (-not (Read-TestText $outputLimitAtomicCheckpoint).Contains('ola-length-edit')) 'valid replace length batch omitted from checkpoint conversation'

    # B. A valid apply_patch in a length-truncated turn cannot create a new file.
    $outputLimitPatchFile = Join-Path $testRoot 'output-limit-new.txt'
    $outputLimitPatchResponses = Join-Path $testRoot 'output-limit-patch-responses.json'
    $outputLimitNewPatch = "*** Begin Patch`r`n*** Add File: output-limit-new.txt`r`n+created`r`n*** End Patch"
    Save-Responses $outputLimitPatchResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'olp-length-patch' 'apply_patch' ([ordered]@{ patch = $outputLimitNewPatch })))
        }) -FinishReason 'length')
    )
    $outputLimitPatchCheckpoint = New-ExternalCheckpoint 'output-limit-patch'
    $outputLimitPatchRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('output-limit-new.txt') -ResponsesPath $outputLimitPatchResponses -Checkpoint $outputLimitPatchCheckpoint -Turns 2 -Strategy ApplyPatch -ExpectedBytes 4096
    Assert-Equal $outputLimitPatchRun.rc 1 'valid patch length batch exit'
    Assert-Equal $outputLimitPatchRun.json.status 'FAIL' 'valid patch length batch status'
    Assert-True ($outputLimitPatchRun.json.errors.code -contains 'OUTPUT_LIMIT_DURING_TOOL_CALL') 'valid patch length batch error code'
    Assert-Equal $outputLimitPatchRun.json.stop_reason 'OUTPUT_LIMIT_DURING_TOOL_CALL' 'valid patch length batch stop reason'
    Assert-Equal $outputLimitPatchRun.json.tool_calls 0 'valid patch length batch tool count'
    Assert-Equal $outputLimitPatchRun.json.read_tool_calls 0 'valid patch length batch read count'
    Assert-Equal $outputLimitPatchRun.json.tool_call_sequence.Count 0 'valid patch length batch sequence count'
    Assert-Equal $outputLimitPatchRun.json.edit_count 0 'valid patch length batch no edits'
    Assert-Equal $outputLimitPatchRun.json.patch_count 0 'valid patch length batch no patches'
    Assert-True (-not (Test-Path -LiteralPath $outputLimitPatchFile)) 'valid patch length batch does not create file'
    Assert-True (-not (Read-TestText $outputLimitPatchCheckpoint).Contains('olp-length-patch')) 'valid patch length batch omitted from checkpoint conversation'

    # C. A mixed length-truncated batch is rejected before even its first valid read executes.
    Write-TestText $allowedFile 'before-mixed-length'
    $outputLimitMixedResponses = Join-Path $testRoot 'output-limit-mixed-responses.json'
    $mixedLengthMalformedCall = [ordered]@{
        id = 'olm-truncated-write'
        type = 'function'
        function = [ordered]@{
            name = 'replace_text'
            arguments = '{"path":"allowed.txt","old_text":"before-mixed-length"'
        }
    }
    Save-Responses $outputLimitMixedResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @(
                (New-ToolCall 'olm-valid-read' 'read_file' ([ordered]@{ path = 'allowed.txt' })),
                $mixedLengthMalformedCall
            )
        }) -FinishReason 'length')
    )
    $outputLimitMixedCheckpoint = New-ExternalCheckpoint 'output-limit-mixed'
    $outputLimitMixedRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('allowed.txt') -ResponsesPath $outputLimitMixedResponses -Checkpoint $outputLimitMixedCheckpoint -Turns 2 -Strategy ReplaceText
    Assert-Equal $outputLimitMixedRun.rc 1 'mixed length batch exit'
    Assert-Equal $outputLimitMixedRun.json.status 'FAIL' 'mixed length batch status'
    Assert-True ($outputLimitMixedRun.json.errors.code -contains 'OUTPUT_LIMIT_DURING_TOOL_CALL') 'mixed length batch error code'
    Assert-Equal $outputLimitMixedRun.json.stop_reason 'OUTPUT_LIMIT_DURING_TOOL_CALL' 'mixed length batch stop reason'
    Assert-Equal $outputLimitMixedRun.json.tool_calls 0 'mixed length batch tool count'
    Assert-Equal $outputLimitMixedRun.json.read_tool_calls 0 'mixed length batch read count'
    Assert-Equal $outputLimitMixedRun.json.tool_call_sequence.Count 0 'mixed length batch sequence count'
    Assert-Equal $outputLimitMixedRun.json.edit_count 0 'mixed length batch no edits'
    Assert-Equal $outputLimitMixedRun.json.patch_count 0 'mixed length batch no patches'
    Assert-Equal (Read-TestText $allowedFile) 'before-mixed-length' 'mixed length batch preserves file'
    $outputLimitMixedCheckpointRaw = Read-TestText $outputLimitMixedCheckpoint
    Assert-True (-not $outputLimitMixedCheckpointRaw.Contains('olm-valid-read')) 'mixed length batch omits valid read from checkpoint conversation'
    Assert-True (-not $outputLimitMixedCheckpointRaw.Contains('olm-truncated-write')) 'mixed length batch omits truncated write from checkpoint conversation'

    # E. finish_reason=stop still permits normal read/write tool turns.
    $outputStopFile = Join-Path $testRoot 'output-stop.txt'
    Write-TestText $outputStopFile 'stop-before'
    $outputStopResponses = Join-Path $testRoot 'output-stop-responses.json'
    Save-Responses $outputStopResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'os-read' 'read_file' ([ordered]@{ path = 'output-stop.txt' })))
        }) -FinishReason 'stop'),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'os-write' 'replace_text' ([ordered]@{ path = 'output-stop.txt'; old_text = 'stop-before'; new_text = 'stop-after' })))
        }) -FinishReason 'stop'),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'stop complete'; tool_calls = @() }) -FinishReason 'stop')
    )
    $outputStopRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('output-stop.txt') -ResponsesPath $outputStopResponses -Checkpoint (New-ExternalCheckpoint 'output-stop') -Turns 4 -Strategy ReplaceText
    Assert-Equal $outputStopRun.rc 0 'stop tool turns exit'
    Assert-Equal $outputStopRun.json.status 'PASS' 'stop tool turns status'
    Assert-Equal $outputStopRun.json.tool_calls 2 'stop tool turns count'
    Assert-Equal $outputStopRun.json.read_tool_calls 1 'stop tool turns read count'
    Assert-Equal $outputStopRun.json.tool_call_sequence.Count 2 'stop tool turns sequence count'
    Assert-Equal $outputStopRun.json.edit_count 1 'stop tool turns edit count'
    Assert-Equal $outputStopRun.json.patch_count 0 'stop tool turns patch count'
    Assert-Equal (Read-TestText $outputStopFile) 'stop-after' 'stop tool turns final text'

    # --- atomic tool preflight contracts (runner 2.4) ---

    # 1. Missing required argument
    $missingArgResponses = Join-Path $testRoot 'missing-arg-responses.json'
    Save-Responses $missingArgResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'ma1' 'read_file' ([ordered]@{})))
        }))
    )
    $missingArgRun = Invoke-Runner -Root $testRoot -Read @('allowed.txt') -ResponsesPath $missingArgResponses -Checkpoint (New-ExternalCheckpoint 'missing-arg') -Turns 2
    Assert-Equal $missingArgRun.rc 2 'missing required argument exit'
    Assert-True ($missingArgRun.json.errors.code -contains 'TOOL_ARGUMENT_REQUIRED') 'missing required argument error code'
    Assert-True (($missingArgRun.json.errors.detail | ForEach-Object { [string]$_ }) -match 'read_file\.path') 'missing required argument detail references path'
    Assert-Equal $missingArgRun.json.tool_call_sequence.Count 1 'missing required argument sequence count'
    Assert-Equal $missingArgRun.json.tool_call_sequence[0].ok $false 'missing required argument sequence item not ok'
    Assert-Equal $missingArgRun.json.edit_count 0 'missing required argument no edits'

    # 2. Disallowed tool
    Write-TestText $allowedFile 'alpha'
    $disallowedResponses = Join-Path $testRoot 'disallowed-responses.json'
    Save-Responses $disallowedResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'dt1' 'delete_file' ([ordered]@{ path = 'allowed.txt' })))
        }))
    )
    $disallowedRun = Invoke-Runner -Root $testRoot -Read @('allowed.txt') -ResponsesPath $disallowedResponses -Checkpoint (New-ExternalCheckpoint 'disallowed') -Turns 2
    Assert-Equal $disallowedRun.rc 2 'disallowed tool exit'
    Assert-True ($disallowedRun.json.errors.code -contains 'TOOL_NOT_ALLOWED') 'disallowed tool error code'
    Assert-Equal $disallowedRun.json.tool_call_sequence.Count 1 'disallowed tool sequence count'
    Assert-Equal $disallowedRun.json.tool_call_sequence[0].ok $false 'disallowed tool sequence item not ok'
    Assert-Equal $disallowedRun.json.edit_count 0 'disallowed tool no edits'
    Assert-Equal (Read-TestText $allowedFile) 'alpha' 'disallowed tool preserves file'

    # 3. Atomic mixed batch: valid read first, disallowed delete second
    $mixedResponses = Join-Path $testRoot 'mixed-responses.json'
    Save-Responses $mixedResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @(
                (New-ToolCall 'mx-read' 'read_file' ([ordered]@{ path = 'allowed.txt' })),
                (New-ToolCall 'mx-del' 'delete_file' ([ordered]@{ path = 'allowed.txt' }))
            )
        }))
    )
    $mixedCheckpoint = New-ExternalCheckpoint 'mixed'
    $mixedRun = Invoke-Runner -Root $testRoot -Read @('allowed.txt') -ResponsesPath $mixedResponses -Checkpoint $mixedCheckpoint -Turns 2
    Assert-Equal $mixedRun.rc 2 'atomic mixed batch exit'
    Assert-True ($mixedRun.json.errors.code -contains 'TOOL_NOT_ALLOWED') 'atomic mixed batch primary error'
    Assert-Equal $mixedRun.json.tool_call_sequence.Count 2 'atomic mixed batch sequence count'
    Assert-Equal $mixedRun.json.tool_call_sequence[0].name 'read_file' 'atomic mixed batch first tool name'
    Assert-Equal $mixedRun.json.tool_call_sequence[1].name 'delete_file' 'atomic mixed batch second tool name'
    Assert-Equal $mixedRun.json.tool_call_sequence[0].ok $false 'atomic mixed batch first item not ok'
    Assert-Equal $mixedRun.json.tool_call_sequence[1].ok $false 'atomic mixed batch second item not ok'
    Assert-Equal $mixedRun.json.edit_count 0 'atomic mixed batch no edits'
    $mixedCheckpointRaw = Read-TestText $mixedCheckpoint
    Assert-True ($mixedCheckpointRaw.Contains('TOOL_NOT_ALLOWED')) 'atomic mixed batch checkpoint contains error'

    # 4. Multiple-write atomic rejection
    $multiDirectory = Join-Path $testRoot 'multi'
    $multiA = Join-Path $multiDirectory 'multi-a.txt'
    $multiB = Join-Path $multiDirectory 'multi-b.txt'
    Write-TestText $multiA 'a0'
    Write-TestText $multiB 'b0'
    $multiWriteResponses = Join-Path $testRoot 'multi-write-responses.json'
    Save-Responses $multiWriteResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @(
                (New-ToolCall 'mw-a' 'replace_text' ([ordered]@{ path = 'multi\\multi-a.txt'; old_text = 'a0'; new_text = 'a1' })),
                (New-ToolCall 'mw-b' 'replace_text' ([ordered]@{ path = 'multi\\multi-b.txt'; old_text = 'b0'; new_text = 'b1' }))
            )
        }))
    )
    $multiWriteRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('multi') -ResponsesPath $multiWriteResponses -Checkpoint (New-ExternalCheckpoint 'multi-write') -Turns 2 -Strategy ReplaceText
    Assert-Equal $multiWriteRun.rc 2 'multiple write atomic rejection exit'
    Assert-True ($multiWriteRun.json.errors.code -contains 'MULTIPLE_WRITE_TOOLS_PER_TURN') 'multiple write atomic rejection error code'
    Assert-Equal $multiWriteRun.json.tool_call_sequence.Count 2 'multiple write atomic rejection sequence count'
    Assert-Equal $multiWriteRun.json.tool_call_sequence[0].ok $false 'multiple write atomic rejection first item not ok'
    Assert-Equal $multiWriteRun.json.tool_call_sequence[1].ok $false 'multiple write atomic rejection second item not ok'
    Assert-Equal $multiWriteRun.json.edit_count 0 'multiple write atomic rejection no edits'
    Assert-Equal (Read-TestText $multiA) 'a0' 'multiple write atomic rejection preserves multi-a'
    Assert-Equal (Read-TestText $multiB) 'b0' 'multiple write atomic rejection preserves multi-b'

    # --- fresh-read recovery before first edit ---
    $freshFirstFile = Join-Path $testRoot 'fresh-first.txt'
    Write-TestText $freshFirstFile 'one'
    $freshFirstResponses = Join-Path $testRoot 'fresh-first-responses.json'
    Save-Responses $freshFirstResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'ff1' 'replace_text' ([ordered]@{ path = 'fresh-first.txt'; old_text = 'one'; new_text = 'two' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'ff2' 'read_file' ([ordered]@{ path = 'fresh-first.txt' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'ff3' 'replace_text' ([ordered]@{ path = 'fresh-first.txt'; old_text = 'one'; new_text = 'two' })))
        })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'fresh-first complete'; tool_calls = @() }) -FinishReason 'stop')
    )
    $freshFirstRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('fresh-first.txt') -ResponsesPath $freshFirstResponses -Checkpoint (New-ExternalCheckpoint 'fresh-first') -Turns 6
    Assert-Equal $freshFirstRun.rc 0 'fresh-read recovery before first edit exit'
    Assert-Equal $freshFirstRun.json.status 'PASS' 'fresh-read recovery before first edit status'
    Assert-True ($freshFirstRun.json.warnings.code -contains 'WRITE_REQUIRES_FRESH_READ') 'fresh-read recovery before first edit warning'
    Assert-Equal $freshFirstRun.json.tool_call_sequence.Count 3 'fresh-read recovery before first edit sequence count'
    Assert-Equal $freshFirstRun.json.tool_call_sequence[0].ok $false 'fresh-read recovery before first edit first replace failed'
    Assert-Equal $freshFirstRun.json.tool_call_sequence[1].ok $true 'fresh-read recovery before first edit read succeeded'
    Assert-Equal $freshFirstRun.json.tool_call_sequence[2].ok $true 'fresh-read recovery before first edit second replace succeeded'
    Assert-Equal $freshFirstRun.json.edit_count 1 'fresh-read recovery before first edit edit count'
    Assert-Equal (Read-TestText $freshFirstFile) 'two' 'fresh-read recovery before first edit final text'

    # --- fresh-read recovery after a successful edit ---
    $freshSecondFile = Join-Path $testRoot 'fresh-second.txt'
    Write-TestText $freshSecondFile 'one'
    $freshSecondResponses = Join-Path $testRoot 'fresh-second-responses.json'
    Save-Responses $freshSecondResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'fs1' 'read_file' ([ordered]@{ path = 'fresh-second.txt' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'fs2' 'replace_text' ([ordered]@{ path = 'fresh-second.txt'; old_text = 'one'; new_text = 'two' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'fs3' 'replace_text' ([ordered]@{ path = 'fresh-second.txt'; old_text = 'two'; new_text = 'three' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'fs4' 'read_file' ([ordered]@{ path = 'fresh-second.txt' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'fs5' 'replace_text' ([ordered]@{ path = 'fresh-second.txt'; old_text = 'two'; new_text = 'three' })))
        })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'fresh-second complete'; tool_calls = @() }) -FinishReason 'stop')
    )
    $freshSecondRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('fresh-second.txt') -ResponsesPath $freshSecondResponses -Checkpoint (New-ExternalCheckpoint 'fresh-second') -Turns 8
    Assert-Equal $freshSecondRun.rc 0 'fresh-read recovery after edit exit'
    Assert-Equal $freshSecondRun.json.status 'PASS' 'fresh-read recovery after edit status'
    Assert-True ($freshSecondRun.json.warnings.code -contains 'WRITE_REQUIRES_FRESH_READ') 'fresh-read recovery after edit warning'
    Assert-Equal $freshSecondRun.json.edit_count 2 'fresh-read recovery after edit edit count'
    Assert-Equal (Read-TestText $freshSecondFile) 'three' 'fresh-read recovery after edit final text'

    # --- post-edit no-progress ---
    $postProgressFile = Join-Path $testRoot 'post-progress.txt'
    Write-TestText $postProgressFile 'before'
    $postProgressResponses = Join-Path $testRoot 'post-progress-responses.json'
    Save-Responses $postProgressResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'pp-read' 'read_file' ([ordered]@{ path = 'post-progress.txt' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'pp-edit' 'replace_text' ([ordered]@{ path = 'post-progress.txt'; old_text = 'before'; new_text = 'after' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'pp-s1' 'search_text' ([ordered]@{ pattern = 'q1' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'pp-s2' 'search_text' ([ordered]@{ pattern = 'q2' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'pp-s3' 'search_text' ([ordered]@{ pattern = 'q3' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'pp-s4' 'search_text' ([ordered]@{ pattern = 'q4' })))
        }))
    )
    $postProgressRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('post-progress.txt') -ResponsesPath $postProgressResponses -Checkpoint (New-ExternalCheckpoint 'post-progress') -Turns 10
    Assert-Equal $postProgressRun.rc 2 'post-edit no-progress exit'
    Assert-Equal $postProgressRun.json.status 'PARTIAL_AFTER_EDIT' 'post-edit no-progress status'
    Assert-True ($postProgressRun.json.warnings.code -contains 'POST_EDIT_NO_PROGRESS_WARNING') 'post-edit no-progress warning'
    Assert-True ($postProgressRun.json.errors.code -contains 'POST_EDIT_NO_PROGRESS_LIMIT_REACHED') 'post-edit no-progress error'
    Assert-Equal $postProgressRun.json.stop_reason 'POST_EDIT_NO_PROGRESS_LIMIT_REACHED' 'post-edit no-progress stop reason'
    Assert-Equal $postProgressRun.json.no_progress_rounds 4 'post-edit no-progress rounds'
    Assert-Equal $postProgressRun.json.edit_count 1 'post-edit no-progress edit count'
    Assert-Equal (Read-TestText $postProgressFile) 'after' 'post-edit no-progress final text'

    # --- Windows backslash and regex round trip ---
    $backslashFile = Join-Path $testRoot 'backslash.txt'
    Write-TestText $backslashFile 'backend\.venv\Scripts\python.exe and (\?|$)'
    $backslashResponses = Join-Path $testRoot 'backslash-responses.json'
    Save-Responses $backslashResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'bs-read' 'read_file' ([ordered]@{ path = 'backslash.txt' })))
        })),
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'bs-edit' 'replace_text' ([ordered]@{
                path = 'backslash.txt'
                old_text = 'backend\.venv\Scripts\python.exe and (\?|$)'
                new_text = 'backend\.venv\Scripts\python.exe and (\?|$) verified'
            })))
        })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'backslash complete'; tool_calls = @() }) -FinishReason 'stop')
    )
    $backslashRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('backslash.txt') -ResponsesPath $backslashResponses -Checkpoint (New-ExternalCheckpoint 'backslash') -Turns 5
    Assert-Equal $backslashRun.rc 0 'backslash round trip exit'
    Assert-Equal $backslashRun.json.status 'PASS' 'backslash round trip status'
    Assert-Equal $backslashRun.json.edit_count 1 'backslash round trip edit count'
    Assert-Equal (Read-TestText $backslashFile) 'backend\.venv\Scripts\python.exe and (\?|$) verified' 'backslash round trip final text'

    # --- TestMode redaction contract ---
    $redactionFile = Join-Path $testRoot 'redaction.txt'
    $redactionContent = [string]::Join([Environment]::NewLine, @(
        'password="DUMMY quoted value with spaces" trailing-context',
        "api_key='DUMMY single quoted value' trailing-context",
        'access-token=DUMMY-unquoted-value with trailing words',
        'Authorization: Bearer DUMMY-token-value trailing words',
        'standalone Bearer DUMMY.second-token_value',
        'standalone sk-DUMMYTOKEN123456',
        '{"password":"DUMMY json value with spaces","Authorization":"Bearer DUMMY-json-token","note":"safe"}',
        "Authorization: Bearer DUMMY-multiline-token`nsafe second line",
        'payload={\"password\":\"DUMMY escaped json value\",\"Authorization\":\"Bearer DUMMY-escaped-json-token\",\"note\":\"safe\"}'
    ))
    Write-TestText $redactionFile $redactionContent
    $forbiddenPayloads = @(
        'DUMMY quoted value with spaces',
        'DUMMY single quoted value',
        'DUMMY-unquoted-value',
        'DUMMY-token-value',
        'DUMMY.second-token_value',
        'sk-DUMMYTOKEN123456',
        'DUMMY json value with spaces',
        'DUMMY-json-token',
        'DUMMY-multiline-token',
        'DUMMY escaped json value',
        'DUMMY-escaped-json-token'
    )
    $redactionResponses = Join-Path $testRoot 'redaction-responses.json'
    Save-Responses $redactionResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'red-read' 'read_file' ([ordered]@{ path = 'redaction.txt' })))
        })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'redaction complete'; tool_calls = @() }) -FinishReason 'stop')
    )
    $redactionCheckpoint = New-ExternalCheckpoint 'redaction'
    $redactionRun = Invoke-Runner `
        -Root $testRoot `
        -Read @('redaction.txt') `
        -ResponsesPath $redactionResponses `
        -Checkpoint $redactionCheckpoint `
        -Turns 4
    Assert-Equal $redactionRun.rc 0 'redaction exit'
    Assert-Equal $redactionRun.json.status 'PASS' 'redaction status'
    Assert-True $redactionRun.json.checkpoint_saved 'redaction checkpoint saved'
    $redactionCheckpointRaw = Read-TestText $redactionCheckpoint
    for ($i = 0; $i -lt $forbiddenPayloads.Count; $i++) {
        Assert-True (-not $redactionRun.raw.Contains($forbiddenPayloads[$i])) "redaction raw forbids payload index $i"
        Assert-True (-not $redactionCheckpointRaw.Contains($forbiddenPayloads[$i])) "redaction checkpoint raw forbids payload index $i"
    }
    Assert-True $redactionCheckpointRaw.Contains('[REDACTED]') 'redaction checkpoint raw contains [REDACTED]'
    $redactionCheckpointJson = $redactionCheckpointRaw | ConvertFrom-Json
    $lastToolMessage = $redactionCheckpointJson.messages | Where-Object { $_.role -eq 'tool' } | Select-Object -Last 1
    $lastToolContentJson = $lastToolMessage.content | ConvertFrom-Json
    $redactedFileText = $lastToolContentJson.content
    Assert-True $redactedFileText.Contains('[REDACTED]') 'redacted tool content contains [REDACTED]'
    $redactedLines = $redactedFileText -split [Environment]::NewLine
    $jsonLine = $redactedLines | Where-Object { $_.StartsWith('{') } | Select-Object -First 1
    $parsedJson = $jsonLine | ConvertFrom-Json
    Assert-Equal $parsedJson.password '[REDACTED]' 'redacted nested JSON password'
    Assert-Equal $parsedJson.Authorization '[REDACTED]' 'redacted nested JSON Authorization'
    Assert-Equal $parsedJson.note 'safe' 'redacted nested JSON note preserved'
    $escapedJsonLine = $redactedLines | Where-Object { $_.StartsWith('payload=') } | Select-Object -First 1
    $escapedJson = $escapedJsonLine.Substring('payload='.Length).Replace('\"', '"') | ConvertFrom-Json
    Assert-Equal $escapedJson.password '[REDACTED]' 'redacted escaped JSON password'
    Assert-Equal $escapedJson.Authorization '[REDACTED]' 'redacted escaped JSON Authorization'
    Assert-Equal $escapedJson.note 'safe' 'redacted escaped JSON note preserved'
    Assert-True $redactedFileText.Contains('safe second line') 'redacted tool content preserves safe second line'

    # --- DeepSeek-like technical review prose (regex/docs/safe markers) must checkpoint successfully ---
    # Second residual bug: escaped key-only fragments like \"secret\": in regex docs must not REDACTION_FAILED.
    $techReviewFile = Join-Path $testRoot 'tech-review-notes.txt'
    Write-TestText $techReviewFile "fixture for technical review notes only"
    $techReviewFinal = @'
Independent review PASS. No Critical/Major findings.

Safe markers present: [REDACTED], [REDACTED_CREDENTIAL_PATH], [REDACTED_ISOLATED_ROOT], Bearer [REDACTED].

Residual logic documents (not secret values):
$safeMarker = '\[REDACTED(?:_[A-Z0-9_]+)?\]'
negative lookahead (?!$safeMarker) and (?!\[REDACTED(?:_[A-Z0-9_]+)?\])
token-shaped bare value(sk-/eyJ/20+)
pattern fragments in source: sk-[A-Za-z0-9_-]{8,} and eyJ[A-Za-z0-9._=-]+
escaped key fragment examples in docs: \"secret\": and \"password\": without values
escaped JSON builder: (?<prefix>\\+"(?:authorization|api[_-]?key|access[_-]?token|secret|password)\\+"\s*[:=]\s*)

Already-safe example assignment: secret: "[REDACTED]"
Discusses refresh token lifecycle and OAuth invalid_grant without raw values.
Environment names only: CLAUDE_CONFIG_DIR, CLAUDE_CODE_FORCE_WINDOWS_CREDMAN, USERPROFILE.
access_token residual check is a pattern name, not a credential.
'@
    $techReviewResponses = Join-Path $testRoot 'tech-review-responses.json'
    Save-Responses $techReviewResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'tr-read' 'read_file' ([ordered]@{ path = 'tech-review-notes.txt' })))
        })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = $techReviewFinal; tool_calls = @() }) -FinishReason 'stop')
    )
    $techReviewCheckpoint = New-ExternalCheckpoint 'tech-review'
    $techReviewRun = Invoke-Runner `
        -Root $testRoot `
        -Read @('tech-review-notes.txt') `
        -ResponsesPath $techReviewResponses `
        -Checkpoint $techReviewCheckpoint `
        -Turns 4
    Assert-equal $techReviewRun.rc 0 'tech-review exit'
    Assert-equal $techReviewRun.json.status 'PASS' 'tech-review status'
    Assert-True $techReviewRun.json.checkpoint_saved 'tech-review checkpoint saved'
    Assert-equal $techReviewRun.json.checkpoint_integrity 'ATOMIC_WRITE_ATTEMPTED' 'tech-review checkpoint integrity'
    Assert-equal (@($techReviewRun.json.errors).Count) 0 'tech-review errors empty'
    Assert-True (-not ($techReviewRun.json.errors.code -contains 'REDACTION_FAILED')) 'tech-review no REDACTION_FAILED'
    Assert-True (-not ($techReviewRun.json.errors.code -contains 'CHECKPOINT_WRITE_FAILED')) 'tech-review no CHECKPOINT_WRITE_FAILED'
    $techReviewCheckpointRaw = Read-TestText $techReviewCheckpoint
    Assert-True $techReviewCheckpointRaw.Contains('[REDACTED]') 'tech-review checkpoint keeps safe markers'
    Assert-True (
        $techReviewCheckpointRaw.Contains('invalid_grant') -or
        $techReviewCheckpointRaw.Contains('safeMarker')
    ) 'tech-review checkpoint keeps technical prose'
    Assert-True (
        ([string]$techReviewRun.json.response).Contains('[REDACTED_CREDENTIAL_PATH]') -or
        $techReviewRun.raw.Contains('[REDACTED_CREDENTIAL_PATH]')
    ) 'tech-review response keeps credential path marker'

    # --- Per-type raw dummy secret negative contracts (each type: raw absent, marker present) ---
    $secretTypeCases = @(
        [pscustomobject]@{ Label = 'bearer'; File = 'type-bearer.txt'; Body = 'Authorization: Bearer DUMMY.TYPE.BEARER_TOKEN_VALUE_001'; Forbidden = @('DUMMY.TYPE.BEARER_TOKEN_VALUE_001') },
        [pscustomobject]@{ Label = 'sk'; File = 'type-sk.txt'; Body = 'standalone sk-DUMMYTYPETOKEN1234567890ABCD'; Forbidden = @('sk-DUMMYTYPETOKEN1234567890ABCD') },
        [pscustomobject]@{ Label = 'jwt'; File = 'type-jwt.txt'; Body = 'token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.DUMMY_TYPE_PAYLOAD.DUMMY_TYPE_SIG'; Forbidden = @('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.DUMMY_TYPE_PAYLOAD.DUMMY_TYPE_SIG') },
        [pscustomobject]@{ Label = 'quoted'; File = 'type-quoted.txt'; Body = 'secret="quoted-dummy-type-secret-value-xyz"'; Forbidden = @('quoted-dummy-type-secret-value-xyz') },
        [pscustomobject]@{ Label = 'nested-json'; File = 'type-nested.txt'; Body = '{"accessToken":"atk_dummy_type_nested_001","refreshToken":"rtk_dummy_type_nested_002","note":"safe"}'; Forbidden = @('atk_dummy_type_nested_001', 'rtk_dummy_type_nested_002') },
        [pscustomobject]@{ Label = 'escaped-json'; File = 'type-escaped.txt'; Body = 'payload={\"password\":\"DUMMY type escaped secret value\",\"Authorization\":\"Bearer DUMMY-type-escaped-token\",\"note\":\"safe\"}'; Forbidden = @('DUMMY type escaped secret value', 'DUMMY-type-escaped-token') },
        [pscustomobject]@{ Label = 'named-token'; File = 'type-named-token.txt'; Body = '{"token":"DUMMY32CHAR_NAMED_TOKEN_VALUE_ABCDEF012345","note":"safe-named"}'; Forbidden = @('DUMMY32CHAR_NAMED_TOKEN_VALUE_ABCDEF012345') }
    )
    foreach ($case in $secretTypeCases) {
        $casePath = Join-Path $testRoot $case.File
        Write-TestText $casePath $case.Body
        $caseResponses = Join-Path $testRoot ($case.Label + '-responses.json')
        Save-Responses $caseResponses @(
            (New-Response -Message ([ordered]@{
                role = 'assistant'
                content = $null
                tool_calls = @((New-ToolCall ('t-' + $case.Label) 'read_file' ([ordered]@{ path = $case.File })))
            })),
            (New-Response -Message ([ordered]@{ role = 'assistant'; content = ($case.Label + ' redaction complete'); tool_calls = @() }) -FinishReason 'stop')
        )
        $caseCheckpoint = New-ExternalCheckpoint ('type-' + $case.Label)
        $caseRun = Invoke-Runner `
            -Root $testRoot `
            -Read @($case.File) `
            -ResponsesPath $caseResponses `
            -Checkpoint $caseCheckpoint `
            -Turns 4
        Assert-equal $caseRun.rc 0 ("type-$($case.Label) exit")
        Assert-equal $caseRun.json.status 'PASS' ("type-$($case.Label) status")
        Assert-True $caseRun.json.checkpoint_saved ("type-$($case.Label) checkpoint saved")
        $caseCpRaw = Read-TestText $caseCheckpoint
        foreach ($forbidden in $case.Forbidden) {
            Assert-True (-not $caseRun.raw.Contains($forbidden)) ("type-$($case.Label) raw forbids secret")
            Assert-True (-not $caseCpRaw.Contains($forbidden)) ("type-$($case.Label) checkpoint forbids secret")
        }
        Assert-True $caseCpRaw.Contains('[REDACTED]') ("type-$($case.Label) checkpoint has marker")
    }

    # --- Checkpoint write failure must not leave PASS/exit 0 ---
    $cpFailFile = Join-Path $testRoot 'checkpoint-fail.txt'
    Write-TestText $cpFailFile 'checkpoint fail target'
    $cpFailResponses = Join-Path $testRoot 'checkpoint-fail-responses.json'
    Save-Responses $cpFailResponses @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall 'cf-read' 'read_file' ([ordered]@{ path = 'checkpoint-fail.txt' })))
        })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'checkpoint fail complete'; tool_calls = @() }) -FinishReason 'stop')
    )
    $cpFailDir = Join-Path $workspaceParent ('.sswcenter-runner-cpfail-' + [guid]::NewGuid().ToString('N'))
    [void][System.IO.Directory]::CreateDirectory($cpFailDir)
    # File path where a directory is required for atomic write parent, or unwritable leaf:
    # Use a checkpoint path whose parent is a file (not a directory) to force write failure.
    $cpFailParentFile = Join-Path $cpFailDir 'not-a-directory'
    Write-TestText $cpFailParentFile 'parent is a file'
    $cpFailPath = Join-Path $cpFailParentFile 'child.checkpoint.json'
    [void]$script:ExternalCheckpoints.Add($cpFailPath)
    $cpFailRun = Invoke-Runner `
        -Root $testRoot `
        -Read @('checkpoint-fail.txt') `
        -ResponsesPath $cpFailResponses `
        -Checkpoint $cpFailPath `
        -Turns 4
    Assert-True ($cpFailRun.rc -ne 0) 'checkpoint write fail nonzero exit'
    Assert-True ($cpFailRun.json.status -ne 'PASS') 'checkpoint write fail not PASS'
    Assert-equal $cpFailRun.json.checkpoint_saved $false 'checkpoint write fail not saved'
    Assert-equal $cpFailRun.json.checkpoint_integrity 'FAIL' 'checkpoint write fail integrity FAIL'
    Assert-True ($cpFailRun.json.errors.code -contains 'CHECKPOINT_WRITE_FAILED') 'checkpoint write fail error code'
    Assert-True (
        $cpFailRun.json.stop_reason -eq 'CHECKPOINT_WRITE_FAILED' -or
        $cpFailRun.json.errors.code -contains 'CHECKPOINT_WRITE_FAILED'
    ) 'checkpoint write fail stop or error'


    # Writer: edit-start deadline still fail-closed after 6 no-edit rounds
    $progressMessages = New-Object System.Collections.Generic.List[object]
    foreach ($term in @('p1', 'p2', 'p3', 'p4', 'p5', 'p6')) {
        [void]$progressMessages.Add((New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall ('s-' + $term) 'search_text' ([ordered]@{ pattern = $term })))
        })))
    }
    Save-Responses $progressResponses @($progressMessages.ToArray())
    $progressRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('allowed.txt') -ResponsesPath $progressResponses -Checkpoint (New-ExternalCheckpoint 'progress') -Turns 12
    Assert-Equal $progressRun.rc 1 'writer no progress exit'
    Assert-True ($progressRun.json.errors.code -contains 'EDIT_START_DEADLINE_REACHED') 'writer no progress stop'
    Assert-True ($progressRun.json.warnings.code -contains 'EDIT_START_DEADLINE_WARNING') 'writer no progress warning'
    Assert-equal $progressRun.json.no_progress_rounds 6 'writer no progress rounds'
    Assert-equal $progressRun.json.mode 'Writer' 'writer no progress mode'

    # ReadOnly: 18 multi-turn reads with zero edits must PASS (edit-start deadline does not apply)
    $roFiles = New-Object System.Collections.Generic.List[string]
    $roReadMessages = New-Object System.Collections.Generic.List[object]
    for ($ri = 1; $ri -le 18; $ri++) {
        $roName = ('ro-file-{0:d2}.txt' -f $ri)
        $roPath = Join-Path $testRoot $roName
        Write-TestText $roPath ("readonly content $ri")
        [void]$roFiles.Add($roName)
        [void]$roReadMessages.Add((New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            tool_calls = @((New-ToolCall ('ro-read-' + $ri) 'read_file' ([ordered]@{ path = $roName })))
        })))
    }
    [void]$roReadMessages.Add((New-Response -Message ([ordered]@{
        role = 'assistant'
        content = 'ReadOnly multi-file review PASS after 18 reads; no edits required.'
        tool_calls = @()
    }) -FinishReason 'stop'))
    $roResponses = Join-Path $testRoot 'readonly-multiread-responses.json'
    Save-Responses $roResponses @($roReadMessages.ToArray())
    $roCheckpoint = New-ExternalCheckpoint 'readonly-multiread'
    $roRun = Invoke-Runner `
        -Root $testRoot `
        -RunMode ReadOnly `
        -Read @($roFiles.ToArray()) `
        -ResponsesPath $roResponses `
        -Checkpoint $roCheckpoint `
        -Turns 24 `
        -MaxReadToolCalls 32
    Assert-equal $roRun.rc 0 'readonly multiread exit'
    Assert-equal $roRun.json.status 'PASS' 'readonly multiread status'
    Assert-equal $roRun.json.mode 'ReadOnly' 'readonly multiread mode'
    Assert-equal $roRun.json.edit_count 0 'readonly multiread zero edits'
    Assert-equal $roRun.json.write_paths.Count 0 'readonly multiread empty write_paths'
    Assert-True ($roRun.json.read_tool_calls -ge 18) 'readonly multiread at least 18 reads'
    Assert-True ($roRun.json.turns_used -ge 18) 'readonly multiread many turns'
    Assert-True $roRun.json.checkpoint_saved 'readonly multiread checkpoint saved'
    Assert-equal $roRun.json.checkpoint_integrity 'ATOMIC_WRITE_ATTEMPTED' 'readonly multiread checkpoint integrity'
    Assert-equal (@($roRun.json.errors).Count) 0 'readonly multiread errors empty'
    Assert-True (-not ($roRun.json.errors.code -contains 'EDIT_START_DEADLINE_REACHED')) 'readonly multiread no edit-start error'
    Assert-True (-not ($roRun.json.warnings.code -contains 'EDIT_START_DEADLINE_WARNING')) 'readonly multiread no edit-start warning'
    Assert-equal $roRun.json.stop_reason 'MODEL_COMPLETED' 'readonly multiread stop MODEL_COMPLETED'
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$roRun.json.response)) 'readonly multiread non-empty response'

    $duplicate = @(
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = $null; tool_calls = @((New-ToolCall 'd1' 'search_text' ([ordered]@{ pattern = 'same' }))) })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = $null; tool_calls = @((New-ToolCall 'd2' 'search_text' ([ordered]@{ pattern = 'same' }))) })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = $null; tool_calls = @((New-ToolCall 'd3' 'search_text' ([ordered]@{ pattern = 'same' }))) }))
    )
    Save-Responses $duplicateResponses $duplicate
    $duplicateRun = Invoke-Runner -Root $testRoot -Allow @('allowed.txt') -ResponsesPath $duplicateResponses -Checkpoint (New-ExternalCheckpoint 'duplicate') -Turns 8
    Assert-Equal $duplicateRun.rc 1 'duplicate exit'
    Assert-True ($duplicateRun.json.warnings.code -contains 'DUPLICATE_TOOL_BATCH') 'duplicate warning'
    Assert-True ($duplicateRun.json.errors.code -contains 'DUPLICATE_TOOL_CALLS') 'duplicate stop'

    Write-TestText $resumeFile 'one'
    $resumeFirst = @(
        (New-Response -Message ([ordered]@{
            role = 'assistant'
            content = $null
            reasoning_content = 'readonly reasoning sk-secret-token-12345'
            tool_calls = @((New-ToolCall 's1' 'search_text' ([ordered]@{ pattern = 'one' })))
        }))
    )
    Save-Responses $resumeResponses $resumeFirst
    $resumeInitial = Invoke-Runner -Root $testRoot -Allow @('resume.txt') -ResponsesPath $resumeResponses -Checkpoint $checkpoint -Turns 1
    Assert-Equal $resumeInitial.rc 1 'resume checkpoint initial stop'
    Assert-True $resumeInitial.json.checkpoint_saved 'resume checkpoint saved'
    $resumeRaw = Read-TestText $checkpoint
    Assert-True ($resumeRaw.Contains('readonly reasoning')) 'ReadOnly reasoning checkpoint preservation'
    Assert-True (-not $resumeRaw.Contains('sk-secret-token-12345')) 'resume checkpoint redacts secret'
    Write-TestText $resumeFile 'changed-before-resume'
    $resumeMismatch = Invoke-Runner -Root $testRoot -Allow @('resume.txt') -ResponsesPath $resumeResponses -Resume $checkpoint -Turns 2
    Assert-Equal $resumeMismatch.rc 1 'resume fingerprint exit'
    Assert-True ($resumeMismatch.json.errors.code -contains 'CHECKPOINT_RESUME_FAILED') 'resume fingerprint fail closed'
    Write-TestText $resumeFile 'one'
    $resumeSecond = @(
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'resumed complete'; tool_calls = @() }) -FinishReason 'stop')
    )
    Save-Responses $resumeResponses $resumeSecond
    $resumeOk = Invoke-Runner -Root $testRoot -Allow @('resume.txt') -ResponsesPath $resumeResponses -Resume $checkpoint -Turns 2
    Assert-Equal $resumeOk.rc 0 'resume success exit'
    Assert-Equal $resumeOk.json.status 'PASS' 'resume success status'
    Assert-Equal $resumeOk.json.turns_used 2 'resume next turn'

    $tampered = $resumeRaw.Replace('"no_progress_rounds":  1', '"no_progress_rounds":  2')
    Write-TestText $checkpoint $tampered
    $hashMismatch = Invoke-Runner -Root $testRoot -Allow @('resume.txt') -ResponsesPath $resumeResponses -Resume $checkpoint -Turns 2
    Assert-Equal $hashMismatch.rc 1 'checkpoint hash exit'
    Assert-True ($hashMismatch.json.errors.code -contains 'CHECKPOINT_HASH_MISMATCH') 'checkpoint hash fail closed'
    Write-TestText $checkpoint $resumeRaw

    Write-TestText $checkpoint 'not-json'
    $corrupt = Invoke-Runner -Root $testRoot -Allow @('resume.txt') -ResponsesPath $resumeResponses -Resume $checkpoint -Turns 2
    Assert-Equal $corrupt.rc 1 'corrupt checkpoint exit'
    Assert-True ($corrupt.json.errors.code -contains 'CHECKPOINT_RESUME_FAILED') 'corrupt checkpoint fail closed'

    # --- Runner 2.5 write strategy contracts ---

    # Writer OfflineConfig Auto normal prompt resolves ReplaceText and exposes read_file/search_text/replace_text, never apply_patch
    $strategyAutoOffline = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('allowed.txt') -Offline -Strategy Auto -PromptText 'fix a typo in the file'
    Assert-Equal $strategyAutoOffline.rc 0 'strategy Auto offline exit'
    Assert-Equal $strategyAutoOffline.json.requested_write_strategy 'Auto' 'Auto requested write strategy'
    Assert-Equal $strategyAutoOffline.json.effective_write_strategy 'ReplaceText' 'Auto resolves ReplaceText'
    Assert-True ($strategyAutoOffline.json.exposed_tool_names -contains 'read_file') 'Auto exposed read_file'
    Assert-True ($strategyAutoOffline.json.exposed_tool_names -contains 'search_text') 'Auto exposed search_text'
    Assert-True ($strategyAutoOffline.json.exposed_tool_names -contains 'replace_text') 'Auto exposed replace_text'
    Assert-True (-not ($strategyAutoOffline.json.exposed_tool_names -contains 'apply_patch')) 'Auto never exposes apply_patch'

    # explicit ApplyPatch exposes read_file/search_text/apply_patch, never replace_text
    $strategyPatchOffline = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('allowed.txt') -Offline -Strategy ApplyPatch -PromptText 'add a new line'
    Assert-Equal $strategyPatchOffline.rc 0 'ApplyPatch offline exit'
    Assert-Equal $strategyPatchOffline.json.requested_write_strategy 'ApplyPatch' 'ApplyPatch requested'
    Assert-Equal $strategyPatchOffline.json.effective_write_strategy 'ApplyPatch' 'ApplyPatch effective'
    Assert-True ($strategyPatchOffline.json.exposed_tool_names -contains 'read_file') 'ApplyPatch exposed read_file'
    Assert-True ($strategyPatchOffline.json.exposed_tool_names -contains 'search_text') 'ApplyPatch exposed search_text'
    Assert-True ($strategyPatchOffline.json.exposed_tool_names -contains 'apply_patch') 'ApplyPatch exposed apply_patch'
    Assert-True (-not ($strategyPatchOffline.json.exposed_tool_names -contains 'replace_text')) 'ApplyPatch never exposes replace_text'

    # missing path + Korean prompt resolves ApplyPatch
    $strategyCreateOffline = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('korean-new-file.txt') -Offline -Strategy Auto -PromptText '새 파일 생성' -ExpectedBytes 4096
    Assert-Equal $strategyCreateOffline.rc 0 'Auto korean new file offline exit'
    Assert-Equal $strategyCreateOffline.json.effective_write_strategy 'ApplyPatch' 'Auto korean new file wording resolves ApplyPatch'

    # very large Writer prompt rejected with WRITER_PACKET_SPLIT_REQUIRED before any request
    $largePrompt = ([string][char]0xAC00) * 21000
    $packetSplitRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('allowed.txt') -Offline -PromptText $largePrompt
    Assert-Equal $packetSplitRun.rc 1 'packet split rejected exit'
    Assert-True ($packetSplitRun.json.errors.code -contains 'WRITER_PACKET_SPLIT_REQUIRED') 'packet split error code'
    Assert-Equal $packetSplitRun.json.request_count 0 'packet split no requests'

    # medium Writer prompt whose estimate exceeds MaxTokens=8192 is rejected with WRITER_OUTPUT_BUDGET_TOO_LOW
    $mediumPrompt = 'x' * 16000
    $mediumBudgetRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('allowed.txt') -Offline -PromptText $mediumPrompt -Tokens 8192
    Assert-Equal $mediumBudgetRun.rc 1 'medium prompt budget too low exit'
    Assert-True ($mediumBudgetRun.json.errors.code -contains 'WRITER_OUTPUT_BUDGET_TOO_LOW') 'medium prompt budget error code'
    Assert-Equal $mediumBudgetRun.json.request_count 0 'medium prompt budget no requests'

    # TestMode no-edit convergence: two no-edit search rounds enter forced-write mode
    $convergeFile = Join-Path $testRoot 'converge.txt'
    Write-TestText $convergeFile 'converge'
    $convergeResponses = Join-Path $testRoot 'converge-responses.json'
    Save-Responses $convergeResponses @(
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = $null; tool_calls = @((New-ToolCall 'cv-s1' 'search_text' ([ordered]@{ pattern = 'nomatch1' }))) })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = $null; tool_calls = @((New-ToolCall 'cv-s2' 'search_text' ([ordered]@{ pattern = 'nomatch2' }))) })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = $null; tool_calls = @((New-ToolCall 'cv-read' 'read_file' ([ordered]@{ path = 'converge.txt' }))) })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = $null; tool_calls = @((New-ToolCall 'cv-edit' 'replace_text' ([ordered]@{ path = 'converge.txt'; old_text = 'converge'; new_text = 'converged' }))) })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'convergence complete'; tool_calls = @() }) -FinishReason 'stop')
    )
    $convergeRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('converge.txt') -ResponsesPath $convergeResponses -Checkpoint (New-ExternalCheckpoint 'converge') -Turns 8 -Strategy Auto
    Assert-Equal $convergeRun.rc 0 'convergence exit'
    Assert-Equal $convergeRun.json.status 'PASS' 'convergence status'
    Assert-Equal $convergeRun.json.convergence_mode 'normal' 'convergence mode resets after successful edit'
    Assert-True ($convergeRun.json.warnings.code -contains 'EDIT_CONVERGENCE_MODE') 'convergence warning present'
    # The third exposure (turn 3, after forced-write) excludes search_text and unselected write tool, includes read_file and replace_text
    Assert-Equal $convergeRun.json.tool_exposure_history.Count 5 'convergence exposure history count'
    $forcedExposure = $convergeRun.json.tool_exposure_history[2]
    Assert-Equal $forcedExposure.turn 3 'forced-write exposure turn'
    Assert-True ($forcedExposure.names -contains 'read_file') 'forced-write includes read_file'
    Assert-True ($forcedExposure.names -contains 'replace_text') 'forced-write includes replace_text'
    Assert-True (-not ($forcedExposure.names -contains 'search_text')) 'forced-write excludes search_text'
    Assert-True (-not ($forcedExposure.names -contains 'apply_patch')) 'forced-write excludes unselected write tool'
    # turn 4 write-only exposure: exactly one name, replace_text only
    $turn4Exposure = $convergeRun.json.tool_exposure_history[3]
    Assert-Equal $turn4Exposure.turn 4 'convergence turn 4 exposure turn'
    Assert-Equal $turn4Exposure.names.Count 1 'convergence turn 4 exactly one exposed name'
    Assert-True ($turn4Exposure.names -contains 'replace_text') 'convergence turn 4 replace_text only'
    Assert-Equal $convergeRun.json.edit_count 1 'convergence edit count'
    Assert-Equal (Read-TestText $convergeFile) 'converged' 'convergence final text'

    # explicit ReplaceText run receiving the hidden wrong write tool fails closed with WRITER_TOOL_NOT_ALLOWED
    $wrongToolFile = Join-Path $testRoot 'wrong-tool.txt'
    Write-TestText $wrongToolFile 'before'
    $wrongToolResponses = Join-Path $testRoot 'wrong-tool-responses.json'
    Save-Responses $wrongToolResponses @(
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = $null; tool_calls = @((New-ToolCall 'wt-read' 'read_file' ([ordered]@{ path = 'wrong-tool.txt' }))) })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = $null; tool_calls = @((New-ToolCall 'wt-bad' 'apply_patch' ([ordered]@{ patch = "*** Begin Patch`r`n*** Update File: wrong-tool.txt`r`n@@`r`n-before`r`n+after`r`n*** End Patch" }))) }))
    )
    $wrongToolRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('wrong-tool.txt') -ResponsesPath $wrongToolResponses -Checkpoint (New-ExternalCheckpoint 'wrong-tool') -Turns 4 -Strategy ReplaceText
    Assert-Equal $wrongToolRun.rc 2 'wrong write tool exit'
    Assert-True ($wrongToolRun.json.errors.code -contains 'WRITER_TOOL_NOT_ALLOWED') 'wrong write tool error code'
    Assert-Equal $wrongToolRun.json.edit_count 0 'wrong write tool no edit'
    Assert-Equal (Read-TestText $wrongToolFile) 'before' 'wrong write tool preserves file'

    # exact replacement with old/new text each over 8 KiB succeeds under MaxTokens 32768
    $largeTextField = Join-Path $testRoot 'large-text.txt'
    $largeOldText = ('OLD' * 3000)
    $largeNewText = ('NEW' * 3000)
    Write-TestText $largeTextField $largeOldText
    $largeTextResponses = Join-Path $testRoot 'large-text-responses.json'
    Save-Responses $largeTextResponses @(
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = $null; tool_calls = @((New-ToolCall 'lt-read' 'read_file' ([ordered]@{ path = 'large-text.txt' }))) })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = $null; tool_calls = @((New-ToolCall 'lt-edit' 'replace_text' ([ordered]@{ path = 'large-text.txt'; old_text = $largeOldText; new_text = $largeNewText }))) })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'large text complete'; tool_calls = @() }) -FinishReason 'stop')
    )
    $largeTextRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('large-text.txt') -ResponsesPath $largeTextResponses -Checkpoint (New-ExternalCheckpoint 'large-text') -Turns 5 -Tokens 32768 -Strategy ReplaceText -ExpectedBytes 24000
    Assert-Equal $largeTextRun.rc 0 'large text replacement exit'
    Assert-Equal $largeTextRun.json.status 'PASS' 'large text replacement status'
    Assert-Equal $largeTextRun.json.edit_count 1 'large text replacement edit count'
    Assert-Equal (Read-TestText $largeTextField) $largeNewText 'large text replacement final text'
    Assert-Equal $largeTextRun.json.expected_write_bytes 24000 'large text expected_write_bytes'
    Assert-Equal $largeTextRun.json.effective_expected_write_bytes 24000 'large text effective_expected_write_bytes'
    Assert-Equal $largeTextRun.json.writer_budget_source 'explicit' 'large text writer_budget_source'
    Assert-True ($largeTextRun.json.estimated_writer_output_tokens -le 32768) 'large text estimate <= 32768'

    # A: missing target budget-missing.txt, Writer Auto Offline ExpectedBytes 0 => WRITER_PACKET_BUDGET_REQUIRED
    $testA = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('budget-missing.txt') -Offline -Strategy Auto -ExpectedBytes 0
    Assert-Equal $testA.rc 1 'A budget missing target exit'
    Assert-True ($testA.json.errors.code -contains 'WRITER_PACKET_BUDGET_REQUIRED') 'A budget missing target error code'
    Assert-Equal $testA.json.request_count 0 'A budget missing target request count'

    # B: create directory ambiguous-root, Writer Auto Allow ambiguous-root Offline ExpectedBytes 4096 => WRITER_WRITE_STRATEGY_REQUIRED
    $ambiguousDirB = Join-Path $testRoot 'ambiguous-root'
    [System.IO.Directory]::CreateDirectory($ambiguousDirB) | Out-Null
    $testB = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('ambiguous-root') -Offline -Strategy Auto -ExpectedBytes 4096
    Assert-Equal $testB.rc 1 'B ambiguous root exit'
    Assert-True ($testB.json.errors.code -contains 'WRITER_WRITE_STRATEGY_REQUIRED') 'B ambiguous root error code'
    Assert-Equal $testB.json.request_count 0 'B ambiguous root request count'

    # C: create exact file large-auto-budget.txt containing 20000 'x', Writer ReplaceText Offline ExpectedBytes 0 short prompt => WRITER_PACKET_BUDGET_REQUIRED
    $largeAutoBudgetFile = Join-Path $testRoot 'large-auto-budget.txt'
    Write-TestText $largeAutoBudgetFile ('x' * 20000)
    $testC = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('large-auto-budget.txt') -Offline -Strategy ReplaceText -ExpectedBytes 0 -PromptText 'fix'
    Assert-Equal $testC.rc 1 'C large auto budget exit'
    Assert-True ($testC.json.errors.code -contains 'WRITER_PACKET_BUDGET_REQUIRED') 'C large auto budget error code'
    Assert-Equal $testC.json.request_count 0 'C large auto budget request count'

    # D: existing allowed.txt, Writer ReplaceText Offline ExpectedBytes 30000 => WRITER_PACKET_SPLIT_REQUIRED
    $testD = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('allowed.txt') -Offline -Strategy ReplaceText -ExpectedBytes 30000
    Assert-Equal $testD.rc 1 'D allowed split required exit'
    Assert-True ($testD.json.errors.code -contains 'WRITER_PACKET_SPLIT_REQUIRED') 'D allowed split required error code'
    Assert-Equal $testD.json.request_count 0 'D allowed split required request count'

    # E: Writer ReplaceText budget exceeded
    $budgetExceedFile = Join-Path $testRoot 'budget-exceed.txt'
    Write-TestText $budgetExceedFile 'before'
    $budgetExceedResponses = Join-Path $testRoot 'budget-exceed-responses.json'
    Save-Responses $budgetExceedResponses @(
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = $null; tool_calls = @((New-ToolCall 'be1' 'replace_text' ([ordered]@{ path = 'budget-exceed.txt'; old_text = 'before'; new_text = ('x' * 5000) }))) }))
    )
    $budgetExceedRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('budget-exceed.txt') -ResponsesPath $budgetExceedResponses -Checkpoint (New-ExternalCheckpoint 'budget-exceed') -Turns 2 -Strategy ReplaceText -ExpectedBytes 128
    Assert-Equal $budgetExceedRun.rc 2 'E write budget exceeded exit'
    Assert-True ($budgetExceedRun.json.errors.code -contains 'WRITER_WRITE_BUDGET_EXCEEDED') 'E write budget exceeded error code'
    Assert-Equal $budgetExceedRun.json.edit_count 0 'E write budget exceeded no edit'
    Assert-Equal (Read-TestText $budgetExceedFile) 'before' 'E write budget exceeded preserves file'

    # F: Writer immediate stop without edit
    $immediateNoEditFile = Join-Path $testRoot 'immediate-no-edit.txt'
    Write-TestText $immediateNoEditFile 'before'
    $immediateNoEditResponses = Join-Path $testRoot 'immediate-no-edit-responses.json'
    Save-Responses $immediateNoEditResponses @(
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'done'; tool_calls = @() }) -FinishReason 'stop')
    )
    $immediateNoEditRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('immediate-no-edit.txt') -ResponsesPath $immediateNoEditResponses -Checkpoint (New-ExternalCheckpoint 'immediate-no-edit') -Turns 2 -Strategy ReplaceText -ExpectedBytes 4096
    Assert-Equal $immediateNoEditRun.rc 2 'F immediate no edit exit'
    Assert-Equal $immediateNoEditRun.json.status 'PARTIAL' 'F immediate no edit status'
    Assert-True ($immediateNoEditRun.json.errors.code -contains 'WRITER_COMPLETED_WITHOUT_EDIT') 'F immediate no edit error code'
    Assert-Equal $immediateNoEditRun.json.stop_reason 'WRITER_COMPLETED_WITHOUT_EDIT' 'F immediate no edit stop reason'
    Assert-Equal $immediateNoEditRun.json.edit_count 0 'F immediate no edit count'
    Assert-Equal (Read-TestText $immediateNoEditFile) 'before' 'F immediate no edit preserves file'

    # noncooperative convergence: model does two searches then reads but still stops without edit
    $noncooperativeFile = Join-Path $testRoot 'noncooperative.txt'
    Write-TestText $noncooperativeFile 'before'
    $noncooperativeResponses = Join-Path $testRoot 'noncooperative-responses.json'
    Save-Responses $noncooperativeResponses @(
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = $null; tool_calls = @((New-ToolCall 'nc-s1' 'search_text' ([ordered]@{ pattern = 'nope1' }))) })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = $null; tool_calls = @((New-ToolCall 'nc-s2' 'search_text' ([ordered]@{ pattern = 'nope2' }))) })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = $null; tool_calls = @((New-ToolCall 'nc-read' 'read_file' ([ordered]@{ path = 'noncooperative.txt' }))) })),
        (New-Response -Message ([ordered]@{ role = 'assistant'; content = 'done without edit'; tool_calls = @() }) -FinishReason 'stop')
    )
    $noncooperativeRun = Invoke-Runner -Root $testRoot -RunMode Writer -Allow @('noncooperative.txt') -ResponsesPath $noncooperativeResponses -Checkpoint (New-ExternalCheckpoint 'noncooperative') -Turns 8 -Strategy ReplaceText -ExpectedBytes 4096
    Assert-Equal $noncooperativeRun.rc 2 'noncooperative convergence exit'
    Assert-Equal $noncooperativeRun.json.status 'PARTIAL' 'noncooperative convergence status'
    Assert-True ($noncooperativeRun.json.errors.code -contains 'WRITER_COMPLETED_WITHOUT_EDIT') 'noncooperative convergence error'
    Assert-Equal $noncooperativeRun.json.stop_reason 'WRITER_COMPLETED_WITHOUT_EDIT' 'noncooperative convergence stop reason'
    Assert-True ($noncooperativeRun.json.warnings.code -contains 'EDIT_CONVERGENCE_MODE') 'noncooperative convergence warning'
    Assert-Equal $noncooperativeRun.json.edit_count 0 'noncooperative convergence edit count'
    Assert-Equal (Read-TestText $noncooperativeFile) 'before' 'noncooperative convergence file unchanged'
    Assert-Equal $noncooperativeRun.json.tool_exposure_history.Count 4 'noncooperative convergence exposure history count'
    $ncTurn3 = $noncooperativeRun.json.tool_exposure_history[2]
    Assert-Equal $ncTurn3.turn 3 'noncooperative turn 3 exposure turn'
    Assert-True ($ncTurn3.names -contains 'read_file') 'noncooperative turn 3 includes read_file'
    Assert-True ($ncTurn3.names -contains 'replace_text') 'noncooperative turn 3 includes replace_text'
    Assert-True (-not ($ncTurn3.names -contains 'search_text')) 'noncooperative turn 3 excludes search_text'
    Assert-True (-not ($ncTurn3.names -contains 'apply_patch')) 'noncooperative turn 3 excludes apply_patch'
    $ncTurn4 = $noncooperativeRun.json.tool_exposure_history[3]
    Assert-Equal $ncTurn4.turn 4 'noncooperative turn 4 exposure turn'
    Assert-Equal $ncTurn4.names.Count 1 'noncooperative turn 4 exactly one exposed name'
    Assert-True ($ncTurn4.names -contains 'replace_text') 'noncooperative turn 4 replace_text only'
    Assert-True (-not ($ncTurn4.names -contains 'read_file')) 'noncooperative turn 4 excludes read_file'
    Assert-True (-not ($ncTurn4.names -contains 'search_text')) 'noncooperative turn 4 excludes search_text'
    Assert-True (-not ($ncTurn4.names -contains 'apply_patch')) 'noncooperative turn 4 excludes apply_patch'

    $textRun = Invoke-Runner -Root $testRoot -Offline -WithoutJson
    Assert-Equal $textRun.rc 0 'text output exit'
    Assert-True $textRun.raw.Contains('DEEPSEEK_WORKSPACE_RUNNER=OFFLINE_CONFIG') 'text compatibility summary'
}
catch {
    $script:Failed++
    [void]$script:Failures.Add(
        'harness exception: ' + $_.Exception.Message + ' ' + $_.InvocationInfo.PositionMessage
    )
}
finally {
    if (Test-Path -LiteralPath $testRoot) {
        try {
            Remove-Item -LiteralPath $testRoot -Recurse -Force -ErrorAction Stop
        }
        catch {
            $script:Failed++
            [void]$script:Failures.Add('test cleanup: ' + $_.Exception.Message)
        }
    }
    foreach ($checkpointPath in @($script:ExternalCheckpoints)) {
        if (Test-Path -LiteralPath $checkpointPath) {
            try {
                Remove-Item -LiteralPath $checkpointPath -Force -ErrorAction Stop
            }
            catch {
                $script:Failed++
                [void]$script:Failures.Add('checkpoint cleanup: ' + $_.Exception.Message)
            }
        }
    }
    Write-Output ('RUNNER_CONTRACT total={0} passed={1} failed={2}' -f $script:Total, $script:Passed, $script:Failed)
    foreach ($failure in $script:Failures) {
        Write-Output ('FAIL: ' + $failure)
    }
    if ($script:Failed -gt 0) {
        exit 1
    }
    exit 0
}
