# W1A-VS1 Opus 1차 반대심사 반환 패킷

## 1. 역할과 실행

- 담당: Claude CLI Opus 5
- 대상 worktree:
  `C:\Users\USER\.codex\worktrees\opus-w1a-019f9e39`
- 현재 호출 설정: `claude --model opus --effort high`
- 추론강도: 별도 사용자 지시가 있을 때까지 이번 재개와 이후 모든 Opus
  호출에서 `high`를 유지한다.
- 첫 호출에서 Claude 구독 세션 reset 시각이
  `2026-07-27 03:50 KST`로 안내됐다. 그 전에는 작업 없는 실패 재호출을
  하지 않는다.
- 금지: agent/subagent 생성, 다른 작업방 호출, Git stage/commit/push/reset,
  정본·계획 수정, W1A 밖 리팩터링, 최종승인 선언

staged 상태는 Codex 본진이 전달한 baseline이다. reset하거나 다시 stage하지
않는다. 현재 unstaged WIP와 untracked
`backend/tests/test_w1a_staff_current_projection.py`를 이어서 완성한다.

## 2. 먼저 읽을 자료

1. `review/packets/W1A_OPUS_HARDENING_PACKET.md`
2. `review/reports/w1a-vs1-marco-opus-round1.md`
3. 필요한 범위의 `review/plans/W1A_STAFF_VERTICAL_SLICE_PLAN.md`

## 3. 반드시 보정할 차단 결함

1. replacement field를 필수 nullable 또는 명시적 action으로 바꾸고,
   생략 422와 명시적 `null` 제거를 API·OpenAPI·실제 PG로 봉인한다.
2. 중복 ID, stale child, 전체 제거, 일부 대체, replacement link,
   actor/time/version, 첫 mutation 뒤 후속 실패의 실제 transaction rollback을
   PostgreSQL에서 독립 검증한다.
3. 직원·capability Query cache를 unmount/logout/account switch에서 확실히
   제거하고 계정 A→logout→계정 B, 페이지 이탈, 지연 reveal 응답을 실제
   AuthProvider 구조로 테스트한다.
4. `record.msg`뿐 아니라 최종 formatted traceback과 Uvicorn error log까지
   0/9 하이픈·비하이픈 주민번호를 redaction한다.
5. workspace 관련 tracked/untracked 텍스트, app/error/access log, PG log,
   Playwright output을 검사하는 독립 GREEN leak gate를 만든다. 실제 민감값은
   실패 출력에 쓰지 않는다.
6. migration ACL fingerprint를 surviving schema/table/sequence 전체로
   확장하고 downgrade 뒤 exact 동일성과 W1A permission row/definition 제거를
   검증한다.
7. UI가 `detail.current_employment`를 사용하게 하고 과거·미래·시작/종료
   경계 fixture를 추가한다. untracked projection test도 최종 파일 목록에
   포함한다.
8. trim·uppercase runtime normalization과 OpenAPI regex pattern을 동시에
   보존하고 role lowercase/trim/invalid/length 테스트를 추가한다.
9. 정식 OpenAPI 생성기를 실행하여 checked-in TypeScript drift를 0으로 만든다.
10. Ruff format 실패 2개 파일을 보정한다.

## 4. 중요 보강

- raw 13자리 regex의 epoch 과검출과 underscore 인접 누락을 함께 막는 공통
  RRN 후보 판별을 logging과 artifact gate에서 사용한다.
- Wave0 auth body/header/cookie, non-API 예상 밖 오류, body request ID와
  `X-Request-ID` 일치를 catch-all 회귀 테스트로 추가한다.
- 광범위한 downgrade revoke가 Wave0 선행 grant 0 불변조건에 의존하면
  precondition을 명시적으로 검증한다.

## 5. 현재 알려진 재검증 기준

- `git diff --check`: PASS
- backend 전체: `46 passed, 11 skipped`
- Ruff format: FAIL 2 files
- Ruff check: PASS
- mypy: PASS
- frontend: 9 files / 37 tests PASS
- frontend lint/build: PASS
- OpenAPI `-Check`: FAIL
- 실제 PostgreSQL 전체 harness: PASS였으나 leak·ACL gate 공백 존재
- 실제 PostgreSQL Playwright 3 viewports / workers=1: `3 passed`

기존 PASS 수치를 그대로 최종 증거로 재사용하지 않는다. 보정 뒤 정확한 명령을
다시 실행한다.

## 6. 완료조건과 반환 형식

- 원래 hardening A~F와 위 차단 10개가 코드와 회귀 테스트로 해결됐다.
- backend format/lint/type/full test가 모두 통과한다.
- frontend test/lint/build가 모두 통과한다.
- OpenAPI 독립 재생성 drift가 0이다.
- 실제 PostgreSQL fresh/upgrade/downgrade/re-upgrade/offline SQL,
  owner/app-role, ACL fingerprint, backup/restore/postcheck가 통과한다.
- 실제 PostgreSQL Playwright 3 viewports가 직렬 실행으로 통과한다.
- 독립 leak gate가 workspace/app log/PG log/Playwright output에서 0건이다.
- `git diff --check`가 통과한다.
- 최종 보고에 변경 파일 전체, 차단 항목별 대응, 실행 명령·exit code·결과,
  남은 위험을 적는다.
- stage·commit·push와 최종승인은 하지 않는다.

## 7. 2026-07-27 03:50 재개 체크포인트

Opus를 `--model opus --effort high`로 03:51 KST에 재개했다. 아래 보정을
진행했으나 04:24 KST에 새 세션 한도에 도달하여 최종보고 전에 중단됐다.
CLI가 안내한 다음 reset 시각은 `2026-07-27 08:50 KST`다.

이번 호출에서 수정 또는 추가된 Opus WIP:

- `backend/app/domains/staff/schemas.py`
- `frontend/src/generated/sswcenter-api.ts`
- `backend/app/core/logging.py`
- `frontend/src/context/AuthProvider.tsx`
- `frontend/src/pages/StaffPage.tsx`
- `backend/tests/test_logging.py`
- `backend/tests/test_w1a_staff_openapi_contract.py`
- `backend/tests/test_w1a_staff_semantics.py`
- `backend/tests/test_w1a_staff_api.py`
- `backend/tests/test_w1a_staff_integration_postgres.py`
- `backend/app/domains/staff/service.py`
- `scripts/test-w1a-vs1-postgres.ps1`
- `frontend/src/test/W1AStaffPage.test.tsx`
- untracked `backend/tests/test_w1a_staff_current_projection.py`
- untracked `frontend/src/test/AuthCacheBoundary.test.tsx`
- untracked `scripts/verify-w1a-vs1-leak-gate.ps1`

Codex 본진의 중단 직후 읽기 전용 검증:

- `git diff --check`: PASS
- backend 전체 pytest: `56 passed, 14 skipped`
- mypy: PASS
- Ruff format/check: FAIL
  - `backend/tests/test_w1a_staff_api.py` format
  - `backend/tests/test_w1a_staff_integration_postgres.py` format
  - 위 integration test의 E501 1건
- frontend `npm test`: `40 passed, 1 failed`
  - 실패:
    `frontend/src/test/AuthCacheBoundary.test.tsx`
  - 증상: 초기 계정 A 직원 목록 fixture가 렌더링되지 않고 loading 상태에 머묾
- frontend lint: PASS
- frontend build: PASS
- 독립 leak gate: 50개 파일 검사, 0건, PASS
- OpenAPI `-Check`: FAIL — checked-in TypeScript drift

08:50 재개 시 위 WIP를 되돌리지 말고 원래 담당자인 Opus가 남은 실패를 직접
수정한다. Codex 본진은 이 결함을 대신 구현하지 않는다. 그 뒤 전체 정적·단위·
OpenAPI·PostgreSQL·E2E·leak gate를 다시 실행하고 최종보고를 제출한다.
