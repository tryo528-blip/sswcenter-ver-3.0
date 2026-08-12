# SSWCenter 2.2 환경 및 Runner 이슈 기록

이 문서는 `C:\sswcenter\2.2` 작업 중 발생한 제품 외부 환경 문제와 AI Runner 결함을 제품 결함과 분리해 누적 기록한다. 인증정보나 API 키 값은 기록하지 않는다.

## 2026-08-05 최신 권위 상태

이 절은 2026-08-05 현재 바이트 기준이다. **권위 절의 현재 수치는 하나**이며, 아래 과거 이슈별 `상태`와 오래된 테스트 수치는 발생 이력으로만 보존한다. **이슈 ID는 유일**해야 한다(동일 ID를 다른 사안에 재사용하지 않음). 현재 판정은 이 절을 우선한다.

### 현재 정본과 디자인 동결

- 정본: `C:\sswcenter\2.2`, branch `main`, HEAD `c50f49dfff3ac4ce5b5307eca1aa765dd26ab3c9` (**사용자 `끝!` 마감 commit**, origin/main 일치).
- 현재 Git 의미 상태(마감 후 clean): **status_count=0**, **staged_count=0**, working tree clean. 구 문서의 status 23·25·41·42·43은 마감 이전 WIP 스냅샷이며 현재 값이 아니다.
- 디자인 동결: `frontend/src/**`, `frontend/public/**`, `frontend/index.html`의 tracked 129개. 마감 전후 동결 집계 SHA-256: `98c93aac800e62d021d7fab27c3c95315739c2e09e612557eb7dea7a5aba60dc` (`aggregate_match=True`, frozen diff clean, frozen untracked 0).
- force push/reset/stash 없음.
- **임시 검수 번들은 최종 검수 후 제거됨.** 환경 로그 `review/environment/operator-environment-issues.jsonl`은 최종 기록으로 **보존**(비밀 없음).

### CLOSED — Runner

- ENV-RUNNER-019/021/022/023/024/028/029: Writer는 `ExpectedWriteBytes` 또는 기존 대상 파일 크기로 유효 쓰기 바이트를 산정하고 최소 출력예산을 `max(8,192, prompt 추정, write 추정)`으로 계산한다. 명시 예산이 32,768 토큰 범위를 넘으면 `WRITER_PACKET_SPLIT_REQUIRED`, 자동 산정 대상이 너무 크면 `WRITER_PACKET_BUDGET_REQUIRED`, 사용자 `MaxTokens`가 작으면 `WRITER_OUTPUT_BUDGET_TOO_LOW`로 API 전에 거부한다. 각 쓰기 호출 직전에는 compact serialized tool arguments의 실제 UTF-8 바이트를 다시 계산해 `WRITER_WRITE_BUDGET_EXCEEDED`로 fail-closed 한다.
- ENV-RUNNER-015: 공급자 응답이 `finish_reason=length`이고 tool call이 하나라도 있으면 tool call 추출 직후 `OUTPUT_LIMIT_DURING_TOOL_CALL`로 현재 batch 전체를 원자 거부한다. `Add-AssistantMessage`, batch/freshness 검증, 현재 batch 회계 및 도구 실행 전에 중단하므로 syntactically valid `replace_text`·`apply_patch`나 mixed valid read도 반영되지 않으며, 정상 `finish_reason=stop` 도구 turn은 유지된다. (해당 봉인 시점 계약은 구현방/오퍼레이터 `404/404` 이력. 현재 수치는 아래 최신 계약 행.)
- 편집 없는 텍스트 완료는 더 이상 PASS가 아니며 `WRITER_COMPLETED_WITHOUT_EDIT`로 거부한다. 첫 편집 없이 2턴이 지나면 `forced-write`, 다음 무편집 턴에는 선택한 쓰기 도구만 노출하는 `write-only`로 전환하고, fresh read가 필요할 때만 `forced-write`로 되돌린다.
- ENV-RUNNER-020/026/030: `WriteStrategy=Auto|ReplaceText|ApplyPatch`를 유지하되 Auto는 프롬프트 언어가 아니라 allowlist 대상의 실제 경로 상태로 판정한다. 모두 기존 leaf 파일이면 `ReplaceText`, 모두 미존재하는 정확한 파일 경로이면 `ApplyPatch`, directory 또는 기존/미존재 혼합은 `WRITER_WRITE_STRATEGY_REQUIRED`다. 선택하지 않은 쓰기 도구는 노출하지 않고 호출도 `WRITER_TOOL_NOT_ALLOWED`로 거부한다.
- ENV-RUNNER-031: 공용 `invoke-deepseek.ps1 -ValidateOnly`는 축약 검사가 아니라 실제 workspace runner의 `OfflineConfig`를 호출한다. 따라서 8,192 하한, strategy, `ExpectedWriteBytes`, packet 분할 판정을 실제 호출과 동일하게 수행하며 네트워크 요청은 하지 않는다.
- ENV-RUNNER-032: checkpoint/result 구조 객체는 재귀 key-aware sanitizer로 처리하고, 일반 텍스트·Bearer·quoted-space·multiline·1단계 및 3단계 escaped JSON의 민감값을 마스킹한다. 미마스킹 marker가 남으면 기록과 결과 생성을 fail-closed 한다.
- ENV-RUNNER-033/034: 자기수정 뒤 3인수 `Math.Max`로 부팅이 막힌 사례는 최소 bootstrap으로 복구했다. `OLD_TEXT_NOT_FOUND`, malformed patch, 필수 path 누락, 6턴 무편집은 모두 허용범위 밖 쓰기 없이 안전 실패했고 반복 실패 작업은 독립 구현방으로 재배정했다.
- ReadPath/WritePath 분리, repository 경계 및 중간 reparse-point 차단, untracked path+content hash, Add File literal-plus 및 malformed marker 방어는 유지된다.
- 최신 Runner 계약 수치는 아래 “최신 제품 지원 프로필” 행만 권위 값이다. ENV-RUNNER-015 length-batch 봉인 시점의 `404/404`는 이력일 뿐 현재 수치가 아니다.

### CLOSED — 환경·도구

- ENV-TOOLING-005/006/007: `scripts/verify-workspace-seal.ps1`의 모든 Git observer 호출은 `--no-optional-locks`와 process-local `GIT_OPTIONAL_LOCKS=0`을 함께 사용한다. 시작·종료 snapshot은 HEAD, 전체 tracked/untracked, 동결 tracked/untracked, index manifest, cached diff, status fingerprint를 모두 포함하고 하나라도 바뀌면 `OBSERVER_SNAPSHOT_CHANGED`로 거부한다. worktree 및 index-only 동시 변경 음성 계약도 포함한다.
- workspace seal 계약은 구현방에서 `120/120` 연속 2회, 오퍼레이터가 독립적으로 `120/120` 1회 통과했다. 보고서 자체 갱신 전 operator checkpoint의 정본 실실행에서도 시작·종료 seal이 일치했고 `.git/index` SHA-256과 mtime은 불변, `index.lock`은 없었다.
- ENV-TOOLCHAIN-001: 외부 실행 파일 resolver 순서는 명시 인수, 저장소 `.sswcenter-ai-tools.psd1`, `PATH`, 승인된 `tool-paths.psd1`이다. 현재 PC에서 Grok은 `approved-home`, Claude는 `approved-home`, DeepSeek credential은 `approved-home`으로 확인됐다.
- DeepSeek credential 순서는 명시 EnvFile, process environment, 저장소 `.env.ai.local`, 사용자 중앙 위치, 저장소 설정, 승인된 fallback이다. 인증이 확인되면 login/logout/setup-token을 실행하지 않는다.
- Grok `grok-4.5`, Claude `claude-opus-5` xhigh safe-mode/dontAsk/Read-Glob-Grep, DeepSeek runner ValidateOnly가 모두 Ready다. 외부 AI 도구 계약 현재 수치는 권위 절 `61/61`. `sswcenter-start` skill quick validation PASS.
- 환경 로그 redactor는 quoted/unquoted, Bearer, JSON, multiline, 1단계와 3단계 escaped JSON을 fail-closed 처리한다. 계약은 `11/11` 통과했다.
- ENV-PYTHON-001과 AUTH-001은 현재 PC에서 CLOSED다. 2.2 venv와 console launcher가 현재 경로를 가리키며 공급자 재로그인 없이 인증 검증이 통과한다.
- ENV-SKILL-001: 이전 삭제 대상이던 `workday-ai-git`과 `prepare`가 다시 나타난 사실을 기록했다. exact target 확인 뒤 전자는 11개 파일, 후자는 빈 `agents` 디렉터리만 bounded 삭제했으며 현재 두 스킬 경로는 모두 absent다. 저장소 영향은 없고 재등장 원인은 UNKNOWN이다.

### 최신 제품 지원 프로필

- Ruff PASS.
- mypy PASS: 54 source files.
- backend pytest: 255 passed, 79 skipped, warning 1.
- frontend supported Vitest: 253 passed.
- frontend build PASS.
- Playwright smoke: 9 passed.
- Runner contract (현재 권위 수치, 하나): `481/481` — `scripts/invoke-deepseek-workspace.ps1` SHA-256=`978d4d57c5495ecde6a0b3e59b35180a7793a621e43aa97170b95b1a57cbe77a`, `scripts/test-invoke-deepseek-workspace.ps1` SHA-256=`0c0843c559b1ecfab68e3d1ab5cc222a6f9447af799badb685e8c2e51d404e0e` (ENV-RUNNER-037 ReadOnly edit-start 분리 포함). length-batch 이력 `404/404`는 ENV-RUNNER-015에만 연결.
- workspace seal contract: `120/120` — `scripts/verify-workspace-seal.ps1` SHA-256 `1d9d11db2e9e61046e36dfaece6a5948ab53acdf6238c5cbf9442d65c2167430` (미사용 ConvertTo-ObserverJson 제거, Record-Error non-terminating).
- external AI tools contract (현재): `61/61` — `sswcenter-start/scripts/test-ai-tools.ps1`.
- Opus wrapper contract (현재): `259/259` — `invoke-opus.ps1` SHA-256 `db4b8c053baf605e46d7a1afa73b1dc0cb167547d908170190e12c23c2b7c2b6` (relative `.\` entrypoint fix + child process contracts + JWT redaction).
- environment redaction contract: `11/11`.
- `sswcenter-start` skill quick validation: PASS.

### CLOSED — 최근 현재성 (2026-08-05 보고서 정합)

- ENV-CLAUDE-001: **CLOSED(기술 경로)**. 역사적으로 revoked/invalid_grant는 로그인 전 OPEN 원인이었으나, **사용자 Claude 1회 로그인 완료** 및 **Opus 기술 최종 검수(5 XHIGH) PASS(Critical/Major 0)** 로 기술 경로는 닫혔다. **사용자 로그인 완료, Opus 기술 최종 검수 PASS. 이번에는 사용자의 지시에 따라 보고서 자체에 대한 Opus 추가 검수는 생략함.** CredMan secret byte-seal은 아래 UNKNOWN으로 **별도** 유지(인증값 미기록). 사용자가 **`끝!`** 을 선언해 Git 마감이 진행됨.
- ENV-GROK-HOME-001 (wrapper): skill wrapper present/absent 구분 restore Minor **CLOSED**. 짧은 `ENV-GROK-HOME` 표기는 사용하지 않음.
- 임시 검수 아티팩트 정리: `review/.deepseek-opus-review`(9 files)·`review/.deepseek-runner-review`(9 files) 삭제. **임시 번들은 최종 검수 후 제거됨.** 과거 검수 당시 사용한 원본 skill/tool SHA는 계약 행·이슈 이력에 역사 증거로만 남길 수 있으며, 위 review 하위 번들 경로는 **현재 파일로 인용하지 않음**. `C:\WINDOWS\TEMP\sswcenter-*.txt`는 정리 시점에 0건(삭제 0).
- ENV-GIT-FINISH-001: **CLOSED**. `sswcenter-git-finish/scripts/git-finish.ps1`이 한글 경로(`docs/00_…문서…md`)에 대해 Git C-style quoted path 전체를 `[IO.Path]::GetFileName`에 넘겨 `Illegal characters in path`로 **stage/commit/push 전** 실패. 수정: `status --porcelain=v1 -z` + `core.quotepath=false` 바이트 파싱, status code와 path 분리, C-style unquote, repo-root containment, malformed fail-closed. 민감 경로 차단 의미 유지(전체 skip 금지). 계약 스크립트 `test-git-finish-path-parsing.ps1` + AST parse PASS. 비밀 없이 `operator-environment-issues.jsonl`에 기록.

### OPEN 또는 의도된 운영 제한

- ENV-HOST-001: Grok Writer 전체 이슈 해결보고서 작성 세션 종료 시 호스트가 `Resident session actor exited unexpectedly; reaping as DeadFailed` 경고를 냈다. **제품 코드 결함으로 단정하지 않음.** 호스트/세션 수명 이슈로 **OPEN** 기록. 비밀 없이 `review/environment/operator-environment-issues.jsonl`에 남김.
- ENV-TOOLING-008: 오퍼레이터의 최초 일반 `git status` 1회는 `--no-optional-locks` 없이 실행됐으므로 그 관찰 시점 이전의 시스템 전체 byte-for-byte 무쓰기는 사후 증명할 수 없어 UNKNOWN이다. 이후 관찰에서는 index SHA-256과 mtime 불변 및 `index.lock` 부재를 확인했다.
- ENV-GROK-HOME-001 (호스트 ambient): 호스트 런처 ambient에 GROK_HOME/HOME 미설정 가능 — **wrapper CLOSED와 분리된 외부 UNKNOWN**.
- CredMan secret byte-seal: UNKNOWN (name-count only; secret 값 미독·미기록). ENV-CLAUDE-001 기술 경로 CLOSED와 혼동하지 않음.
- RUNNER-013: 한 턴 한 파일 한 write는 의도된 안전 제한이다. 다중 파일 packet은 오퍼레이터가 독립 packet으로 나눈다.
- TOOLING-004: `$`, 백틱 또는 긴 다중행 프롬프트는 `PromptFile`이 필수다.
- TOOLING-001/THREAD-001: 세션 interrupt 및 Desktop message handler 상태는 제품 외부 환경이다. 전달 여부를 먼저 확인하고 중복 호출하지 않는다.
- HARNESS-001: 현재 후보가 dirty인 동안 CleanHead 전용 0014 live wrapper는 성공 경로를 실행할 수 없다.
- PYTEST-001: live PostgreSQL 및 historical 전체 프로필은 외부 전제 또는 별도 clean 후보가 필요하며 이번 최신 지원 프로필에는 포함하지 않았다.

### 최신 수정 과정에서 추가 기록한 비차단 실패

- 대형 DeepSeek 자기수정 packet은 483,129ms, 31 requests, 약 7.9M cumulative prompt를 사용하고도 일부 수정과 미완료 항목을 함께 남긴 채 PASS를 반환했다. 결과를 완료 증거로 채택하지 않고 packet을 분해했다.
- `OLD_TEXT_NOT_FOUND`, malformed patch, `read_file` 필수 path 누락, 6턴 무편집 및 write budget 초과는 모두 fail-closed 됐다. 반복 실패 범위는 독립 구현방으로 재배정해 현재 계약으로 봉인했다.
- 자기 호스팅 runner가 3인수 `Math.Max`를 만들며 다음 호출을 부팅하지 못한 사례는 최소 bootstrap 복구로 닫았고 아래 상세 이력에 남겼다.
- 비차단: read-only hash manifest PowerShell 명령 한 번이 `foreach` 뒤 빈 pipe parser error로 실행 전에 종료됐고, corrected in-memory array 명령은 정상 완료됐다.

## 2026-08-04

### ENV-RUNNER-001 — 다중 AllowPath 전달 실패

- 구분: `sswcenter-start` DeepSeek 호출 래퍼
- 증상: Writer 호출이 시작되기 전에 `A positional parameter cannot be found that accepts argument ...`로 종료했다.
- 영향: DeepSeek API 호출 및 제품 파일 변경 모두 발생하지 않았다.
- 원인: `invoke-deepseek.ps1`이 `powershell.exe -File`의 평면 인자 배열 뒤에 여러 `AllowPath` 값을 붙였다. Windows PowerShell의 스크립트 배열 매개변수 바인딩에서 첫 값 뒤의 경로가 위치 인자로 해석됐다.
- 조치: 래퍼가 동일 PowerShell 프로세스에서 해시테이블 splatting으로 workspace runner를 호출하고 `AllowPath`를 실제 `string[]`로 전달하도록 변경했다.
- 재발 방지: 둘 이상의 허용 경로를 사용하는 실제 Writer 호출을 검증 대상으로 유지한다.
- 상태: 조치 완료. 후속 실제 호출에서 7개 허용 경로가 모두 정상 읽혀 검증 완료.

### ENV-RUNNER-002 — 정상 API 응답의 선택 속성 접근 실패

- 구분: `scripts/invoke-deepseek-workspace.ps1` 2.2.0
- 증상: API 요청은 약 5.5초 만에 응답했지만 `The property '__runner_error' cannot be found on this object`로 종료했다.
- 영향: 응답 처리 전에 중단되어 tool call과 제품 파일 변경은 0건이었다.
- 원인: StrictMode에서 정상 응답에 존재하지 않는 선택 속성을 `$response.__runner_error`로 직접 읽었다. 오류 응답에만 해당 속성이 존재한다.
- 조치: `PSObject.Properties[...]`로 속성 존재 여부를 먼저 확인하고, 선택적인 상세 오류 속성도 같은 방식으로 읽도록 변경했다.
- 재발 방지: Runner 계약 테스트에 두 선택 속성의 StrictMode 안전 가드가 존재하는지 확인하는 회귀 검사를 추가했다.
- 상태: 조치 완료. Runner 계약 `112/112` 및 후속 실제 응답 처리로 검증 완료.

### ENV-RUNNER-003 — Thinking 도구호출 후속 요청 HTTP 400

- 구분: DeepSeek thinking-mode 다단계 tool call 재전송
- 증상: 첫 응답에서 7개 `read_file` 호출은 정상 완료됐으나 도구 결과를 포함한 두 번째 요청이 HTTP 400으로 거절됐다.
- 영향: 읽기만 수행됐고 제품 파일 변경은 0건이었다. 체크포인트는 안전하게 저장됐다.
- 원인: 메시지 계약 자체보다 Windows PowerShell 5.1의 `Invoke-RestMethod` 후속 전송 경로에 있었다. 동일한 thinking 메시지와 tool result를 .NET `HttpClient`로 전송하자 두 번째 요청이 정상 완료됐다. 기존 경로는 공급자 오류 본문도 폐기해 상세 원인을 남기지 못했다.
- 조치: API 응답의 tool call은 입력 계약의 `id`, `type`, `function` 필드로 정규화하고 `reasoning_content`를 보존한다. 실제 전송은 UTF-8 `StringContent`를 사용하는 .NET `HttpClient`로 교체했으며, 실패 시 구조화된 공급자 오류 코드와 메시지만 안전하게 회수한다.
- 재발 방지: Runner 계약 테스트에 tool-call 정규화와 .NET HTTP 응답 본문 회수 가드를 추가했다.
- 상태: HTTP 400 해소 확인. 후속 요청이 실제로 `stop` 응답까지 도달함.

### ENV-RUNNER-004 — 최종 응답의 선택 tool_calls 접근 실패

- 구분: `scripts/invoke-deepseek-workspace.ps1` StrictMode 응답 처리
- 증상: 두 번째 API 요청은 정상 완료됐지만 최종 `stop` 응답에 `tool_calls` 속성이 없어서 속성 접근 예외가 발생했다.
- 영향: 파일 읽기만 수행했고 제품 파일 변경은 없었다. 최종 텍스트를 결과로 확정하기 직전에 중단됐다.
- 원인: 최종 자연어 응답에는 `tool_calls`가 선택 필드인데 직접 속성으로 읽었다.
- 조치: `PSObject.Properties['tool_calls']` 존재 여부를 확인한 뒤에만 배열을 읽도록 변경했다.
- 재발 방지: 동일한 StrictMode 가드를 Runner 계약 테스트에 추가했다.
- 상태: 조치 완료. Runner 계약 `116/116`과 실제 thinking-mode 2요청 프로브 `PROBE_OK`로 검증 완료.

### ENV-PYTHON-001 — 2.2 backend 가상환경 실행 파일 연결 단절

- 구분: 로컬 Python 의존성 환경
- 증상: `backend\.venv\Scripts\python.exe` 실행 시 존재하지 않는 `C:\Users\sswce\AppData\Local\Programs\Python\Python311\python.exe`를 찾는다는 오류가 발생했다.
- 영향: 2.2 자체 가상환경으로 Python 진단 및 테스트를 실행할 수 없다.
- 원인: 다른 Windows 사용자 또는 이전 설치 경로에서 복사된 가상환경으로 보이며, 현재 호스트의 기반 Python과 연결되지 않는다.
- 조치: 환경 자체는 임의 재설치하지 않았다. 검증 시 승인된 대체 인터프리터를 명시하고 실행 경로 차이를 결과에 남긴다.
- 재발 방지: 2.2 전용 가상환경을 현재 호스트에서 재생성하기 전까지 자체 `.venv`를 정상 환경으로 간주하지 않는다.
- 상태: 미해결 환경 이슈로 기록.

### ENV-RUNNER-005 — 대형 파일 교정 중 4턴 무수정 조기 중단

- 구분: DeepSeek workspace runner 진행 정체 보호
- 증상: 2,700줄 규모 postcheck와 관련 테스트 교정 중 4턴에 걸쳐 10회 읽기·검색을 수행했으나, 첫 편집 전에 `NO_PROGRESS_LIMIT_REACHED`로 중단됐다.
- 영향: 교정 제품 파일 변경은 0건이었다. 기존 P0 변경은 보존됐다.
- 원인: 무한 탐색 방지 기준 4턴이 대형 파일의 근거 탐색에는 지나치게 짧았다.
- 조치: 4턴에는 경고만 남기고, 객관적 편집 진전이 8턴 연속 없을 때 안전 중단하도록 완화했다. 편집이 발생하면 카운터는 즉시 초기화된다.
- 재발 방지: 계약 테스트가 서로 다른 8회 검색 후 정확히 중단되는지 검증한다. 동일 도구 배치 반복 차단과 전체 turn/context 한도는 그대로 유지한다.
- 상태: 조치 완료. 계약 `116/116` 통과 후 교정 재호출이 기존 4턴을 넘어 편집을 완료해 검증됨.

### ENV-RUNNER-006 — 공개 .env.example 템플릿까지 민감 경로로 차단

- 구분: Writer allowlist 민감 경로 보호
- 증상: 보안 설정 교정 패킷이 API 호출 전에 `ALLOWLIST_SENSITIVE_PATH`로 중단됐다.
- 영향: 제품 파일 변경과 API 호출은 모두 0건이었다.
- 원인: `.env`, `.env.local`, `.env.ai.local` 등을 차단하는 규칙이 Git 공개 템플릿인 저장소 루트의 정확한 `.env.example`에도 동일하게 적용됐다.
- 조치: 오직 정규화된 루트 상대경로 `.env.example`만 공개 템플릿으로 허용했다. 다른 위치의 `.env.example`과 모든 실제 `.env*`, auth, secret, credential 경로 차단은 유지한다.
- 재발 방지: `.env` 차단과 루트 `.env.example` 허용을 각각 Runner 계약 테스트로 검증한다.
- 상태: 조치 완료. Runner 계약 `118/118` 통과 및 보안 패킷의 `.env.example` 수정 완료로 검증됨.

### ENV-RUNNER-007 — 새 허용 파일 생성 전 read_file 실패

- 구분: Writer 신규 파일 생성 흐름
- 증상: 새 `frontend/playwright.smoke.config.ts`를 만들기 위해 Writer가 먼저 읽기를 시도하자 `FILE_NOT_FOUND`가 leading tool failure로 처리되어 전체 패킷이 중단됐다.
- 영향: 제품 파일 변경은 0건이었다.
- 원인: 명시적으로 allowlist에 포함된 미존재 경로도 일반 읽기 오류로 처리해 `apply_patch`의 `Add File` 단계에 도달할 수 없었다.
- 조치: 정확히 allowlist에 포함된 미존재 파일의 `read_file`은 성공 응답으로 `exists=false`, `bytes=0`, 빈 content를 반환한다. 존재 파일은 `exists=true`를 반환한다. `Add File`도 edit와 patch 계측을 각각 1건 올린다. 허용되지 않은 경로와 민감 경로 보호는 변하지 않는다.
- 재발 방지: 미존재 허용 파일 읽기 후 `Add File` 패치로 생성하는 전 과정을 Runner 계약 테스트에 추가했다.
- 상태: 조치 완료. Runner 계약의 missing-read 후 Add File 생성은 통과함.

### ENV-RUNNER-008 — apply_patch 형식 계약 불명확

- 구분: Writer patch tool 호출 규격
- 증상: Writer가 일반 `diff --git` unified diff를 전송해 `PATCH_FORMAT_INVALID`로 중단됐다.
- 영향: 패치는 적용 전 거부됐고 제품 파일 변경은 0건이었다.
- 원인: 도구 설명은 단일 파일이라고만 했고 Runner가 요구하는 `*** Begin Patch` / `*** Add File|Update File` / `*** End Patch` 형식을 명시하지 않았다.
- 조치: apply_patch 도구 설명과 Writer 시스템 메시지 모두에 정확한 단일 파일 Codex patch 형식과 `diff --git` 금지를 명시했다.
- 재발 방지: 형식 지침이 두 위치에 존재하는지 Runner 계약 테스트로 검증한다. 잘못된 패치를 쓰기 전에 거부하는 fail-closed 동작은 유지한다.
- 상태: Codex marker 형식 안내는 계약 테스트로 검증됨.

### ENV-RUNNER-009 — Add File 본문의 + 접두 요구로 재중단

- 구분: Writer 신규 파일 patch 파서
- 증상: Writer가 올바른 `*** Begin Patch`와 `*** Add File` 마커를 사용했지만 본문을 일반 원문 줄로 보내 `PATCH_ADD_LINE_INVALID`가 발생했다.
- 영향: 생성 전 거부되어 제품 파일 변경은 0건이었다.
- 원인: Add File 파서가 모든 줄에 `+` 접두를 요구했으나 도구 계약에는 그 요구가 명시되지 않았다.
- 조치: allowlist와 단일 Add File 마커로 경로가 봉인된 신규 파일 본문은 일반 원문 줄과 `+` 접두 줄을 모두 허용한다. 내부 `***` 마커 삽입은 계속 거부하며 Update File hunk 파서는 변경하지 않았다.
- 재발 방지: 일반 원문 Add File을 실제 생성하는 Runner 계약 테스트로 검증한다.
- 상태: 조치 완료. Runner 계약 `122/122` 통과 및 실제 Writer의 `frontend/playwright.smoke.config.ts` Add File 성공으로 실호출까지 검증됐다.

### ENV-RUNNER-010 — 읽기 참고 파일과 쓰기 허용 파일을 하나의 allowlist로만 표현

- 구분: Writer 최소 권한 파일 범위
- 증상: Writer가 변경하면 안 되는 기존 `frontend/playwright.config.ts`를 참고하려고 `read_file`을 호출하자 `PATH_NOT_ALLOWLISTED`로 즉시 중단됐다.
- 영향: API 호출 1회, 도구 호출 1회 후 종료됐고 제품 파일 변경은 0건이었다.
- 원인: 현재 Runner의 `AllowPath`는 읽기와 쓰기 권한을 함께 부여한다. 따라서 참고용 읽기 파일을 제외하면 조사 단계가 막히고, 포함하면 기술적으로는 쓰기 권한까지 열리는 한계가 있다.
- 임시 조치: 해당 파일의 사전 SHA-256을 고정하고 allowlist에 포함하되, Writer에게 변경 금지를 명시한 뒤 호출 직후 해시 불변을 독립 확인한다.
- 개선 후보: 후속 Runner 교정에서 `ReadPath`와 `WritePath`를 분리하고, 쓰기 도구는 `WritePath`만 허용하도록 계약 테스트와 함께 강화한다.
- 상태: 임시 조치 검증 완료. 기준 해시 `4d71f99f8df7038e1beec1611a7ba17cfb911dbbfbe98cfaab742223c46868b6`가 호출 전후 동일했고 Writer 변경 경로에도 포함되지 않았다. 구조 개선은 기록된 후속 과제로 유지한다.

### ENV-E2E-001 — 기존 비 real-PG 후보도 모두 독립 스모크는 아님

- 구분: 기본 Playwright 스모크 후보 선별
- 증상: 세 후보 파일 45건은 정상 수집됐지만 실제 실행에서 `w1b-recipients-red.spec.ts` 일부가 `127.0.0.1:8000`으로 통과 요청을 보내 연결 거부됐고, `wave0-shell.spec.ts`의 첫 시나리오는 현재 화면에 없는 `header-btn-new-schedule`을 기다리다 30초 제한으로 실패했다.
- 영향: 최초 스모크 구성은 기본 명령으로 독립 실행 가능한 GREEN 묶음이 아니었다. 제품 파일은 이 검증으로 변경되지 않았다.
- 원인: 파일명에 `real-pg`가 없다는 사실만으로 독립 스모크라고 간주했지만, W1B RED 패킷에는 일부 API 통과 경로가 있고 Wave 0 계약은 현재 정본 UI와 불일치한다.
- 조치: 현재 정본 디자인과 기존 RED 계약을 고쳐서 억지로 통과시키지 않는다. 실제 독립 실행이 확인된 완전 mock 기반 `w1c-certification.spec.ts`만 기본 스모크로 재선정하고, real-PG/RED/과거 Wave 0 계약은 각 전용 검증 흐름에 남긴다.
- 재발 방지: 설정의 `--list`뿐 아니라 백엔드 없는 실제 실행을 기본 스모크 완료 조건으로 둔다.
- 상태: 조치 완료. 기본 수집은 `1 file / 9 tests`, 백엔드 없는 실제 실행은 `9 passed`로 검증됐다.

### ENV-TOOLING-001 — 실행 중 Playwright 세션에 인터럽트 전달 불가

- 구분: Codex 통합 실행 세션 제어
- 증상: 이미 충분한 실패 근거를 확보한 45건 실행에 Ctrl+C를 보내자 `process interrupt is not supported by this process backend`가 반환됐다.
- 영향: 실패가 반복되는 다음 테스트들이 계속 실행되어 불필요한 대기와 로그가 발생했다.
- 조치: 명령행에 현재 저장소의 `playwright.smoke.config.ts` 또는 Vite 경로가 명확히 표시된 프로세스 ID만 조회·확인한 뒤 해당 Playwright와 Vite 프로세스만 종료했다.
- 재발 방지: 불확실한 장기 묶음은 먼저 단일 프로젝트·단일 테스트로 검증하고, 통합 실행은 후보가 GREEN인 뒤 수행한다.
- 상태: 실행 세션과 Vite 종료 확인 완료. 제품 파일 영향 없음.

### ENV-RUNNER-011 — 대형 파일 연속 치환에서 이전 문맥 재사용

- 구분: DeepSeek Writer 대형 단일 파일 교정
- 증상: 약 1,800줄 PowerShell 검증기에서 두 번의 치환은 성공했지만 세 번째 도구 호출이 이미 바뀐 이전 문맥을 다시 `old_text`로 사용해 `OLD_TEXT_NOT_FOUND`로 종료됐다.
- 영향: 앞선 두 변경만 원자적으로 보존됐고 이후 교정은 적용되지 않았다. PowerShell 파서 오류는 0건이었다.
- 원인: 모델이 초기 읽기 문맥을 기준으로 여러 순차 치환을 계획했으나 선행 치환 후의 최신 바이트를 세 번째 호출에 반영하지 못했다. Runner는 첫 쓰기 실패를 leading failure로 처리해 후속 쓰기를 안전하게 차단했다.
- 조치: 현재 파일을 다시 읽는 새 Writer 패킷으로 남은 교정을 이어간다. 성공한 앞선 변경을 되돌리거나 직접 덮어쓰지 않는다.
- 개선 후보: 대형 파일의 다단계 Writer 작업은 작은 단계별 패킷으로 나누고, 각 쓰기 뒤 최신 파일 재읽기를 프롬프트와 Runner 지침에 명시한다. `OLD_TEXT_NOT_FOUND` 때 민감정보 없는 주변 문맥을 제한적으로 반환하는 기능도 검토한다.
- 상태: 같은 유형이 후속 대형 패킷과 첫 소형 정확 치환에서도 재현됐다. 이후 변경을 고유 주변 문맥이 포함된 단일 `apply_patch` 패킷으로 전환하자 연속 성공했다. 안전 중단·부분 변경 보존·파서 정상은 유지됐다.

### ENV-RUNNER-012 — PowerShell 호출 문자열에서 프롬프트의 `$변수명` 선확장

- 구분: Operator에서 DeepSeek Wrapper로 프롬프트 전달
- 증상: `$Mode`를 `$CandidateMode`로 바꾸라는 소형 패킷에 Writer가 두 이름이 동일하다고 오판하고 쓰기 0건으로 종료했다.
- 영향: 파일 손상은 없었지만 호출 1회와 약 40초가 낭비됐고, 앞선 0014 상세 지시의 PowerShell 변수명도 일부 소실됐을 가능성이 확인됐다.
- 원인: `-Prompt` 값을 PowerShell 큰따옴표 문자열로 구성해 프롬프트 내부의 `$CandidateMode`, `$PythonExecutable` 등이 Wrapper 호출 전에 현재 셸 변수로 확장됐다.
- 조치: `$`를 포함하는 모든 Writer 프롬프트는 PowerShell의 확장 없는 single-quoted here-string으로 만들고 그 변수를 `-Prompt`에 전달한다. API 키나 인증 값은 프롬프트에 포함하지 않는다.
- 개선 후보: Wrapper에 UTF-8 `-PromptFile` 또는 base64 입력 매개변수를 추가해 호출 셸의 인용·변수 확장과 분리한다.
- 상태: 조치 완료. 리터럴 here-string 호출에서 `$CandidateMode`와 `$PythonExecutable` 이름이 보존됐고, 정확 패치 적용까지 확인했다.

### ENV-TOOLING-002 — 문서 Writer here-string 종료표시 누락

- 구분: Operator PowerShell 호출 구성
- 증상: 문서 정리 패킷이 `The string is missing the terminator: '@` 파서 오류로 즉시 종료됐다.
- 영향: Wrapper·API 호출과 파일 변경은 모두 0건이었다.
- 원인: single-quoted here-string을 도입하는 과정에서 닫는 `'@` 줄을 한 번 누락했다.
- 조치: 종료표시를 독립된 줄에 추가해 동일 패킷을 재호출했고 두 문서 변경이 정상 완료됐다.
- 재발 방지: `$` 포함 프롬프트는 리터럴 here-string을 사용하되, 실행 전 여는 `@'`와 닫는 `'@`가 각각 독립된 줄인지 확인한다.
- 상태: 재호출 성공, 제품 파일의 부분 변경 없음.

### ENV-HARNESS-001 — 수정 중 작업트리에서는 CleanHead 성공검증 불가

- 구분: 0014 PostgreSQL Wrapper `CleanHead` 사전검사
- 증상: 정확한 현재 HEAD를 전달해도 작업 중 변경 15건 때문에 `SSWCENTER_0014_HARNESS_CLEAN_HEAD_REQUIRED`로 종료됐다.
- 영향: 성공 GREEN은 현재 dirty 정본에서 만들 수 없었다. 이는 의도한 실패-폐쇄 동작이다.
- 조치: 깨진 2.2 venv 대신 명시적 `-PythonExecutable C:\sswcenter\2.1\backend\.venv\Scripts\python.exe`를 사용해 다른 환경 선행 실패를 분리했다. PowerShell 파서 오류 0, 종료 1, 새 `sswcenter-0014-pg-*` 임시 폴더 0을 확인했다.
- 후속 검증: 변경이 최종 커밋되어 정확 SHA의 clean checkout이 생긴 뒤 `-CandidateMode CleanHead -PreflightOnly -ExpectedSha <exact-sha>` 성공을 검증해야 한다.
- 상태: 실패-폐쇄 경계 검증 완료, 성공 경로는 clean 후보 생성 전까지 보류.

### ENV-RUNNER-013 — 여러 파일용 응답을 단일 파일 patch 도구에 전달

- 구분: DeepSeek Writer 다중 파일 교정
- 증상: Writer가 여러 파일 변경을 하나의 `apply_patch` 호출에 합치면서 `PATCH_HUNK_LINE_INVALID`가 발생했다. 이후 소형 정확 치환에서도 같은 계열의 잘못된 hunk 형식이 한 번 재현됐다.
- 영향: 각 실패 호출의 patch는 적용 전에 전부 거부됐고, 해당 호출로 생긴 제품 파일 변경은 0건이었다. 앞서 성공한 별도 변경은 그대로 보존됐다.
- 원인: Runner 도구는 호출당 단일 파일 patch만 허용하지만 모델이 다중 파일 diff처럼 응답했거나, hunk 본문 줄의 필수 접두 문자를 빠뜨렸다.
- 조치: 파일별로 독립된 Writer 패킷을 만들고, 고유한 현재 문맥을 포함한 단일 `*** Update File` patch만 요청했다. 실패한 묶음을 재사용하지 않고 각 파일의 최신 바이트를 다시 읽게 했다.
- 개선 후보: 도구 설명에 다중 `Update File` 마커의 명시적 금지와 hunk 줄 접두 규칙을 더 짧은 예제로 고정하고, 잘못된 다중 파일 응답을 재현하는 계약 테스트를 추가한다.
- 상태: 우회 완료. 후속 파일별 정확 patch가 적용됐고 통합검증까지 통과했다.

### ENV-RUNNER-014 — Writer tool 인수에서 역슬래시 소실

- 구분: DeepSeek tool-call JSON과 PowerShell·정규식 문자열 전달
- 증상: Writer가 읽은 `backend\.venv\Scripts\python.exe`를 patch 인수에서는 `backend.venvScriptspython.exe`로, 정규식 `(\?|$)`를 `(?|$)`로 전달했다. 그 결과 실제 파일 문맥과 일치하지 않아 `PATCH_CONTEXT_NOT_FOUND`가 반복됐다.
- 영향: 실패한 patch는 모두 적용 전 거부됐으며 해당 호출의 파일 변경은 0건이었다. 인증이나 API 연결 실패는 아니었다.
- 원인: 모델이 생성한 tool-call 문자열 또는 Runner의 tool 인수 역직렬화 단계에서 역슬래시가 이스케이프 문자로 소비된 것으로 보인다. 정확한 소실 단계는 아직 분리되지 않았다.
- 조치: 기존 역슬래시 포함 줄은 건드리지 않고, Python override는 그 뒤에 새 블록으로 추가했다. URL 정규식은 역슬래시가 필요 없는 `[?]` 표현을 사용했다.
- 개선 후보: `read_file`로 얻은 역슬래시 문자열을 `apply_patch`에 그대로 되돌리는 왕복 계약 테스트를 추가하고, Wrapper에 `-PromptFile` 또는 명확한 JSON 이중 이스케이프 경계를 둔다.
- 상태: 제품 교정은 우회 완료. Runner 자체의 역슬래시 왕복 보강은 후속 과제로 기록한다.

### ENV-PYTEST-001 — 2.2 새 저장소에서 과거 Git 객체 및 live PostgreSQL 전제가 없음

- 구분: 백엔드 전체 `pytest -q` 프로필
- 증상: 무조건 전체 수집을 실행하면 `32 failed, 244 passed, 76 skipped`였다. 이 중 17건은 live PostgreSQL URL이 없는 상태에서 실행된 `test_w1a_vs6_postgres.py`였고, 나머지 과거 W1B/W1D/W1E 계약군은 2.1 정본의 고정 Git 객체와 당시 OpenAPI 기준을 요구했다.
- 확인: 새 2.2 저장소에는 과거 기준 SHA `e204023a...`, `a86567fe...`, `122f428f...` 객체가 존재하지 않는다. 현재 제품 결함과 과거 저장소 증거 부재를 같은 실패로 취급하면 기본 로컬 검증이 항상 RED가 된다.
- 조치: `scripts/test.ps1` 기본 프로필은 live PostgreSQL 파일과 세 과거 계약 파일을 명시적으로 제외한다. `-RequirePostgres`와 `-IncludeHistoricalContracts`를 주면 각 전용 프로필을 명시적으로 요청할 수 있고, 실행 시 `SSWCENTER_TEST_PROFILE`을 출력한다.
- 검증: 대체 Python 경로를 명시한 기본 지원 프로필은 Ruff 통과, mypy `54 source files` 통과, pytest `230 passed, 76 skipped`, 프런트 단위테스트 `253 passed`, 빌드 성공, Playwright 스모크 `9 passed`로 종료 0이었다.
- 잔여 조건: live PostgreSQL 프로필은 `_test` 또는 `_review` 데이터베이스 URL이 필요하다. 과거 계약 프로필을 재현하려면 해당 Git 객체와 당시 계약 기준을 별도로 공급해야 한다.
- 상태: 프로필 분리 및 기본 GREEN 검증 완료. 원시 전체 실행의 실패 근거는 숨기지 않고 본 기록에 유지한다.

### ENV-THREAD-001 — 기존 독립방 재지시 handler 부재

- 구분: Codex Desktop 독립방 조정
- 증상: 기존 `독립방 4`에 정본 최종 재검수 지시를 보내는 호출이 `No handler registered for tool: send_message_to_thread`로 거부됐다.
- 영향: 호출 결과만 보면 전달 여부가 불명확했다. 같은 방에 중복 재전송하지 않았고 독립방 및 제품 파일 변경은 없었다.
- 조치: 곧바로 기존 방을 읽기 전용 조회했다. 조회 결과 재검수 메시지가 실제로 전달되어 4번방이 수행 중임을 확인했다.
- 상태: Desktop 도구 반환값과 실제 전달 상태가 불일치한 환경 이슈로 기록. 중복 dispatch 방지 절차가 유효했으며 제품 결함은 아님.

### ENV-AUTH-001 — 2.2 로컬 DeepSeek 자격 증명 파일 부재와 2.1 fallback

- 구분: DeepSeek 인증 경로
- 확인: `C:\sswcenter\2.2\.env.ai.local`은 없고, 설정된 집 PC fallback인 `C:\sswcenter\2.1\.env.ai.local`은 존재한다. 키 값은 읽어 출력하거나 문서에 복사하지 않았다.
- 영향: 현재 집 PC에서는 fallback으로 실호출이 성공하지만, 2.1 폴더가 이동·삭제되거나 사무실 PC 경로가 다르면 2.2 Writer 호출이 인증 전 단계에서 막힐 수 있다.
- 조치: 이번 세션은 이미 검증된 2.1 자격 증명 위치를 사용했다. 인증 실패로 오판하지 않고 경로 의존성으로 분리했다.
- 개선 후보: 실제 사무실 경로를 확인한 뒤 `tool-paths.psd1`의 두 번째 고정 후보로만 추가한다. 키 파일 자체를 저장소에 복사하거나 커밋하지 않는다.
- 상태: 집 PC 호출 성공. 2.2 자체 자격 증명 파일은 없음.

### ENV-TOOLCHAIN-001 — 실행 도구의 고정 설치경로 및 fresh setup 문서 부족

- 구분: Windows 개발·검증 도구 탐색
- 확인: 일부 스크립트가 Node 및 PostgreSQL의 표준 설치 위치를 고정 경로로 사용한다. 현재 PC의 `C:\Program Files\nodejs\npm.cmd`와 `C:\Program Files\PostgreSQL\17\bin\psql.exe`는 존재하지만, 2.2의 복사된 `.venv`는 실행 파일이 있어도 기반 Python 연결이 깨져 있다.
- 영향: 현재 PC에서는 명시적 Python override로 검증할 수 있지만, PATH-only 설치나 다른 Python 사용자 경로의 새 PC에서는 시작 절차가 재현되지 않을 수 있다.
- 조치: `scripts/test.ps1`에 절대 `-PythonExecutable` override를 추가해 현재 검증을 복구했다. 의존성 재설치나 환경 변경은 사용자 승인 없이 수행하지 않았다.
- 개선 후보: 공통 resolver를 `명시적 매개변수 → workspace runtime → PATH → 승인된 고정 경로` 순서로 적용하고, fresh clone의 Python venv·npm·PostgreSQL 준비 절차를 문서화한다.
- 상태: 현재 PC 지원 프로필은 GREEN. 이식성 개선은 후속 과제로 기록한다.

### 인증 및 경로 판정

- 위 두 실패는 인증 실패가 아니다. 두 번째 호출은 DeepSeek API 엔드포인트까지 정상 도달했다.
- API 키 값과 인증 헤더는 로그 및 이 문서에 기록하지 않았다.
- 제품 수정과 무관한 환경·경로·인증·포트·의존성 이슈가 추가로 발생하면 같은 형식으로 이 문서에 누적한다.

### ENV-RUNNER-015 — 대형 단일 패치가 출력 한도에서 잘려 잘못된 JSON으로 종료 (초기 보고)

- 구분: DeepSeek Writer 대형 PowerShell 정리 패치
- 증상: 1,900줄 규모의 0014 래퍼에서 Legacy 전용 분기를 한 번에 제거하도록 요청한 호출이 약 409초 동안 응답한 뒤 completion 32,768토큰 한도에 도달했다. 마지막 `apply_patch` 도구 인수가 완성되지 않아 `TOOL_ARGUMENTS_INVALID_JSON`, `LEADING_TOOL_FAILURE`로 종료됐다.
- 영향: 읽기 2회 뒤 첫 쓰기 도구 호출이 적용 전에 거부되어 변경 파일은 0개였다. 기존 dirty 정본 바이트는 보존됐다.
- 원인: 모델이 여러 분기 제거를 하나의 거대한 패치 도구 호출로 구성했고, 도구 JSON이 닫히기 전에 출력 한도에 도달했다. 인증·API 경로 실패는 아니다.
- 조치: 같은 대형 요청을 재호출하지 않는다. 공개 진입점에서 Legacy 모드를 먼저 차단하는 작은 교정과 계약 테스트를 파일별로 분리하고, 각 호출에 `replace_text` 또는 작은 단일 파일 패치만 허용한다.
- 최종 조치: `finish_reason=length`와 tool call이 함께 오면 인수의 JSON 유효성이나 도구 종류와 무관하게 tool call 추출 직후 batch 전체를 `OUTPUT_LIMIT_DURING_TOOL_CALL`로 원자 거부한다. assistant 대화 추가, batch/freshness 검증, 현재 batch 회계와 도구 실행은 시작하지 않는다.
- 상태: CLOSED. Room4가 syntactically valid write가 실행될 수 있는 원자성 공백을 M1로 REJECT했고, 수정 후 구현방 `404/404` 연속 2회와 오퍼레이터 독립 `404/404` 1회가 통과했다.

### ENV-RUNNER-016 — 작은 테스트 패치에서도 malformed hunk와 stale old-text가 연속 발생

- 구분: DeepSeek Writer 단일 Python 테스트 파일 교정
- 증상: 첫 호출은 쓰기 전 `PATCH_HUNK_LINE_INVALID`로 종료됐다. `apply_patch`를 금지하고 세 개의 `replace_text`로 재호출하자 import와 경로 상수 두 건은 적용됐지만, 마지막 치환은 이미 바뀐 현재 문맥을 찾지 못해 `OLD_TEXT_NOT_FOUND`로 종료됐다.
- 영향: 첫 호출은 변경 0개였다. 두 번째 호출은 명시된 두 치환만 적용된 부분 성공이었고 파일 문법은 깨지지 않았다. 적용된 현재 바이트를 다시 읽어 마지막 함수 추가만 별도 호출해 완료했다.
- 조치: 실패 뒤 원복이나 처음부터 재작업하지 않고, 변경 해시와 현재 파일을 확인한 후 남은 한 블록만 정확 치환했다. 최종 PowerShell 파서 정상, 관련 pytest 8개 통과, 퇴역 모드 동적 호출 exit 1을 확인했다.
- 개선 후보: 각 성공한 도구 호출 뒤 모델 컨텍스트에 최신 파일 버전을 강제로 갱신하고, `OLD_TEXT_NOT_FOUND`일 때 즉시 전체 작업을 중단하기보다 재읽기 후 남은 허용 작업만 계속하는 안전한 복구 상태를 제공해야 한다.
- 상태: 우회 완료. Runner 자체의 부분 성공 복구 정책은 후속 개선 대상.

### ENV-RUNNER-017 — 성공한 교정 뒤 최종 read_file이 빈 경로로 실패

- 구분: DeepSeek Writer 완료 보고 단계
- 증상: postcheck의 Ruff/mypy 교정 6개가 모두 성공한 뒤, 모델의 마지막 확인용 `read_file` 호출이 path 없이 전송되어 `PATH_REQUIRED`, `LEADING_TOOL_FAILURE`로 종료됐다.
- 영향: 제품 교정은 모두 적용된 상태였으나 Runner 결과는 PARTIAL/exit 2로 보고됐다. 현재 파일을 별도로 읽고 Ruff 0건, mypy 54개 소스 0건으로 실제 완료를 확인했다.
- 조치: 성공한 도구 호출 내역과 변경 해시를 기준으로 제품 바이트를 보존하고, 마지막 보고 호출 실패만 환경 이슈로 분리했다.
- 개선 후보: 모든 요청 스키마의 required 인수를 API 전송 전에 로컬 검증하고, 쓰기가 이미 완료된 뒤 확인용 read만 실패한 경우 `PARTIAL_AFTER_EDIT`처럼 상태를 구분해야 한다.
- 상태: 제품 교정 확인 완료. Runner 인수 사전검증은 후속 대상.

### ENV-RUNNER-018 — 외부 PowerShell 테스트 하네스의 배열 인수 및 junction 정리 호환성

- 구분: Runner 동적 계약 테스트
- 증상: 외부 `powershell.exe -File` 호출에서 `-AllowPath` 뒤 두 값을 개별 argv로 전달하자 두 번째 값이 다음 위치 매개변수 `Provider`로 해석됐다. 또한 PowerShell 5.1 `Remove-Item`으로 임시 junction을 지울 때 null 참조가 발생했다.
- 영향: 첫 계약 실행은 새 검증 62개 통과 후 테스트 하네스에서 중단됐고, 두 번째 실행은 junction 차단 검증 65개 통과 후 정리 단계에서 중단됐다. 제품 Runner의 권한 판정 실패는 아니었다.
- 조치: untracked 해시 테스트는 단일 허용 경로만으로 동일 계약을 검증하게 했고, 검증된 임시 루트 안 junction 링크는 비재귀 `System.IO.Directory.Delete`로만 제거했다. 최종 계약은 `150/150` 통과했다.
- 개선 후보: 외부 프로세스 기반 테스트 helper가 배열 매개변수를 안전하게 직렬화하는 전용 인수 파일 또는 encoded-command 경로를 제공해야 한다.
- 상태: 테스트 하네스 교정 및 전체 계약 통과 완료.

### ENV-TOOLING-003 — PowerShell 보간 문자열의 변수명 뒤 콜론 해석

- 구분: 다중 PowerShell AST 진단 명령
- 증상: 오류 위치를 `"$file:$line"` 형태로 만들자 PowerShell이 `$file:`을 드라이브 스코프 변수로 해석해 `Variable reference is not valid` 파서 오류를 냈다.
- 영향: 진단 명령 자체만 실행되지 않았고 대상 파일은 변경되지 않았다. 같은 시점 Runner 계약과 스킬 ValidateOnly는 각각 정상 통과했다.
- 조치: 변수 경계를 `"${file}:$line"`으로 명시해 다시 실행했고 세 PowerShell 파일 모두 `ALL_PARSE_OK`를 확인했다.
- 상태: 해결 완료.

### ENV-RUNNER-019 — 단일 파일 Writer가 읽기만 반복한 뒤 출력 한도로 빈 응답 종료

- 구분: DeepSeek Writer의 계획·도구 호출 진행 제어
- 증상: M5 운영 비밀값 검증을 `backend/app/core/settings.py` 한 파일로 제한한 호출이 5턴 동안 `read_file` 3회와 `search_text` 4회만 수행하고 쓰기는 한 번도 시도하지 않았다. 마지막 응답이 completion 12,000토큰 한도에 도달해 `finish_reason=length`, `EMPTY_MODEL_RESPONSE`, exit 1로 종료됐다.
- 영향: 실행 시간은 207,216ms였지만 `edit_count=0`, `patch_count=0`, `changed_paths=[]`였고 HEAD도 유지됐다. 제품 바이트와 디자인 동결 파일에는 변화가 없다.
- 원인 추정: 상세한 구현 요구를 모델이 과도하게 분석하면서 실제 도구 교정 전에 출력 예산을 모두 사용했다. API·인증·경로·권한 분리 실패는 아니다.
- 조치: 동일한 대형 프롬프트를 그대로 재사용하지 않고, 구현 형태와 첫 행동을 짧게 고정한 단일 교정 패킷으로 같은 Writer를 재시도한다. 재시도 전 현재 바이트를 기준으로 삼고 실패 호출의 작업을 처음부터 되돌리지 않는다.
- 개선 후보: 읽기 전용 턴이 연속될 때 남은 출력 예산과 함께 즉시 작은 편집을 요구하는 경고를 모델 문맥에 삽입하고, `finish_reason=length`의 빈 응답을 `OUTPUT_LIMIT_BEFORE_EDIT`로 분류한다.
- 상태: 실패 호출 무변경 확인 및 환경 로그 기록 완료. 축소 패킷 재시도 예정.

### ENV-RUNNER-020 — 축소된 단일 파일 패치도 malformed hunk로 적용 전 거부

- 구분: DeepSeek Writer `apply_patch` 인수 생성
- 증상: M5를 helper 추가와 production 연결로 나눈 첫 패킷에서 모델이 파일을 1회 읽고 2회 검색한 뒤 `apply_patch`를 호출했으나 Runner가 `PATCH_HUNK_LINE_INVALID`, `LEADING_TOOL_FAILURE`, exit 2로 거부했다.
- 영향: `edit_count=0`, `patch_count=0`, `changed_paths=[]`였고 HEAD 및 workspace diff hash가 호출 전과 같았다. 잘못된 hunk는 적용 전에 차단되어 제품 바이트 손상은 없다.
- 조치: 동일한 `apply_patch` 방식을 다시 쓰지 않고, 현재 파일의 정확한 기존 블록을 다시 읽은 뒤 `replace_text`만 허용하는 패킷으로 재시도한다.
- 개선 후보: Runner가 거부한 hunk의 줄 번호와 접두 종류를 비밀정보 없이 진단에 포함하고, tool schema에 유효한 hunk 최소 예시를 더 짧게 고정한다.
- 상태: 실패 무변경 확인 및 환경 로그 기록 완료.

### ENV-TOOLING-004 — Writer 프롬프트의 백틱이 오케스트레이션 템플릿 문자열과 충돌

- 구분: Codex 도구 호출용 JavaScript와 내장 PowerShell 프롬프트 경계
- 증상: `functions.exec`의 JavaScript template literal 안에 Markdown 백틱을 포함한 프롬프트를 넣어 V8 파서가 `SyntaxError`를 발생시켰다.
- 영향: 오류는 `exec_command` 실행 전에 발생했으므로 DeepSeek API 요청, 프로세스 시작, 파일 변경은 전혀 없었다.
- 조치: 내장 프롬프트에서 백틱을 제거하고 동일한 의미의 일반 텍스트로 다시 호출한다.
- 개선 후보: 긴 PowerShell 프롬프트를 구성할 때 JavaScript template literal과 겹치는 문자를 사전 검사하거나 안전한 인수 전달 helper를 사용한다.
- 상태: 원인 확인 및 무변경 확인 완료.

### ENV-RUNNER-021 — 테스트 계약 패킷도 첫 편집 전에 출력 한도 소진

- 구분: DeepSeek Writer의 테스트 설계 응답 크기와 편집 착수 지연
- 증상: `test_settings.py` 쓰기, `settings.py` 참고 전용으로 분리한 M5 테스트 패킷이 두 파일을 각 1회 읽은 뒤 completion 9,000토큰 한도에 도달했다. `finish_reason=length`, `EMPTY_MODEL_RESPONSE`, exit 1이었다.
- 영향: `edit_count=0`, `changed_paths=[]`이고 workspace diff hash도 호출 전과 같았다. 반면 결과의 `read_paths`와 `write_paths`는 의도대로 분리되어 새 Runner 권한 계약은 실호출에서도 확인됐다.
- 조치: 강한 양성 fixture 교체와 음성 계약 추가를 서로 다른 작은 패킷으로 나누고, 각 패킷에 단일 `replace_text`를 요구한다.
- 개선 후보: 모델이 읽기 직후 긴 내부 테스트 설계를 출력하지 않도록 첫 편집 turn 제한을 강제하고, 출력 예산이 절반 아래로 내려가면 편집 없는 분석을 중단시키는 정책을 둔다.
- 상태: 실패 무변경 확인 및 분할 재시도 진행.

### ENV-RUNNER-022 — 두 개의 작은 settings 교정도 분석 단계에서 출력 한도 소진

- 구분: DeepSeek Writer의 다중 교정 계획 과분석
- 증상: 순차 문자열 탐지 보강과 DB placeholder 검사 순서 변경을 함께 요청한 호출이 쓰기 파일과 참고 파일을 읽은 뒤 completion 5,000토큰 한도에 도달해 `EMPTY_MODEL_RESPONSE`, exit 1로 끝났다.
- 영향: 쓰기 도구 호출, 파일 변경, HEAD 변경이 모두 0건이었다. 읽기·쓰기 권한 집합은 의도대로 분리됐다.
- 조치: 두 교정을 각각 단일 `replace_text` 호출로 다시 분리하고 참고 파일도 필요한 호출에만 제공한다.
- 개선 후보: 한 파일에서 독립된 두 교정조차 편집 전에 장문 분석하는 경우 첫 계획 턴의 출력 상한을 별도로 낮추고 즉시 도구 사용을 요구한다.
- 상태: 실패 무변경 확인 및 추가 분할 진행.

### ENV-RUNNER-023 — 단일 helper 교체도 thinking 출력이 편집보다 먼저 예산 소진

- 구분: DeepSeek thinking mode와 Writer 도구 우선순위
- 증상: 순차 문자열 helper 블록 하나만 교체하도록 축소했음에도 파일을 1회 읽은 뒤 completion 4,000토큰을 모두 사용하고 `EMPTY_MODEL_RESPONSE`, exit 1로 종료됐다.
- 영향: `read_file` 1회 외 도구 호출이 없고 변경 파일도 0개였다. 작업 난이도나 patch 크기와 무관하게 thinking 출력이 편집을 지연하는 패턴이 반복됐다.
- 조치: 같은 기계적 교체에 한해 모델은 유지하되 `ThinkingMode=disabled`, `ReasoningEffort=low`로 내려 `replace_text` 우선 실행을 검증한다.
- 개선 후보: Runner가 단일 정확 교체 패킷을 식별하면 thinking 토큰 상한과 첫 편집 deadline을 별도로 적용하고, 사용자가 지정한 전체 출력 예산을 내부 추론이 독점하지 못하게 한다.
- 상태: 저추론 기계적 재시도가 즉시 `replace_text`를 생성해 편집 착수 지연은 해소됐다. 큰 교체에는 별도의 충분한 출력 reserve가 필요하다.

### ENV-RUNNER-024 — 저추론 교체는 즉시 편집했지만 도구 JSON이 3,000토큰에서 절단

- 구분: DeepSeek `replace_text` 도구 인수와 completion reserve
- 증상: `ThinkingMode=disabled`, `ReasoningEffort=low` 호출은 파일 1회 읽기 직후 곧바로 `replace_text`를 생성했으나, 기존 블록과 새 블록을 함께 담은 JSON이 3,000토큰 한도에서 잘려 `TOOL_ARGUMENTS_INVALID_JSON`, exit 2가 발생했다.
- 영향: 잘린 도구 인수는 적용 전에 거부됐고 파일 변경은 0건이다. 저추론 설정이 편집 착수 지연을 해소한다는 점은 확인됐다.
- 조치: 추론 설정과 패킷은 유지하고 도구 인수 여유만 6,000토큰으로 늘려 동일 교체를 재시도한다.
- 개선 후보: Runner가 예상 old/new text 길이를 계산해 필요한 최소 도구 출력 reserve를 자동 산정하고, 부족하면 API 호출 전 명확히 거부한다.
- 상태: 6,000토큰 reserve 재시도에서 동일 교체가 성공했고, 후속 기계적 패킷들도 13~34초 내 정상 완료됐다.

### ENV-TOOLCHAIN-002 — README의 정적 RandomNumberGenerator.Fill 예시는 PowerShell 5.1에서 사용 불가

- 구분: Windows PowerShell 5.1과 .NET 암호화 API 호환성
- 증상: 현재 Windows PowerShell에서 `RandomNumberGenerator`의 정적 `Fill` 메서드 존재 여부를 읽기 전용 reflection으로 확인했으며 `RNG_FILL_UNAVAILABLE`이었다.
- 영향: 문서의 CSPRNG 생성 예시를 그대로 실행하면 비밀값 생성 전에 메서드 호출 오류가 발생한다. 확인 과정에서 난수나 비밀값은 생성·출력하지 않았다.
- 조치: `RandomNumberGenerator.Create()` 인스턴스의 `GetBytes()`를 사용하고 반드시 dispose하는 PowerShell 5.1 호환 예시로 교체한다. raw secret용 hex 예시도 32바이트 생성으로 맞춘다.
- 상태: README를 PowerShell 5.1 호환 예시로 교정했고, 실제 값은 출력하지 않은 채 32바이트 입력과 44자 Base64 결과 길이를 확인해 `PS51_RNG_EXAMPLE_OK`를 얻었다.

### ENV-TOOLING-005 — 즉석 디자인 해시 스크립트의 배열 정렬이 거짓 불일치 생성

- 구분: PowerShell `object[]` 정렬과 ordinal manifest 생성
- 증상: 첫 즉석 검증에서 `[Array]::Sort`와 `StringComparer.Ordinal`을 PowerShell 배열에 직접 사용하자 집계가 기준과 다른 `2e548f...`로 계산됐다. 같은 시점 `git diff --quiet HEAD`는 0, 동결 untracked는 0이었다.
- 영향: 디자인 바이트가 바뀐 것처럼 보이는 거짓 경보가 발생했지만 파일 수정은 없었다.
- 조치: 표시할 repository-relative path 객체를 명시적 ordinal `Comparison` comparer로 정렬해 다시 계산했다. 129개 집계가 기준 `98c93aac800e62d021d7fab27c3c95315739c2e09e612557eb7dea7a5aba60dc`와 정확히 일치했다.
- 개선 후보: 디자인 동결 검증식을 즉석 명령이 아닌 계약 테스트된 공용 스크립트로 고정하고 path representation, case-sensitive ordinal 정렬, CRLF 연결, 마지막 개행 없음 조건을 자체 출력한다.
- 상태: 거짓 경보 해소. 디자인 변경 0건 재확인.

### ENV-TOOLING-006 — 독립방 최종 Git 경고가 PowerShell terminating error로 승격

- 구분: Room4 read-only Git 해시 명령과 PowerShell native stderr 처리
- 증상: 최종 diff/status 해시 확인 중 Git의 LF→CRLF 경고가 PowerShell 오류 처리에 의해 terminating error로 승격되어 명령이 한 번 중단됐다.
- 영향: 검수 명령만 중단됐고 Room4는 파일 변경이 없음을 확인했다. 제품·디자인·Git 상태 변경은 없다.
- 조치: 동일한 read-only 검사를 경고를 오류로 승격하지 않는 방식으로 한 번만 재실행하도록 했다.
- 개선 후보: Git의 정상 warning과 실제 nonzero exit를 분리해 판정하는 공용 PowerShell helper를 사용한다.
- 상태: Room4가 `core.autocrlf=false`의 동등한 read-only 재검사를 수행해 exit 0을 확인했고 최종 PASS를 보고했다. 제품 실패가 아닌 경고 승격 문제로 종결한다.

### ENV-CLAUDE-001 — read-only Opus 검수가 저장소 밖 사용자 Claude 상태를 갱신

- 구분: Claude CLI 기본 프로필·plugin autoupdater·plan/tool-result persistence·OAuth credential lifecycle
- 초기 증상: Opus는 저장소를 변경하지 않았지만, 큰 명령 출력을 사용자 Claude projects의 `tool-results`에, 검수 계획을 plans에 기록할 수 있었다.
- 2026-08-05 추가 관찰(독립방 4): 기본 프로필 호출 중 plugin autoupdater가 `\.claude\plugins` 약 649 entry를 staging→rename 갱신. content delta: known_marketplaces.json, official marketplace.json, .gcs-sha. `--no-session-persistence`는 transcript만 막음.
- 독립방 4 REJECT Major (재수정 대상):
  - **M1** inherited `CLAUDE_CODE_FORCE_WINDOWS_CREDMAN` 우회 부재
  - **M2** wrapper 자체 source 전후 2-pass seal 부재
  - **M3** 128 계약의 실질 공백(in-process env restore, nested cleanup, hostile redaction, reparse non-traversal 등)
  - **M4** live 실패 원인 문서 불일치 및 “재로그인 없이 반드시 성공” 과대 표현
- **M4 원인 교정(중요):** 이전 live 실패의 본질은 Windows CredMan 단절이 아니다. **expired access token + server에서 폐기/철회된 refresh token의 `invalid_grant`** 이다. revoked credential 상태에서 재로그인 없는 성공을 보장하지 않는다.
- 조치(재수정):
  - process-local isolated profile + `CLAUDE_CODE_FORCE_WINDOWS_CREDMAN=0` assert + finally 복원
  - 첫 Claude 전 `%USERPROFILE%\.claude` 전체 + sibling `.claude.json` 2-pass snapshot(파일/디렉터리, content SHA256, length, mtime ticks, reparse attrs, ordinal 정렬 aggregate). mid-tree reparse fail-closed. post cleanup 후 변경 시 `CLAUDE_SOURCE_STATE_CHANGED`(자동 복구 없음). 모델은 “process 격리 + 사후 변경 탐지”이며 외부 동시 프로세스 완전 차단을 주장하지 않음
  - `Invoke-SswOpusReviewCore` 분리 + dot-source guard; entrypoint 얇게 유지
  - nested plugins/projects/sessions 생성·삭제, ACL current-user-only, junction non-traversal, test-only cleanup injection, hostile secret redaction, raw nonzero redaction
  - CredMan은 plaintext backend 강제 + target-name count 보조 봉인(secret 값 미독)
  - approved child-only OAuth broker 경로만 선택 허용(현재 broker 없음). `OAUTH_TOKEN_FILE_DESCRIPTOR` 미사용
- 계약(당시 이력): `test-invoke-opus.ps1` **242/242** PASS (in-process). 당시 `test-ai-tools` 47/47, redaction 11/11, AST 0, skill quick_validate PASS. (현재 권위: Opus 259/259, ai-tools 61/61 — 권위 절.)
- DeepSeek PASS 후 비차단 후속(테스트 공백만):
  1. `Assert-NoSecretLeak`가 `[REDACTED]` 등 안전 마커를 누출로 오판하지 않도록 명시 허용; 고유 더미 원문만 거부.
  2. hostile fake가 Bearer/token/JSON/quoted secret/path 등 **원문 더미**를 stdout·stderr에 내고 `Protect-SswClaudeOutputText` 치환·잔여 fail-closed를 success/nonzero/throw 경로에서 검증. Claude 프로세스 캡처 시 `$ErrorActionPreference=Continue`로 stderr ErrorRecord가 redaction 전에 terminating 되지 않게 함.
- live(역사): revoked/invalid_grant credential blocker 구간에서는 재호출을 하지 않았고, 당시 필요 조치는 Claude credential 갱신/login 1회였다.
- **현재성(2026-08-05):** 사용자 Claude **1회 로그인 완료**. **Opus 기술 최종 검수(5 XHIGH) PASS, Critical/Major 0**. **사용자 로그인 완료, Opus 기술 최종 검수 PASS. 이번에는 사용자의 지시에 따라 보고서 자체에 대한 Opus 추가 검수는 생략함.** 실제 인증값·토큰은 기록하지 않음.
- UNKNOWN(별도 유지): Windows Credential Manager secret 값 byte-seal 불가(name-count only). 기술 경로 CLOSED와 분리.
- 상태: **CLOSED(기술 경로)**. 사용자 다음 행동 = 보고서 확인 후 `끝!`(재로그인 아님). Git commit/push 아직 안 함.

### ENV-RUNNER-025 — 구조화 FK 교정 3건 성공 후 무진행 한도로 PARTIAL 종료

- 구분: DeepSeek Writer의 성공 편집 후 완료 수렴
- 증상: `postcheck_w1a_vs1.py`에 세 번의 `replace_text`를 성공 적용한 뒤, 모델이 read/search만 반복해 12턴째 `NO_PROGRESS_LIMIT_REACHED`, exit 2로 종료됐다. 누적 문맥 사용량은 약 915K 토큰이었다.
- 영향: 세 교정은 현재 파일에 정상 반영됐고 다른 파일은 바뀌지 않았다. Runner 최종 상태만 PARTIAL이며 제품 교정의 완성 여부는 별도 검증이 필요하다.
- 조치: 성공한 현재 바이트를 보존하고 원복·처음부터 재작업하지 않는다. Ruff/mypy와 정확한 diff를 확인한 뒤 빠진 항목만 작은 후속 패킷으로 전달한다.
- 개선 후보: 편집 완료 후 연속 read/search가 발생하면 모델에 변경 요약 후 종료를 강제하고, no-progress 기준을 마지막 성공 편집 이후의 검증 단계와 편집 전 정체 단계로 구분한다.
- 상태: 부분 성공 보존. 현재 바이트 검증 진행.

### ENV-RUNNER-026 — 구조화 FK 후속 패킷의 잘못된 apply_patch 형식

- 구분: DeepSeek Writer의 패치 직렬화와 선두 도구 실패 처리
- 증상: `postcheck_w1a_vs1.py` 후속 정리를 요청한 Runner 2.3.0 작업 `task-80f1960886c64353a61a6e09eed04d01`이 읽기·검색 후 `apply_patch`를 호출했지만 `PATCH_HUNK_LINE_INVALID`로 거부됐고 exit 2/PARTIAL로 종료됐다.
- 영향: `edit_count=0`, `changed_paths=[]`였으며 HEAD와 현재 작업 바이트에는 변화가 없었다. 기존의 구조화 FK 부분 수정도 그대로 보존됐다.
- 조치: 같은 현재 바이트에서 작업을 단일 정확 교체로 더 작게 나누고 `replace_text`만 사용하도록 강제했다. 긴 타입 선언 정리, 전 필드 fail-closed 비교, 주석 정리, mypy 변수명 분리는 각각 성공했다.
- 개선 후보: 모델이 `apply_patch`를 선택할 때 Runner가 hunk 문법을 사전 검증하고, 기계적 단일 교체 요청에는 `replace_text`를 우선 선택하도록 도구 라우팅을 고정한다.
- 상태: 제품 변경 0건 실패로 격리했고 후속 정확 교체 및 Ruff/mypy 검증으로 해소했다.

### ENV-RUNNER-027 — 0014 테스트 개수 연동 패킷이 부분 성공 뒤 OLD_TEXT_NOT_FOUND

- 구분: DeepSeek Writer의 다중 `replace_text` 수렴과 현재 바이트 재탐색
- 증상: Runner 2.3.0 작업 `task-5b71499af61848398494acc47358d950`이 0014 wrapper의 `expected=6` 표시와 passed 비교 두 건을 성공 적용한 뒤, collection regex 교체에서 `OLD_TEXT_NOT_FOUND`로 exit 2/PARTIAL 종료됐다.
- 영향: wrapper의 성공한 두 변경은 보존됐고 테스트 파일은 이 호출에서 바뀌지 않았다. HEAD, staged 상태, 다른 작업 바이트에는 변화가 없었다.
- 조치: 현재 wrapper를 다시 읽어 남은 `collected\s+3\s+items?` 한 곳만 별도 정확 교체해 6으로 맞췄고, 테스트 계약 추가도 별도 단일 패킷으로 완료했다.
- 개선 후보: 한 호출에서 앞선 교체가 문맥을 바꾼 뒤에는 후속 `old_text`를 최초 snapshot이 아니라 최신 파일 바이트에 재기반하고, 실패 시 이미 성공한 편집과 남은 목표를 구조화해 반환한다.
- 상태: 성공 편집 보존 후 해소. Ruff/mypy, 집중 pytest, PowerShell AST 검증 통과.

## 2026-08-05 추가 이력

### ENV-RUNNER-028 — 대형 자기수정 packet의 과도한 지연과 불완전 PASS

- 구분: DeepSeek Runner 자체 보강을 한 번에 요청한 대형 Writer packet.
- 증상: 483,129ms 동안 31 requests와 약 7.9M cumulative prompt를 사용했다. 허용된 Runner 일부만 수정한 뒤 응답 본문에는 테스트와 결과 필드 작업이 남았다고 적으면서 최종 상태는 PASS로 반환했다.
- 영향: 부분 수정 자체는 보존했지만 이 PASS를 완료 증거로 채택할 수 없었다. 디자인 및 허용범위 밖 저장소 파일에는 영향이 없었다.
- 조치: 현재 바이트를 다시 기준화하고 Runner, 계약 테스트, Observer를 작은 독립 packet으로 분해했다. 미완료 여부는 모델 문구가 아니라 edit·result·계약 gate로 판정한다.
- 상태: 발생 이력 기록 완료. 구조적 closure는 ENV-RUNNER-029/030과 당시(이력) Runner `353/353` 계약으로 확인했다.

### ENV-RUNNER-029 — 출력예산, 무편집 완료 및 forced-write 수렴의 구조적 공백

- 구분: Writer 출력 reserve와 완료 판정.
- 기존 결함: 짧은 프롬프트가 큰 허용 파일을 읽어 긴 `old_text`/`new_text`를 만드는 경우를 prompt 길이만으로 예측하지 못했고, 편집 0건의 텍스트 완료가 PASS가 될 수 있었다. forced-write도 검색만 제한해 무편집 read 반복을 끝내지 못했다.
- 조치: `ExpectedWriteBytes`와 기존 대상 크기로 사전 예산을 계산하고, 쓰기 직전 compact serialized tool arguments의 실제 UTF-8 바이트를 다시 검사한다. 예산 초과는 적용 전에 거부한다.
- 조치: 편집 없는 최종 응답은 `WRITER_COMPLETED_WITHOUT_EDIT`로 실패 처리한다. 2턴 무편집 뒤 `forced-write`, 다음 무편집 턴에는 선택한 쓰기 도구만 남기는 `write-only`로 전환한다.
- 상태: CLOSED. 큰 old/new, 동적 인수 초과, 즉시 무편집 final, 비협조 read 반복 계약을 포함해 당시(이력) Runner `353/353` 통과.

### ENV-RUNNER-030 — 한국어 새 파일 요청의 Auto 오라우팅

- 구분: `WriteStrategy=Auto`의 도구 선택.
- 증상: 영어 `add file`, `create new file` 같은 문구만 인식해 `새 파일 생성`처럼 정상적인 한국어 요청은 기본 `ReplaceText`로 잘못 라우팅될 수 있었다.
- 조치: 프롬프트 언어 판정을 제거했다. allowlist가 모두 기존 leaf이면 `ReplaceText`, 모두 미존재하는 정확한 파일 경로이면 `ApplyPatch`, directory 또는 기존/미존재 혼합이면 `WRITER_WRITE_STRATEGY_REQUIRED`로 거부한다.
- 상태: CLOSED. 한국어 미존재 경로, directory ambiguity, 선택 도구 단일 노출 및 숨긴 도구 거부 계약을 포함해 검증했다.

### ENV-RUNNER-031 — 공용 ValidateOnly와 실제 Writer preflight 불일치

- 구분: `sswcenter-start`의 공용 `invoke-deepseek.ps1 -ValidateOnly`.
- 증상: wrapper는 `MaxTokens=3000`도 Ready로 반환했지만 실제 Runner Writer는 최소 8,192 출력 토큰을 요구해 본 호출에서 `WRITER_OUTPUT_BUDGET_TOO_LOW`로 실패했다.
- 조치: ValidateOnly가 실제 workspace Runner를 `OfflineConfig`로 호출하도록 바꿔 strategy, `ExpectedWriteBytes`, 최소 출력예산과 packet 분할을 본 호출과 동일하게 검증한다. 네트워크 요청은 발생하지 않는다.
- 상태: CLOSED. 당시(이력) 외부 AI 도구 계약 `47/47`, PowerShell AST 오류 0, skill quick validation PASS. (현재 권위 ai-tools 61/61.)

### ENV-RUNNER-032 — Bearer, quoted-space 및 escaped JSON redaction 공백

- 구분: 환경 JSONL 기록기와 Runner checkpoint/result redaction.
- 증상: 공백을 포함한 quoted secret, `Authorization: Bearer ...`, 중첩·다중 직렬화된 escaped JSON에서 민감값 일부가 뒤에 남거나 구조 객체가 손실될 수 있었다.
- 조치: 구조 객체는 재귀 key-aware sanitizer로 처리하고, 일반 텍스트와 1단계·3단계 escaped JSON은 역슬래시 깊이를 보존해 마스킹한다. 미마스킹 secret marker가 남으면 기록 자체를 fail-closed 한다.
- 상태: CLOSED. 환경 redaction `11/11`; 원문 credential 값은 로그나 이 문서에 기록하지 않았다.

### ENV-RUNNER-033 — 자기수정 뒤 3인수 Math.Max로 Runner 부팅 실패

- 구분: self-hosted Runner의 출력예산 계산 교정.
- 증상: 자기수정 결과가 현재 PowerShell/.NET에서 지원하지 않는 3인수 `[Math]::Max(...)` 호출을 만들어 다음 Writer 호출이 preflight 전에 부팅되지 않았다.
- 조치: exact 현재 바이트를 확인한 뒤 해당 식만 중첩된 2인수 `Math.Max`로 바꾸는 최소 bootstrap을 수행하고, 이후 교정은 다시 Writer와 독립 구현방에 맡겼다.
- 상태: CLOSED. Runner와 계약 테스트 PowerShell AST 오류 0, 당시(이력) Runner `353/353` 통과.

### ENV-RUNNER-034 — 반복된 도구 인수 안전 실패와 재배정

- 구분: DeepSeek의 exact replacement, patch 직렬화 및 수렴.
- 증상: `OLD_TEXT_NOT_FOUND`, malformed patch context/hunk, path 없는 `read_file`, 6턴 무편집이 여러 작은 packet에서도 반복됐다. Observer patch 한 건은 선언한 write budget을 넘겨 적용 전에 중단됐다.
- 영향: 해당 실패는 edit 0 또는 이미 성공한 bounded edit만 보존한 PARTIAL로 끝났고 허용범위 밖 쓰기는 없었다.
- 조치: 같은 실패 형태를 무한 재호출하지 않고 current-byte packet을 더 작게 나눈 뒤, 반복 실패 범위는 독립 구현방으로 재배정했다.
- 상태: 안전 실패와 재배정 근거 기록 완료. 당시(이력) Runner `353/353`, Observer `120/120` 및 정본 실실행 PASS로 closure 확인.

### ENV-TOOLING-007 — Git optional index write 가능성과 단일 snapshot 경쟁 창

- 구분: `scripts/verify-workspace-seal.ps1`의 엄밀한 read-only 및 동시 변경 봉인.
- 기존 결함: 일반 `git status`는 optional index stat refresh를 기록할 수 있었고, HEAD/status/manifest를 한 번씩만 관찰해 hash 뒤 외부 변경을 놓칠 수 있었다.
- 조치: 모든 Git observer 호출에 `--no-optional-locks`와 process-local `GIT_OPTIONAL_LOCKS=0`을 적용했다. 시작·종료에 HEAD, 전체 tracked/untracked, 동결 tracked/untracked, index manifest, cached diff, status fingerprint를 다시 계산해 하나라도 달라지면 `OBSERVER_SNAPSHOT_CHANGED`로 거부한다.
- 검증: worktree 및 index-only concurrent mutation 음성 계약을 포함해 구현방 `120/120` 연속 2회와 오퍼레이터 독립 `120/120` 1회를 통과했다. 보고서 자체 갱신 전 operator checkpoint의 정본 시작·종료 seal은 모두 `c978e10047b7bfcf3f03d0c7e2b947dac5b0aa7b1b45bc108882cf6f7ab1571d`였다.
- 상태: CLOSED. 정본 `.git/index` SHA-256/mtime 불변, `index.lock` 없음.

### ENV-TOOLING-008 — 최초 일반 git status의 과거 무쓰기 증명 한계

- 구분: 오퍼레이터의 첫 identity 관찰.
- 사실: 최초 일반 `git status` 1회는 `--no-optional-locks`와 `GIT_OPTIONAL_LOCKS=0` 없이 실행됐다. Git의 optional stat refresh 가능성을 사후 배제할 수 없어 그 시점 이전 시스템 전체 byte-for-byte 무쓰기는 UNKNOWN이다.
- 후속 확인: 이후 모든 observer는 strict read-only 옵션을 사용했고 index SHA-256과 mtime은 불변, `index.lock`은 없었다.

### ENV-RUNNER-036 — 안전 마커/보안 설명 텍스트로 CHECKPOINT REDACTION_FAILED 및 PASS 모순

- 구분: `invoke-deepseek-workspace.ps1` checkpoint redaction residual 검사와 완료 상태 일관성.
- 1차 증상: 실제 비밀 없이 안전 마커/`secret:` 설명 문구만 있는 응답에서 `REDACTION_FAILED` → `CHECKPOINT_WRITE_FAILED`. 동시에 모델 완료가 먼저 PASS/exit 0을 세팅해 envelope 모순.
- 1차 원인: residual이 `secret:`/`password:` 뒤 비-`[REDACTED]` prose를 전부 실패 처리.
- 1차 조치: residual을 value-shaped로 축소; checkpoint 실패 시 PASS demote. 계약 437/437.
- **2차 재발(숨기지 않음):** 1차 수정 후 DeepSeek 재검수 모델 판정은 PASS였으나, 기술 설명 응답(`$safeMarker` 정규식, `(?!$safeMarker)`, `token-shaped bare value(sk-/eyJ/20+)`, escaped key 문서 `\"secret\":` / `\"password\":`, `secret: "[REDACTED]"`, refresh token/OAuth invalid_grant 설명)에서 다시 `REDACTION_FAILED` → envelope는 demote 정상(`FAIL`/`exit 1`/`checkpoint_integrity=FAIL`). 즉 PASS 모순은 닫혔고 **오탐 residual은 OPEN으로 재발**.
- **2차 원인:** escaped JSON residual이 **값 없는 key fragment** `\"secret\":` 만으로도 매칭됨(문서/정규식 설명 오탐). 실제 secret value 탐지를 끈 것이 아니라, key-only 문서 조각을 value로 오인.
- **2차 조치:** escaped residual은 `\"key\":\"non-marker-value\"` 형태만 fail-closed. 안전 마커/정규식 문서/prose 허용. JWT `eyJ….…` 마스킹·residual 추가. raw Bearer/sk-/quoted/nested/escaped dummy는 유지.
- **실증:** 안전 fixture read-only live DeepSeek 1회 → `status=PASS`, `exit_code=0`, `checkpoint_saved=true`, `checkpoint_integrity=ATOMIC_WRITE_ATTEMPTED`, `errors=0`, `stop_reason=MODEL_COMPLETED`.
- 검증: 당시(이력) Runner `460/460` 등. **현재 권위 Runner 수치는 권위 절 `481/481` 한 곳뿐.**
- 상태: CLOSED (2차).

### ENV-RUNNER-037 — ReadOnly 다파일 검수에 Writer edit-start deadline 오적용

- 구분: `scripts/invoke-deepseek-workspace.ps1` no-progress / edit-start 게이트.
- 증상: DeepSeek 독립 재검수(mode=ReadOnly, write_paths=[], 18 read_file 성공, edit_count=0)가 `EDIT_START_DEADLINE_WARNING` 후 `EDIT_START_DEADLINE_REACHED`로 FAIL/exit 1. checkpoint는 저장됐으나 response empty, 코드 판정 전 중단.
- 원인: `EditCount==0` 분기에서 forced-write 전환만 Writer 가드가 있고, `EDIT_START_DEADLINE_WARNING`(≥4) / `EDIT_START_DEADLINE_REACHED`(≥6)는 Mode와 무관하게 적용됨. ReadOnly의 정상 multi-turn 읽기가 무편집 deadline에 걸림.
- 조치: edit-start deadline·forced-write/write-only 수렴·POST_EDIT_NO_PROGRESS_* 를 **Writer 전용**으로 제한. ReadOnly는 read/search 진행 중 zero-edit 허용.
- 계약: Writer 6-round no-edit 여전히 `EDIT_START_DEADLINE_REACHED` fail-closed. ReadOnly 18-file multi-turn fixture → status PASS, exit 0, turns≥18, read_tool_calls≥18, edit_count=0, checkpoint_saved=true, integrity ATOMIC_WRITE_ATTEMPTED, errors=0, stop MODEL_COMPLETED, no edit-start warning/error.
- 검증: Runner **현재 권위** `481/481` (권위 절과 동일; 이 이슈 도입 시점 계약).
- 상태: CLOSED.

### ENV-OPUS-001 — invoke-opus.ps1 relative `.\` 호출 silent no-op

- 구분: `sswcenter-start/scripts/invoke-opus.ps1` entrypoint dot-source guard.
- 증상: `$MyInvocation.Line.TrimStart().StartsWith('.')` 때문에 `.\invoke-opus.ps1` 상대 실행이 false-positive dot-source로 판정되어 본문 미실행·exit 0.
- 조치: guard를 `$MyInvocation.InvocationName -eq '.'` 단일 조건으로 축소. 자식 프로세스 계약: `-File` abs, `.\` relative, `&` abs에서 fake 본문·exit 전달 증명. JWT redaction 대칭 추가.
- 검증: Opus 계약 `259/259`, wrapper SHA-256 `db4b8c053baf605e46d7a1afa73b1dc0cb167547d908170190e12c23c2b7c2b6`.
- 상태: CLOSED.

### ENV-GROK-HOME-001 — worktree gc 경고(neither GROK_HOME nor HOME)

- 구분: **ENV-GROK-HOME-001만** 사용(짧은 `ENV-GROK-HOME` 표기 금지). (a) skill wrapper process env (b) 호스트 Grok ambient env — **분리 판정**.
- 증상: 호출 시작 시 `auto worktree gc failed: neither $GROK_HOME nor $HOME is set`.
- 조치: `Save-SswProcessEnvironmentValue`/`Restore-SswProcessEnvironmentValue`로 process env **present vs absent** 구분. `Set-SswGrokProcessHomeEnvironment`가 child 직전에 `GROK_HOME` 설정 및 absent/blank `HOME`을 UserProfile로 채움. finally에서 parent exact 복원(success/throw 계약). Windows .NET은 empty string env를 유지하지 못함(empty set=delete).
- 상태: **skill wrapper Minor CLOSED**. **호스트 런처 ambient env는 제품 밖 UNKNOWN**(wrapper CLOSED와 혼동 금지).

### ENV-RUNNER-035 — 세션 ID 회수 누락에 따른 계약 중복 실행

- 구분: 오퍼레이터 테스트 오케스트레이션.
- 증상: 첫 Runner 계약 실행의 세션 ID를 회수하지 못해 동일 계약을 한 번 더 실행했다.
- 영향: 제품·디자인·Git 상태 변경은 없었다. 두 실행 모두 정상 종료했고 temp residue도 남지 않았다.
- 상태: 비차단 이력 기록 완료. 두 결과 모두 `RUNNER_CONTRACT total=353 passed=353 failed=0`.

### ENV-SKILL-001 — 삭제 지시된 스킬 디렉터리의 재등장

- 구분: 사용자 로컬 Codex skill registry 환경.
- 증상: 사용자가 이전에 삭제를 지시한 `C:\Users\USER\.codex\skills\workday-ai-git`의 11개 파일과 `C:\Users\USER\.codex\skills\prepare`의 빈 `agents` 디렉터리가 다시 존재했다.
- 조치: exact target을 확인한 뒤 11개 파일은 bounded patch로 삭제하고 빈 디렉터리만 삭제했다. 다른 스킬 또는 저장소 파일은 건드리지 않았다.
- 영향: 두 로컬 디렉터리에서 복구할 수 없으며 `C:\sswcenter\2.2` 저장소에는 영향이 없다.
- 상태: 두 경로 모두 absent. 재등장 원인은 UNKNOWN이며 `skill-registry` 환경 이슈로 기록했다.

### ENV-GIT-FINISH-001 — git-finish.ps1 Korean/C-quoted path sensitive check crash

- 구분: 로컬 skill `sswcenter-git-finish/scripts/git-finish.ps1` (제품 저장소 밖 skill; 제품 디자인 무변경).
- 증상: 후보 경로 수집 후 `Test-SensitiveGitPath`가 Git이 출력한 C-style quoted 한글 경로(따옴표·`\NNN` octal)를 raw로 `[IO.Path]::GetFileName`에 전달 → `Illegal characters in path`. **이 실패 시점에는 stage/commit/push 미실행.**
- 조치: porcelain/v1 `-z`와 `core.quotepath=false`로 NUL 분리 바이트 출력 파싱; XY status와 path 분리; quoted path UTF-8 복원; repo-relative containment; malformed fail-closed. 민감 leaf 검사는 decode된 repo-relative path에만 적용. 한글·공백·따옴표·백슬래시 계약 및 AST parse 확인.
- 상태: **CLOSED**.

### ENV-HOST-001 — Grok resident session actor DeadFailed (호스트/세션)

- 구분: 호스트 Grok Build/세션 런타임(제품 저장소 코드 아님).
- 증상: 전체 이슈 해결보고서 작성 세션 종료 시 경고 `Resident session actor exited unexpectedly; reaping as DeadFailed`.
- 영향: 보고서 파일 산출·observer·디자인 동결 판정과는 별개의 호스트 수명 경고. 인증값·토큰·비밀 없음. 제품 코드 버그로 과장하지 않음.
- 조치: 비밀 없이 environment JSONL(`review/environment/operator-environment-issues.jsonl`) 및 본 권위 목록에 기록. 자동 복구/재로그인/Opus 재호출 없음.
- 상태: **OPEN**(미해결 호스트/세션 관찰). 사용자 필수 조치 아님; 다음 행동은 보고서 확인 후 `끝!`.

### 기타 비차단 이력

- ENV-TOOLING-009: read-only hash manifest PowerShell 명령이 `foreach` 뒤 빈 pipe parser error로 실행 전에 종료됐다. corrected in-memory array 명령은 성공했고 파일·Git 상태에는 영향이 없으며 `operator-tooling` JSONL에 기록했다.
- 비차단 재발: 같은 형태의 read-only hash manifest `foreach` 뒤 빈 pipe parser error가 재발했으나 실행 전에 종료됐다. corrected in-memory array 명령은 성공했고 해당 명령 형태는 재사용 금지로 기록했다.

### ENV-RUNNER-015 이력 계속 — length tool batch 원자 거부 closure

- 구분: 공급자 `finish_reason=length`와 tool call이 함께 온 현재 batch의 처리 순서. **ENV-RUNNER-015의 후속 이력 절(동일 이슈 ID의 상세 계속). ENV-RUNNER-036은 체크포인트 redaction 전용으로 별개.**
- Room4 REJECT: 기존 후보는 잘린 batch라도 tool arguments가 syntactically valid하면 `replace_text` 또는 `apply_patch`를 실행할 수 있어 M1이었다.
- 조치: tool call 추출 직후 `finish_reason=length`이고 toolCalls>0이면 `OUTPUT_LIMIT_DURING_TOOL_CALL`로 원자 거부.
- 당시 검증(이력): 구현방/오퍼레이터 `404/404`. 당시 Runner SHA-256 `748f6e1b16435254a8091f20aeacc77c838f672678cad11eced01d8d7ff2553e`, 계약 테스트 SHA-256 `37a7354c2f52366728a1890528a8b6ef08adfe8817afaa2e255d1e8997d720db` (당시 바이트; 현재 권위 수치·현재 SHA는 권위 절 최신 계약 행).
- 상태: CLOSED (이력).
