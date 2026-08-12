# W1A-VS4 RED 계약 검증 증거

> 상태: `RED_VALIDATED / RED_SEALED`
>
> 검증 시각: 2026-07-28 08:52 KST
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

두 RED 모두 환경 traceback·import·collection 실패가 아니라 아직 없는 `0006`
건강검진 migration, API, OpenAPI와 독립 `검진` 화면을 가리키는 안정된
`W1A_VS4_*` named assertion에서 실패한다. fact create payload와
query/mutation cache 격리 계약의 테스트 결함도 보정 후 다시 검증했다.
따라서 `W1A-VS4 RED_VALIDATED / RED_SEALED`로 판정하고 단계 B backend·DB
구현 진입을 승인한다.

## 2. Backend·PostgreSQL RED

| 검증 | Exit | 결과 |
|---|---:|---|
| Ruff format/check, 대상 Python 5개 | 0 / 0 | 통과 |
| mypy, backend app | 0 | 29 source files, issue 0 |
| compile / Pytest collect | 0 / 0 | 16 tests collected |
| PowerShell AST parse | 0 | parse error 0 |
| 실제 격리 PostgreSQL harness | 1 | `W1A_VS4_RED_VALID` |
| `git diff --check` | 0 | whitespace error 없음 |

실제 PostgreSQL harness 증거:

- database bootstrap과 현재 `0005` head 적용: 0
- 실행: 2 passed, 14 failed, 0 skipped, 0 errors
- 첫 marker: `W1A_VS4_MIGRATION_MISSING`
- offline baseline database/apply/verify: 0 / 0 / 0
- 실제 baseline dump/restore revision: `20260728_0005_w1a_staff_training`
- PostgreSQL stop, database drop, temp cluster, listener cleanup: 0

보강된 행동계약은 다음을 실제 제품 경로로 고정한다.

- 건강검진 fact와 requirement 원장의 분리, same-date 복수 fact 허용
- nullable employment의 same-staff guard와 requirement의 same-staff fact guard
- `COMPLETE` / `INCOMPLETE` / `EXEMPT` exact truth table
- `(staff_id, target_key)` active unique와 실제 동시 duplicate race
- stale row version 409, field-level 422, audit·invalidation·replacement
- audit insert 실패 시 fact/requirement mutation과 audit의 exact rollback
- 실제 FastAPI permission dependency의 ADMIN, granted `STAFF_VIEW`,
  granted `STAFF_MANAGE`, ungranted USER와 CSRF
- fact/requirement named OpenAPI model 분리
- 자동 target generator·D-day·task·업무카드·file/evidence/attachment 부재
- migration lifecycle·offline·postcheck·실제 restore 계약

## 3. Frontend·E2E·ABS·leak RED

| 검증 | Exit | 결과 |
|---|---:|---|
| Focused Vitest | 1 | 5 collected, 5 named RED |
| 전체 frontend Vitest | 1 | 74 passed, VS4 5 failed |
| lint / build | 0 / 0 | 통과 |
| OpenAPI generated type check | 0 | `OPENAPI_TYPES_UP_TO_DATE` |
| Playwright discovery | 0 | workers 1, 3 tests, 3 viewport projects |
| 실제 격리 PostgreSQL E2E | 1 | 3 viewport 모두 검진 탭 부재 RED |
| leak negative self-test / artifact 포함 normal gate | 0 / 0 | 212 files scan |
| `git diff --check` | 0 | whitespace error 없음 |

확인한 named marker:

- focused 첫 marker: `W1A_VS4_UI_HEALTH_TAB_MISSING`
- real-PG E2E 첫 marker: `W1A_VS4_E2E_HEALTH_TAB_MISSING`

본진은 fresh isolated PostgreSQL 17 cluster를 만들고 `0001`~`0005` migration을
적용한 뒤 application role로 FastAPI를 자체 기동했다. Playwright는 workers 1,
`1440x1000`, `1440x900`, `1366x768`에서 각각 동일한 첫 제품 부재 marker로
실패했다. 결과는 3 failed, 0 skipped이며 환경·bootstrap 오류는 없었다.

실패 artifact는 4 files, 44,157 bytes, media 0이었다. artifact와 runtime data를
포함한 leak gate는 212 files를 검사해 GREEN이었다. 검사 후 test-results,
임시 DB/data root, backend·frontend·PostgreSQL server와 `55455`·`8000`·`4173`
listener를 모두 0으로 cleanup했다.

보정한 테스트 계약도 직접 확인했다.

- fact POST create에는 `expected_row_version`이 없고, update/invalidate와
  requirement mutation에는 유지된다.
- actual QueryClient의 query/mutation cache를 직접 조회한다.
- A→B와 session/logout 전환 후 A health data·error·pending/failed mutation
  잔존을 stable named marker로 검사한다.
- AbortSignal·지연응답·DOM·cache·민감정보·금지 surface 검증은 유지된다.

## 4. RED 파일 경계

이루나 소유:

- `backend/tests/test_w1a_vs4_semantics.py`
- `backend/tests/test_w1a_vs4_api.py`
- `backend/tests/test_w1a_vs4_postgres.py`
- `backend/tests/test_w1a_vs4_openapi_contract.py`
- `backend/tests/test_w1a_vs4_absence_contract.py`
- `scripts/test-w1a-vs4-postgres.ps1`

송루나 소유:

- `frontend/src/test/W1AStaffHealthCheck.test.tsx`
- `frontend/e2e/w1a-staff-health-check-real-pg.spec.ts`

RED 담당자는 제품 코드, 기존 `0001`~`0005`, VS1~VS3 봉인물, generated
TypeScript, 정본, 계획, 패킷과 이 evidence 파일을 수정하지 않았다.
stage·commit·push는 수행하지 않았다.

## 5. 단계 B 구현 승인 조건

backend·DB 구현자는 named marker를 제거하거나 assertion을 약화하지 않고
`0006` migration, model, repository, service, permission, API, audit,
postcheck·restore의 실제 동작으로 RED를 GREEN으로 전환해야 한다.

backend·PostgreSQL 전체 GREEN과 OpenAPI 계약 고정 전에는 frontend 제품 구현과
생성 타입 갱신을 시작하지 않는다.
