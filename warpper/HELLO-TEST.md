# HELLO TEST (안녕 테스트)

호출어: **“안녕테스트해줘”**

이 테스트는 인증만 확인하지 않고 Grok, Codex Spark, Opus, DeepSeek를 각각 실제로 한 번 호출해 응답까지 확인한다. 프로젝트 작업이나 독립방 검증이 아니라 명시적 연결 진단이며, Codex 단계는 Claude→Codex wrapper 진입점을 확인한다.

네 번 모두 실제 모델 호출이므로 사용량이 발생한다. 파일은 수정하지 않는다. 한 번에 하나씩 실행하며, 실행 중 다른 에이전트나 터미널에서 이 저장소에 Git 명령을 실행하지 않는다.

## 실행

PowerShell 7에서 아래 공통 변수를 먼저 입력한다.

```powershell
$root = 'C:\sswcenter\3.0'
$pwsh = 'C:\tools\PowerShell7\pwsh.exe'
$structuredHello = '연결 smoke test다. 파일은 수정하지 말고 최종 summary에 "안녕"을 넣어.'
$directHello = '안녕이라고만 답해.'
```

### 1. Grok Writer

```powershell
& $pwsh -NoProfile -File 'C:\sswcenter\3.0\warpper\invoke-grok.ps1' `
  -MachineProfile office `
  -RepositoryRoot $root `
  -WriteAllowPath 'backend\app\db\models.py' `
  -Prompt $structuredHello
```

### 2. Claude→Codex wrapper 진입점 smoke

```powershell
& $pwsh -NoProfile -File 'C:\sswcenter\3.0\warpper\invoke-codex.ps1' `
  -MachineProfile office `
  -RepositoryRoot $root `
  -TestGrade 1 `
  -Prompt $structuredHello
```

### 3. Opus 독립검수

```powershell
& $pwsh -NoProfile -File 'C:\sswcenter\3.0\warpper\invoke-opus.ps1' `
  -MachineProfile office `
  -RepositoryRoot $root `
  -Prompt $structuredHello
```

### 4. DeepSeek 직접 응답

```powershell
$keyFile = 'C:\sswcenter\api-keys.local.env'
$keyLines = @(Get-Content -LiteralPath $keyFile | Where-Object { $_ -match '^\s*DEEPSEEK_API_KEY\s*=' })
if ($keyLines.Count -ne 1) { throw 'FIXED_KEY_INVALID' }
$deepSeekKey = ($keyLines[0] -split '=', 2)[1].Trim().Trim('"').Trim("'")
if ([string]::IsNullOrWhiteSpace($deepSeekKey)) { throw 'FIXED_KEY_EMPTY' }

Import-Module 'C:\sswcenter\3.0\deepseek_runner\DeepSeekClient.psm1' -Force
$client = New-DeepSeekClient `
  -ApiKey $deepSeekKey `
  -Model 'deepseek-v4-pro' `
  -TimeoutSec 60 `
  -ThinkingEnabled $false `
  -MaxTokens 128
$deepSeekResult = Invoke-DeepSeekChat `
  -Client $client `
  -Messages @(@{ role = 'user'; content = $directHello }) `
  -ForceNonThinking $true
$deepSeekResponse = if ($deepSeekResult.ok) { [string]$deepSeekResult.message.content } else { '' }
[ordered]@{
  status = if ($deepSeekResult.ok -and $deepSeekResponse -match '안녕') { 'PASS' } else { 'FAIL' }
  response = $deepSeekResponse
  request_count = 1
  finish_reason = [string]$deepSeekResult.finish_reason
} | ConvertTo-Json -Compress
$deepSeekKey = $null
```

## 성공 판단

- Grok·Codex·Opus: 종료 코드 `0`, stdout JSON의 `summary`에 `안녕`, 제품 파일 변경 없음
- DeepSeek: 명령 성공, JSON의 `status`가 `PASS`, `response`에 `안녕`, `request_count`가 `1`
- `AUTH_GUIDANCE`, `API_KEY_MISSING`, `WRAPPER_ERROR`, `blocked by policy`가 나오면 모델 응답까지 도달하지 못한 것이므로 연결 실패로 기록한다.

형님이 **“안녕테스트해줘”**라고 하면 이 문서의 네 호출을 각각 한 번씩 실행한다. 실패해도 자동 재호출하지 않고 해당 래퍼의 종료 코드와 stderr를 먼저 확인한다.
