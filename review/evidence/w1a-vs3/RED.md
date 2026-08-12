# W1A-VS3 RED 계약 검증 증거

> 상태: `RED_VALIDATED / RED_SEALED`
>
> 검증 시각: 2026-07-28 04:20 KST
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 기준 구현 SHA: `728958d4357b12bf34996ce10221118238b67c20`
>
> 검증자: 김부장(Codex 본진 / SOL Max)
>
> 제품 구현 변경: 없음

## 1. 판정

이루나의 backend·PostgreSQL RED와 송루나의 frontend·E2E·ABS·leak RED를
작업방 완료보고와 별도로 메인 checkout에서 파일 의미와 실행 결과로 검증했다.

두 RED 모두 환경 traceback·import·collection 실패가 아니라 아직 없는 `0005`
교육 migration, API, OpenAPI와 교육 화면을 가리키는 안정된 `W1A_VS3_*`
named assertion에서 실패한다. 따라서 `W1A-VS3 RED_VALIDATED / RED_SEALED`로
판정하고 단계 B backend·DB 구현 진입을 승인한다.

## 2. Backend·PostgreSQL RED

| 검증 | Exit | 결과 |
|---|---:|---|
| Ruff format check, 대상 Python 5개 | 0 | 5 files already formatted |
| Ruff check, 대상 Python 5개 | 0 | All checks passed |
| mypy, backend cwd 대상 Python 5개 | 0 | no issues found |
| Pytest collect | 0 | 18 tests collected |
| PowerShell AST parse | 0 | parse error 0 |
| 실제 격리 PostgreSQL harness | 1 | `W1A_VS3_RED_VALID` |
| `git diff --check` | 0 | whitespace error 없음 |

실제 PostgreSQL harness 증거:

- database bootstrap: roles 0, database 0
- quality gate: format 0, Ruff 0, compile 0
- 현재 head migration upgrade: 0
- `0005` lifecycle: 제품 migration 부재로 명시적 skip
- collection: 18 tests
- 실행: 3 passed, 15 failed, 0 skipped, 0 errors
- 첫 marker: `W1A_VS3_MIGRATION_MISSING`
- marker 집합: migration, offline, API, OpenAPI, PostgreSQL semantics, restore 부재
- PostgreSQL stop: 0
- cleanup 뒤 임시 cluster: 0

보강된 행동계약은 다음을 실제 제품 경로로 고정한다.

- `StaffService.create_employment`와 실제 PostgreSQL 세션을 통한
  employment/onboarding 동일 transaction 및 실패 시 staff·employment·onboarding·
  audit·counter exact rollback
- 같은 `2026-H1` 안의 퇴사·재입사에서 재직별 서로 다른 미완료 onboarding과
  기존 `2026-H1` periodic 동일 ID·완료상태 유지
- 실제 FastAPI create/update 경로의 cycle/period truth table, 동시 중복
  1 success/1 stable 409, stale row version 409와 무변경
- 완료 `false→true`, 완료해제 `true→false`의 audit before/after, actor, UTC,
  row version과 audit insert 실패 시 fact/audit 동시 rollback
- 실제 permission dependency를 통과하는 ADMIN, granted `STAFF_VIEW`,
  granted `STAFF_MANAGE`, ungranted USER, CSRF, field-level 422와 stable 409
- 다른 직원 행은 404로 약화하지 않고 409 또는 422만 허용

## 3. Frontend·E2E·ABS·leak RED

| 검증 | Exit | 결과 |
|---|---:|---|
| Focused Vitest | 1 | 4 collected, 4 named RED |
| 전체 frontend Vitest | 1 | 62 passed, VS3 4 failed |
| Playwright discovery | 0 | workers 1, 3 viewport projects |
| 실제 격리 PostgreSQL E2E | 1 | 3 viewport 모두 교육 탭 부재 RED |
| lint / build | 0 / 0 | 통과 |
| backend VS3 absence contract | 1 | 7 collected, 7 named RED |
| leak negative self-test / normal gate | 0 / 0 | 197 files scan |
| `git diff --check` | 0 | whitespace error 없음 |

확인한 named marker:

- focused 첫 marker: `W1A_VS3_UI_EDUCATION_TAB_MISSING`
- real-PG E2E 첫 marker: `W1A_VS3_E2E_EDUCATION_TAB_MISSING`
- backend absence 첫 marker: `W1A_VS3_OPENAPI_MISSING`

실제 E2E는 fresh isolated PostgreSQL, 자체 bootstrap, workers 1,
`1440x1000`, `1440x900`, `1366x768`에서 동일한 제품 부재를 재현했다.
artifact는 4 files, media 0이었고 검사 뒤 artifact·server·listener·임시 DB를
모두 cleanup했다. DOM·query/mutation cache·log·artifact의 금지 교육 필드와
민감정보 검사는 유지한다.

## 4. RED 파일 경계

이루나 소유:

- `backend/tests/test_w1a_vs3_semantics.py`
- `backend/tests/test_w1a_vs3_api.py`
- `backend/tests/test_w1a_vs3_postgres.py`
- `backend/tests/test_w1a_vs3_openapi_contract.py`
- `backend/tests/test_w1a_vs3_absence_contract.py`
- `scripts/test-w1a-vs3-postgres.ps1`

송루나 소유:

- `frontend/src/test/W1AStaffTraining.test.tsx`
- `frontend/e2e/w1a-staff-training-real-pg.spec.ts`

RED 담당자는 제품 코드, 기존 `0001`~`0004`, 생성 타입, 정본, 계획, 패킷,
이 evidence 파일을 수정하지 않았다. stage·commit·push는 수행하지 않았다.

## 5. 단계 B 구현 승인 조건

backend·DB 구현자는 named marker를 제거하거나 assertion을 약화하지 않고
`0005` migration, model, repository, service, permission, API, audit,
postcheck·restore의 실제 동작으로 RED를 GREEN으로 전환해야 한다.

backend·PostgreSQL 전체 GREEN과 OpenAPI 계약 고정 전에는 frontend 제품 구현과
생성 타입 갱신을 시작하지 않는다.
