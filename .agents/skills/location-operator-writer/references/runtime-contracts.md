# AI 호출 런타임 계약

이 문서는 **실제 호출 명령 형식만** 소유한다. 역할·호출 권한·모델 배정은 [`00-오케스트레이션-작업지침.md`](../../../../00-오케스트레이션-작업지침.md), 경로·인증·Git 경계는 [`00-먼저읽기-작업환경안내.md`](../../../../00-먼저읽기-작업환경안내.md)를 따른다.

## 호출 권한

| 호출 | 허용 조건 |
|---|---|
| `invoke-grok.ps1` | `WRITER=GROK` |
| `invoke-deepseek-writer.ps1` | `WRITER=DEEPSEEK` |
| `invoke-codex.ps1` | `OPERATOR=CLAUDE_CODE`의 테스트·검수 위임 |
| `invoke-opus.ps1` | 최종 독립검수 |

`OPERATOR=CODEX`인 본진과 독립방에서는 `invoke-codex.ps1`를 호출하지 않는다. 독립방은 이미 모델이 배정된 Codex 세션이므로 자기 worktree에서 직접 테스트·검수한다.

## 공통 사전확인

1. 대상 경로가 본진 또는 승인된 worktree의 정확한 Git 최상위인지 확인한다.
2. `wrapper-config.json`의 `repositoryRoot`가 `C:\sswcenter\3.0`인지 확인한다.
3. 선택한 장소의 profile과 실제 실행파일 존재를 확인한다.
4. 호출 권한 표와 현재 `OPERATOR`·`WRITER`가 일치하는지 확인한다.
5. 불일치하면 호출하지 않고 `CONFIG_DRIFT`, 파일이나 인증이 없으면 `BLOCKED`로 보고한다.

## Grok Writer

```powershell
& $pwsh -NoProfile -File $grokWrapper `
  -RepositoryRoot $targetRoot `
  -MachineProfile $machineProfile `
  -WriteAllowPath $writeAllowPath `
  -PromptFile $promptFile
```

`WriteAllowPath`에는 승인된 상대경로만 넣는다. 저장소 전체나 `.git`을 허용하지 않는다.

## DeepSeek Writer

```powershell
& $pwsh -NoProfile -File `
  'C:\sswcenter\3.0\deepseek_runner\invoke-deepseek-writer.ps1' `
  -RepoRoot $targetRoot `
  -TaskPacketPath $taskPacketPath `
  -WriteAllowList $writeAllowPath `
  -ReadAllowList $readAllowPath `
  -EnvFile 'C:\sswcenter\api-keys.local.env'
```

Task Packet의 `write_paths`와 `WriteAllowList`는 같아야 한다. API key 값은 명령행·prompt·로그에 넣지 않는다.

## Claude Code에서 Codex 위임

다음 명령은 `OPERATOR=CLAUDE_CODE`에서만 허용한다.

```powershell
# 테스트
& $pwsh -NoProfile -File $codexWrapper `
  -RepositoryRoot $targetRoot `
  -MachineProfile $machineProfile `
  -TestGrade <1..5> `
  -PromptFile $promptFile

# read-only 검수
& $pwsh -NoProfile -File $codexWrapper `
  -RepositoryRoot $targetRoot `
  -MachineProfile $machineProfile `
  -ReviewGrade <1..5> `
  -PromptFile $promptFile
```

한 호출에는 `TestGrade`와 `ReviewGrade` 중 하나만 전달한다. `Prompt`와 `PromptFile`도 둘 중 하나만 전달한다. 모델·effort·fast는 오케스트레이션 정본의 표와 일치해야 한다.

## Opus 최종검수

```powershell
& $pwsh -NoProfile -File $opusWrapper `
  -RepositoryRoot $targetRoot `
  -MachineProfile $machineProfile `
  -PromptFile $promptFile
```

새 비대화 세션 하나에 자료·기준·출력 형식을 모두 전달한다. 모델은 `claude-opus-4-6`, effort는 `max`, 표준 컨텍스트, thinking 비활성, read-only로 고정한다. `--resume`과 `--continue`는 사용하지 않는다.

## 공통 종료 규칙

- 자동 retry, resume, fallback, 다른 모델 연속 호출을 하지 않는다.
- 실제 변경 경로와 모델 보고를 대조한다.
- 실패해도 reset, checkout, clean으로 자동 복구하지 않는다.
- `PASS`, `FAIL`, `BLOCKED`, 실제 명령, 변경 경로, 미검증 항목을 보고한다.
