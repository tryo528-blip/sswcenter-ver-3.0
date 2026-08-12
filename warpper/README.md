# AI 래퍼 사용 안내

`안녕테스트해줘` 호출은 [HELLO-TEST.md](./HELLO-TEST.md)의 네 공급자 실제 호출 테스트를 뜻한다.

이 패키지의 목적은 경로·설정·인증 같은 단순한 문제로 유료 작업을 다시 호출하는 일을 줄이고, 선택한 모델에 완성된 작업을 한 번 맡긴 뒤 구조화된 최종 보고를 받는 것입니다.

- 실제 작업 CLI 프로세스와 하나의 작업 세션은 래퍼 실행당 최대 1회입니다.
- 래퍼가 수행하는 retry, resume, fallback, 대체 모델 호출이 없습니다.
- Grok은 자격정보를 로컬에서 검사합니다. Opus와 Codex는 작업 전에 비과금 인증 상태 명령을 최대 1회 실행합니다.
- 사전확인이 실패하거나 인증 단계에서 저장소 변경이 감지되면 작업 모델 호출은 0회입니다.
- 세 래퍼 모두 런타임 하부 에이전트를 차단합니다.
- 인증과 실제 작업은 각각 독립된 저장소 감시 구간으로 봉인되며, 변경을 자동 복구하거나 기존 더티 WIP를 reset하지 않습니다.

오프라인 테스트는 실제 AI, 과금, 원격 모델 응답을 확인하지 않습니다. 실제 래퍼의 작업 호출은 해당 공급자 사용량을 발생시키며, 한 작업 세션 안의 정상적인 agent tool-use 턴이나 공급자 전송 처리는 별도 래퍼 재호출로 세지 않습니다.

## 역할

| 사용 상황 | 호출 | 모델/강도 | 권한 |
|---|---|---|---|
| 모든 오퍼레이터의 Writer | `invoke-grok.ps1 -WriteAllowPath <상대경로>` | `grok-4.5` | 명시한 쓰기 경계 안의 읽기·생성·수정만 |
| Codex 오퍼레이터의 최종 독립검수 | `invoke-opus.ps1` | `claude-opus-4-6`, `max`, 표준 컨텍스트, thinking 비활성 | plan/safe-mode, 읽기 전용 |
| Claude Code 오퍼레이터의 등급별 테스트 | `invoke-codex.ps1 -TestGrade 1..5` | 등급표에 따라 Spark/Luna/Sol 고정 | 1~2 읽기 전용, 3~5 격리 테스트 실행 |
| Claude Code 오퍼레이터의 등급별 검수 | `invoke-codex.ps1 -ReviewGrade 1..5` | 등급표에 따라 Luna/Sol 고정 | `read-only` sandbox |

Codex의 구현 모드와 `-Implement`는 제거됐습니다. 전달하면 PowerShell 인자 처리 단계에서 거부되어 인증·작업 프로세스가 시작되지 않습니다. DeepSeek 러너와 당일 Writer 선택은 이 패키지 범위 밖입니다.

Grok은 `--no-subagents`, Opus는 `Agent` 도구 차단, Codex는 `features.multi_agent=false`로 실행됩니다. Grok은 셸·웹·외부 MCP를 사용할 수 없습니다. Opus와 검수용 Codex는 읽기 전용이며, 테스트 3~5등급 Codex도 저장소/Git 변경은 금지되고 사후 감시에서 한 건이라도 발견되면 실패합니다.

### Codex 테스트 등급

| 등급 | 대표 범위 | 모델 | effort | fast | sandbox/network |
|---:|---|---|---|---|---|
| 1 | 정적·문법·import·compile·단일 smoke | `gpt-5.3-codex-spark` | `xhigh` | off | `read-only`, network off |
| 2 | bounded unit·component·contract | `gpt-5.3-codex-spark` | `xhigh` | off | `read-only`, network off |
| 3 | 격리 PostgreSQL·DB integration | `gpt-5.6-luna` | `max` | on | `workspace-write`, network on |
| 4 | API·frontend·service·E2E | `gpt-5.6-luna` | `max` | on | `workspace-write`, network on |
| 5 | 운영·복구·migration lifecycle·security·최종 acceptance | `gpt-5.6-sol` | `max` | off | `workspace-write`, network on |

3~5등급의 network 허용은 명시적으로 요청한 로컬 테스트 서비스와 격리 테스트 DB를 위한 것입니다. public internet, 패키지 다운로드, 설치, production/shared/식별 불가 DB는 프롬프트에서 금지합니다. sandbox가 쓰기를 허용하더라도 저장소와 Git은 불변이어야 하며 watcher/fingerprint 검증을 통과해야 합니다.

### Codex 검수 등급

| 등급 | 대표 범위 | 모델 | effort | fast |
|---:|---|---|---|---|
| 1 | 빠른 집중 검수 | `gpt-5.6-luna` | `max` | on |
| 2 | 일반 정확성·회귀·테스트 적정성 검수 | `gpt-5.6-luna` | `max` | on |
| 3 | cross-layer·data flow·integration·edge 검수 | `gpt-5.6-sol` | `xhigh` | off |
| 4 | architecture·security·concurrency·recovery·운영 검수 | `gpt-5.6-sol` | `xhigh` | off |
| 5 | 최종 adversarial acceptance 검수 | `gpt-5.6-sol` | `ultra` | off |

Codex 래퍼는 세션 시작에 설정을 묻지 않습니다. 호출할 때 `-TestGrade` 또는 `-ReviewGrade` 중 정확히 하나를 반드시 전달합니다. 누락하거나 둘 다 전달하면 native 인증·작업 호출 없이 종료 코드 64입니다. `-SimpleTest`는 호환용 테스트 1등급 별칭이며 다른 등급 인자와 함께 쓸 수 없습니다.

## 실행 전 사전확인

모든 래퍼는 다음 순서로 검사합니다.

1. 설정 JSON
2. 읽기 전용 `git rev-parse --show-toplevel`, `--git-dir`, `--git-common-dir` 결과와 요청한 정확한 저장소 최상위 경로
3. 선택한 PC profile의 native `.exe` 절대경로와 파일 존재 여부
4. 입력 prompt와 Codex 테스트/검수 등급
5. Grok의 비어 있지 않은 `-WriteAllowPath` 사전 쓰기 경계
6. 저장소 감시가 적용된 공급자 인증
7. 새 기준선과 새 감시 구간에서 실제 작업 모델 호출 최대 1회

인증 제한시간은 30초입니다.

- Grok: 격리된 실행 환경의 `XAI_API_KEY` 또는 `GROK_HOME\auth.json`/사용자 홈의 `.grok\auth.json`에서 비어 있지 않은 자격·갱신정보를 확인합니다.
- Opus: `claude auth status --json`을 실행합니다.
- Codex: `codex login status`를 실행합니다.

인증 직전에 안정된 저장소 기준선을 만들고 watcher를 시작합니다. 인증이 끝나거나 실패하면 watcher를 먼저 정지·drain한 다음 새 안정 스냅샷과 비교합니다. 따라서 인증이 ignored 파일을 바꾸거나 파일을 바꾼 뒤 원복해도 실제 작업은 시작하지 않습니다. mutation 오류는 인증 오류보다 우선합니다. 인증 명령의 stdout/stderr 원문은 출력하지 않습니다. 저장소 변경 없이 인증만 실패하면 `AUTH_GUIDANCE`에 로그인 명령만 안내하고 종료 코드 65로 끝납니다. 이 검사는 네트워크 장애, 계정 권한, 원격 모델 가용성을 보장하지 않습니다.

## 집/사무실 실행파일 설정

[`wrapper-config.json`](./wrapper-config.json)에 집·사무실 공통 경로 템플릿이 있습니다.

- `home`, `office`: 같은 `%USERPROFILE%`, `%APPDATA%`, `%LOCALAPPDATA%` 템플릿을 사용합니다.
- `activeMachineProfile`: 옵션을 생략했을 때 쓸 profile이며 현재 설정은 `office`입니다.

```json
"office": {
  "grokExecutable": "%USERPROFILE%\\.grok\\bin\\grok.exe",
  "opusExecutable": "%APPDATA%\\npm\\node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe",
  "codexExecutable": "%LOCALAPPDATA%\\OpenAI\\Codex\\bin\\0000000000000000\\codex.exe"
}
```

집에서는 `-MachineProfile home`, 사무실에서는 `-MachineProfile office`를 붙입니다. 두 profile은 같은 설치 규격이며 현재 PC의 세 환경변수만 확장합니다. 선택한 도구가 없으면 작업 호출 없이 종료 코드 64로 실패합니다. 상대경로와 `.cmd`·`.bat`, 그 밖의 환경변수 토큰은 허용하지 않습니다.

Codex Desktop 자동 업데이트로 설정된 `%LOCALAPPDATA%\OpenAI\Codex\bin\<16자리 해시>\codex.exe`가 사라졌을 때만 같은 `bin`의 직접 하위 해시 폴더들을 확인해 가장 최근에 수정된 정상 `codex.exe`를 자동 선택합니다. 다른 레이아웃, 재귀 검색, PATH 추측에는 적용하지 않으며 JSON을 자동으로 다시 쓰지도 않습니다. 복구되면 stderr에 `CODEX_EXECUTABLE_AUTO_RECOVERED`를 남깁니다.

AI 자식 환경은 부모 환경을 통째로 상속하지 않습니다. Windows·일반 개발도구에 필요한 값과 해당 공급자의 home/auth 값만 새 환경에 넣고 `PSModulePath`는 전달하지 않습니다. `TEMP`와 `TMP`는 부모 값과 무관하게 검증한 `%LOCALAPPDATA%\Temp` 절대경로로 고정합니다. 임시 디렉터리 정리도 생성 시 봉인한 같은 canonical base만 사용합니다. 별도 proxy 변수가 필요하면 비밀 노출 여부를 검토한 뒤 코어 허용목록에 명시적으로 추가해야 합니다.

## 작업 저장소 선택

현재 기본값은 `C:\sswcenter\3.0`입니다. USB, 다른 C: 경로 또는 GitHub에서 받은 로컬 clone/worktree는 `-RepositoryRoot`에 정확한 절대경로를 지정합니다.

```powershell
# 기본 USB 작업본에서 Grok Writer 실행
pwsh -NoProfile -File .\invoke-grok.ps1 -WriteAllowPath 'backend\app' -Prompt '요청한 기능을 구현해'

# C:의 로컬 worktree
pwsh -NoProfile -File .\invoke-grok.ps1 `
  -RepositoryRoot 'C:\work\sswcenter' `
  -WriteAllowPath 'backend\app' `
  -Prompt '요청한 기능을 구현해'

# GitHub에서 받은 로컬 clone을 Codex Sol 3등급으로 검수
pwsh -NoProfile -File .\invoke-codex.ps1 `
  -RepositoryRoot 'C:\Users\USER\GitHub\sswcenter' `
  -ReviewGrade 3 `
  -Prompt '현재 변경분을 검수해'

# 사무실 PC에서 Opus 최종 독립검수
pwsh -NoProfile -File .\invoke-opus.ps1 `
  -MachineProfile office `
  -RepositoryRoot 'C:\work\sswcenter' `
  -Prompt '현재 변경분을 최종 독립검수해'
```

쓰기 경계는 여러 번 전달할 수 있습니다.

```powershell
& .\invoke-grok.ps1 `
  -WriteAllowPath @('backend\app', 'backend\tests\test_target.py') `
  -Prompt '요청한 기능을 구현해'
```

배열형 다중 경로는 PowerShell 7 세션에서 위처럼 script를 직접 호출합니다. `pwsh -File` 명령줄에 같은 named parameter를 반복하면 PowerShell binder가 script 실행 전에 거부합니다.

`-AllowPath`는 `-WriteAllowPath`의 alias입니다. 항목은 저장소 상대경로 또는 저장소 내부 절대경로입니다. 사전확인 시 이미 존재하는 디렉터리만 그 하위 전체를 허용하며, 기존 파일과 아직 없는 경로는 exact-only입니다. 따라서 기존 파일을 같은 이름의 디렉터리로 바꿔 child를 만드는 우회도 차단됩니다. 저장소 루트와 `.git`은 허용할 수 없고, 생략하거나 빈 배열이면 native 호출 전에 종료 코드 64로 실패합니다. 기존 항목·상위 component·허용 디렉터리의 기존 하위 트리에 reparse point가 있거나 기존 파일의 hardlink 수가 1이 아니거나 조회할 수 없으면 fail-closed합니다.

Git 루트는 `.git` 표식만 신뢰하지 않고 실제 Git의 세 경로를 검증합니다. 일반 clone과 linked worktree를 지원하며, 가짜 `.git`, Git 저장소의 하위 폴더, 일반 폴더는 작업 호출 전에 차단됩니다. clone, pull, push 또는 Git 상태 변경은 하지 않습니다.

## 기본 실행

PowerShell 7에서 실행합니다.

```powershell
# Grok Writer
pwsh -NoProfile -File .\invoke-grok.ps1 -WriteAllowPath 'frontend\src' -Prompt '요청한 기능을 구현해'

# Codex 오퍼레이터가 사용하는 Opus 최종 독립검수
pwsh -NoProfile -File .\invoke-opus.ps1 -Prompt '현재 변경분을 최종 독립검수해'

# Claude Code 오퍼레이터가 사용하는 Codex Sol 3등급 검수
pwsh -NoProfile -File .\invoke-codex.ps1 -ReviewGrade 3 -Prompt '현재 변경분을 검수해'

# Codex Spark 2등급 unit/contract 테스트
pwsh -NoProfile -File .\invoke-codex.ps1 -TestGrade 2 -Prompt '지정한 unit/contract 테스트를 실행하고 결과를 보고해'

# Codex Luna 3등급 격리 DB 테스트
pwsh -NoProfile -File .\invoke-codex.ps1 -TestGrade 3 -Prompt '지정한 격리 PostgreSQL 테스트를 실행하고 결과를 보고해'

# 호환용 Spark 1등급 별칭
pwsh -NoProfile -File .\invoke-codex.ps1 -SimpleTest -Prompt '지정한 작은 테스트만 실행하고 결과를 보고해'
```

긴 요청은 UTF-8 파일로 전달할 수 있습니다. `-Prompt`와 `-PromptFile`은 둘 중 하나만 사용합니다.

```powershell
pwsh -NoProfile -File .\invoke-codex.ps1 `
  -RepositoryRoot 'C:\Users\USER\GitHub\sswcenter' `
  -ReviewGrade 4 `
  -PromptFile 'C:\요청\검수요청.txt'
```

성공한 작업 호출의 stdout은 최종 JSON 한 개입니다. 진행·경고·오류는 stderr로 분리됩니다. Codex 자식 프로세스가 끝난 뒤 저장소 guard 또는 최종 보고 검증이 실패하면 자식 stdout/stderr와 `--output-last-message` JSON을 `CODEX_CHILD_*` 표식 사이에 stderr로 보존합니다. 실패한 자식 JSON을 성공 결과로 오인하지 않도록 stdout은 계속 비워 둡니다.

wrapper core는 실제 child 캡처와 별개로, 로드 직후 `Console.OutputEncoding`과 `Console.InputEncoding`을 BOM 없는 UTF-8로 설정합니다. 따라서 CP949 같은 부모 콘솔에서도 wrapper가 최종으로 내보내는 stdout JSON과 stderr 진단은 UTF-8 바이트를 유지합니다. 이 설정은 출력 전에 시도되며, 콘솔 속성을 설정할 수 없는 host에서는 별도 오류를 내지 않습니다.

Grok Writer는 비대화형 실행에서 허용된 편집 도구가 승인 대기 없이 동작하도록 `--always-approve`를 사용합니다. 이 옵션은 도구를 추가하지 않으며, 사용 가능한 도구는 `read_file,search_replace,grep,list_dir`로 제한됩니다. Bash, 웹, MCP, 하부 에이전트 차단은 그대로 유지됩니다.

Grok Writer는 작업 중간 진행을 허용하기 위해 `--json-schema`를 사용하지 않고 `--output-format json`만 사용합니다. Grok CLI가 여러 턴의 진행문과 마지막 응답을 `text`에 이어 붙일 수 있으므로, 래퍼는 `text` 맨 끝의 JSON 객체만 최종 보고서 후보로 추출해 엄격히 검증합니다. envelope와 보고서는 최상위 객체만 허용하므로 1개짜리 배열도 거부합니다. 최종 보고는 `status`, `summary`, `changed_paths`, `tests`, `unverified` 다섯 필드만 정확한 타입으로 가져야 하며, 중복 JSON key, 추가·누락 필드, 소문자 상태, `end_turn`이 아닌 종료는 성공으로 처리하지 않습니다. 자동 재호출도 하지 않습니다.

Opus도 `--output-format json`만 사용합니다. Claude의 `--json-schema`는 보고 형식 불일치 때 같은 CLI 안에서 형식 교정 재시도를 수행할 수 있어, 모델에 한 번 맡기고 형식 오류는 그대로 종료한다는 이 래퍼의 목적과 맞지 않으므로 사용하지 않습니다. 래퍼는 `type=result`, `subtype=success`, `is_error=false`인 성공 envelope의 `result` 문자열만 받아 최종 JSON을 직접 엄격 검증합니다. 오류 envelope, 미완료 terminal reason, 주변 설명문, 누락·추가 필드와 잘못된 타입은 모두 종료 코드 20입니다.

Codex는 공식 `--output-schema`와 새 임시 `--output-last-message` 파일을 사용한 뒤 같은 스키마를 래퍼가 다시 엄격 검증합니다. 한 명령이 정책에 막혀도 같은 범위의 다른 허용된 방법으로 확인할 수 있으면 동일 호출 안에서 계속합니다. 모델·effort·fast·sandbox/network 조합은 위 등급표에서만 결정되고 사용자가 임의 조합을 전달하는 표면은 없습니다.

Codex CLI는 비대화형 실행에 맞게 `approval_policy="never"`를 유지합니다. Windows에서는 `windows.sandbox="elevated"`를 명시하고, login-shell 요청 자체를 0ms에 거부하던 `allow_login_shell=false` 강제값은 사용하지 않습니다. AI 자식 환경에는 `GIT_OPTIONAL_LOCKS=0`, `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`를 넣어 읽기 명령의 선택적 `.git/index.lock`과 인증 프롬프트를 예방합니다.

native 프로세스는 셸 파이프 배경 실행이 아니라 stdin/stdout/stderr를 모두 redirect한 `ProcessStartInfo`와 Windows Job Object로 실행하므로 콘솔 핸들 상속 hang을 피합니다. 배열 인자는 `pwsh -File script.ps1 -Param @(…)`로 넘기지 말고, 위 다중 `WriteAllowPath` 예시처럼 PowerShell 7에서 `& .\script.ps1 -Param @(…)`로 직접 호출합니다.

## 저장소 변경 봉인

각 인증·작업 구간의 기준선은 실제 Git top-level/git-dir/common-dir, HEAD와 branch, index entry, tracked 파일과 일반 untracked 파일의 현재 SHA-256 바이트로 구성됩니다. 시작 기준선은 두 번 연속 같은 digest여야 합니다. 따라서 실행 전부터 더티인 tracked/untracked 파일도 현재 바이트가 기준이며, 공급자가 그 파일을 더 수정하면 새 변화로 검출됩니다. index·HEAD·Git topology 변경도 별도로 차단합니다.

ignored 파일을 4만 개 이상 전부 매번 해시하지는 않습니다. 대신 저장소와, linked worktree일 때 저장소 밖에 있는 git-dir/common-dir를 `FileSystemWatcher`로 감시합니다. 파일·디렉터리 생성/삭제/이름변경과 내용·크기 쓰기는 감시하지만, 실제 바이트나 Git 상태를 바꾸지 않는 Windows ACL·attribute·creation-time 알림은 watcher 오탐을 막기 위해 감시 대상에서 제외합니다. ignored 파일 생성이나 파일을 바꾼 뒤 원복하는 실제 transient 쓰기는 계속 차단합니다. watcher overflow/error와 callback drain 실패는 저장소 mutation으로 오보하지 않고 `<PROVIDER>_REPOSITORY_WATCHER_UNRELIABLE`로 분리해 fail-closed하며, 오류 종류와 감지 경로를 stderr에 남깁니다.

Grok의 실제 변경 경로는 pre/post current-byte fingerprint의 worktree+index delta로 계산합니다. 모든 실제 경로가 사전 `WriteAllowPath` 안에 있어야 하고, 최종 `changed_paths`와 대소문자 무시 집합으로 정확히 일치해야 합니다. 허용 밖 변경, 미보고 변경, 실제 변경 없는 거짓 `COMPLETE`, reparse/hardlink 경계는 종료 코드 20입니다. Codex와 Opus는 실제 작업과 인증 모두 delta와 watcher 이벤트가 완전히 0이어야 합니다. provider가 nonzero, timeout, output-limit 또는 잘못된 JSON으로 끝나도 변경 검증을 생략하지 않으며 mutation 실패가 우선합니다. 어떤 경우에도 wrapper가 reset, checkout, clean 또는 자동 restore하지 않습니다.

## 종료 코드

| 코드 | 의미 |
|---:|---|
| `0` | Writer 완료/변경 불필요 또는 검수·단순테스트 PASS |
| `10` | Opus/Codex 검수·단순테스트 FAIL |
| `11` | 모델이 BLOCKED 보고 |
| `20` | 최종 구조화 보고 오류 또는 저장소 변경·쓰기 경계 위반 |
| `64` | 설정·Git 루트·실행파일·입력 오류, native 호출 0회 |
| `65` | 인증 사전확인 실패·시간초과·출력초과, 작업 호출 0회 |
| `70` | 래퍼 내부 I/O·시작·임시파일 정리 오류 또는 repository watcher 신뢰성 실패 |
| `124` | 실제 작업의 전체 제한시간 초과 |
| `125` | 실제 작업의 stdout+stderr 합산 출력 한도 초과 |
| `126` | Windows Job Object 종료 후 프로세스 트리 종료 미확인 |

그 밖의 실제 작업 CLI 비정상 종료 코드는 그대로 전달합니다. 최종 보고가 잘못돼도 자동으로 다시 호출하지 않습니다.

## 오프라인 회귀 테스트

```powershell
pwsh -NoProfile -File .\test-ai-wrappers-offline.ps1
```

현재 기대 결과:

```text
AI_WRAPPER_OFFLINE total=99 passed=99 failed=0
```

테스트는 실제 AI 대신 `%LOCALAPPDATA%\Temp` 아래의 임시 Git 저장소와 native 가짜 실행파일만 사용합니다. 인증 사전확인과 작업 호출을 별도로 세어 사전확인 실패·인증 mutation 시 작업 0회, 성공 시 작업 정확히 1회를 검증합니다. TEMP/TMP 강제와 PSModulePath 제거, 가짜 Git root와 linked worktree, 기존 더티 WIP 바이트, ignored·out-of-scope·미보고·nonzero 뒤 mutation, reparse descendant와 hardlink, empty-directory watcher event와 삭제된 parent event, attribute-only 이벤트 제외, watcher 내부 오류의 별도 분류, Grok 중복 key·추가 필드·1개짜리 배열, Codex/Opus 읽기 전용 mutation, mutation 실패 시 Codex transcript/final JSON 보존, 인증의 ignored·변경 후 원복 mutation, callback drain, Codex 10개 등급 조합, 등급 누락/충돌, 자동 업데이트 경로 복구, Git optional-lock 방지 환경, 비밀 격리와 임시파일 정리를 포함합니다.

## 의도적으로 하지 않는 것

- PATH·재귀 검색으로 실행파일이나 저장소 추측
- 래퍼 실행 때 모델 목록을 자동 조회하거나 유료 요청으로 사전검사
- 실패 후 retry, resume, fallback 또는 다른 모델 호출
- 런타임 하부 에이전트 호출
- 자동 clone, pull, stage, commit, push, reset, clean
- 사용자 승인 없는 실제 AI live smoke test

Grok의 사전 쓰기 경계와 사후 fingerprint/watcher 검증은 fail-closed 검증층이며 OS 수준 파일시스템 sandbox는 아닙니다. 명시 경로에서 외부로 이어지는 기존 reparse point와 hardlink는 공급자 시작 전에 거부하고 실행 뒤에도 다시 확인합니다. 또한 `.NET Process.Start()` 직후 Job Object 할당 전의 매우 짧은 구간은 별도 suspended-process runner 없이는 원자적으로 봉인되지 않습니다.
