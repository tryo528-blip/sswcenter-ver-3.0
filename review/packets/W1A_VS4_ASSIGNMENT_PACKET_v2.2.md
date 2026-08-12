# W1A-VS4 직원 건강검진 작업 배정 패킷 v2.2

> 상태: `PASS / GREEN_SEALED / COMPLETE`
>
> 작성일: 2026-07-28 KST
>
> 운영정본: `docs/AI_업무분담_운영규정_v2.32.md`
>
> 상세계획: `review/plans/W1A_VS4_STAFF_HEALTH_CHECK_PLAN.md`
>
> 최종증거: `review/evidence/w1a-vs4/GREEN.md`
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 기준 commit: `728958d4357b12bf34996ce10221118238b67c20`
>
> 선행 gate: `W1A-VS3 PASS / GREEN_SEALED`
>
> 총괄·최종판정: 김부장(Codex 본진 / SOL Max)

## 1. 공통 통제

- 기존 지정 작업방만 사용한다.
- 새 작업방·하부·보조·대체 에이전트를 만들지 않는다.
- 메인 checkout은 `C:\Users\USER\Documents\sswcenter-ver-2.1 2`다.
- 각 담당자는 아래 exact allowlist만 수정한다.
- 기존 `0001`~`0005`, VS1~VS3 RED/GREEN, 제품 GREEN, generated TypeScript,
  정본·계획·패킷·evidence, package/lockfile과 Git을 수정하지 않는다.
- stage·commit·push·pull·reset·rebase를 실행하지 않는다.
- test 자체 SQL·가짜 예외·import failure·traceback으로 RED를 제조하지 않는다.
- 민감 후보 원문을 console·log·artifact·보고서에 출력하지 않는다.

## 2. 이루나 — backend·PostgreSQL RED

기존 작업방:
`019fa2dc-2c9a-7a51-83f8-1704c1b2320b`

수정 허용 파일:

1. `backend/tests/test_w1a_vs4_semantics.py`
2. `backend/tests/test_w1a_vs4_api.py`
3. `backend/tests/test_w1a_vs4_postgres.py`
4. `backend/tests/test_w1a_vs4_openapi_contract.py`
5. `backend/tests/test_w1a_vs4_absence_contract.py`
6. `scripts/test-w1a-vs4-postgres.ps1`

필수 계약:

- missing `20260728_0006_w1a_staff_health_check` named marker
- 실제 service/FastAPI/PostgreSQL 경로
- 같은 날짜 복수 fact 허용
- nullable employment의 same-staff guard
- requirement의 same-staff health fact guard
- exact 3상태 valid/invalid truth table
- `(staff_id,target_key)` active duplicate race
- stale 409, field-level 422, audit·invalidation·exact rollback
- ADMIN·granted VIEW·granted MANAGE·ungranted·CSRF
- OpenAPI fact/requirement named model 분리
- 자동 target generator·D-day·task·업무카드·file FK/route/property 부재
- fresh/lifecycle/offline/postcheck/restore와 temp cleanup

완료보고:

- 파일별 diff와 행동 의미
- Ruff format/check, mypy, compile, collect, PowerShell AST
- 실제 PG command, exit, collected/passed/failed/skipped/errors
- 첫 named `W1A_VS4_*` marker와 제품 부재 의미
- PostgreSQL stop·temp cluster cleanup
- `git diff --check`와 Git 미실행 확인

## 3. 송루나 — frontend·E2E·ABS·leak RED

기존 작업방:
`019fa2dc-58b2-7e72-8073-be5d78ac3bee`

수정 허용 파일:

1. `frontend/src/test/W1AStaffHealthCheck.test.tsx`
2. `frontend/e2e/w1a-staff-health-check-real-pg.spec.ts`

필수 계약:

- 독립 `검진` tab
- `검진사실`과 `대상별 상태` 두 영역
- fact same-date 복수·선택 employment
- existing synthetic requirement의 COMPLETE/INCOMPLETE/EXEMPT conditional fields
- VIEW read-only, MANAGE·ADMIN write
- loading·empty·error·403·409·422와 상태 보존
- 성공 재조회, A↔B·검색·정렬·page·실제 scroll·tab·browser-back
- session/logout 지연응답·AbortSignal·query/mutation cache 격리
- 미승인 자동 target·D-day·task·업무카드·첨부·file/evidence UI 부재
- fresh isolated PostgreSQL, E2E 자체 bootstrap과 trusted synthetic requirement
  fixture, workers 1, 3 viewport
- DOM/cache/log/artifact 민감정보 0, popup/overflow 0
- leak negative self-test/normal과 cleanup

금지:

- API mock, `page.route` rewrite, assertion 삭제·skip·약화
- sleep 기반 경합 은폐
- 제품 frontend/backend/generated/migration 수정
- 미승인 public requirement-create/target-generator route 가정

완료보고:

- 파일별 diff와 behavioral assertion 의미
- focused/full frontend, lint/build
- Playwright discovery와 real-PG command·exit·viewport
- 첫 named `W1A_VS4_*` marker와 제품 부재 의미
- leak/artifact/media/temp/server/listener/test-results cleanup
- `git diff --check`와 Git 미실행 확인

## 4. RED 봉인 뒤 후속

김부장이 두 RED의 파일 의미와 실제 실행을 독립 재현해 유효 RED만
`review/evidence/w1a-vs4/RED.md`에 봉인한다.

그 뒤 기존 김루나 방에 backend·DB 구현을, backend·OpenAPI 고정 뒤 기존
박루나 방에 생성 타입 기반 frontend 구현을 배정한다. 교차검증은 다시 기존
이루나·송루나 방에서 수행한다. 제품 결함은 본진이 직접 고치지 않고 원 구현
소유자에게 정확한 파일범위와 완료조건으로 반환한다.

두 RED는 `review/evidence/w1a-vs4/RED.md`에 봉인됐다. 단계 B backend·DB,
단계 C frontend, 단계 D 이루나·송루나 교차검증과 김부장 전체 runtime gate가
모두 PASS했다. 최종 증거는 `review/evidence/w1a-vs4/GREEN.md`에
`PASS / GREEN_SEALED`로 봉인했고 이 패킷은 완료 상태다.
