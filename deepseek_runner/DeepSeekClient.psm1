# DeepSeekClient.psm1
# HTTP client for DeepSeek Chat Completions + tool calls + reasoning_content handling

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

class DeepSeekClient {
    [string]$ApiKey
    [string]$BaseUrl = 'https://api.deepseek.com'
    [string]$Model = 'deepseek-v4-pro'
    [int]$TimeoutSec = 180
    [bool]$ThinkingEnabled = $true
    [string]$ReasoningEffort = 'high'
    [int]$MaxTokens = 32768
    [hashtable]$LastUsage = @{}
}

function New-DeepSeekClient {
    param(
        [Parameter(Mandatory)][string]$ApiKey,
        [string]$Model = 'deepseek-v4-pro',
        [string]$BaseUrl = 'https://api.deepseek.com',
        [int]$TimeoutSec = 180,
        [bool]$ThinkingEnabled = $true,
        [string]$ReasoningEffort = 'high',
        [int]$MaxTokens = 32768
    )
    $c = [DeepSeekClient]::new()
    $c.ApiKey = $ApiKey
    $c.Model = $Model
    $c.BaseUrl = $BaseUrl.TrimEnd('/')
    $c.TimeoutSec = $TimeoutSec
    $c.ThinkingEnabled = $ThinkingEnabled
    $c.ReasoningEffort = $ReasoningEffort
    $c.MaxTokens = $MaxTokens
    return $c
}

function Get-WriterToolsDefinition {
    param([bool]$AllowDelete = $false)
    # Strict Writer-only schemas. The provider is never given a shell, Git,
    # test, network, or process-execution function.
    $editOps = @('replace','rewrite','create')
    $deleteDescription = ''
    if ($AllowDelete) {
        $editOps += 'delete'
        $deleteDescription = "`n- delete: delete a file only because this Task Packet explicitly allows it. Provide path and expected_sha."
    }
    return @(
        @{
            type = 'function'
            function = @{
                name = 'read_file'
                description = 'Read the current content and SHA-256 of a file under the repository. Returns path, sha, size, content, truncated flag. For large files use offset/max_bytes to read in chunks. Always call this before rewrite/delete/replace so you obtain expected_sha.'
                parameters = @{
                    type = 'object'
                    properties = @{
                        path = @{ type = 'string'; description = 'Relative path from RepoRoot' }
                        offset = @{ type = 'integer'; description = 'Byte offset to start reading from (default 0)' }
                        max_bytes = @{ type = 'integer'; description = 'Max bytes to return (default 120000). Use with offset to page through large files.' }
                    }
                    required = @('path')
                }
            }
        },
        @{
            type = 'function'
            function = @{
                name = 'search_text'
                description = 'Search for a literal string across files under the repository (or a path prefix). Returns matching path + line + snippet.'
                parameters = @{
                    type = 'object'
                    properties = @{
                        query = @{ type = 'string'; description = 'Literal string to search' }
                        path_prefix = @{ type = 'string'; description = 'Optional directory prefix to limit search' }
                        max_results = @{ type = 'integer'; description = 'Max hits (default 50)' }
                    }
                    required = @('query')
                }
            }
        },
        @{
            type = 'function'
            function = @{
                name = 'list_files'
                description = 'List files and directories under a path (default repo root). Useful for discovery.'
                parameters = @{
                    type = 'object'
                    properties = @{
                        path = @{ type = 'string'; description = 'Relative directory (empty = root)' }
                        max_depth = @{ type = 'integer'; description = 'Max recursion depth (default 4)' }
                    }
                    required = @()
                }
            }
        },
        @{
            type = 'function'
            function = @{
                name = 'edit_files'
                description = @'
Apply one or more file mutations in a single atomic batch. Supports:
- replace: exact context match (no whitespace normalize). Provide path, context (exact unique snippet), optional old_text inside context, new_text, and expected_sha (REQUIRED for rewrite/delete/replace on existing files).
- rewrite: replace entire file content. Provide path, content, expected_sha (REQUIRED for rewrite/delete/replace on existing files).
- create: create new file. Provide path, content.
$deleteDescription

All paths relative to RepoRoot. Prefer one batch for related changes. On any failure the whole batch is rolled back from memory preimages.
'@
                parameters = @{
                    type = 'object'
                    properties = @{
                        operations = @{
                            type = 'array'
                            items = @{
                                type = 'object'
                                properties = @{
                                    path = @{ type = 'string' }
                                    op = @{ type = 'string'; enum = $editOps }
                                    context = @{ type = 'string'; description = 'Exact original text snippet that must appear once (for replace)' }
                                    old_text = @{ type = 'string'; description = 'Optional: the exact substring inside context to replace' }
                                    new_text = @{ type = 'string'; description = 'Replacement text (for replace)' }
                                    content = @{ type = 'string'; description = 'Full new content (for rewrite/create)' }
                                    expected_sha = @{ type = 'string'; description = 'REQUIRED for rewrite/delete/replace. SHA of current file from read_file. Runner rejects mutation without it.' }
                                }
                                required = @('path','op')
                            }
                        }
                    }
                    required = @('operations')
                }
            }
        }
    )
}

function ConvertTo-DeepSeekMessage {
    # Normalize a PS object / hashtable message into the shape the API expects
    param($Msg)
    $m = @{
        role = $Msg.role
    }
    $hasTools = $false
    if ($Msg.PSObject.Properties['tool_calls'] -and $Msg.tool_calls -and @($Msg.tool_calls).Count -gt 0) {
        $hasTools = $true
        $m.tool_calls = $Msg.tool_calls
    }
    # P0: tool-call assistant messages must carry non-null content
    if ($hasTools) {
        if ($null -eq $Msg.content) { $m.content = '' } else { $m.content = $Msg.content }
    } elseif ($null -ne $Msg.content) {
        $m.content = $Msg.content
    }
    if ($Msg.PSObject.Properties['reasoning_content'] -and $null -ne $Msg.reasoning_content) {
        $m.reasoning_content = $Msg.reasoning_content
    }
    if ($Msg.PSObject.Properties['tool_call_id'] -and $Msg.tool_call_id) {
        $m.tool_call_id = $Msg.tool_call_id
    }
    if ($Msg.PSObject.Properties['name'] -and $Msg.name) {
        $m.name = $Msg.name
    }
    return $m
}

function Resolve-HttpErrorClass {
    param(
        [int]$StatusCode,
        [string]$Body = ''
    )
    if ($StatusCode -eq 400 -and $Body -match 'reasoning') {
        return 'REASONING_PROTOCOL_ERROR'
    }
    if ($StatusCode -eq 429) {
        return 'RATE_LIMIT'
    }
    if ($StatusCode -ge 500) {
        return 'TRANSPORT_ERROR'
    }
    if ($StatusCode -ge 400) {
        return 'MODEL_REQUEST_FAILED'
    }
    return 'MODEL_REQUEST_FAILED'
}

function Invoke-DeepSeekChat {
    param(
        [Parameter(Mandatory)][DeepSeekClient]$Client,
        [Parameter(Mandatory)][array]$Messages,
        [array]$Tools = $null,
        [string]$ToolChoice = 'auto',
        [bool]$ForceNonThinking = $false
    )

    $body = @{
        model = $Client.Model
        messages = @($Messages | ForEach-Object { ConvertTo-DeepSeekMessage $_ })
        stream = $false
        max_tokens = $Client.MaxTokens
    }

    $useThinking = $Client.ThinkingEnabled -and -not $ForceNonThinking
    if ($useThinking) {
        $body.thinking = @{ type = 'enabled' }
        $body.reasoning_effort = $Client.ReasoningEffort
    }

    if ($Tools) {
        $body.tools = $Tools
        # §4: when thinking is active, omit tool_choice entirely to avoid protocol clash
        if (-not $useThinking) {
            $body.tool_choice = $ToolChoice
        }
    }

    $json = $body | ConvertTo-Json -Depth 20 -Compress
    $uri = "$($Client.BaseUrl)/chat/completions"

    $headers = @{
        'Authorization' = "Bearer $($Client.ApiKey)"
        'Content-Type'  = 'application/json'
        'Accept'        = 'application/json'
    }

    $statusCode = 0
    try {
        $resp = Invoke-RestMethod -Uri $uri -Method Post -Headers $headers -Body $json `
            -TimeoutSec $Client.TimeoutSec -SkipHttpErrorCheck -StatusCodeVariable statusCode
    } catch {
        # No HTTP response (timeout / connection reset / DNS)
        $msg = $_.Exception.Message
        return @{
            ok = $false
            error = 'TRANSPORT_ERROR'
            status_code = $null
            message = $msg
        }
    }

    if ($statusCode -ge 400) {
        $respBody = ''
        try {
            if ($null -ne $resp) {
                if ($resp -is [string]) { $respBody = $resp }
                else { $respBody = ($resp | ConvertTo-Json -Depth 10 -Compress) }
            }
        } catch { $respBody = '' }
        $errClass = Resolve-HttpErrorClass -StatusCode $statusCode -Body $respBody
        return @{
            ok = $false
            error = $errClass
            status_code = $statusCode
            message = "HTTP $statusCode | $respBody"
            raw = $respBody
        }
    }

    # A 2xx response is not automatically usable. Providers occasionally send
    # an empty/malformed envelope; return a normal runner error instead of
    # throwing before the checkpoint/final-report path can run.
    if ($null -eq $resp) {
        return @{ ok = $false; error = 'MODEL_RESPONSE_MALFORMED'; status_code = $statusCode; message = 'HTTP success response was empty' }
    }
    $choicesProp = $resp.PSObject.Properties['choices']
    if (-not $choicesProp -or $null -eq $choicesProp.Value -or @($choicesProp.Value).Count -eq 0) {
        return @{ ok = $false; error = 'MODEL_RESPONSE_MALFORMED'; status_code = $statusCode; message = 'HTTP success response has no choices' }
    }
    $choice = @($choicesProp.Value)[0]
    if ($null -eq $choice) {
        return @{ ok = $false; error = 'MODEL_RESPONSE_MALFORMED'; status_code = $statusCode; message = 'HTTP success response has a null choice' }
    }
    $messageProp = $choice.PSObject.Properties['message']
    if (-not $messageProp -or $null -eq $messageProp.Value) {
        return @{ ok = $false; error = 'MODEL_RESPONSE_MALFORMED'; status_code = $statusCode; message = 'HTTP success response has no message' }
    }
    # Success path — all optional fields via PSObject.Properties (StrictMode safe)
    $msg = $messageProp.Value
    $finishProp = $choice.PSObject.Properties['finish_reason']
    $finish = if ($finishProp) { $finishProp.Value } else { $null }

    function Get-OptionalProp($obj, $name) {
        $p = $obj.PSObject.Properties[$name]
        if ($p) { return $p.Value }
        return $null
    }

    $toolCalls = $null
    $rawToolCalls = Get-OptionalProp $msg 'tool_calls'
    if ($rawToolCalls) {
        $toolCalls = @()
        foreach ($tc in $rawToolCalls) {
            $id = Get-OptionalProp $tc 'id'
            if ([string]::IsNullOrWhiteSpace($id)) {
                $id = 'call_' + [guid]::NewGuid().ToString('N').Substring(0, 24)
            }
            $fn = Get-OptionalProp $tc 'function'
            $toolCalls += @{
                id = $id
                type = 'function'
                function = @{
                    name = if ($fn) { Get-OptionalProp $fn 'name' } else { $null }
                    arguments = if ($fn) { Get-OptionalProp $fn 'arguments' } else { '{}' }
                }
            }
        }
    }

    $contentVal = Get-OptionalProp $msg 'content'
    # P0 invariant: tool_calls present => content is never null
    if ($toolCalls -and @($toolCalls).Count -gt 0 -and $null -eq $contentVal) {
        $contentVal = ''
    }
    $assistantMsg = [PSCustomObject]@{
        role = 'assistant'
        content = $contentVal
        reasoning_content = Get-OptionalProp $msg 'reasoning_content'
        tool_calls = $toolCalls
        finish_reason = $finish
    }

    # Usage
    $usage = @{}
    $usageObj = Get-OptionalProp $resp 'usage'
    if ($usageObj) {
        $usage = @{
            prompt_tokens = Get-OptionalProp $usageObj 'prompt_tokens'
            completion_tokens = Get-OptionalProp $usageObj 'completion_tokens'
            total_tokens = Get-OptionalProp $usageObj 'total_tokens'
            prompt_cache_hit_tokens = Get-OptionalProp $usageObj 'prompt_cache_hit_tokens'
            prompt_cache_miss_tokens = Get-OptionalProp $usageObj 'prompt_cache_miss_tokens'
        }
        $Client.LastUsage = $usage
    }

    return @{
        ok = $true
        message = $assistantMsg
        finish_reason = $finish
        usage = $usage
        raw = $resp
    }
}

Export-ModuleMember -Function @(
    'New-DeepSeekClient',
    'Get-WriterToolsDefinition',
    'Invoke-DeepSeekChat',
    'ConvertTo-DeepSeekMessage',
    'Resolve-HttpErrorClass'
)
