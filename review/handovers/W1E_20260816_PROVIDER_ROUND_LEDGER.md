# W1E Provider Round Settings Ledger

작성일: 2026-08-16 (Asia/Seoul)
정본 후보 작업 디렉터리: `/home/codexctl/workspace/sswcenter-3-0`

이 문서는 W1E 후보 작업에서 provider 실행 설정과 라운드 순서를 기록한다.
provider 완료 문구는 acceptance가 아니며, 각 결과는 Codex가 현재 바이트·diff·실행 exit와 대조한다.

## 실행 정책

- 초기 후보 구현 뒤, 완성 후보를 대상으로 DeepSeek↔Grok이 각 라운드마다
  `TEST → REVIEW → 필요한 FIX`를 수행한다.
- 총 2라운드 후 후보를 새 worktree로 분리한다.
- 새 worktree의 최종 독립검수는 `gpt-5.6-sol`, reasoning effort `ultra`로 수행한다.
- 성과가 좋아도 형님 승인 전에는 정본 승격·stage·commit·push를 하지 않는다.

## Provider 설정 기준

| 항목 | 기준 |
|---|---|
| 기본 tool turns | 128 |
| 필요 시 확장 상한 | 256 |
| 이 작업의 timeout | 3600초 |
| DeepSeek 모델 | `deepseek-v4-pro` |
| Grok 모델 | runner의 승인된 기본 모델 |
| 최종 독립검수 | `gpt-5.6-sol` / `ultra` |

### 범위별 턴 상한 운용 규칙 (2026-08-16 추가)

- 작업 시작 전에 범위를 판정한다. 단일 파일·국소 수정·짧은 read-only 검수는
  `max_turns=128`, `timeout=3600초`를 사용한다.
- 다중 파일 구현, DB migration/trigger, API·OpenAPI, 실 PostgreSQL 하니스,
  DeepSeek↔Grok 상호검수, 새 worktree 독립검수가 하나라도 포함되면 처음부터
  `max_turns=256`, `timeout=3600초`를 배정한다. 이 경우 DeepSeek와 Grok 모두 같은
  256턴 상한을 적용한다.
- `256`은 최대 허용 턴이지 반드시 소진하는 턴 수가 아니다. provider가 먼저
  완료하면 즉시 종료하며, `3600초` 초과는 정상적인 장기 실행이 아니라 timeout/failure로
  기록하고 재시도·범위 축소를 판단한다.
- 이번 W1E 추가 구현 라운드는 초기 Grok `128`에서 시작하고 DeepSeek만 `256`으로
  확장했던 예외 사례다. 이후 동일하게 넓은 라운드는 두 provider 모두 `256`으로
  시작한다.

## 실행 기록

### 초기 후보 구현

- actor/action: `DEEPSEEK / IMPLEMENT`
- 시작: 2026-08-16, 현재 세션
- 실제 설정: `deepseek-v4-pro`, `max_turns=128`, `timeout=900초`
- 사유: 최초 호출이 사용자 설정 정정 전에 시작됨
- 처리: 결과를 성공으로 간주하지 않고 Codex가 현재 바이트와 실행 증거를 대조한다.
- 재시도 조건: 900초 timeout 또는 provider 오류이면 동일 범위를
  `max_turns=256`, `timeout=3600초`로 재실행한다.

#### 결과

- 종료: 2026-08-16 00:39 전후
- provider result: `status=succeeded`, `exit=0`, `duration_ms=998422`
- 변경 경로: `backend/tests/test_w1e_0026_postgres.py`,
  `backend/tests/test_w1e_phase1_behavior.py`,
  `scripts/test-w1e-0026-postgres-linux.ps1`
- DeepSeek가 보고한 수정: 0026 seed의 필수 `mobile_phone` 보정, fake audit의
  `action_code` 보존과 side-effect assertion 강화, Linux 0026 PostgreSQL
  lifecycle harness 추가
- Codex 확인: `git diff --check` exit 0, W1E Python `py_compile` exit 0.
- 환경 차단: backend `.venv`에 pytest/Ruff/alembic/FastAPI가 없고 `pwsh`가
  provider sandbox에 없어 실행 테스트·lint·OpenAPI·harness live run은 아직 미검증.
- 계약 미결: FAMILY position/qualification guard 범위는 GENERAL-only로 보존됐으며
  current 3.0 canonical text와의 ambiguity를 해결하지 않았다.

### 1라운드

- Grok: `TEST → REVIEW → FIX`, 기본 `max_turns=128`, 필요 시 `256`, `timeout=3600초`
- DeepSeek: `TEST → REVIEW → FIX`, 기본 `max_turns=128`, 필요 시 `256`, `timeout=3600초`
- 각 단계 사이에 Codex가 diff·테스트·미검증 범위를 확인한다.

#### Grok 1차 결과

- actor/action: `GROK / FIX` (내부 순서: TEST → REVIEW → FIX)
- 설정: runner 기본 Grok model, `max_turns=128`, `timeout=3600초`
- provider result: `status=succeeded`, `exit=0`, `duration_ms=600391`
- 변경 경로: `backend/tests/test_w1e_phase1_behavior.py`,
  `backend/tests/test_w1e_phase1_contract.py`,
  `backend/tests/test_w1e_0026_postgres.py`,
  `scripts/test-w1e-0026-postgres-linux.ps1`
- 제품 코드·0026 migration은 Grok이 수정하지 않았다.
- Grok 보고: audit assertion 순서/중복 민감화, trigger-bypass runtime/static gate,
  exact 5-node binding, existing 422 behavior cases, harness preflight/cleanup gate 강화.
- Codex 확인: `git diff --check` exit 0, W1E Python `py_compile` exit 0,
  변경 범위가 허용된 W1E test/harness 파일에 한정됨.
- 환경 차단 유지: pytest/Ruff/OpenAPI/live 0026 harness 실행은 empty venv와
  provider sandbox의 `pwsh` 부재로 미검증.
- 미결 유지: FAMILY position/qualification guard 범위는 명시적 결정 없이 보존됨.

#### DeepSeek 1라운드 후속 결과

- actor/action: `DEEPSEEK / FIX`, `ROUND=1`, `PHASE=AFTER_GROK`
- 설정: `deepseek-v4-pro`, `max_turns=128`, `timeout=3600초`
- provider result: `status=failed`, `exit=4`, `error_code=DEEPSEEK_TURN_LIMIT`
- 결과: 128 tool turns 초과로 완료 선언·검수 결과를 받지 못했으므로 성공으로
  처리하지 않는다.
- 현재 바이트: provider가 `scripts/test-w1e-0026-postgres-linux.ps1`를
  수정한 흔적이 있어, 다음 256턴 재실행 전에 Codex가 해당 파일을 재검토한다.
- 정적 확인: `git diff --check` exit 0, W1E Python `py_compile` exit 0.
- 다음 조치: 동일 범위를 `max_turns=256`, `timeout=3600초`로 재실행하고,
  부분 변경도 독립 검수 대상으로 취급한다.

#### DeepSeek 1라운드 확장 재시도 결과

- actor/action: `DEEPSEEK / FIX`, `ROUND=1`, `PHASE=AFTER_GROK_RETRY_256`
- 설정: `deepseek-v4-pro`, `max_turns=256`, `timeout=3600초` (필요 시 확장)
- provider result: `status=succeeded`, `exit=0`, `duration_ms=1081138`
- 변경 경로: `NONE`; 부분 harness와 Grok 변경을 재검토했으나 evidence-backed
  수정은 하지 않았다.
- Codex 확인: 현재 W1E 소스 mtime에 추가 변경 없음, `git diff --check` exit 0,
  W1E Python `py_compile` exit 0.
- 정적 확인: 13개 W1E Python AST/compile, exact 5-node binding,
  0025→0026 ancestry, FAMILY CHECK fragment consistency가 provider에서 통과.
- 환경 차단: backend `.venv`의 pytest/Ruff/Alembic/FastAPI 등 부재와
  `pwsh` 부재로 live pytest·lint·OpenAPI·0026 PostgreSQL harness 미검증.
- 미결 유지: FAMILY position/qualification guard 범위는 GENERAL-only로 보존됐고
  current 3.0 문서의 해석 ambiguity는 해결하지 않았다.

### 2라운드

- Grok: `TEST → REVIEW → FIX`, 기본 `max_turns=128`, 필요 시 `256`, `timeout=3600초`
- DeepSeek: `TEST → REVIEW → FIX`, 기본 `max_turns=128`, 필요 시 `256`, `timeout=3600초`
- 각 단계 사이에 Codex가 diff·테스트·미검증 범위를 확인한다.

#### Grok 2차 결과

- actor/action: `GROK / FIX`, `ROUND=2`, `PHASE=AFTER_DEEPSEEK_ROUND1`
- 설정: runner 기본 Grok model, `max_turns=128`, `timeout=3600초`
- provider result: `status=succeeded`, `exit=0`, `duration_ms=486796`
- 변경 경로: `backend/app/db/postcheck_current_0026.py`,
  `backend/tests/test_w1e_0026_postgres.py`,
  `backend/tests/test_w1e_phase1_behavior.py`,
  `backend/tests/test_w1e_phase1_contract.py`
- Grok 보고: postcheck에 FAMILY kind guard·exclusion·`erp_app` ACL을 추가하고,
  5번째 PG 노드에서 `SET LOCAL session_replication_role`/`DISABLE TRIGGER USER`
  권한 거부를 확인하도록 보강했으며, audit JSON 필드와 계약 정적 단언을 강화했다.
  제품 API/domain/0026 migration은 변경하지 않았다.
- Codex 확인: `git diff --check` exit 0, W1E Python `py_compile` exit 0,
  변경 mtime은 위 4개 허용 경로에 한정됨. 기존 W0–W1D dirty WIP와 ledger는 보존.
- 환경 차단 유지: pytest/Ruff/OpenAPI/live 0026 harness는 empty venv와
  provider sandbox의 `pwsh` 부재로 미검증.
- 미결 유지: FAMILY position/qualification guard 범위는 GENERAL-only로
  보존됐고 current 3.0 문서와 구 2.1 plan/0012 사이의 ambiguity는 해결하지 않았다.

#### DeepSeek 2차 기본 실행 결과

- actor/action: `DEEPSEEK / FIX`, `ROUND=2`, `PHASE=AFTER_GROK_ROUND2`
- 설정: `deepseek-v4-pro`, `max_turns=128`, `timeout=3600초`
- provider result: `status=failed`, `exit=4`, `error_code=DEEPSEEK_TURN_LIMIT`
- duration: 약 18분 실행 후 128 tool turns 초과. 완료 선언·검수 결과를 받지 못했으므로
  성공으로 처리하지 않는다.
- Codex 부분 변경 확인: 새 mtime·추가 경로 없이 Grok 2차 현재 바이트가 유지됐고,
  `git diff --check` exit 0, W1E Python `py_compile` exit 0.
- 다음 조치: 동일 범위를 `max_turns=256`, `timeout=3600초`로 재실행한다.

#### DeepSeek 2차 확장 재시도 결과

- actor/action: `DEEPSEEK / FIX`, `ROUND=2`, `RETRY=256`,
  `PHASE=AFTER_GROK_ROUND2`
- 설정: `deepseek-v4-pro`, `max_turns=256`, `timeout=3600초`
- provider result: `status=succeeded`, `exit=0`, `duration_ms=1053286`
- 변경 경로: `NONE`; 현재 바이트를 재검수했으나 evidence-backed 수정은 없었다.
- provider static 결과: root/branch/status, 13개 W1E Python compile, 전체 static/whitespace/
  conflict scan, exact 5-node binding, migration→grant→postcheck→pytest 순서,
  trigger-bypass gate, 0025→0026 ancestry 모두 exit 0.
- provider review: GENERAL-only position/qualification 동작, FAMILY service/DB CHECK,
  422 precheck와 409/`23P01` mapping, audit lineage, postcheck ACL을 확인했으며
  FAMILY position/qualification scope ambiguity는 추정하지 않고 유지했다.
- Codex 확인 예정/필수: provider 성공 선언과 무관하게 현재 status, `git diff --check`,
  W1E compile, 변경 mtime·hash를 재확인한 뒤 2라운드를 닫는다.
- 환경 차단 유지: pytest/Ruff/OpenAPI/live 0026 PostgreSQL harness는 empty venv와
  sandbox `pwsh` 부재로 미실행.

### 최종 독립검수

- 대상: 2라운드 종료 후보의 별도 worktree
- actor: Codex subagent `gpt-5.6-sol`
- reasoning effort: `ultra`
- 범위: 현재 후보와 독립 worktree의 byte/diff/test/recovery 경계 대조 및 필요한 수정
- 정본 승격: 형님 승인 전까지 보류

#### Sol ultra 최종 독립검수 결과

- worktree: `/home/codexctl/worktrees/sswcenter-3-0-final-review-20260816`
- HEAD: `059ecf3dbfb54ac0a896303702d74ef190f8d984`, detached
- actor/action: `CODEX / FIX`, `FINAL_INDEPENDENT_REVIEW=true`
- 설정: `gpt-5.6-sol`, reasoning `ultra`; 원본 worktree와 Git stage/commit/push는 사용하지 않음.
- result: `STATUS=PASS_W1E`; `REPOSITORY_WIDE_STATUS=RED_OUT_OF_SCOPE`
- 변경 경로(10): `20260814_0026_w1e_care_assignment_family_relationship_lock.py`,
  `backend/app/db/models.py`, `backend/app/db/postcheck_current_0026.py`,
  `backend/app/db/postcheck_dispatch.py`, `backend/app/domains/w1e/errors.py`,
  `backend/app/domains/w1e/service.py`, `backend/tests/test_w1e_0026_postgres.py`,
  `backend/tests/test_w1e_phase1_behavior.py`,
  `backend/tests/test_w1e_phase1_contract.py`,
  `scripts/test-w1e-0026-postgres-linux.ps1`
- 수정 요지: fake method shadowing, migration naming, CHECK cast normalization,
  Windows TEMP 유입, trigger `ENABLE REPLICA` 우회, exclusion predicate/deferrability,
  ACL `REFERENCES`/`TRIGGER`/grant-option, 0026→0025→0026 왕복 harness, Ruff/scoped mypy.
- 실행 증거: W1E gate `36 passed, 5 skipped`; 집중 behavior `7 passed`; Ruff 18파일,
  scoped mypy 10소스, OpenAPI `OPENAPI_TYPES_UP_TO_DATE`, exact 5-node live PG16
  harness `5 passed`, cleanup listener/process/temp/git_delta 모두 `0`, 전체 핵심 exit `0`.
- 적대적 검증: `ENABLE REPLICA`, exclusion/equality/range/predicate/deferrability,
  ACL REFERENCES/TRIGGER/grant-option drift를 실 DB에서 주입 후 fail-closed 확인.
- 범위 밖 적색: 전체 backend `422 passed, 148 skipped, 13 failed`, full mypy 범위 밖
  3파일 12 errors. E2E 단일 HTTP→실 PG 연결은 미실행. 이는 W1E PASS를 무효화하지 않으나
  repository-wide seal 근거는 아니다.
- Codex 재확인: target `git diff --check` exit 0, W1E compile exit 0. target 최종
  hashes는 provider 보고와 일치했으며, 원본 동일 경로 hashes는 Sol 변경 전 값으로
  유지되어 자동 반영이 없음을 확인했다.
- 미결 유지: FAMILY position/qualification canonical scope ambiguity는 GENERAL-only로
  보존. 형님 승인 전 정본 승격·원본 반영·Git 작업은 하지 않는다.

#### Sol 결과의 원본 반영 및 테스트 worktree 준비

- 형님 지시에 따라 Sol ultra 최종 10개 경로를
  `/home/codexctl/workspace/sswcenter-3-0` 원본에 반영했다.
- source worktree와 원본의 10개 SHA-256이 모두 일치했으며, stage/commit/push는 하지 않았다.
- 테스트 전용 detached worktree를 생성했다:
  `/home/codexctl/worktrees/sswcenter-3-0-test-spark-20260816`
- 후보 W1E 경로와 handoff/ledger만 복제했고, 현재 preflight는
  W1E Python compile exit 0, `git diff --check` exit 0이다.
- 요청 모델 `gpt-5.3 Codex Spark · xhigh`는 현재 collaboration runtime에 노출되지 않아
  실행이 거부됐다. 사용 가능한 모델을 임의 대체하지 않았으며, 실제 사용 가능 모델은
  `gpt-5.6-sol/terra/luna`, `gpt-5.5`, `gpt-5.4`이다.

#### 테스트 실행에서 발견된 API 계약 누락과 수정

- 테스트 worktree에서 확인된 최초 결과: 실 PG harness `5 passed`, unit `3 passed`,
  contract `4 failed`, behavior collection `1 error`.
- 원인: `get_w1e_service` dependency export 누락, `w1e_router`의 `app.main` 등록 누락,
  read-only `RecipientSexCodeRead(MALE/FEMALE/TEST)` 누락, generated OpenAPI client drift.
- evidence-backed 수정 경로: `backend/app/api/dependencies.py`, `backend/app/main.py`,
  `backend/app/domains/recipient/schemas.py`,
  `backend/app/domains/recipient/service.py`,
  `frontend/src/generated/sswcenter-api.ts`.
- 수정 후 원본 targeted 결과: phase-1 contract/behavior/unit `27 passed, 1 warning`,
  W1E-only mypy `7 source files` success, Ruff check `All checks passed`, Ruff format
  `14 files already formatted`, OpenAPI `OPENAPI_TYPES_UP_TO_DATE`.
- 수정 후 원본 live PG 재검증: `5 passed`, `W1E_0026_POSTGRES_LIVE_GREEN`,
  cleanup `listener=0 process=0 temp=0 git_delta=0`, `W1E_0026_POSTGRES_SEAL_GREEN`.
- broad mypy에서 기존 범위 밖 `postcheck_current_0025.py` 1건과
  `recipient/service.py` 기존 3건이 남았으며 W1E-only 결과와 분리했다.
- 이 수정은 기존 Sol ultra 검수 이후 추가된 것이므로, 최종 repository seal 전에는
  새 현재 바이트를 대상으로 독립 final review를 한 번 더 수행해야 한다.

#### 현재 바이트 재검증 및 독립검수 재개

- 재검증 시각: 2026-08-16 KST; 원본 HEAD는
  `059ecf3dbfb54ac0a896303702d74ef190f8d984`를 유지하고 stage/commit/push는 하지 않았다.
- 현재 원본 재검증: phase-1 contract/behavior/unit `27 passed, 1 warning`; Ruff check
  `All checks passed`; Ruff format `14 files already formatted`; W1E-only mypy
  `7 source files` success; OpenAPI `OPENAPI_TYPES_UP_TO_DATE`; `git diff --check` exit 0.
- 실 PG 재검증: migration `0026 -> 0025 -> 0026`, postcheck, exact 5-node tests
  `5 passed`; `W1E_0026_POSTGRES_LIVE_GREEN`; cleanup `listener=0 process=0 temp=0 git_delta=0`;
  `W1E_0026_POSTGRES_SEAL_GREEN`.
- 새 독립 worktree: `/home/codexctl/worktrees/sswcenter-3-0-final-current-20260816`,
  detached HEAD 동일. 현재 W1E 후보·recipient/API 누락 수정·generated client·handoff를
  복제해 검수 입력을 고정했다.
- 요청 모델 `gpt-5.3 Codex Spark / xhigh`는 runtime에 노출되지 않아 호출 불가했다.
  형님이 앞서 승인한 최종검수 모델 `gpt-5.6-sol / ultra`로 대체한 사실을 숨기지 않고
  기록하며, 새 독립검수 결과가 나오기 전에는 봉인하지 않는다.

#### 독립 worktree 동기화 누락으로 인한 중간 false positive

- Sol ultra 중간 검수는 target worktree의 `backend/app/core/readiness.py`가 HEAD의
  0025 `CURRENT_REVISION/verify_current_0025`를 남긴 상태라며 실제 0026 API readiness
  `503 alembic_revision_mismatch`를 재현했다.
- 원본 현재 바이트를 대조한 결과 원본 `readiness.py`는 이미
  `ACTIVE_REVISION/verify_current_0026`로 수정되어 있었고,
  `backend/tests/test_w0_readiness_write_gate.py`도 0026 기준이었다. 이는 원본 결함이
  아니라 새 독립 worktree 복제 목록에서 현재 dirty인 두 경로를 빠뜨린 동기화 누락이다.
- 두 파일을 target에 현재 바이트로 복사하고 SHA/게이트를 재대조하도록 지시했다.
  이 finding은 target fixture incompleteness로 분류하며, 재검수 완료 전까지 봉인은 계속
  보류한다.
- 같은 중간 검수에서 `scripts/restore-drill.ps1`도 HEAD의 0025-only 버전으로 읽힌 것을
  확인했다. 원본 현재 파일은 0026 current revision/marker와 historical 0025를 모두
  지원하도록 이미 수정되어 있었고, 해당 경로도 target에 보충했다. readiness/restore
  두 건은 후보 worktree 동기화 누락으로 재분류하며 현재 바이트 재baseline을 다시 수행한다.

#### 현재 바이트 Sol ultra 독립검수 최종 결과

- 검수 worktree: `/home/codexctl/worktrees/sswcenter-3-0-final-current-20260816`,
  detached HEAD `059ecf3dbfb54ac0a896303702d74ef190f8d984`; 검수자는 파일을 수정하지
  않았고 stage/commit/push도 하지 않았다. Spark 5.3 미노출로 Sol ultra를 대체 사용했다.
- 동기화 누락으로 분류한 중간 false positive: `backend/app/core/readiness.py`,
  `backend/tests/test_w0_readiness_write_gate.py`, `scripts/restore-drill.ps1`은 원본의
  현재 0026 바이트를 target에 보충한 뒤 철회했다. 보충 후 W0 readiness gate `9 passed`.
- 최종 판정: `STATUS=FAIL`, `SEAL=NO-SEAL`. 치명적 crash는 없지만 중요 finding과
  계약·거버넌스 미확정이 있어 현재 바이트 봉인·정본 승격을 하지 않는다.
- 중요 finding 1: Linux 0026 harness의 5개 노드는 FAMILY CHECK/정상 GENERAL/overlap/
  catalog·ACL만 실행한다. contract/employment/position/qualification forward/reverse
  guard와 PERIOD_FACT 정정은 Windows legacy 9 live node에만 남아 있고, current postcheck는
  trigger name/state만 확인해 guard 함수 no-op 변조를 검출하지 못한다. 실제
  `HTTP -> service -> repository -> erp_app -> PostgreSQL -> audit` 통합 경로도 미검증이다.
- 중요 finding 2: harness의 `git_delta=0`은 실행 전후 porcelain 문자열만 비교한다.
  후보가 이미 `M/??`인 상태에서는 내용 변경을 놓칠 수 있어 cleanup가 false-pass다.
  경로별 SHA-256 before/after 비교가 필요하다.
- 중요 finding 3: 현재 구현을 승인할 3.0 current packet/plan이 없다. 기존 문서는
  Windows 2.1/0012 GENERAL-only 역사 RED이며 FAMILY/API/service/live PG를 제외한다.
  현재 matrix와 구 plan의 FAMILY/side-effect ID 및 `CARE_ASSIGNMENT_PERIOD_CONFLICT`
  409 대 현재 구현 422가 불일치해 FAMILY 범위·HTTP 계약을 명시적으로 결정해야 한다.
- 중요 finding 4: 운영표준은 R2 opener `DeepSeek -> Grok` 및 SHA manifest/finding-ID
  ledger를 요구하지만 실제 ledger는 양 라운드 `Grok -> DeepSeek`이고 필수 manifest/table이
  없다. 최종 report 자체는 원본에 존재하지만 초기 target 복제에서 빠졌던 별도 sync 누락은
  보충 후 철회했다. 라운드 순서·manifest·finding table의 실제 불일치는 유지된다.
- 보통 finding: 역순 날짜는 실제 `422 / VALIDATION_ERROR`지만 W1E OpenAPI 422 설명과
  generated TypeScript 설명에 해당 코드를 열거하지 않는다.
- 실행 증거: phase1 contract/behavior/unit `27 passed, 1 warning`; W0 readiness `9 passed`;
  live PG `5 passed`, cleanup listener/process/temp/git_delta `0`; OpenAPI generator
  `OPENAPI_TYPES_UP_TO_DATE`; generated client SHA `a755224e...`; `git diff --check` 통과.
  target에서 사용 가능한 venv는 Python 3.12.3이고 canonical 3.11.15 실행은 독립검수에서
  미검증이다.
- 다음 조치: 형님이 current packet/plan, FAMILY 범위, 422/409 계약, live HTTP/PG 범위와
  harness/postcheck 강화 여부를 결정한 뒤 별도 구현 라운드와 새 독립검수를 수행한다.
  그 전까지는 봉인하지 않고 대기한다.

#### 추가 구현 라운드: Grok finding → DeepSeek FIX → Grok 재검수

- 실행일: 2026-08-16 KST. 이 라운드의 provider 기본 `max_turns=128`,
  `timeout=3600초`; DeepSeek FIX는 형님 지시의 확장 한도에 따라
  `max_turns=256`, `timeout=3600초`로 재실행했다. provider 실행 중 Git stage/commit/push,
  reset/clean은 하지 않았다.
- Grok 1차 read-only review: `GROK / REVIEW`, runner 기본 모델(명시적 `grok-4.5`는
  `/home/codexctl/.local/bin/ssw-agent` parser가 허용하지 않아 실행 불가), duration 약
  `554149ms`, `STATUS=FAIL`. 확인된 finding은 dirty W1E 배선·0012 oracle manifest 누락,
  `_compact_sql` 토큰 경계 붕괴, FAMILY precedence 및 8개 guard mutation 증거 부족이었다.
- DeepSeek FIX: `DEEPSEEK / FIX`, `deepseek-v4-pro`, `max_turns=256`,
  `timeout=3600초`, duration 약 `613643ms`, `status=succeeded`. 변경 경로는
  `backend/app/db/postcheck_current_0026.py`,
  `backend/tests/test_w1e_0026_postcheck_unit.py`,
  `backend/tests/test_w1e_0026_postgres.py`,
  `scripts/test-w1e-0026-postgres-linux.ps1`이다.
  SHA manifest를 27개 scoped path로 확장해 0012 oracle과 dirty W1E wiring을 포함했고,
  `_compact_sql`을 문자열·quoted identifier·연산자·identifier token 경계를 보존하는
  정규화기로 교체했으며, FAMILY precedence mutation과 8개 guard 각각의
  `IF FALSE` dead-code savepoint mutation을 추가했다.
- Codex 현재 바이트 검증: Ruff format/check exit 0, W1E scoped mypy 8 source exit 0,
  phase1/postcheck targeted `35 passed` 후 W0 readiness까지 합친 `44 passed, 1 warning`,
  실 PG16 0026→0025→0026 하니스 `8 passed`,
  `W1E_0026_POSTGRES_LIVE_GREEN`, cleanup
  `listener=0 process=0 temp=0 git_delta=0 manifest_delta=0`,
  `W1E_0026_POSTGRES_SEAL_GREEN`, OpenAPI `OPENAPI_TYPES_UP_TO_DATE`를 확인했다.
  Python 검증은 외부 test venv 3.12.3이며 canonical 3.11.15와 구분해 기록한다.
- Grok 재검수: `GROK / REVIEW`, runner 기본 모델, duration 약 `749843ms`,
  `STATUS=PASS`. 현재 manifest·토큰 경계·boolean precedence·8개 mutation·trigger
  catalog·OpenAPI `VALIDATION_ERROR`가 구조적으로 일치한다고 확인했다. Low 수준의 단위
  단언 폭/`_compact_sql` dollar-quote 미검증은 남겼고, live PG·canonical 3.11 재실행은
  Grok sandbox에서 못 했으나 Codex 실행 증거와 충돌하지 않는다.
- 다음 입력: 새 독립 worktree
  `/home/codexctl/worktrees/sswcenter-3-0-final-current-2-20260816`를 HEAD
  `059ecf3dbfb54ac0a896303702d74ef190f8d984`에서 분리하고 현재 dirty 33경로를 동기화했다.
  `gpt-5.6-sol / ultra` 독립 `REVIEW`를 target에만 배정했으며, 결과 전에는 봉인하지 않는다.
- 이번 라운드에서도 미결인 3.0 current packet/plan, FAMILY position/qualification 범위,
  422/409 계약, HTTP→real PG→audit 통합, concurrency/write-skew, repository-wide
  suite/full mypy, 운영표준 R2 opener/finding-ID governance는 결정·검증하지 않았다.

## 증거 업데이트 규칙

각 실행 종료 후 아래 항목을 해당 섹션에 추가한다.

1. 실제 시작·종료 시각과 provider/model/action
2. `max_turns`, `timeout`, 재시도 여부
3. 변경 경로와 변경 전후 SHA 또는 diff 요약
4. 실행한 명령·exit·테스트 수치
5. provider finding과 Codex가 확인한 finding의 차이
6. 미검증·차단 항목과 다음 라운드 입력

## 환경 drift 복구 및 현재 venv gate (2026-08-16 추가)

- 실제 저장소 `backend/.venv`가 Python 3.12.3이지만 의존성이 비어 있던 문제를
  `scripts/ensure-runtime.ps1`로 복구했다. `backend/requirements.lock` 104개 패키지를
  `uv pip sync --offline`으로 설치했으며 네트워크 없이 재현된다.
- `scripts/verify-runtime.ps1`를 추가해 Python 3.12.3, pytest 9.1.1, Ruff 0.16.0,
  mypy 2.3.0, FastAPI 0.139.2, SQLAlchemy 2.0.51, Alembic 1.18.5, psycopg 3.3.4,
  Node 24.19.0, npm 11.17.0, PowerShell 7.6.4, PostgreSQL client 16.14를 한 번에
  확인한다. 결과 `SSWCENTER_RUNTIME_GREEN`.
- canonical venv 재검증: targeted pytest `58 passed, 1 warning`; Ruff check/format
  exit 0; scoped mypy exit 0; OpenAPI `OPENAPI_TYPES_UP_TO_DATE`; live PG `10 passed`,
  cleanup `listener=0 process=0 temp=0 git_delta=0 manifest_delta=0`.
- canonical mypy가 드러낸 기존 4개 타입 오류(`postcheck_current_0025` 기본 인자,
  guardian slot literal, recipient deadline loop shadowing)를 수정하고 관련 recipient
  contract와 W1E 테스트 `94 passed, 1 skipped, 1 warning`으로 회귀 확인했다.
- 실행 interpreter는 실제 설치 상태에 맞춰 3.12.3으로 문서화했으며, `pyproject.toml`의
  정적 `py311` target은 호환성 검사 target으로 별도 기록했다. 역사 실행 기록의 당시
  `3.11.15 미검증` 표기는 과거 증거로 보존한다.

### Grok FIX: uncommitted assignment parent-lock gap (2026-08-16)

- actor/action: `GROK / FIX`
- 범위: DeepSeek 구현 이후 dirty 후보. 기존 W1E dirty WIP는 보존하고
  historical 0012는 수정하지 않았다. stage/commit/push 없음.
- 재현: 0026 edge helper가 committed assignment만 lock해서, uncommitted
  INSERT와 parent reverse가 둘 다 success/success로 끝나 orphan이 생길 수
  있었다. 대상 노드는
  `test_w1e_0026_pg_contract_concurrent_assignment_vs_parent_update`,
  `test_w1e_0026_pg_employment_concurrent_assignment_vs_parent_update`.
- 수정: `fn_w1e_lock_contract_assignment_edges` /
  `fn_w1e_lock_employment_assignment_edges`가 committed edge가 있으면
  `(contract_id, employment_id)` 순서로만 lock하고, 없으면 해당
  parent-domain lock을 유지한다. contract parent가 domain lock을 먼저
  잡고 employment/position/qualification parent가 employment domain을
  먼저 잡는 교차 순서는 deadlock이므로 사용하지 않는다.
- ABI 검수: postcheck는 `proargtypes` OID 20/20 20, exact argument
  names, missing/extra overload를 fail-closed로 거부한다. live 적대
  테스트는 integer overload(`overloads:...count=2`), missing bigint,
  renamed argument를 각각 거부했다.
- `scripts/verify-runtime.ps1` 검수: npm basename fail-closed와 strict
  semver 정규식은 현재 바이트에 있다. 이 Grok sandbox에는 `pwsh`가
  없어 스크립트 자체와 printf 행동 테스트는 실행하지 못했고, 소스
  계약 단위 테스트는 통과했다.
- 실행 증거:
  - targeted unit/contract/behavior/postcheck/readiness:
    `60 passed, 1 skipped, 1 warning`
  - 같은 묶음에 live PG 게이트를 포함하면 `60 passed, 13 skipped, 1 warning`
    (12개 0026 노드 + printf 행동 테스트 skip)
  - Ruff check/format: 변경 파일 exit 0
  - scoped mypy: 8 W1E product source, 이어서 9 source(`app/api/w1e.py`
    포함) 모두 `Success: no issues found`
  - `git diff --check`: exit 0
  - 실 PostgreSQL 16.14 격리 cluster: `0026 -> 0025 -> 0026`, grant,
    current postcheck OK, exact 12-node pytest `12 passed` in 1.49s,
    cleanup cluster 0
  - 포함 노드: assignment-vs-contract, assignment-vs-employment,
    contract-service vs qualification invalidation(1 success + 23514,
    orphan=0), integer/missing/renamed ABI
- 미실행: canonical `pwsh scripts/ensure-runtime.ps1` /
  `verify-runtime.ps1` / `test-w1e-0026-postgres-linux.ps1` /
  OpenAPI `-Check`. 이 sandbox는 `/home/codexctl/.local/bin/pwsh`와
  `/usr/local/bin/node` 실행이 막혀 있다. OpenAPI spec은 Python으로
  extract했고 경로 76개·W1E assignment 경로 5개가 로드됐다.
- finding: `W1E-0026-F09`를 current plan에 추가했다.

### Grok FIX: canonical FAMILY trim set + npm sibling identity (2026-08-16)

- actor/action: `GROK / FIX`
- 범위: DeepSeek 기술 검수 이후 현재 dirty 0026 후보. 기존 dirty WIP는
  보존하고 historical 0012는 수정하지 않았다. stage/commit/push 없음.
- 제품 finding F10: API `str.strip()`은 Unicode/FF/VT까지 지우지만 DB 0026
  CHECK/postcheck는 SPACE/HT/LF/CR만 `btrim`했다. 직접 SQL의 FF/VT-only
  FAMILY 값은 DB를 통과하고 API는 거부했다.
- 결정: 정본 trim 집합은 ASCII 6문자 ` \t\n\r\f\v`. Unicode whitespace는
  의미 있는 내용이며 트림하지 않는다. 단일 모듈
  `backend/app/db/w1e_family_relationship.py`를 API/service, ORM metadata,
  0026 precheck/CHECK, postcheck exact CHECK, 테스트가 공유한다.
- npm finding F08 평가: 현재 계약은 basename + semver다. Linux
  `/usr/local/bin/npm` 고정과 npm 바이너리/lock 해시는 현재 계약이 아니고
  Windows `npm.cmd`를 깨므로 넣지 않았다. 안전한 보강으로 기본 npm을
  해결된 `node`의 sibling으로 고르고, 명시 `-NpmExecutable`도 같은
  디렉터리여야 한다.
- 거버넌스: R2 opener가 운영표준의 DeepSeek→Grok 교대와 달리 양 라운드
  Grok→DeepSeek였다. 이는 제품 결함이 아니다. 이 FIX 이후 fresh Sol Ultra
  독립 worktree 검수는 아직이며 봉인하지 않는다 (`G04`, `G05`).
- 실행 증거:
  - targeted W0+W1E: `61 passed, 1 skipped, 1 warning`
    (`test_verify_runtime_behavior_rejects_printf_as_npm_executable`는
    이 sandbox에 `pwsh`가 없어 skip)
  - 실 PostgreSQL 16.14 격리 cluster: `0026 -> 0025 -> 0026`, grant,
    current postcheck OK, exact 12-node pytest `12 passed` in 1.55s,
    cluster/temp cleanup 0
  - live FAMILY 적대: FF/VT-only 거부, 4-char CHECK mutation 거부,
    NBSP와 문자 `v`는 통과 (E-string `\\v` 함정 회귀)
  - Ruff check 22파일 exit 0, format already formatted
  - scoped mypy 13 source exit 0
  - `git diff --check` exit 0
  - OpenAPI: Python extract 경로 76개, W1A staff 존재.
    공식 `generate-openapi-types.ps1 -Check`는 `pwsh`/`npm` 실행 불가로
    미실행. 스키마 변경 없음
  - candidate manifest 재생성: 48 paths
- 미실행: canonical `pwsh scripts/ensure-runtime.ps1` /
  `verify-runtime.ps1` / `test-w1e-0026-postgres-linux.ps1` /
  OpenAPI `-Check`. 이 sandbox는 `pwsh`가 없고 `/usr/local/bin/node`·
  `/usr/local/bin/npm` 실행이 Permission denied다.
- SEAL=NO-SEAL. fresh Sol Ultra 독립 worktree 검수 전.

### DeepSeek FIX: multi-edge lock ordering + sequence/ABI postcheck (2026-08-16)

- actor/action: `DEEPSEEK / IMPLEMENT`
- 범위: 현재 dirty 0026 후보. 기존 dirty WIP는 보존하고 historical
  `20260801_0012`는 수정하지 않았다. stage/commit/push 없음.
- P1 재현: 기존 `fn_w1e_lock_employment_assignment_edges`가 edge마다
  `C -> E`를 호출해 multi-edge employment parent가 `C1,E`를 들고 `C2`를
  기다리는 동안 assignment-side `C2 -> E`가 `C2`를 들고 `E`를 기다리면
  `40P01` deadlock이 가능했다.
- P1 수정: `fn_w1e_lock_contract_assignment_edges` /
  `fn_w1e_lock_employment_assignment_edges`가 committed edge 집합에서
  distinct contract id를 ascending으로 먼저 lock하고, 이어서 distinct
  employment id를 ascending으로 lock한다. 빈 edge fallback은 해당
  parent-domain lock만 유지한다. assignment path는 contract -> employment
  단일 순서를 유지한다.
- P2 수정: `erp_app` role 누락을 early fail-closed하고,
  `erp.care_assignment_id_seq` owner가 care_assignment table owner와
  일치하며 `erp_app`에 `USAGE+SELECT`만 있는지 검사한다. lock helper ABI는
  기존 name/args/body/owner/language/security-definer/proconfig에 더해
  `proretset`, `provolatile`, `proisstrict`, `proparallel`,
  `proleakproof`, `proacl`, `erp_app` EXECUTE ACL/grant-option을
  fail-closed로 검사한다.
- 변경 경로: `backend/alembic/versions/20260814_0026_...py`,
  `backend/app/db/postcheck_current_0026.py`,
  `backend/tests/test_w1e_0026_postcheck_unit.py`,
  `backend/tests/test_w1e_0026_postgres.py`,
  `backend/tests/test_w1e_phase1_contract.py`,
  `scripts/test-w1e-0026-postgres-linux.ps1`
- 실행 증거:
  - targeted pytest: `59 passed, 1 warning`
  - Ruff check: `All checks passed`; Ruff format check `5 files already formatted`
  - scoped mypy 6 source: `Success: no issues found`
  - 수동 격리 PostgreSQL 16.14 cluster: upgrade head, grant, postcheck OK,
    live 0026 pytest `15 passed`; 추가 lifecycle·cleanup는 아래 별도 확인
  - 새 live 노드: multi-edge employment parent vs assignment `C2 -> E`
    deadlock regression, sequence ACL mutation 3건, lock helper property/ACL
    mutation 6건
- 미실행/미검증: canonical `pwsh scripts/ensure-runtime.ps1` /
  `verify-runtime.ps1` / `test-w1e-0026-postgres-linux.ps1`와 공식 OpenAPI
  `-Check`는 이 sandbox에 `pwsh`가 없어 미실행. Python 기반 OpenAPI 비교와
  수동 PG lifecycle는 별도 실행 결과로 기록한다.
- SEAL=NO-SEAL. 변경 후 fresh Sol Ultra 독립 worktree 검수 전.

### Grok FIX: SemVer 2.0.0 + 0012 backup sequence ACL (2026-08-16)

- actor/action: `GROK / FIX`
- 범위: DeepSeek multi-edge/ACL 라운드 이후 현재 dirty 0026 후보.
  기존 dirty WIP는 보존하고 historical `20260801_0012`는 수정하지 않았다.
  stage/commit/push/checkout/reset/clean 없음.
- 재검증: DeepSeek의 contract-domain-first lock 순서는 현재 0026 helper
  바이트와 일치했다. empty-edge fallback은 committed edge가 없을 때만
  parent-domain lock을 유지한다. 격리 PG 15-node live에서 multi-edge
  employment parent vs assignment `C2 -> E`가 `15 passed`였고 `40P01`은
  없었다.
- P2 보강: postcheck가 `erp_backup` SELECT-only(USAGE/UPDATE/grant-option
  금지)를 0012와 같이 fail-closed한다. live mutation에
  REVOKE SELECT, USAGE/UPDATE grant-option, backup USAGE/UPDATE/SELECT
  제거를 추가했다. identity sequence는 `ALTER SEQUENCE ... OWNER`가
  SQLSTATE `0A000`으로 거부되므로 owner live mutation은 넣지 않았고
  catalog owner 비교만 유지한다.
- P3 보강: lock helper live mutation에 SECURITY DEFINER, `SET search_path`,
  EXECUTE WITH GRANT OPTION을 추가했다. 기존 overload/missing/renamed
  ABI와 STABLE/STRICT/PARALLEL SAFE/LEAKPROOF/OWNER/GRANT EXECUTE는 유지.
- P4 수정: `scripts/RuntimeVersion.psm1`에 SemVer 2.0.0 공식 문법 regex와
  identifier helper를 두고 `verify-runtime.ps1`이 import한다. 이전
  `^[0-9]+.[0-9]+.[0-9]+` matcher는 `01.2.3`, `1.2.3-01`, `alpha..1`을
  허용했다. 단위 벡터와 pwsh helper/fake-npm `--version` 행동 테스트,
  `/usr/bin/printf` basename 거부를 추가했다.
- 변경 경로: `scripts/RuntimeVersion.psm1`(신규),
  `scripts/verify-runtime.ps1`,
  `scripts/test-w1e-0026-postgres-linux.ps1`,
  `backend/app/db/postcheck_current_0026.py`,
  `backend/tests/test_verify_runtime_script.py`,
  `backend/tests/test_w1e_0026_postcheck_unit.py`,
  `backend/tests/test_w1e_0026_postgres.py`,
  `backend/tests/test_w1e_phase1_contract.py`,
  current packet/plan/ledger/report/manifest
- 실행 증거:
  - targeted unit/contract/behavior/postcheck/readiness:
    `66 passed, 15 skipped, 1 warning` (15개는 live PG 게이트 skip)
  - 격리 PostgreSQL 16.14 Linux harness
    `scripts/test-w1e-0026-postgres-linux.ps1`:
    `0026 -> 0025 -> 0026`, grant, current postcheck OK,
    exact 15-node pytest `15 passed`,
    cleanup `listener=0 process=0 temp=0 git_delta=0 manifest_delta=0`,
    harness marker `W1E_0026_POSTGRES_SEAL_GREEN`
  - Ruff check 32 files `All checks passed`; format already formatted
  - scoped mypy 24 source `Success: no issues found`
  - `git diff --check` exit 0
  - historical 0012 sha
    `95ea8be02d2f14aea394dfc3d7fe95905046c51110863232dfcafff5c910d158`
    unchanged
  - OpenAPI Python extract 경로 76개, W1A staff 존재, generated client에
    CareAssignment/`VALIDATION_ERROR` 존재. 공식
    `generate-openapi-types.ps1 -Check`는 이 샌드박스가
    `/opt/node-v24.19.0/bin/node`를 Permission denied로 막아 미실행
  - `scripts/verify-runtime.ps1` 전체 GREEN은 같은 node 실행 거부로
    미도달. SemVer helper/fake-npm/printf 행동 테스트는 pwsh 7.6.4로
    PASS
- 미검증: HTTP→service→repository→real PG→audit 통합, repository-wide
  suite/full mypy, canonical Python 3.11, 공식 OpenAPI `-Check`,
  공식 `verify-runtime.ps1` GREEN. R2 opener는 운영표준의
  DeepSeek→Grok 교대와 달리 양 라운드 Grok→DeepSeek였다.
- SEAL=NO-SEAL. 이 FIX 이후 fresh Sol Ultra 독립 worktree 검수 전.

### DeepSeek FIX: Sol Ultra target-only finding 반영 (2026-08-16)

- actor/action: `DEEPSEEK / FIX`
- 범위: 최종 독립검수 target-only finding 4건을 현재 원본 dirty 0026 후보에
  반영. 기존 dirty WIP는 보존하고 historical `20260801_0012`는 수정하지
  않았다. stage/commit/push/checkout/reset/clean 없음.
- finding/FIX:
  - `W1E-0026-F14` (HIGH/P1): employment helper의 `locked_edge` fallback이
    첫 contract-edge SELECT 후 edge disappearance 시 E-lock을 건너뛰어
    `C2→E` assignment + parent shrink write-skew가 가능했다.
    `fn_w1e_lock_employment_assignment_edges`를 distinct contract id
    ascending 선취 후 **항상 `p_employment_id` employment lock**을 취득하는
    구조로 단순화했다. 두 번째 employment-edge SELECT 제거.
  - `W1E-0026-F15` (MEDIUM): `_strip_harmless_display_casts`가 `::text`
    외의 임의 `::type`(`::date`)을 삭제해 의미가 다른 CHECK가 expected와
    같게 정규화될 수 있었다. PostgreSQL `pg_get_constraintdef(..., true)`가
    넣는 `::text`만 제거하고 다른 type cast는 보존하도록 수정.
  - `W1E-0026-F16` (MEDIUM): `_verify_w1e_constraint_triggers`가
    `provolatile`/`proisstrict`/`proparallel`/`proleakproof`/`proacl`과
    `erp_app` EXECUTE/grant-option drift를 놓쳤다. W1E trigger function에
    exact catalog attrs(volatile `v`, strict false, parallel `u`,
    leakproof false, proacl null, security invoker, no proconfig, table
    owner)와 EXECUTE ACL을 fail-closed로 검사.
  - `W1E-0026-F17` (MEDIUM): sequence ACL이 `erp_app`/`erp_backup` effective
    tuple만 확인해 PUBLIC/제3 role grant를 통과시켰다. `relacl`/`aclexplode`
    exact grantee/privilege/grant-option 검사를 추가해 owner entry와 조건부
    `erp_app`(USAGE+SELECT, no grant option), 조건부 `erp_backup`(SELECT
    only, USAGE revoked, no grant option) 외 drift를 fail-closed.
- 실행 증거:
  - targeted W0+W1E unit/contract/behavior: `62 passed, 1 warning`
  - `app/db/postcheck_current_0026.py` scoped mypy: `Success: no issues found`
  - Ruff check/format: 변경 5파일 exit 0; `git diff --check` exit 0
  - OpenAPI 재생성 exact compare: `OPENAPI_TYPES_UP_TO_DATE`
  - 격리 PostgreSQL 16.14 Linux 수동 하니스: `0026 → 0025 → 0026`, grant,
    current postcheck OK, exact 17-node pytest `17 passed`,
    cleanup `listener=0 process_delta=0 temp=0 git_delta=0 manifest_delta=0`
  - 새 live adversarial: employment helper empty-edge/transient-disappearance
    advisory-lock interleaving, trigger function catalog mutation 10건,
    sequence PUBLIC/third-role grant/revoke mutation
- 미검증: 이 sandbox에는 `pwsh`가 없어 canonical
  `scripts/verify-runtime.ps1`/`test-w1e-0026-postgres-linux.ps1`/공식
  OpenAPI `-Check`는 직접 실행하지 못했다. Python 기반 OpenAPI compare와
  수동 PG lifecycle는 별도 실행 결과로 기록한다. HTTP→real PG→audit 통합,
  repository-wide suite/full mypy, canonical Python 3.11은 계속 미검증이다.
  R2 opener 편차(Grok→DeepSeek)는 이전 기록과 동일하게 보존한다.
- SEAL=NO-SEAL. fresh Sol Ultra worktree review 전.

### Grok FIX: F14-F17 현재 바이트 재검수+보강 (2026-08-16)

- actor/action: `GROK / FIX`
- 범위: DeepSeek가 보고한 Sol Ultra F14-F17 수정을 현재 바이트로 재검증하고,
  남은 검수 틈을 수정. 기존 dirty WIP 보존. historical `20260801_0012`는
  수정하지 않았다. stage/commit/push/checkout/reset/clean 없음.
- 재검증 결과:
  - F14 제품 helper는 distinct contract id ascending 후 항상
    `p_employment_id` employment-domain lock을 잡는다. assignment path는
    C→E, contract parent는 C들 다음 E들, employment parent는 C들 다음
    고정 E. 전역 contract-before-employment 순서는 유지된다.
  - F14 live 회귀는 `pg_locks`의 임의 ungranted lock만 봐서 contract
    blocker rollback 직후 C-wait를 E-wait로 오인할 수 있었다. 관측을
    `hashtextextended(domain, key)` exact advisory lock으로 바꿨다.
  - F15 `_strip_harmless_display_casts`는 `::text`/`::TEXT`만 제거하고
    `::date`/`::varchar`/`::pg_catalog.text`/`::citext`/quoted `"text"`는
    보존한다. unit adversarial와 live `::date` mutation fail-closed.
  - F16 trigger catalog는 return/signature/body/owner/language/security/
    proconfig/provolatile/proisstrict/proparallel/proleakproof/proacl과
    erp_app EXECUTE/grant-option을 fail-closed한다. `proretset` false를
    trigger function catalog에도 추가했다. live mutation 10건 유지.
  - F17 sequence ACL은 owner entry를 허용하고, non-owner row는
    grantor=owner이며 존재하는 `erp_app`(USAGE+SELECT) /
    `erp_backup`(SELECT only) exact set만 허용한다. PUBLIC/제3 role/
    extra privilege/grant-option/missing required entry는 fail-closed.
    effective `has_sequence_privilege`는 exact set을 대체하지 않는다.
    identity sequence `ALTER SEQUENCE ... OWNER`는 PostgreSQL `0A000`.
- 변경 경로:
  `backend/app/db/postcheck_current_0026.py`,
  `backend/tests/test_w1e_0026_postgres.py`,
  `backend/tests/test_w1e_0026_postcheck_unit.py`,
  `backend/tests/test_w1e_phase1_contract.py`,
  current packet/plan/ledger/report/manifest
- 실행 증거:
  - `uv pip sync --offline` 104 packages, Python 3.12.3 venv
  - targeted W0+W1E: `68 passed, 17 skipped, 1 warning`
    (17개는 `SSWCENTER_W1E_0026_REAL_PG` 게이트)
  - Ruff check/format 31 files exit 0
  - scoped mypy 22 sources: `Success: no issues found`
  - `git diff --check` exit 0
  - historical 0012 sha
    `95ea8be02d2f14aea394dfc3d7fe95905046c51110863232dfcafff5c910d158`
    unchanged
  - OpenAPI Python extract 경로 76개, W1A staff/CareAssignment/
    `VALIDATION_ERROR` 존재. 공식 `generate-openapi-types.ps1 -Check`는
    `/usr/local/bin/node` Permission denied로 미실행
  - 격리 PostgreSQL 16.14 Linux harness
    `scripts/test-w1e-0026-postgres-linux.ps1`:
    `0026 -> 0025 -> 0026`, grant, current postcheck OK,
    exact 17-node pytest `17 passed`,
    cleanup `listener=0 process=0 temp=0 git_delta=0 manifest_delta=0`,
    harness marker `W1E_0026_POSTGRES_SEAL_GREEN`
  - 공식 `scripts/ensure-runtime.ps1`/`verify-runtime.ps1`는 이 샌드박스에서
    `SSWCENTER_RUNTIME_GREEN`을 내지 못했다. 기본 `uv` cache 경로
    `/home/codexctl/.cache/uv` Permission denied, `/usr/local/bin/node`
    Permission denied. 세션 전용 공식 PowerShell 7.6.4 tarball
    (SHA-256 `4471b5a3...`)과 `UV_CACHE_DIR=/tmp/sswcenter-uv-cache`로
    offline sync와 harness를 실행했다. runtime GREEN으로 선언하지 않는다.
- 미검증: HTTP→service→repository→real PG→audit 통합, repository-wide
  suite/full mypy, canonical Python 3.11, 공식 OpenAPI `-Check`,
  공식 `verify-runtime.ps1` GREEN. R2 opener는 운영표준의
  DeepSeek→Grok 교대와 달리 양 라운드 Grok→DeepSeek였다.
- SEAL=NO-SEAL. 이 FIX 이후 fresh Sol Ultra 독립 worktree 검수 전.

### DeepSeek FIX: multi-row assignment transaction-wide global mutex (2026-08-16)

- actor/action: `DEEPSEEK / FIX`
- 범위: 최신 Sol Ultra 독립검수에서 재현된 W1E-0026 P1. 기존 dirty WIP는
  보존하고 historical `20260801_0012`는 수정하지 않았다.
  stage/commit/push/checkout/reset/clean 없음.
- P1 재현: 기존 `fn_w1e_lock_assignment_path`는 호출 1건에서는 `C→E`지만,
  DEFERRABLE FOR EACH ROW trigger가 한 transaction의 여러 assignment row를
  처리하면 row별 `C1,E` 후 `C2,E`가 되어 transaction-wide `C1,E,C2` 순서가
  된다. 상대가 `C2→E`를 처리하면 T1은 E를 들고 C2를 기다리고, T2는 C2를
  들고 E를 기다려 PostgreSQL 16 SQLSTATE `40P01` deadlock이 발생한다.
- P1 수정: 모든 W1E write path가 어떤 domain lock보다 먼저 단일 공통
  transaction mutex `erp.fn_w1e_lock_global()`(`hashtextextended(
  'erp.w1e.global', 0)`)을 잡도록 0026 current migration의 lock helper를
  교체했다. `fn_w1e_lock_contract_path`/`fn_w1e_lock_employment_path`도
  global mutex를 선취하므로 도메인 helper를 직접 호출하는 미래 경로도
  우회하지 못한다. mutex 안에서는 기존 contract-domain ascending-first →
  employment-domain 순서를 유지하고, empty-edge fallback과 F14 transient
  disappearance 동작은 그대로 보존한다.
- P2 재점검: F15 FAMILY normalizer(`::text`만 제거), F16 trigger catalog
  exactness(proretset/provolatile/proisstrict/proparallel/proleakproof/
  proacl/EXECUTE ACL), F17 sequence relacl/aclexplode를 재확인했다.
  F17 verifier는 owner-grantee ACL row를 skip하지 않고
  `grantee=sequence_owner`일 때 `grantor=sequence_owner`와 no grant
  option을 요구하도록 보강했다. identity sequence `ALTER SEQUENCE ...
  OWNER` 제한(`0A000`)은 유지한다.
- 변경 경로:
  `backend/alembic/versions/20260814_0026_w1e_care_assignment_family_relationship_lock.py`,
  `backend/app/db/postcheck_current_0026.py`,
  `backend/tests/test_w1e_0026_postcheck_unit.py`,
  `backend/tests/test_w1e_0026_postgres.py`,
  `backend/tests/test_w1e_phase1_contract.py`,
  `scripts/test-w1e-0026-postgres-linux.ps1`,
  current packet/plan/ledger/report/manifest
- 실행 증거(이 DEEPSEEK sandbox):
  - `git diff --check` exit 0
  - targeted W0/W1E pytest: `65 passed, 3 skipped, 1 warning`
    (3개는 `pwsh` 부재로 skip)
  - Ruff check/format: 변경 5개 Python 파일 exit 0
  - scoped mypy 9 source: `Success: no issues found`
  - OpenAPI Python extract + `npm exec openapi-typescript` exact compare:
    `OPENAPI_TYPES_UP_TO_DATE`
  - 격리 PostgreSQL 16.14 Linux 수동 하니스:
    `0026 -> 0025 -> 0026`, grant, current postcheck OK,
    exact 18-node pytest `18 passed`,
    cleanup listener(port free)/process 0/temp 0을 확인
  - 새 live 노드 `test_w1e_0026_pg_multi_row_assignment_transaction_global_mutex`
    포함 18-node 전부 통과
  - historical 0012 sha
    `95ea8be02d2f14aea394dfc3d7fe95905046c51110863232dfcafff5c910d158`
    unchanged
  - 이 sandbox에는 `pwsh`가 없어 canonical
    `scripts/verify-runtime.ps1`/`scripts/test-w1e-0026-postgres-linux.ps1`/
    `generate-openapi-types.ps1 -Check`는 직접 실행하지 못했다.
    Python·Ruff·mypy·node·npm·psql 버전은 확인했고, PostgreSQL lifecycle은
    수동 동등 절차로 대체했다. canonical runtime GREEN으로 선언하지 않는다.
- 미검증: HTTP→service→repository→real PG→audit 통합, repository-wide
  suite/full mypy, canonical Python 3.11, 공식 `verify-runtime.ps1` GREEN,
  공식 pwsh harness. R2 opener는 운영표준의 DeepSeek→Grok 교대와 달리 양
  라운드 Grok→DeepSeek였다.
- SEAL=NO-SEAL. 이 FIX 이후 fresh Sol Ultra 독립 worktree 검수 전.

### Grok FIX: F18 상대검수 + 40P01 leftover 500 + granted-key live 관측 (2026-08-16)

- actor/action: `GROK / FIX`
- 범위: DeepSeek 최신 Sol P1 global mutex 보고를 현재 바이트로 재검증하고
  남은 결함을 수정. 기존 dirty WIP 보존. historical `20260801_0012`는
  수정하지 않았다. stage/commit/push/checkout/reset/clean 없음.
- 재검증:
  - 모든 W1E write helper가 domain lock 전에 `erp.fn_w1e_lock_global()`
    (`hashtextextended('erp.w1e.global', 0)`)을 취득한다.
    `fn_w1e_lock_assignment_path`는 contract_path → employment_path를
    호출하므로 각 domain helper가 global을 선취한다. 한 transaction의
    반복 호출은 xact advisory lock이라 재진입된다.
  - contract parent는 global 후 C들→E들, employment parent는 global 후
    C들→항상 `p_employment_id`. assignment는 global 후 C→E. 교차
    deadlock/write-skew는 공통 mutex로 serialize된다. 직렬화 tradeoff는
    packet/plan에 기록되어 있다.
  - F14 empty-edge/transient-disappearance는 exact C 대기 → edge delete →
    exact E 대기를 유지한다.
  - F15는 `::text`만 제거한다. F16 trigger catalog는
    proretset/provolatile/proisstrict/proparallel/proleakproof/proacl/
    erp_app EXECUTE를 fail-closed한다. F17 relacl/aclexplode는
    owner-grantee/grantor=owner/no grant option과 app/backup exact set,
    PUBLIC/제3 role extras를 거부한다.
- 제품 결함 F19: W1E `_flush`/`_commit`가 IntegrityError만 매핑하고
  OperationalError `40P01`은 500이었다. `_map_sqlalchemy_error`가
  `40P01`을 `409 CARE_ASSIGNMENT_CONCURRENT_CONFLICT`로 매핑한다.
  W1D/Staff는 SQLSTATE만으로 W1E deadlock을 구분할 수 없어 W1E code로
  재표시하지 않았다. OpenAPI 스키마 변경 없음.
- live 테스트 보강: multi-row 회귀가 T1 granted global/C1/E와 C2 wait,
  T2 global wait와 C2/E 미보유를 exact advisory key로 관측한다.
- 변경 경로:
  `backend/app/domains/w1e/service.py`,
  `backend/tests/test_w1e_0026_postgres.py`,
  `backend/tests/test_w1e_0026_integrity_mapping.py`,
  `backend/tests/test_w1e_0026_postcheck_unit.py`,
  `backend/tests/test_w1e_phase1_behavior.py`,
  `backend/tests/test_w1e_phase1_contract.py`,
  current packet/plan/ledger/report/manifest
- 실행 증거(이 GROK sandbox):
  - targeted W0+W1E: `69 passed, 3 skipped, 1 warning`
    (3개는 `pwsh` 부재로 verify-runtime 행동 테스트 skip)
  - Ruff check/format: 변경 Python 파일 exit 0
  - scoped mypy 20 source: `Success: no issues found`
  - `git diff --check` exit 0
  - historical 0012 sha
    `95ea8be02d2f14aea394dfc3d7fe95905046c51110863232dfcafff5c910d158`
    unchanged
  - OpenAPI Python extract 경로 76개, W1E 409/422 설명 exact.
    공식 `generate-openapi-types.ps1 -Check`는 `/usr/local/bin/node`
    Permission denied로 미실행
  - 격리 PostgreSQL 16.14 수동 하니스(공식 pwsh 스크립트와 동등 절차):
    `0026 -> 0025 -> 0026`, grant, current postcheck OK,
    exact 18-node pytest `18 passed`,
    cleanup listener=0 process=0 temp=0 git_delta=0 manifest_delta=0
  - 공식 `pwsh scripts/ensure-runtime.ps1`/`verify-runtime.ps1`는
    이 sandbox에 `pwsh`가 없어 미실행. runtime GREEN으로 선언하지 않는다
- 미검증: HTTP→service→repository→real PG→audit 통합, repository-wide
  suite/full mypy, canonical Python 3.11, 공식 OpenAPI `-Check`,
  공식 `verify-runtime.ps1` GREEN. R2 opener는 운영표준의
  DeepSeek→Grok 교대와 달리 양 라운드 Grok→DeepSeek였다.
- SEAL=NO-SEAL. 이 FIX 이후 fresh Sol Ultra 독립 worktree 검수 전.


### DeepSeek FIX: fine-grained optimistic/fail-fast protocol replaces global mutex (2026-08-16 latest decision)

- actor/action: `DEEPSEEK / FIX`
- 범위: 형님 최신 지시가 기존 0026 global-mutex 설계를 대체함. 기존 dirty WIP는
  보존하고 historical `20260801_0012`는 수정하지 않았다.
  stage/commit/push/checkout/reset/clean 없음.
- 설계: `erp.fn_w1e_lock_global()`과 `erp.w1e.global` key를 제거하고,
  contract/employment 도메인별 `pg_try_advisory_xact_lock` non-waiting
  transaction-scoped advisory lock으로 교체했다. lock loss는 SQLSTATE `55P03`,
  message `CARE_ASSIGNMENT_CONCURRENT_CONFLICT`로 즉시 fail-fast한다.
- 순서: 모든 W1E write path는 contract-domain ascending-first → employment-domain
  순서를 유지한다. non-waiting이므로 partial set을 든 채 대기하지 않아 multi-row
  assignment와 multi-edge parent에서 `40P01` cycle이 없다. lock 취득 후 각 guard가
  최신 committed state를 재검증해 READ COMMITTED snapshot timing을 정확히 처리한다.
- HTTP 매핑: W1E `_map_sqlalchemy_error`가 `40P01`/`55P03`을 409로 매핑하고,
  deferred assignment guard의 `23514`도 precheck 통과 후 final-save race이므로 409로
  매핑한다. W1D/Staff parent guard의 `55P03`도 409 `CARE_ASSIGNMENT_CONCURRENT_CONFLICT`로
  매핑한다. 기존 precheck 422와 orphan 409는 유지한다.
- 변경 경로:
  `backend/alembic/versions/20260814_0026_w1e_care_assignment_family_relationship_lock.py`,
  `backend/app/db/postcheck_current_0026.py`,
  `backend/app/domains/w1e/service.py`,
  `backend/app/domains/w1d/errors.py`,
  `backend/app/domains/w1d/service.py`,
  `backend/app/domains/staff/service.py`,
  `backend/tests/test_w1e_0026_integrity_mapping.py`,
  `backend/tests/test_w1e_0026_postcheck_unit.py`,
  `backend/tests/test_w1e_0026_postgres.py`,
  `backend/tests/test_w1e_phase1_contract.py`,
  `scripts/test-w1e-0026-postgres-linux.ps1`,
  current packet/plan/ledger/report/manifest
- 실행 증거(이 DEEPSEEK sandbox):
  - targeted W0+W1E unit/contract/behavior/postcheck/readiness: `70 passed, 1 warning`
  - Ruff check/format: 변경 Python 파일 exit 0
  - scoped mypy 5 source files: `Success: no issues found`
  - OpenAPI exact compare: `OPENAPI_TYPES_UP_TO_DATE` (Python extract +
    `npm exec openapi-typescript` + byte compare)
  - 격리 PostgreSQL 16.14 수동 하니스(공식 pwsh 스크립트와 동등 절차):
    `0026 -> 0025 -> 0026`, grant, current postcheck OK,
    exact 19-node pytest `19 passed` in 3.50s
  - 새 live 노드: unrelated write가 old `erp.w1e.global` key를 든 blocker와 무관하게
    commit; multi-row assignment가 C2 blocker 앞에서 즉시 `55P03`; employment helper
    empty/with-edge가 exact employment key에서 `55P03` fail-fast
  - barrier race 4종(assignment↔contract, assignment↔employment,
    contract↔qualification, multi-edge)은 1 success + 1 loser(`55P03` 또는 final
    validation `23514`), orphan 0, 40P01 0
  - historical 0012 sha `95ea8be02d2f14aea394dfc3d7fe95905046c51110863232dfcafff5c910d158`
    unchanged
- 미검증: canonical `pwsh scripts/ensure-runtime.ps1`/`verify-runtime.ps1`/
  `test-w1e-0026-postgres-linux.ps1`는 이 sandbox에 `pwsh`가 없어 미실행.
  위 PG16 절차는 동등 bash/Python 수동 harness로 재현했다. HTTP→real PG→audit
  단일 E2E, repository-wide suite/full mypy/canonical 3.11, fresh Sol Ultra
  worktree review는 계속 follow-up이다. R2 opener 편차(Grok→DeepSeek)는 보존.
- SEAL=NO-SEAL. 이 FIX 이후 fresh Sol Ultra 독립 worktree 검수 전.

### Grok FIX: COMPLETE_CANDIDATE_MUTUAL_VERIFICATION fine-grained protocol (2026-08-16)

- actor/action: `GROK / FIX`, `ROUND=COMPLETE_CANDIDATE_MUTUAL_VERIFICATION`
- 설정: 기본 128턴, 이 넓은 상호검증은 상한 256턴·timeout 3600초. Git 쓰기 없음.
- 범위: 현재 dirty 0026 complete candidate를 untrusted로 재검증. historical
  `20260801_0012`는 수정하지 않았다. 기존 dirty WIP 보존.
- DESIGN_VERDICT: PostgreSQL 16 READ COMMITTED + deferred row constraint
  trigger + `pg_try_advisory_xact_lock` exact contract/employment keys는
  현재 W1E 도메인에서 안전하다. 최종 save가 자기 conflict domain을 원자적으로
  잡고 committed state를 재검증하며, 관련 경쟁 commit의 패자는 fail-fast
  `55P03` 또는 재검증 `23514`로 rollback한다. 무관한 C/E write는 서로 다른
  key를 동시에 든 채 둘 다 commit한다. 폐기된 `erp.w1e.global` mutex는
  필요하지 않다.
- finding/FIX:
  - `W1E-0026-F22` (HIGH): old global key를 든 채 한쪽 write만 통과하는
    약한 증명은 거부. 두 실제 assignment INSERT를 disjoint C/E에서
    barrier로 overlap시키고 exact advisory key 동시 보유·ungranted wait
    0·both commit를 live 관측.
  - `W1E-0026-F23` (HIGH): application `lock_timeout=5s` 때문에 모든
    `55P03`을 care-assignment 409로 재표시하면 안 된다. helper RAISE
    message `CARE_ASSIGNMENT_CONCURRENT_CONFLICT`가 있는 층만 409.
    nested `orig`/`diag`/`__cause__` 검사. lock timeout/NOWAIT는 500.
    W1D/Staff와 recipient detail batch deferred commit도 같은 식별자를 씀.
  - `W1E-0026-F24` (MEDIUM): postcheck가 resurrected
    `fn_w1e_lock_global`/`erp.w1e.global` remnant를 거부하도록
    `CURRENT_0026_W1E_FORBIDDEN_LOCK_REMNANT` fail-closed + live CREATE
    mutation.
- 실행 증거(이 GROK sandbox):
  - targeted unit/contract/behavior/postcheck/readiness:
    `76 passed, 3 skipped, 1 warning` (3개는 `pwsh` 부재 verify-runtime
    행동 테스트 skip)
  - Ruff check/format: 변경 Python 파일 exit 0
  - scoped mypy 12 source: `Success: no issues found`
  - `git diff --check` exit 0
  - historical 0012 sha
    `95ea8be02d2f14aea394dfc3d7fe95905046c51110863232dfcafff5c910d158`
    unchanged
  - OpenAPI Python extract 경로 76개, W1E 409/422 코드 존재. 공식
    `generate-openapi-types.ps1 -Check`는 `/usr/local/bin/node`
    Permission denied로 미실행
  - 격리 PostgreSQL 16.14 수동 하니스(공식 pwsh 스크립트와 동등 절차):
    `0026 -> 0025 -> 0026`, grant, current postcheck OK,
    exact 21-node pytest `21 passed` in 3.76s,
    cleanup cluster exists=0
  - 새 live 노드: disjoint-domain two-write overlap+both commit;
    resurrected global helper remnant fail-closed
  - 공식 `pwsh scripts/ensure-runtime.ps1`/`verify-runtime.ps1`/
    `test-w1e-0026-postgres-linux.ps1`는 이 sandbox에 `pwsh`가 없어
    미실행. runtime GREEN으로 선언하지 않는다
- 미검증: HTTP→service→repository→real PG→audit 통합, repository-wide
  suite/full mypy, canonical Python 3.11, 공식 OpenAPI `-Check`,
  공식 `verify-runtime.ps1` GREEN. R2 opener 편차(Grok→DeepSeek) 보존.
- SEAL=NO-SEAL. 이 FIX 이후 fresh Sol Ultra 독립 worktree 검수 전.

### DeepSeek FIX: REVERSE_MUTUAL_VERIFICATION_AFTER_GROK (2026-08-16 latest)

- actor/action: `DEEPSEEK / FIX`, `ROUND=REVERSE_MUTUAL_VERIFICATION_AFTER_GROK`
- 범위: Grok `COMPLETE_CANDIDATE_MUTUAL_VERIFICATION` 이후 현재 dirty 0026
  complete candidate를 독립적으로 TEST→REVIEW→FIX. 기존 dirty WIP 보존.
  historical `20260801_0012`는 수정하지 않았다. stage/commit/push/
  checkout/reset/clean 없음.
- TEST 재현:
  - `test_w1d_contract.py::test_w1d_03_openapi_routes_and_named_models_are_registered`
    가 Ubuntu에서 `No such file or directory: 'npm.cmd'`로 실패.
  - 이 저장소는 Linux-only이고 canonical npm은 `/usr/local/bin/npm`이다.
- finding/FIX:
  - `W1E-0026-F25` (HIGH): W1D contract test가 hardcoded `npm.cmd`를
    호출. `backend/tests/test_w1d_contract.py`에 non-Windows
    `shutil.which("npm")` + canonical `/usr/local/bin/npm` fallback resolver를
    추가하고 생성된 TS byte/contract 단언은 유지. Windows에서만 `npm.cmd`를
    사용하는 cross-platform resolver로 교체. 회귀 test 추가.
  - `W1E-0026-F26` (HIGH): real HTTP integration test가 W1E repository의
    `assignment_overlaps_active`가 `exclude_assignment_id=None`을 untyped
    parameter로 PostgreSQL에 보내 `AmbiguousParameter` 500을 만드는 제품
    결함을 재현. SQL을 `CAST(:exclude_assignment_id AS bigint)`로 고정.
  - `W1E-0026-G02` (closure): `test_w1e_0026_pg_http_create_replace_through_real_service_and_audit`
    를 exact live PG node로 추가. FastAPI `TestClient`로 실제 route/
    dependency/service/repository를 통과시키고 authentication identity만
    dependency override(관리·조회 account)로 주입. fake repository/service는
    사용하지 않음. create 201, replacement 200 lineage/row_version,
    audit `CARE_ASSIGNMENT_CREATE`/`CARE_ASSIGNMENT_REPLACE`/
    `CARE_ASSIGNMENT_REPLACEMENT_CREATE` exact actions, version-conflict
    409 rollback no extra audit를 `erp_app` role로 검증.
- 변경 경로:
  `backend/app/domains/w1e/repository.py`,
  `backend/tests/test_w1d_contract.py`,
  `backend/tests/test_w1e_0026_postgres.py`,
  `backend/tests/test_w1e_phase1_contract.py`,
  `scripts/test-w1e-0026-postgres-linux.ps1`,
  current packet/plan/ledger/report/manifest
- 실행 증거(이 DEEPSEEK sandbox):
  - targeted W0+W1D+W1E unit/contract/behavior/integrity/postcheck:
    `98 passed, 3 skipped, 1 warning`
  - W1D contract 단독: `11 passed`
  - W1E behavior에 `recipient_detail_batch_defer_commit` flush-only 회귀 추가
  - Ruff check/format: 변경 31개 Python 파일 exit 0
  - scoped mypy 12 source: `Success: no issues found`
  - OpenAPI exact compare: `OPENAPI_TYPES_UP_TO_DATE`
  - 격리 PostgreSQL 16.14 수동 하니스(공식 pwsh 스크립트와 동등 절차):
    `0026 -> 0025 -> 0026`, grant, current postcheck OK,
    exact 22-node pytest `22 passed` in 4.70s,
    cleanup `listener=0 process=0 temp=0 git_delta=0 manifest_delta=0`,
    harness marker `W1E_0026_POSTGRES_SEAL_GREEN`
  - historical 0012 sha
    `95ea8be02d2f14aea394dfc3d7fe95905046c51110863232dfcafff5c910d158`
    unchanged
  - `git diff --check` exit 0
- 미검증: 공식 `pwsh scripts/ensure-runtime.ps1`/`verify-runtime.ps1`/
  `test-w1e-0026-postgres-linux.ps1`는 이 sandbox에 `pwsh`가 없어 직접
  실행하지 못했다. 위 PG16 절차는 동등 bash/Python 수동 harness로 재현했다.
  repository-wide suite/full mypy/canonical 3.11은 계속 follow-up이다.
  R2 opener 편차(Grok→DeepSeek) 보존.
- SEAL=NO-SEAL. 이 FIX 이후 fresh Sol Ultra 독립 worktree 검수 전.

### Grok FIX: CLOSING_MUTUAL_VERIFICATION (2026-08-16)

- actor/action: `GROK / FIX`, `ROUND=CLOSING_MUTUAL_VERIFICATION`
- 범위: DeepSeek `REVERSE_MUTUAL_VERIFICATION_AFTER_GROK` 이후 현재 dirty
  0026 complete candidate를 untrusted로 TEST→REVIEW→FIX. 기존 dirty WIP
  보존. historical `20260801_0012`는 수정하지 않았다. stage/commit/push/
  checkout/reset/clean 없음.
- DESIGN_VERDICT: 현재 fine-grained `pg_try_advisory_xact_lock` + 최종
  committed-state 재검증은 유지한다. DeepSeek CAST/HTTP/npm 후보는 구조는
  맞지만 계약 공백 4건이 남아 수정했다.
- finding/FIX:
  - `W1E-0026-F27` (HIGH): deferred assignment `23514` 메시지 폴백이 422.
    flush/commit은 409 `CARE_ASSIGNMENT_CONCURRENT_CONFLICT`.
  - `W1E-0026-F28` (HIGH): `55P03` 식별이 `str(layer)` 부분문자열을 보면
    wrapper/SQL에 코드가 섞인 lock timeout을 409로 재표시. exact
    `message_primary`/SQLAlchemy 첫 줄만 인정. W1D/Staff IntegrityError
    경로도 같은 식별자를 쓰도록 보강.
  - `W1E-0026-F29` (MEDIUM): HTTP live node가 settings/engine `erp_app`
    username, service/session override 부재, `current_user`와 app-role
    readback을 단언하지 않음.
  - `W1E-0026-F30` (MEDIUM): CAST None/실 id 결정적 회귀 부재. repository
    unit + source contract 추가. Linux npm resolver는 실제
    `openapi-typescript` 생성을 skip하지 않음을 AST로 고정.
- 실행 증거(이 GROK sandbox):
  - targeted W0+W1D+W1E unit/contract/behavior/integrity/postcheck/
    readiness/verify-runtime: `94 passed, 3 skipped, 1 deselected, 1 warning`
    (3개는 `pwsh` 부재 verify-runtime 행동 테스트 skip; 1개는
    `test_w1d_03` OpenAPI TS 생성이 `/usr/local/bin/npm` Permission denied)
  - Ruff check/format: 변경 Python 파일 exit 0
  - scoped mypy 9 source: `Success: no issues found`
  - `git diff --check` exit 0
  - historical 0012 sha
    `95ea8be02d2f14aea394dfc3d7fe95905046c51110863232dfcafff5c910d158`
    unchanged
  - OpenAPI Python extract 경로 76개, W1E assignment 경로 5개,
    409/422 코드 존재. 공식 `generate-openapi-types.ps1 -Check`는
    `/usr/local/bin/node` Permission denied로 미실행
  - 격리 PostgreSQL 16.14 수동 하니스(공식 pwsh 스크립트와 동등 절차):
    `0026 -> 0025 -> 0026`, grant, current postcheck OK as `erp_app`,
    exact 22-node pytest `22 passed` in 4.65s,
    cleanup `listener=0 process=0 temp=0 git_delta=0 manifest_delta=0`,
    `W1E_0026_POSTGRES_LIVE_GREEN`, `W1E_0026_POSTGRES_SEAL_GREEN`
  - 공식 `pwsh scripts/ensure-runtime.ps1`/`verify-runtime.ps1`/
    `test-w1e-0026-postgres-linux.ps1`는 이 sandbox에 `pwsh`가 없어
    미실행. runtime GREEN으로 선언하지 않는다
- 미검증: 공식 `verify-runtime.ps1` GREEN, 공식 OpenAPI `-Check`,
  repository-wide suite/full mypy, canonical Python 3.11, fresh Sol Ultra
  worktree review. R2 opener 편차(Grok→DeepSeek) 보존.
- SEAL=NO-SEAL. 이 FIX 이후 fresh Sol Ultra 독립 worktree 검수 전.

### DeepSeek FIX: F14_TRANSIENT_DISAPPEARANCE_LIVE_PROOF (2026-08-16)

- actor/action: `DEEPSEEK / FIX`, `UNIT=W1E_0026_F14_TRANSIENT_DISAPPEARANCE_LIVE_PROOF`
- SOURCE_REVIEW: `/home/codexctl/worktrees/sswcenter-3-0-final-current-8-20260816`
  (fresh gpt-5.6-sol ultra Grade 5 review `STATUS=FAIL/NO-SEAL`, P2 F14
  evidence/governance blocker)
- 범위: Sol Ultra Grade 5 review에서 제기된 F14 live evidence/governance
  blocker를 수정한다. 기존 dirty WIP 보존. historical
  `20260801_0012`는 수정하지 않았다. stage/commit/push/checkout/reset/clean 없음.
- finding/FIX:
  - `W1E-0026-F14` (P2 evidence/governance): 기존
    `test_w1e_0026_pg_employment_lock_helper_always_locks_employment_path`는
    empty-edge/ordinary with-edge만 E prehold + immediate 55P03로 관측하고
    DELETE/transient window를 실제로 강제하지 않았다.
  - 새 live node
    `test_w1e_0026_pg_employment_helper_transient_disappearance_still_locks_employment`
    를 추가해 exact sequence를 강제한다. production employment helper body는
    수정하지 않고, `fn_w1e_lock_contract_path`에만 test-only explicit advisory
    gate를 주입한다.
  - sequence: 첫 contract-edge SELECT가 committed C1을 관측 →
    C1 contract-lock 호출 지점 gate에서 정지(pg_locks ungranted exact key로
    관측) → 별도 transaction이 edge DELETE commit → gate 해제 후 helper 재개 →
    edge 부재에도 exact E key를 요청하며 별도 exact E blocker가 stable
    `55P03`/`CARE_ASSIGNMENT_CONCURRENT_CONFLICT`를 관측 → 40P01/orphan/residue 0.
  - test-only `CREATE OR REPLACE` instrumentation은 `finally`에서
    `pg_get_functiondef` 원본으로 byte-exact 복원, catalog/ACL 비교,
    `verify_current_0026` 통과.
  - `test_w1e_0026_pg_employment_lock_helper_always_locks_employment_path`
    docstring은 empty-edge/ordinary with-edge만 주장하도록 정정하고,
    transient proof는 새 노드로 연결.
- 변경 경로:
  `backend/tests/test_w1e_0026_postgres.py`,
  `backend/tests/test_w1e_phase1_contract.py`,
  `scripts/test-w1e-0026-postgres-linux.ps1`,
  current packet/plan/ledger/report/manifest
- 실행 증거(이 DEEPSEEK sandbox):
  - targeted W0+W1D+W1E unit/contract/behavior/integrity/postcheck/readiness/
    verify-runtime: `98 passed, 3 skipped, 1 warning`
  - live PG 단일 노드 focused: `1 passed`
  - 격리 PostgreSQL 16.14 수동 하니스(공식 pwsh 스크립트와 동등 절차):
    `0026 -> 0025 -> 0026`, grant, current postcheck OK as `erp_app`,
    exact 23-node pytest `23 passed` in 5.33s,
    cleanup `listener=0 process=0 temp=0 git_delta=0 manifest_delta=0`,
    `W1E_0026_POSTGRES_LIVE_GREEN`
  - Ruff check/format: 변경 Python 파일 exit 0
  - scoped mypy 15 source: `Success: no issues found`
  - OpenAPI exact compare: `OPENAPI_TYPES_UP_TO_DATE`
  - `git diff --check` exit 0
  - historical 0012 sha
    `95ea8be02d2f14aea394dfc3d7fe95905046c51110863232dfcafff5c910d158`
    unchanged
  - 공식 `pwsh scripts/ensure-runtime.ps1`/`verify-runtime.ps1`/
    `test-w1e-0026-postgres-linux.ps1`는 이 sandbox에 `pwsh`가 없어
    직접 실행하지 못했다. 위 PG16 절차는 동등 bash/Python 수동 harness로
    재현했다. runtime GREEN으로 선언하지 않는다.
- 미검증: 공식 `verify-runtime.ps1` GREEN, 공식 OpenAPI `-Check`,
  repository-wide suite/full mypy, canonical Python 3.11, fresh Sol Ultra
  worktree review. R2 opener 편차(Grok→DeepSeek) 보존.
- SEAL=NO-SEAL. 이 FIX 이후 fresh Sol Ultra 독립 worktree 검수 전.

### Grok FIX: F14_TRANSIENT_DISAPPEARANCE_CLOSING_MUTUAL_VERIFICATION (2026-08-16)

- actor/action: `GROK / FIX`,
  `UNIT=W1E_0026_F14_TRANSIENT_DISAPPEARANCE_CLOSING_MUTUAL_VERIFICATION`
- 설정: subscription CLI 기본 모델 `grok-4.6`, 명시 `reasoning_effort=xhigh`.
  Git 쓰기 없음. historical `20260801_0012` 미수정.
- SOURCE: DeepSeek F14 live-proof 완료 후보를 untrusted로 자체 TEST→REVIEW→FIX.
  DeepSeek PASS를 신뢰하지 않았다. 이전 30초 Grok 실행은 파일 변경이 없어
  pass로 세지 않는다.
- TEST 재현:
  - 현재 후보는 dedicated 23번째 live node와 empty-edge/with-edge 보존은
    맞지만, catalog capture가 `pg_proc` 일부 컬럼만 비교하고,
    instrumentation이 outer try 밖이며, `finally`의 `_fail`이 함수 복원보다
    먼저 실행될 수 있었다.
  - gate 관측 시점에 edge 잔존·helper의 production C/E 미보유·exact E
    blocker 유지·무관 C blocker 부재·domain hash 비충돌을 단언하지 않았다.
- finding/FIX:
  - catalog: `pg_get_functiondef` + `to_jsonb(pg_proc)::text`로
    OID/owner/ACL/cost/rows/support/args/defaults/body/config/flags를
    비교. MVCC system column은 `to_jsonb(pg_proc)`에 없다. PostgreSQL 16.14의
    `pg_get_function_identity_arguments`는 이 함수에서
    `p_contract_id bigint`를 반환한다.
  - cleanup fail-safe: instrumentation을 restoration-guaranteed scope로
    옮김. gate/E blocker 항상 해제, bounded join, exact helper
    `pg_cancel_backend`, isolated ephemeral
    `/tmp/sswcenter-w1e-0026-pg-*`에서만 `pg_terminate_backend`,
    invalidate+close, advisory/PID/residue 확인, DDL 복원, catalog 비교,
    `verify_current_0026` 뒤에만 primary/cleanup 실패를 표면에 냄.
  - sequence 강화: gate에서 edge 존재, helper는 production C/E 미보유,
    DELETE 후에도 exact gate wait, conflict 시 exact E blocker 유지,
    무관 C blocker 부재, C/E/test-gate hash 비충돌. poll sleep은 exact
    `pg_locks` predicate backoff만 사용.
  - empty-edge/ordinary with-edge 노드는 유지. AST 23-node 유지.
    제품 migration/helper는 수정하지 않음.
- 정책 문서 4종(`00-먼저읽기-작업환경안내.md`,
  `00-오케스트레이션-작업지침.md`,
  `docs/AI_프로젝트_에이전트_실행계약_v1.0.md`,
  `docs/AI_2라운드_상호검증_운영표준_v1.0.md`)은 Codex가 pre-settings
  manifest 이후 기본 128 / 장시간 256 / hard max 256 / timeout 3600과
  Grok 기본 모델+명시 xhigh를 기록한 현재 바이트다. 이 세션은
  `grok-4.6`+xhigh와 일치한다. 이 sandbox에는 `ssw-agent`/`pwsh`가 없어
  runner 바이너리까지는 대조하지 못했고 문서 자체는 수정하지 않았다.
- 변경 경로:
  `backend/tests/test_w1e_0026_postgres.py`,
  `backend/tests/test_w1e_phase1_contract.py`,
  current packet/plan/ledger/report/manifest
- 실행 증거(이 GROK sandbox):
  - Python 3.12.3, pytest 9.1.1, Ruff 0.16.0, mypy 2.3.0
  - targeted W0+W1D+W1E: `94 passed, 1 failed, 26 skipped, 1 warning`
    (23개는 live PG 게이트 skip, 3개는 `pwsh` 부재 verify-runtime skip,
    1개는 `/usr/local/bin/npm` Permission denied로
    `test_w1d_03` OpenAPI TS 생성 실패. 테스트를 skip/xfail하지 않음)
  - Ruff check/format: 변경 Python 파일 exit 0
  - scoped mypy 16 source: `Success: no issues found`
  - OpenAPI Python extract 경로 76개. 공식 `generate-openapi-types.ps1
    -Check`와 `/usr/local/bin/npm`은 Permission denied로 미실행
  - `git diff --check` exit 0
  - historical 0012 sha
    `95ea8be02d2f14aea394dfc3d7fe95905046c51110863232dfcafff5c910d158`
    unchanged
  - 격리 PostgreSQL 16.14 수동 하니스(공식 pwsh 스크립트와 동등 절차):
    `0026 -> 0025 -> 0026`, grant, current postcheck OK as `erp_app`,
    exact 23-node pytest `23 passed` in 5.10s,
    cleanup `listener=0 process=0 temp=0 git_delta=0`,
    `W1E_0026_POSTGRES_LIVE_GREEN`, `W1E_0026_POSTGRES_SEAL_GREEN`.
    CREATE OR REPLACE 복원 후 `pg_get_functiondef`와
    `to_jsonb(pg_proc)::text`가 원본과 일치했다.
  - 공식 `pwsh scripts/ensure-runtime.ps1`/`verify-runtime.ps1`/
    `test-w1e-0026-postgres-linux.ps1`는 이 sandbox에 `pwsh`가 없어
    미실행. `SSWCENTER_RUNTIME_GREEN`을 선언하지 않는다.
  - candidate manifest는 이 FIX 종료 시
    `review/evidence/W1E_20260816_CURRENT_CANDIDATE_MANIFEST.sha256`로
    재생성한다. Codex가 갱신한 정책 문서 4종의 현재 바이트를 포함한다.
- 미검증: 공식 `verify-runtime.ps1` GREEN, 공식 OpenAPI `-Check`,
  repository-wide suite/full mypy, canonical Python 3.11, fresh Sol Ultra
  worktree review. R2 opener 편차(Grok→DeepSeek) 보존.
- SEAL=NO-SEAL. 이 FIX 이후 fresh Sol Ultra 독립 worktree 검수 전.

### Codex FIX: F14 cleanup SystemExit 보존 (2026-08-16)

- actor/action: `CODEX / FIX`. Grok 완료 후보에 대한 current-byte 병렬 정적검수
  finding을 반영했다. 제품 코드·0026 migration·historical `20260801_0012`는
  수정하지 않았다.
- finding: `verify_current_0026`은 postcheck 불일치에 `SystemExit`를 사용하지만,
  F14 cleanup은 `except Exception`만 사용했다. 따라서 복구 후 postcheck 실패가
  기존 primary/cleanup 오류 집계를 우회하고 앞선 원인을 가릴 수 있었다. 정상
  경로의 거짓 PASS는 아니지만 primary와 cleanup 오류 보존 계약에 미달했다.
- FIX: cleanup postcheck만 `BaseException`으로 포착해 `SystemExit`의 타입과
  메시지를 cleanup evidence에 보존한다. `KeyboardInterrupt`는 모든 복구 시도를
  마친 뒤 다시 전달하고, 일반 primary 오류도 `type + message`로 집계한다.
- 재검증:
  - 공식 Linux PG lifecycle `0026 -> 0025 -> 0026`, exact `23 passed`,
    `W1E_0026_POSTGRES_SEAL_GREEN`, cleanup
    `listener=0 process=0 temp=0 git_delta=0 manifest_delta=0`
  - Ruff check PASS. 첫 format-check는 한 줄 기계 서식 때문에 exit 1이었고
    바로 수정 후 check/format PASS.
  - 후속 pytest 첫 실행은 앱 capture 임시파일 `FileNotFoundError`로 `0 tests`;
    `TMP=/tmp TEMP=/tmp TMPDIR=/tmp`와 capture off로 재실행해 `51 passed`.
  - 이 수정 뒤 fresh Sol Ultra 독립 worktree 검수가 필요하다.
- SEAL=NO-SEAL. stage/commit/push/checkout/reset/clean 없음.
