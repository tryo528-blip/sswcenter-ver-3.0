# 장소별 런타임과 Opus 최종검수 계약

## 래퍼 위치와 프로필

장소별 wrapper package를 먼저 찾고 그 안의 `wrapper-config.json`을 읽는다. 3.0 사무실 실행은 다음 경로를 고정한다.

- 저장소: `C:\sswcenter\3.0`
- wrapper package: `C:\sswcenter\3.0\warpper`
- Grok: `invoke-grok.ps1`
- Codex: `invoke-codex.ps1`
- Opus: `invoke-opus.ps1`
- DeepSeek: `C:\sswcenter\3.0\deepseek_runner\invoke-deepseek-writer.ps1`
- DeepSeek 인증: `C:\sswcenter\api-keys.local.env`

실행파일은 실제 존재를 확인한다. `home`과 `office` profile은 `%USERPROFILE%`, `%APPDATA%`, `%LOCALAPPDATA%` 기반의 같은 설치 규격을 사용한다. DeepSeek 인증 파일은 위 절대 경로만 읽고 다른 위치 탐색·환경변수 fallback을 사용하지 않는다.

## DeepSeek Writer 계약

DeepSeek Writer는 반드시 JSON Task Packet과 허용 목록을 함께 받는다. 자연어 prompt만 전달하거나 저장소 전체를 쓰기 허용하지 않는다.

```powershell
& 'C:\tools\PowerShell7\pwsh.exe' -NoProfile -File `
  'C:\sswcenter\3.0\deepseek_runner\invoke-deepseek-writer.ps1' `
  -RepoRoot 'C:\sswcenter\3.0' `
  -TaskPacketPath $taskPacketPath `
  -WriteAllowList $writeAllowPath `
  -ReadAllowList $readAllowPath `
  -EnvFile 'C:\sswcenter\api-keys.local.env'
```

`EnvFile`이 없거나 `DEEPSEEK_API_KEY` 항목이 정확히 하나가 아니면 실행을 중단한다. API key 값은 명령행·prompt·로그에 넣지 않는다.

## Git 변경 계약

이 스킬은 `pull`, `stage`, `commit`, `cherry-pick`, `push`, `reset`, `checkout`, `clean`을 자동 실행하지 않는다. 형님이 명시적으로 요청한 경우에만 현재 상태와 diff를 먼저 확인하고 해당 작업을 수행한다.

## 래퍼와 스킬 매핑의 일치 확인

`invoke-opus.ps1`는 `claude-opus-4-6`, `max`, 표준 컨텍스트, thinking 비활성을 내부에서 고정한다. Codex 래퍼도 테스트 Grade 5와 검수 Grade 3~4의 fast를 off로 고정한다. 따라서 실행 전 다음을 확인한다.

1. 래퍼가 선택한 모델·effort·fast를 소스 또는 session settings에서 읽는다.
2. 이 스킬의 요구와 다르면 `CONFIG_DRIFT`를 보고한다.
3. 양쪽 wrapper package의 소스와 offline 회귀 테스트가 같은 매핑인지 확인한다.

## Opus 직접 CLI 계약

Opus 최종검수는 한 번의 새 비대화 세션에 자료를 모두 넣는다. PowerShell에서는 실제 Claude CLI 경로와 실제 `pwsh` 경로를 먼저 해석한다.

```powershell
$claudePrompt = Get-Content -Raw -LiteralPath $promptFile
$previousDisable1M = [Environment]::GetEnvironmentVariable('CLAUDE_CODE_DISABLE_1M_CONTEXT', 'Process')
$previousDisableThinking = [Environment]::GetEnvironmentVariable('CLAUDE_CODE_DISABLE_THINKING', 'Process')

try {
  $env:CLAUDE_CODE_DISABLE_1M_CONTEXT = '1'
  $env:CLAUDE_CODE_DISABLE_THINKING = '1'

  & $claude `
    -p `
    --model 'claude-opus-4-6' `
    --effort max `
    --output-format json `
    --no-session-persistence `
    $claudePrompt
}
finally {
  [Environment]::SetEnvironmentVariable('CLAUDE_CODE_DISABLE_1M_CONTEXT', $previousDisable1M, 'Process')
  [Environment]::SetEnvironmentVariable('CLAUDE_CODE_DISABLE_THINKING', $previousDisableThinking, 'Process')
}
```

실행 전에 다음을 보장한다.

- 자식 프로세스에 `CLAUDE_CODE_DISABLE_1M_CONTEXT=1`을 전달한다.
- 자식 프로세스에 `CLAUDE_CODE_DISABLE_THINKING=1`을 전달한다.
- 모델 인자나 alias에 `[1m]`을 넣지 않는다.
- `alwaysThinkingEnabled`를 포함한 `--settings`를 전달하지 않는다.
- `--resume` 또는 `--continue`를 사용하지 않는다.
- 모델은 정확히 `claude-opus-4-6`을 사용한다.
- prompt는 검수 자료, 기준, 요구된 JSON 보고 형식을 한 번에 포함한다.

`CLAUDE_CODE_DISABLE_THINKING=1`이 Extended/Adaptive Thinking을 강제로 끄며, `CLAUDE_CODE_DISABLE_1M_CONTEXT=1`이 1M 컨텍스트 사용을 막는다. `--effort max`는 유지하되 이 두 비용 옵션을 다시 켜는 설정으로 사용하지 않는다.
