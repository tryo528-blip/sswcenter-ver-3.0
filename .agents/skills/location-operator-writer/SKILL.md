---
name: location-operator-writer
description: 호출명에서 장소·오퍼레이터·라이터를 확정하는 SSWCenter 3.0 라우팅 스킬이다. `사무실-코덱스-그록` 또는 `집-코덱스-딥시크`처럼 지정된 조합의 경로·등급·독립 작업방·수동 Git 흐름을 적용한다.
---

# 장소·오퍼레이터·라이터 선정

## 호출 규격: 라우팅을 호출명에서 확정한다

이 스킬은 다음 형식으로 호출한다.

```text
$location-operator-writer <장소>-<오퍼레이터>-<라이터>
```

예시:

```text
$location-operator-writer 사무실-코덱스-그록
$location-operator-writer 집-코덱스-딥시크
$location-operator-writer 사무실-클로드-그록
```

호출명의 세 토큰은 실행 전에 확정한다.

| 호출 토큰 | 정규 값 | 허용 별칭 |
|---|---|---|
| 장소 | `OFFICE` / `HOME` | `사무실` / `집` |
| 오퍼레이터 | `CODEX` / `CLAUDE_CODE` | `코덱스` / `클로드` / `클로드코드` |
| 라이터 | `GROK` / `DEEPSEEK` | `그록` / `딥시크` |

- 세 토큰이 모두 있고 허용 조합으로 해석될 때만 실행한다.
- 호출명에 지정된 조합이 `PLACE`, `OPERATOR`, `WRITER`의 기준값이며, 실행 전 선택 보고에 그대로 표시한다.
- 호출명에 라우팅이 없거나 토큰이 모호하면 장소·오퍼레이터·라이터를 추론하지 않는다. `ROUTE_REQUIRED` 또는 `ROUTE_INVALID`로 중단하고 올바른 호출 형식을 요청한다.
- 현재 PC, 이전 작업, 기본 제안(`사무실 + Codex + DeepSeek`)으로 호출명의 누락값을 채우지 않는다.
- 라우팅이 확정된 뒤에만 경로·인증·래퍼 검사를 수행하고 모델을 호출한다.

## 핵심 원칙

이 스킬은 현재 작업의 실행 조합을 먼저 고른다.

`장소 → 저장소/도구 경로 → 오퍼레이터 → 라이터 → 등급 의미 → 모델 설정 → 독립 작업방 → 실행 순서`

다음 경계를 지킨다.

- `집`과 `사무실`은 같은 `sswcenter` 프로젝트를 가리킬 수 있어도 실행파일, PowerShell, 인증 홈, 래퍼 설정이 다르다. 장소를 생략하지 말고 프로필과 실제 파일 존재를 확인한다.
- `Codex`와 `Claude Code`는 오퍼레이터다. `Grok`과 `DeepSeek`는 라이터다. 이 역할을 섞어 모델을 임의로 바꾸지 않는다.
- 테스트·검수의 **등급 의미**는 현재 저장소의 `docs/운영_오퍼레이터_등급_정의_v1.0.md`에서 읽는다. handoff의 모델·effort·fast 표는 사용하지 않고, 아래의 이번 라우팅 매핑만 적용한다.
- 이 스킬의 대상 저장소는 `C:\sswcenter\3.0`으로 고정한다. 활성 저장소·runner·wrapper·인증 설정이 `C:\sswcenter\2.2`를 가리키면 즉시 중단하고 보고한다. 과거 handoff/report에 남은 2.2 문자열은 역사 기록으로만 취급하고 그 경로를 따라가거나 실행하지 않는다.
- WorkCadence 또는 사용자가 범위에서 제외한 외부 저장소는 읽거나 수정하지 않는다.

### SSWCenter 3.0 고정 경로

- 저장소: `C:\sswcenter\3.0`
- 집·사무실 공통 wrapper 패키지: `C:\sswcenter\3.0\warpper`
- DeepSeek Writer: `C:\sswcenter\3.0\deepseek_runner\invoke-deepseek-writer.ps1`
- 프로젝트 스킬: `C:\sswcenter\3.0\.agents\skills\location-operator-writer`
- DeepSeek 인증: `C:\sswcenter\api-keys.local.env`
- 인증 파일은 위 절대 경로만 사용한다. 다른 위치를 검색하거나 `DEEPSEEK_API_KEY` 프로세스 환경변수로 대체하지 않는다. 파일이 없거나 형식이 잘못되면 호출하지 않고 `BLOCKED`로 보고한다.

## 1. 장소와 경로를 결정한다

1. 호출명에서 확정한 `HOME` 또는 `OFFICE`만 장소로 사용한다. “오늘처럼”, “현재 환경” 또는 현재 wrapper 설정으로 호출명의 장소를 추론하지 않는다.
2. 저장소 내부 `C:\sswcenter\3.0\warpper\wrapper-config.json`만 읽는다. 저장소 밖 wrapper 복사본을 실행하지 않는다.
3. 선택한 프로필의 Grok·Opus·Codex 경로 템플릿이 현재 PC에서 실제 파일로 해석되는지 확인한다. 허용 토큰은 `%USERPROFILE%`, `%APPDATA%`, `%LOCALAPPDATA%`뿐이며 `home`과 `office`는 같은 설치 규격을 사용한다.
4. PowerShell 7은 장소에서 실제로 해석되는 `pwsh` 경로를 확인한다. `C:\tools\PowerShell7\pwsh.exe`는 현재 사무실에서 확인된 예시일 뿐, 집에 그대로 적용하지 않는다.
5. 저장소 루트는 반드시 `C:\sswcenter\3.0`인지 확인한다. wrapper의 기본 루트와 Git 최상위가 다르면 실행하지 않고 `CONFIG_DRIFT`로 보고한다.
6. 다음을 선택 기록으로 남긴다.

```text
PLACE=OFFICE
WRAPPER_PACKAGE=<선택한 장소의 절대 경로>
MACHINE_PROFILE=office
REPOSITORY_ROOT=C:\sswcenter\3.0
POWERSHELL=<실제 pwsh.exe 절대 경로>
```

실행파일, 저장소, 인증 프로필 중 하나라도 확인되지 않으면 모델 호출을 시작하지 말고 `BLOCKED`로 보고한다.

## 2. 오퍼레이터와 라이터를 선정한다

### 오퍼레이터

- 사용자가 `Codex`를 지정하면 Codex를 오퍼레이터로 고정하고 7개 독립 작업방 규칙을 적용한다.
- 사용자가 `Claude Code`를 지정하면 Claude Code를 오퍼레이터로 고정한다. 7개 방을 자동으로 만들지 말고 기존 Claude 작업방 정책을 따른다.
- 오퍼레이터가 불명확하고 작업이 여러 슬라이스로 나뉘면 먼저 선택을 요청한다. 모델 이름만 보고 오퍼레이터를 추정하지 않는다.

### 라이터

- 사용자가 `Grok` 또는 `DeepSeek`를 지정하면 그대로 사용한다.
- 라이터는 호출명에서 확정한 값만 사용한다. 라이터가 호출명에 없거나 자연어와 충돌하면 인증·실행파일을 점검하지 말고 `ROUTE_REQUIRED` 또는 `ROUTE_INVALID`로 중단한다.
- Grok은 `invoke-grok.ps1`와 `-WriteAllowPath`를 사용한다. DeepSeek는 `C:\sswcenter\3.0\deepseek_runner\invoke-deepseek-writer.ps1`만 사용하며 `-RepoRoot`, `-TaskPacketPath`, `-WriteAllowList`, `-ReadAllowList`, `-EnvFile C:\sswcenter\api-keys.local.env`를 명시한다.
- DeepSeek 러너의 `-EnvFile`은 고정 인증 경로와 일치해야 하며, `-ApiKey`를 prompt·로그·보고서에 직접 넣지 않는다.
- 라이터에게 저장소 전체 쓰기 권한을 주지 않는다. 슬라이스의 허용 경로를 먼저 정하고 그 경로만 전달한다.

## 3. 정본 등급 문서에서 등급 의미만 읽는다

1. 현재 `REPOSITORY_ROOT\docs\운영_오퍼레이터_등급_정의_v1.0.md`를 반드시 읽는다. 이 파일이 없으면 handoff나 README에서 의미를 추출하지 말고 `BLOCKED`로 보고한다.
2. 문서에서 테스트·검수 등급 번호와 대표 범위/의미만 추출한다. 모델명, effort, fast, sandbox, network 설정은 이 문서에서 읽지 않는다. 이번 스킬의 모델 배정은 다음 표를 사용한다.
3. 현재 슬라이스의 handoff·packet·plan은 작업 맥락과 추천 등급의 근거로만 읽는다. 정본 등급 문서와 충돌하면 정본 문서를 우선하고 충돌을 보고한다.
4. 사용자가 등급을 주지 않았다면 작업 위험도와 중요도를 정본 문서의 대표 범위에 대조해 1~5를 제안하고, 선택 결과를 실행 전에 보여준다.

검색 절차와 문서 소유권은 [operator-doc-discovery.md](references/operator-doc-discovery.md)를 따른다.

## 4. 이번 모델·effort·fast 매핑을 적용한다

아래 매핑은 이 스킬의 실행 규칙이다. 같은 숫자라도 테스트와 검수에서 별도 매핑을 적용한다.

| 용도 | 등급 | 모델 | effort | fast mode |
|---|---:|---|---|---|
| 테스트 | 1~2 | `gpt-5.3-codex-spark` | `xhigh` | off |
| 테스트 | 3~4 | `gpt-5.6-luna` | `max` | on |
| 테스트 | 5 | `gpt-5.6-sol` | `max` | off |
| 검수 | 1~2 | `gpt-5.6-luna` | `max` | on |
| 검수 | 3~4 | `gpt-5.6-sol` | `xhigh` | off |
| 검수 | 5 | `gpt-5.6-sol` | `ultra` | off |

실행 전 래퍼가 실제로 선택한 모델·effort·fast를 session settings로 확인한다. 래퍼와 표가 다르면 `CONFIG_DRIFT`로 보고하고 실행하지 않는다. 현재 양쪽 wrapper 패키지는 이 표를 구현해야 하며, 변경 후 offline 회귀 테스트를 통과해야 한다.

## 5. Codex 오퍼레이터의 7개 독립 작업방

Codex가 오퍼레이터이면 작업 시작 전에 정확히 7개의 독립 작업방을 준비한다.

- 각 방은 별도 Codex task/thread와 별도 Git worktree를 가진다.
- 방 이름은 `room-1`부터 `room-7`까지 사용하고, 같은 worktree를 두 방에서 공유하지 않는다.
- 기존 경로가 있으면 삭제·덮어쓰기·reset하지 말고 충돌을 보고한다.
- 메인 worktree에서 직접 구현하지 않는다. 각 슬라이스를 해당 방에 배정한다.
- `room-7`은 일반 슬라이스에도 사용할 수 있지만, Opus 한도 초과 시 최종검수 대체 방으로 사용할 수 있도록 항상 독립 상태를 유지한다.
- 한 슬라이스가 끝나면 결과·실행 로그·미검증 항목·다음 작업을 handoff로 남기고 그 task/thread를 보관한다. 같은 방을 재사용하지 말고 다음 슬라이스에 새 방을 만든다.
- 보관은 task/thread를 아카이브하는 의미이며, worktree 삭제·정리는 사용자가 명시하지 않는 한 수행하지 않는다.

Claude Code 오퍼레이터는 이 7개 방 규칙을 자동 상속하지 않는다. 사용자가 별도로 7개 방을 지시했을 때만 적용한다.

## 6. 슬라이스 실행 순서

각 독립 방에서 다음 순서를 지킨다.

1. 현재 슬라이스, 쓰기 허용 경로, 테스트·검수 등급, 기준 커밋/브랜치, 장소·오퍼레이터·라이터를 handoff에 고정한다.
2. Grok 또는 DeepSeek 라이터를 한 번 실행해 구현한다. 라이터 결과의 `changed_paths`를 실제 diff와 대조한다.
3. 필요한 테스트 등급으로 테스트한다. 테스트 범위를 등급 의미보다 넓히지 않는다.
4. 필요한 검수 등급으로 검수한다. 검수는 read-only로 실행하고 변경을 허용하지 않는다.
5. 슬라이스 최종검수와 검수 Grade 5는 아래 Opus 규칙을 적용한다.
6. PASS/FAIL/BLOCKED, 실제 실행 명령, 변경 경로, 테스트 결과, 미검증 항목을 handoff에 기록한다.

Grok 호출의 기본 형태:

```powershell
& $pwsh -NoProfile -File $grokWrapper `
  -RepositoryRoot $roomRoot `
  -MachineProfile $machineProfile `
  -WriteAllowPath $writeAllowPath `
  -PromptFile $promptFile
```

DeepSeek Writer 호출의 기본 형태:

```powershell
& $pwsh -NoProfile -File $deepSeekRunner `
  -RepoRoot $roomRoot `
  -TaskPacketPath $taskPacketPath `
  -WriteAllowList $writeAllowPath `
  -ReadAllowList $readAllowPath `
  -EnvFile 'C:\sswcenter\api-keys.local.env'
```

`$deepSeekRunner`는 `C:\sswcenter\3.0\deepseek_runner\invoke-deepseek-writer.ps1`로 고정한다. 이 러너는 자연어 prompt를 직접 받지 않고 JSON Task Packet만 받는다.

Codex 테스트·검수는 래퍼가 실제로 해당 표를 구현한 경우에만 다음 진입점을 사용한다.

```powershell
# 테스트
& $pwsh -NoProfile -File $codexWrapper `
  -RepositoryRoot $roomRoot -MachineProfile $machineProfile `
  -TestGrade <1..5> -PromptFile $promptFile

# 검수
& $pwsh -NoProfile -File $codexWrapper `
  -RepositoryRoot $roomRoot -MachineProfile $machineProfile `
  -ReviewGrade <1..5> -PromptFile $promptFile
```

래퍼가 `-Fast`, 모델, effort를 직접 받지 않는 것은 정상일 수 있지만, 호출 전 stderr/session settings 또는 소스의 등급 분기를 확인해 반드시 실제 조합을 검증한다.

## 7. Opus 최종검수 규칙

각 슬라이스의 최종검수와 검수 Grade 5는 다음 조합을 고정한다.

- `Claude Opus 4.6`
- 모델은 `claude-opus-4-6`으로 고정하고 `[1m]` 변형은 사용하지 않는다.
- `--effort max`
- 표준 컨텍스트만 사용하도록 `CLAUDE_CODE_DISABLE_1M_CONTEXT=1`을 자식 프로세스에 전달한다.
- Extended/Adaptive Thinking을 끄도록 `CLAUDE_CODE_DISABLE_THINKING=1`을 자식 프로세스에 전달한다.
- `alwaysThinkingEnabled` 설정은 전달하지 않는다.
- 검수 자료를 한 번에 prompt로 제공하고, `-p/--print` 한 번의 새 세션으로 끝낸다. `--resume`, `--continue`, 긴 질의응답을 사용하지 않는다.
- 검수마다 새 세션을 만든다. 같은 검수의 재시도는 최대 1회이며, 재시도 전 실패 원인(인증/한도/CLI/입력/검수 결과)을 분류하고 최소 재현만 수행한다.
- Opus 검수는 read-only 도구만 사용한다. 최종 보고는 PASS/FAIL/BLOCKED와 근거·미검증 항목을 포함한다.

`invoke-opus.ps1`는 이 조합을 내부 인자로 고정한다. 실행 전 stderr/session settings와 실제 모델 인자를 확인하고, 불일치하면 `CONFIG_DRIFT`로 중단한다. 직접 CLI가 필요한 경우의 인자 계약은 [runtime-contracts.md](references/runtime-contracts.md)를 따른다.

### Opus 한도 초과 대체

Opus가 사용 한도에 걸리면 Opus를 반복 호출하지 않는다.

1. 독립된 `room-7`을 새 작업방으로 만들거나 아직 사용하지 않은 `room-7`을 사용한다.
2. Opus가 받은 것과 동일한 검수 자료·기준·handoff를 한 번에 전달한다.
3. `gpt-5.6-sol`, `effort=ultra`, `fast=off`로 대체 검수한다.
4. 결과에 `OPUS_FALLBACK=CODEX_SOL_GRADE_5`와 Opus 미실행 사유를 명시한다. 이를 Opus PASS로 표시하지 않는다.

## 8. 실패·재시도·보안 경계

- Writer FAIL/BLOCKED는 원인과 실제 변경 여부를 확인한 뒤 사용자에게 보고한다. 자동으로 등급을 올리거나 다른 Writer를 연속 호출하지 않는다.
- Opus FAIL은 원인 분류와 최소 재현까지만 수행하고 동일 검수 재시도는 1회로 제한한다. 검수 실패를 구현 실패로 단정하지 않는다.
- `git reset`, `checkout`, `clean`, 자동 복구, 자동 clone/pull/push/stage/commit/cherry-pick을 수행하지 않는다.
- Git `pull`, `commit`, `push`, `cherry-pick`은 형님이 명시적으로 요청한 경우에만 실행한다. 요청이 없으면 현재 브랜치와 변경사항을 보존하고, 작업 완료 보고만 한다.
- 인증 파일, API key, `.env`, `.codex`, `.grok`, `auth.json`을 prompt나 보고서에 넣지 않는다.
- 인증은 `C:\sswcenter\api-keys.local.env`만 사용하며, 인증 파일의 내용을 출력·복사·커밋하지 않는다.
- Writer의 허용 경로 밖 변경, 메인 worktree 변경, Git metadata 변경, 다른 장소의 config 변경이 감지되면 즉시 중단하고 `BLOCKED`로 보고한다.

## 최종 선택 보고 형식

실행 전에 다음처럼 짧게 확정한다.

```text
ROUTE=사무실-코덱스-그록
PLACE=OFFICE
OPERATOR=CODEX
WRITER=DEEPSEEK
REPOSITORY_ROOT=C:\sswcenter\3.0
ROOMS=7 isolated worktrees
TEST=Grade 3 / gpt-5.6-luna / max / fast on
REVIEW=Grade 3 / gpt-5.6-sol / xhigh / fast off
FINAL=Opus 4.6 / max / standard context / thinking off
```

경로·실행파일·래퍼 조합이 실제 확인 결과와 다르면 이 보고를 `BLOCKED` 또는 `CONFIG_DRIFT`로 바꾸고 실행하지 않는다.
