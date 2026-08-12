# W1A-VS2 RED 계약 검증 증거

> 상태: `RED_VALIDATED`
>
> 검증 시각: 2026-07-27 23:25 KST
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 기준 구현 SHA: `728958d4357b12bf34996ce10221118238b67c20`
>
> 검증자: 김부장(Codex 본진 / SOL Max)
>
> 제품 구현 변경: 없음

## 1. 판정

이루나의 backend·PostgreSQL RED 계약 A와 송루나의 ABS·DOM·E2E RED 계약 B를
각 작업방 완료보고와 별도로 메인 checkout에서 재실행했다.

두 계약 모두 syntax·import·collection·도구 실패가 아니라 VS2 제품 구현 부재를
가리키는 안정된 `W1A_VS2_*` named assertion에서 실패했다. 따라서
`W1A-VS2 RED_CONTRACT_VALID`로 판정하고 backend·DB 구현 단계 진입을 승인한다.

## 2. Backend·PostgreSQL 계약 A

| 검증 | Exit | 결과 |
|---|---:|---|
| Ruff format check, 대상 Python 4개 | 0 | 4 files already formatted |
| Ruff check, 대상 Python 4개 | 0 | All checks passed |
| PowerShell AST parse | 0 | parse error 0 |
| Pytest collect | 0 | 16 tests collected |
| no-DB focused RED | 1 | 11 failed, 5 skipped, 첫 marker `W1A_VS2_SEMANTICS_MISSING` |
| 실제 격리 PostgreSQL harness | 1 | `W1A_VS2_RED_CONTRACT_VALID` |

실제 PostgreSQL harness에서 확인한 세부 증거:

- quality gate: format 0, Ruff 0, compile 0
- migration base→head: 0
- offline SQL 생성: 0
- offline SQL 빈 DB 적용: database 0, apply 0
- collection: 16 tests
- 실행: 0 passed, 16 failed, 0 errors
- 첫 marker: `W1A_VS2_SEMANTICS_MISSING`
- cleanup 뒤 port 55434 listener 0, 임시 cluster 0

## 3. ABS·DOM·E2E 계약 B

| 검증 | Exit | 결과 |
|---|---:|---|
| Backend ABS collect | 0 | 7 tests collected |
| Backend ABS RED | 1 | 6 failed, 1 passed, 첫 marker `W1A_VS2_NAMED_MODELS_MISSING` |
| Ruff format/check | 0/0 | 통과 |
| Focused Vitest | 1 | 7 tests collected, 7 named RED, 첫 marker `W1A_VS2_DOM_LICENSE_TAB_MISSING` |
| oxlint | 0 | 통과 |
| TypeScript `--noEmit` | 0 | 통과 |
| Playwright discovery | 0 | 3 viewport projects, 1 file |
| Playwright dependency run | 0 | workers 1, 3 explicit dependency skips |

Playwright의 실제 PostgreSQL UI 실행은 backend 제품 구현과 인증된 GREEN harness가
아직 없으므로 `W1A_VS2_PG_DEPENDENCY_BLOCKER`로만 skip되었다. 이는 RED 성공으로
계산하지 않았고, 구현 뒤 GREEN gate에서 세 viewport 모두 실제 실행한다.

## 4. RED 파일 경계

이루나 소유:

- `backend/tests/test_w1a_vs2_semantics.py`
- `backend/tests/test_w1a_vs2_openapi_contract.py`
- `backend/tests/test_w1a_vs2_api.py`
- `backend/tests/test_w1a_vs2_postgres.py`
- `scripts/test-w1a-vs2-postgres.ps1`

송루나 소유:

- `backend/tests/test_w1a_vs2_absence_contract.py`
- `frontend/src/test/W1AStaffQualifications.test.tsx`
- `frontend/e2e/w1a-staff-qualifications-real-pg.spec.ts`

RED 담당자는 제품 코드, 기존 migration, 생성 타입, 정본, 이 evidence 파일을
수정하지 않았다. stage·commit·push는 수행하지 않았다.

## 5. 구현 단계 완료조건

backend·DB 구현자는 위 RED를 단순 marker 제거로 우회하지 않고 실제 catalog,
constraint, ACL, transaction, API, OpenAPI 동작으로 GREEN으로 전환해야 한다.
backend 계약이 고정된 뒤 생성 TypeScript 타입과 frontend 구현을 진행한다.
