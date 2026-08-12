# W1A-VS5 직원 분기상담 작업 배정 패킷 v2.32

> 상태: `STAGE_A_RED_SEALED`
>
> 작성일: 2026-07-28 KST
>
> 운영정본: `docs/AI_업무분담_운영규정_v2.32.md`
>
> 상세계획: `review/plans/W1A_VS5_STAFF_QUARTERLY_CONSULTATION_PLAN.md`
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 기준 commit: `4adc6a63f7482e1e4e2470f9e4c072ed1cb229de`
>
> 선행 gate: `W1A-VS4 PASS / GREEN_SEALED`
>
> 총괄·최종판정: 김부장(Codex 본진 / SOL Max)

## 1. 공통 통제

- 기존 지정 작업방만 사용하고 새 작업방·하위·보조 에이전트를 만들지 않는다.
- 공유 checkout은
  `C:\project sswcenter\sswcenter ver2.1\sswcenter-ver-2.1-office`다.
- 각 담당자는 아래 exact allowlist만 수정한다.
- 기존 `0001`~`0006`, VS1~VS4 RED/GREEN, 제품 코드, generated TypeScript,
  정본·계획·패킷·evidence, package/lockfile을 수정하지 않는다.
- stage·commit·push·pull·reset·rebase·checkout·stash를 실행하지 않는다.
- test 자체 SQL·가짜 예외·import failure·traceback으로 RED를 제조하지 않는다.
- 민감 후보 원문을 console·log·artifact·보고서에 출력하지 않는다.

## 2. 이루나 — backend·PostgreSQL RED

기존 작업방:
`019fa2bf-e4eb-78d1-ae7e-a2ed024196ea`

수정 허용 파일:

1. `backend/tests/test_w1a_vs5_semantics.py`
2. `backend/tests/test_w1a_vs5_api.py`
3. `backend/tests/test_w1a_vs5_postgres.py`
4. `backend/tests/test_w1a_vs5_openapi_contract.py`
5. `backend/tests/test_w1a_vs5_absence_contract.py`
6. `scripts/test-w1a-vs5-postgres.ps1`

필수 계약:

- missing `20260728_0007_w1a_staff_quarterly_consultation`
- 실제 service/FastAPI/PostgreSQL 경로
- exact 3상태 valid/invalid truth table와 nonblank
- `(staff_id,calendar_year,quarter_no)` active unique와 실제 race
- calendar year/quarter 생성 key, update payload에서 immutable
- stale 409, wrong-staff, field-level 422
- replacement payload 기반 invalidate/replace와 두 audit
- audit insert 실패 시 exact rollback
- ADMIN·granted VIEW·granted MANAGE·ungranted·CSRF
- named OpenAPI models/routes
- care-change/file/evidence/attachment DB/API/OA 부재
- fresh/lifecycle/offline/postcheck/restore와 temp cleanup

완료보고:

- `RED_VALID` 또는 `REQUIRED_CHANGES`
- 파일별 diff와 behavioral 의미
- Ruff format/check, mypy, compile, collect, PowerShell AST
- 실제 PG command, exit, collected/passed/failed/skipped/errors
- 첫 named `W1A_VS5_*` marker와 제품 부재 의미
- PostgreSQL stop·temp cluster cleanup
- `git diff --check`와 Git 미실행 확인

## 3. 송루나 — frontend·E2E·ABS·leak RED

기존 작업방:
`019fa2bf-f060-7d32-ae58-78eb568102ff`

수정 허용 파일:

1. `frontend/src/test/W1AStaffQuarterlyConsultation.test.tsx`
2. `frontend/e2e/w1a-staff-quarterly-consultation-real-pg.spec.ts`

필수 계약:

- 독립 `분기상담` tab
- 연도·분기와 exact 3상태
- COMPLETE 상담일·처리내용만, INCOMPLETE 미완료 사유만,
  EXEMPT 면제 사유만 required/visible/payload
- VIEW read-only, MANAGE·ADMIN write
- loading·empty·error·403·409·422와 상태 보존
- 성공 재조회, A↔B·검색·정렬·page·실제 scroll·tab·browser-back
- session/logout 지연응답·AbortSignal·query/mutation cache 격리
- 교체상담·actual service·Day 14/15·file/evidence/attachment UI 부재
- fresh isolated PostgreSQL, E2E 자체 bootstrap, workers 1, 3 viewport
- DOM/cache/log/artifact 민감정보 0, popup/overflow 0
- leak negative self-test/normal과 cleanup

금지:

- API mock을 real-PG E2E 증거로 계산
- `page.route` product rewrite, assertion 삭제·skip·약화
- sleep 기반 경합 은폐
- 제품 frontend/backend/generated/migration 수정

완료보고:

- `RED_VALID` 또는 `REQUIRED_CHANGES`
- 파일별 diff와 behavioral assertion 의미
- focused/full frontend, lint/build
- Playwright discovery와 가능한 real-PG command·exit·viewport
- 첫 named `W1A_VS5_*` marker와 제품 부재 의미
- leak/artifact/media/temp/server/listener/test-results cleanup
- `git diff --check`와 Git 미실행 확인

## 4. RED 봉인 뒤 후속

김부장이 두 RED의 파일 의미와 실제 실행을 독립 재현해 유효 RED만
`review/evidence/w1a-vs5/RED.md`에 봉인한다.

그 뒤 기존 김루나 방에 backend·DB 구현을 배정한다. backend·OpenAPI 고정 뒤
김부장이 생성 타입을 갱신하고 기존 박루나 방에 frontend 구현을 배정한다.
교차검증은 기존 이루나·송루나 방에서 수행한다. 결함은 원 구현 소유자에게
정확한 파일범위와 완료조건으로 반환한다.
