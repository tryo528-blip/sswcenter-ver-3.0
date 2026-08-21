[CmdletBinding()]
param(
    [int]$PollSeconds = 15,
    [int]$ActiveWindowSeconds = 45,
    [int]$CompletionQuietSeconds = 120,
    [switch]$Once,
    [switch]$NoSlack
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-CodexHome {
    if ($env:CODEX_HOME) { return $env:CODEX_HOME }
    return (Join-Path $HOME '.codex')
}

function Get-CodexProcesses {
    @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessName -match '(?i)codex'
    })
}

function Get-RecentSessionFile {
    param([string]$CodexHome)

    $roots = @(
        (Join-Path $CodexHome 'sessions'),
        (Join-Path $CodexHome 'archived_sessions')
    ) | Where-Object { Test-Path $_ }

    if (-not $roots) { return $null }

    $files = foreach ($root in $roots) {
        Get-ChildItem -Path $root -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -in '.jsonl', '.json' }
    }

    $files | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
}

function Get-SessionProjectHint {
    param([System.IO.FileInfo]$File)

    if (-not $File) { return $null }

    try {
        $maxBytes = 262144
        $stream = [System.IO.File]::Open($File.FullName, 'Open', 'Read', 'ReadWrite')
        try {
            $len = $stream.Length
            $start = [Math]::Max(0, $len - $maxBytes)
            $stream.Seek($start, [System.IO.SeekOrigin]::Begin) | Out-Null
            $reader = New-Object System.IO.StreamReader($stream)
            $text = $reader.ReadToEnd()
        }
        finally {
            if ($reader) { $reader.Dispose() }
            $stream.Dispose()
        }

        $patterns = @(
            '"cwd"\s*:\s*"([^"]+)"',
            '"repository_root"\s*:\s*"([^"]+)"',
            '"workspace"\s*:\s*"([^"]+)"'
        )

        foreach ($pattern in $patterns) {
            $matches = [regex]::Matches($text, $pattern)
            if ($matches.Count -gt 0) {
                $raw = $matches[$matches.Count - 1].Groups[1].Value
                return ($raw -replace '\\\\', '\')
            }
        }
    }
    catch {
        return $null
    }

    return $null
}

function Get-CodexSnapshot {
    param([string]$CodexHome)

    $now = [DateTime]::UtcNow
    $procs = Get-CodexProcesses
    $session = Get-RecentSessionFile -CodexHome $CodexHome

    if (-not $procs) {
        return [pscustomobject]@{
            State = 'APP_OFF'
            Detail = 'Codex 프로세스가 보이지 않습니다.'
            Project = $null
            SessionPath = if ($session) { $session.FullName } else { $null }
            AgeSeconds = $null
            ObservedAtUtc = $now.ToString('o')
        }
    }

    if (-not $session) {
        return [pscustomobject]@{
            State = 'APP_ON_NO_SESSION'
            Detail = 'Codex는 실행 중이지만 세션 파일을 찾지 못했습니다.'
            Project = $null
            SessionPath = $null
            AgeSeconds = $null
            ObservedAtUtc = $now.ToString('o')
        }
    }

    $age = [Math]::Max(0, [int](($now - $session.LastWriteTimeUtc).TotalSeconds))
    $project = Get-SessionProjectHint -File $session
    $state = if ($age -le $ActiveWindowSeconds) { 'ACTIVE_RECENT' } else { 'QUIET' }

    [pscustomobject]@{
        State = $state
        Detail = if ($state -eq 'ACTIVE_RECENT') { '최근 세션 기록이 계속 갱신되고 있습니다.' } else { '최근 세션 기록 갱신이 멈춰 있습니다.' }
        Project = $project
        SessionPath = $session.FullName
        AgeSeconds = $age
        ObservedAtUtc = $now.ToString('o')
    }
}

function Get-StateStorePath {
    $root = Join-Path $env:LOCALAPPDATA 'CodexStatusRelay'
    if (-not (Test-Path $root)) {
        New-Item -ItemType Directory -Path $root -Force | Out-Null
    }
    Join-Path $root 'state.json'
}

function Read-PreviousState {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    try { Get-Content -Raw -Path $Path | ConvertFrom-Json } catch { $null }
}

function Save-State {
    param([string]$Path, $State)
    $State | ConvertTo-Json -Depth 5 | Set-Content -Path $Path -Encoding UTF8
}

function Send-Slack {
    param([string]$Text)

    if ($NoSlack) { return }
    $url = $env:SLACK_WEBHOOK_URL
    if (-not $url) { return }

    $body = @{ text = $Text } | ConvertTo-Json -Compress
    Invoke-RestMethod -Method Post -Uri $url -ContentType 'application/json; charset=utf-8' -Body $body | Out-Null
}

function Format-StatusMessage {
    param($Snapshot, [string]$Prefix)

    $parts = @("$Prefix Codex 상태: $($Snapshot.State)")
    if ($Snapshot.Project) { $parts += "프로젝트: $($Snapshot.Project)" }
    if ($null -ne $Snapshot.AgeSeconds) { $parts += "마지막 활동: $($Snapshot.AgeSeconds)초 전" }
    $parts += $Snapshot.Detail
    $parts -join "`n"
}

$codexHome = Get-CodexHome
$statePath = Get-StateStorePath

Write-Host "CodexStatusRelay (read-only)"
Write-Host "CODEX_HOME=$codexHome"
Write-Host "StateStore=$statePath"
if (-not $NoSlack -and -not $env:SLACK_WEBHOOK_URL) {
    Write-Warning 'SLACK_WEBHOOK_URL이 없어 콘솔 감지만 수행합니다.'
}

while ($true) {
    $snapshot = Get-CodexSnapshot -CodexHome $codexHome
    $previous = Read-PreviousState -Path $statePath

    $notify = $false
    $prefix = '[상태변경]'

    if (-not $previous) {
        $notify = $true
        $prefix = '[감시시작]'
    }
    elseif ($previous.State -ne $snapshot.State) {
        $notify = $true
    }
    elseif ($previous.Project -ne $snapshot.Project -and $snapshot.Project) {
        $notify = $true
        $prefix = '[프로젝트변경]'
    }

    # ACTIVE -> QUIET 전환 뒤 충분히 조용하면 "완료 추정"을 한 번만 알립니다.
    $completionCandidate = $false
    if ($snapshot.State -eq 'QUIET' -and $null -ne $snapshot.AgeSeconds -and $snapshot.AgeSeconds -ge $CompletionQuietSeconds) {
        $wasActive = $false
        if ($previous) {
            $wasActive = ($previous.State -eq 'ACTIVE_RECENT') -or ($previous.WasActive -eq $true)
        }
        $alreadyNotified = $previous -and ($previous.CompletionNotified -eq $true) -and ($previous.SessionPath -eq $snapshot.SessionPath)
        if ($wasActive -and -not $alreadyNotified) {
            $completionCandidate = $true
            $notify = $true
            $prefix = '[작업 종료 추정]'
        }
    }

    if ($notify) {
        $msg = Format-StatusMessage -Snapshot $snapshot -Prefix $prefix
        Write-Host "`n$msg`n"
        try { Send-Slack -Text $msg } catch { Write-Warning "Slack 전송 실패: $($_.Exception.Message)" }
    }

    $persisted = [ordered]@{
        State = $snapshot.State
        Project = $snapshot.Project
        SessionPath = $snapshot.SessionPath
        AgeSeconds = $snapshot.AgeSeconds
        ObservedAtUtc = $snapshot.ObservedAtUtc
        WasActive = if ($snapshot.State -eq 'ACTIVE_RECENT') { $true } elseif ($previous) { [bool]$previous.WasActive } else { $false }
        CompletionNotified = if ($completionCandidate) { $true } elseif ($snapshot.State -eq 'ACTIVE_RECENT') { $false } elseif ($previous -and $previous.SessionPath -eq $snapshot.SessionPath) { [bool]$previous.CompletionNotified } else { $false }
    }
    Save-State -Path $statePath -State $persisted

    if ($Once) { break }
    Start-Sleep -Seconds $PollSeconds
}
