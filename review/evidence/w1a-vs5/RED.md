# W1A-VS5 직원 분기상담 RED 봉인

> 판정: `RED_SEALED`
>
> 판정일: 2026-07-28 KST
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 기준 commit: `4adc6a63f7482e1e4e2470f9e4c072ed1cb229de`
>
> 총괄·최종판정: 김부장(Codex 본진 / SOL Max)

## 1. 봉인 범위

다음 제품 부재 계약을 환경·import·collection 오류가 아닌 named
`W1A_VS5_*` marker로 고정했다.

- `20260728_0007_w1a_staff_quarterly_consultation`
- 독립 `staff_quarterly_consultation` 원장과 exact 3상태 truth table
- staff/year/quarter active unique, 실제 race, optimistic locking
- invalidate/replacement, 두 audit, audit 실패 exact rollback
- ADMIN·VIEW·MANAGE·ungranted·CSRF
- named FastAPI/OpenAPI routes와 schemas
- 독립 `분기상담` tab, 조건부 fields/payloads, 오류 상태 보존
- A↔B·검색·정렬·page·scroll·tab·browser-back와 session/cache/abort
- care-change·file·evidence·attachment·민감정보 노출 부재

## 2. 봉인 파일

backend·PostgreSQL RED:

1. `backend/tests/test_w1a_vs5_semantics.py`
2. `backend/tests/test_w1a_vs5_api.py`
3. `backend/tests/test_w1a_vs5_postgres.py`
4. `backend/tests/test_w1a_vs5_openapi_contract.py`
5. `backend/tests/test_w1a_vs5_absence_contract.py`
6. `scripts/test-w1a-vs5-postgres.ps1`

frontend·browser RED:

1. `frontend/src/test/W1AStaffQuarterlyConsultation.test.tsx`
2. `frontend/e2e/w1a-staff-quarterly-consultation-real-pg.spec.ts`

## 3. 본진 독립 재현 결과

### backend·PostgreSQL

- Ruff format/check, compile, import, PowerShell AST: PASS
- mypy: `Success: no issues found in 5 source files`
- collect: `19 tests collected`
- non-PG focused: `8 failed / 6 passed / 5 skipped / 0 errors`
- fresh PostgreSQL: `13 failed / 6 passed / 0 skipped / 0 errors`
- 첫 marker: `W1A_VS5_MIGRATION_MISSING`
- migration baseline 왕복: PASS
- offline SQL 빈 DB 적용: PASS
- baseline postcheck: PASS
- baseline backup/restore: PASS
- 기존 backend 회귀: `87 passed / 33 skipped`
- PG stop, 임시 cluster, listener: `0`

fresh PostgreSQL RED의 실패는 `0007`·model·service·API·OpenAPI·postcheck·
restore 지원이 아직 제품에 없다는 의미다. traceback·collection/setup 오류는
없었다.

### frontend·browser

- focused Vitest: `6 failed / 0 errors`
- 전체 Vitest: 기존 `79 passed`, VS5 `6 failed`
- 첫 marker: `W1A_VS5_UI_QUARTERLY_CONSULTATION_TAB_MISSING`
- generated model 독립 marker:
  `W1A_VS5_GENERATED_QUARTERLY_MODELS_MISSING`
- lint: PASS
- TypeScript production build: PASS
- Playwright discovery: `3 tests / 3 viewport`
- fresh PostgreSQL+FastAPI+real browser:
  `0 passed / 3 failed / 0 skipped / 0 errors`
- real-browser 첫 marker:
  `W1A_VS5_E2E_QUARTERLY_CONSULTATION_TAB_MISSING`
- real-browser harness 판정: `W1A_VS5_E2E_RED_VALID`
- `page.route` product rewrite: 없음
- backend/frontend listener, PG listener, Playwright artifact, temp cluster: `0`

세 viewport 모두 실제 로그인·합성 직원 등록·직원 선택까지 통과한 뒤 현재
제품에 `분기상담` tab이 없어서 같은 marker에서 실패했다. 따라서 browser
RED는 DB·서버·인증·fixture 환경 실패가 아니다.

## 4. leak·경계 확인

- 송루나 leak negative self-test: `W1A_LEAK_GATE_SELF_TEST_OK`
- 송루나 normal gate: `W1A_LEAK_GATE_GREEN`
- 본진 untracked whitespace 검사: PASS
- 변경 경계: 지정 RED, 계획, 패킷, 본 evidence만
- 제품 코드·기존 migration·generated TypeScript 변경: 없음
- stage·commit·push·pull·reset·rebase·checkout·stash: 담당자 실행 없음

본진의 후속 baseline pytest가 만든 접근 제한 `.pytest_cache`는 제품·RED
판정과 무관한 로컬 생성 캐시다. 최종 GREEN 전 전체 artifact cleanup에서
다시 0을 확인한다.

## 5. 판정

backend와 frontend RED는 모두 제품 부재를 안정적으로 재현하고 구현 후
GREEN으로 전환 가능한 계약이다. `W1A-VS5`는 단계 B backend·DB 구현으로
진입한다.
