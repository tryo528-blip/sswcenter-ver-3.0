# W1A-VS3 직원 신규·정기교육 상세 작업계획

> 문서 상태: `PASS / GREEN_SEALED / COMPLETE`
>
> 작성일: 2026-07-28 KST
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 기준 commit: `728958d4357b12bf34996ce10221118238b67c20`
>
> 선행 gate: `W1A-VS2 PASS / GREEN_SEALED`
>
> 총괄·최종판정: 김부장(Codex 본진 / SOL Max)
>
> RED 검증 증거: `review/evidence/w1a-vs3/RED.md` 예정

## 1. 권위와 목표

이 계획은 다음 정본과 검증표를 구현 가능한 하나의 micro-slice로 고정한다.

- `docs/02_새프로젝트_기능요구사항_정리본_v1.0.md` §3.3
- `docs/04_DB_업무구조_최종설계_v4.7_PostgreSQL.md` §3.6
- `docs/05_기술아키텍처_및_개발기준_v1.4.md`
- `docs/07_개발로드맵_및_결정현황_v1.0.md` §3 W1A
- `review/WAVE1_CLEAN_TEST_MATRIX.md`
  `W1-STF-07`, `W1-CMN-06`~`07`, `W1-ABS-13`·`16`
- `docs/AI_업무분담_운영규정_v2.2.md`

`W1A-VS3`의 목표는 직원 교육을 아래 두 원장으로 분리해 완성하는 것이다.

1. 재직마다 하나씩 생성되는 신규직원교육
2. 직원·과목·대상기간에 귀속되어 같은 기간 재입사 뒤에도 유지되는 정기교육

교육은 완료 여부 boolean만 관리하며 완료와 완료해제를 모두 감사한다.

`W1A-VS3` 완료는 W1A 전체 완료가 아니다. 건강검진, 직원 분기상담,
초기 직원 이관과 legacy mapping은 후속 W1A micro-slice에서 별도로 완료한다.

## 2. 범위

### 2.1 포함

- exact 교육과목 catalog 7행과 결정적 표시 순서
- 신규 재직 생성과 같은 transaction의 미완료 신규직원교육 1행
- 재입사 시 새 재직에 새 미완료 신규직원교육 1행
- 직원·과목·대상기간별 정기교육 원장
- 신규·정기교육 완료/완료해제와 `audit_event`
- active row 중복·동시성·optimistic lock·무효화/대체
- `STAFF_VIEW` 읽기와 `STAFF_MANAGE` 쓰기 권한
- OpenAPI 생성 타입과 직원 화면의 독립 교육 탭
- 실제 PostgreSQL, 실제 API, 3 viewport Playwright, 누출·부재 gate
- migration upgrade/downgrade/round-trip, offline SQL, postcheck, restore 의미검사

### 2.2 제외

- 교육시간, 이수일자, 이수센터, 교육 증빙·문서·file FK
- 교육 일정 자동생성, D-day, 업무카드, 알림
- 건강검진 사실·대상상태
- 직원 분기상담
- 초기 직원 이관기와 `staff_legacy_mapping`
- Wave 2 디자인·내부 사용성 조정
- 기존 적용 migration `0001`~`0004` 수정

## 3. 확정 업무계약

### 3.1 exact 교육과목 catalog

| sort | code | 표시명 | cycle |
|---:|---|---|---|
| 1 | `NEW_HIRE_ORIENTATION` | 신규직원교육 | `ON_HIRE` |
| 2 | `ELDER_RIGHTS` | 노인인권 | `HALF_YEAR` |
| 3 | `DISABLED_ABUSE` | 장애인학대 신고의무자교육 | `ANNUAL` |
| 4 | `ELDER_ABUSE` | 노인학대 신고의무자교육 | `ANNUAL` |
| 5 | `SEXUAL_HARASSMENT` | 직장 내 성희롱 예방교육 | `ANNUAL` |
| 6 | `WORKPLACE_BULLYING` | 직장 내 괴롭힘 예방교육 | `ANNUAL` |
| 7 | `PRIVACY` | 개인정보보호교육 | `ANNUAL` |

- 기존 code의 의미·표시명·cycle은 일반 업무에서 변경하거나 삭제하지 않는다.
- API와 UI는 위 7행을 `sort_order`, 그 뒤 미래 code를 code 순서로 결정적으로
  반환한다.
- `ON_HIRE` 과목은 정확히 한 행이어야 한다.

### 3.2 신규직원교육

- 각 유효 재직에는 active `NEW_HIRE_ORIENTATION` 행이 정확히 1개 존재한다.
- 최초 재직과 재입사 모두 재직 생성 transaction 안에서 `completed=false` 행을
  함께 만든다.
- 재입사는 이전 신규직원교육을 재사용하지 않는다.
- 완료와 완료해제는 현재값, 새값, 행위자, 시각을 매번 `audit_event`에 append한다.
- 일반 수정은 `expected_row_version`을 요구한다.

### 3.3 정기교육

- 정기교육은 `staff_id + course_code + period_key`에 귀속하며
  `employment_id`를 갖지 않는다.
- `HALF_YEAR` period key는 `YYYY-H1` 또는 `YYYY-H2`다.
- `ANNUAL` period key는 `YYYY`다.
- 같은 직원·과목·period의 active 행은 최대 1개다.
- 같은 period 안에서 퇴사·재입사해도 기존 정기교육 완료상태를 유지한다.
- 완료와 완료해제는 각각 별도 감사 event를 남긴다.

## 4. DB·migration 계약

새 migration은 기존 `0004`를 수정하지 않고 새 revision으로 추가한다.

예상 파일:

- `backend/alembic/versions/20260728_0005_w1a_staff_training.py`
- `backend/app/db/models.py`
- `backend/app/db/postcheck_w1a_vs1.py` 또는 후속 W1A postcheck
- `scripts/restore-drill.ps1`

필수 구조:

- `training_course(code PK, display_name, cycle_type, active, sort_order)`
- `staff_onboarding_training`
  - 안정 PK
  - 같은 직원의 `staff_id + employment_id` 복합 FK
  - `course_code`
  - `completed`
  - actor/timestamp/row_version
  - invalidation/replacement
- `staff_periodic_training_status`
  - 안정 PK
  - `staff_id`
  - `course_code`
  - `period_key`
  - `completed`
  - actor/timestamp/row_version
  - invalidation/replacement

필수 불변조건:

- exact 7행 seed와 cycle
- 신규직원교육은 `ON_HIRE` 과목만 참조
- 정기교육은 `HALF_YEAR` 또는 `ANNUAL` 과목만 참조
- cycle과 `period_key` 형식 일치
- active onboarding은 재직별 최대 1행
- active periodic은 직원·과목·period별 최대 1행
- FK·unique·check·index·trigger 이름은 현재 naming policy를 따른다.
- 동시 중복 생성은 한 건만 성공한다.
- downgrade 후 기존 Wave 0~VS2 값과 `staff.display_name`·`staff.memo`가 보존된다.

검증 lifecycle:

1. fresh base→`0005`
2. `0004`→`0005`
3. `0005`→`0004`→`0005`
4. offline SQL parse와 금지 SQL/이름 검사
5. postcheck와 backup/restore 의미검사

## 5. API·OpenAPI 계약

예상 경로:

- `GET /api/v1/staff/training-courses`
- `GET /api/v1/staff/{staff_id}/onboarding-trainings`
- `PATCH /api/v1/staff/{staff_id}/onboarding-trainings/{training_id}`
- `GET /api/v1/staff/{staff_id}/periodic-trainings`
- `POST /api/v1/staff/{staff_id}/periodic-trainings`
- `PATCH /api/v1/staff/{staff_id}/periodic-trainings/{training_id}`
- `POST /api/v1/staff/{staff_id}/periodic-trainings/{training_id}/invalidate`

권한:

- ADMIN: 읽기·쓰기
- `STAFF_VIEW`: 읽기만
- `STAFF_MANAGE`: 읽기·쓰기
- 권한 없는 USER: 403

필수 동작:

- write는 CSRF와 `expected_row_version`을 요구한다.
- stale version은 안정 409 업무오류다.
- 잘못된 cycle/period, 다른 직원 row, 금지 과목은 안정 409 또는 field-level 422다.
- raw constraint명, SQL, DSN, 내부 object명이 오류에 노출되지 않는다.
- OpenAPI에는 신규교육과 정기교육을 분리한 named model이 존재한다.
- 공개 model에 교육시간·이수일자·이수센터·file/evidence property가 없다.

## 6. UI·DOM 계약

- 직원 상세에 `교육` 탭을 독립 제공한다.
- `신규직원교육`과 `정기교육`을 별도 영역으로 표시한다.
- exact 한국어 과목명과 주기를 표시한다.
- 신규직원교육은 재직별 완료 checkbox로 표현한다.
- 정기교육은 period 선택과 과목별 완료 checkbox로 표현한다.
- 완료 저장 중 상태, 성공 재조회, 409 입력/선택 보존, 422 field 오류를 다룬다.
- A↔B, 검색·정렬·페이지·스크롤·선택 탭, browser back 문맥을 보존한다.
- 권한 없는 쓰기 제어는 보이지 않거나 disabled다.
- 교육시간·이수일자·이수센터·첨부·업무카드 제어가 DOM에 없어야 한다.

## 7. RED-first 검증

RED는 환경 traceback이나 단순 import 실패가 아니라 제품계약 부재를 증명해야 한다.

### 이루나 — backend·PostgreSQL RED

- exact 7행 seed와 결정적 순서
- employment 생성과 onboarding 원자성·rollback
- 재입사 새 onboarding과 이전행 보존
- periodic same-period 재입사 유지
- cycle/period truth table
- active duplicate race
- completed true→false 각각 audit 1건
- ADMIN/VIEW/MANAGE/ungranted USER
- CSRF, stale version, 409/422 안정 오류
- upgrade/downgrade/round-trip/offline/postcheck/restore
- 금지 column/FK/route/property 정적 부재

### 송루나 — frontend·E2E·ABS RED

- 생성 OpenAPI 타입 기반 adapter 계약
- 교육 탭과 exact 7개 label/cycle
- 신규교육/정기교육 분리
- 재입사 및 same-period 상태 보존
- loading/empty/error/403/409/422/session transition
- A↔B와 browser back 문맥
- 실제 PostgreSQL, E2E 자체 bootstrap, workers 1, 3 viewport
- DOM/query cache/mutation cache/log/artifact의 민감정보·내부오류 0
- 금지 교육 필드·file/task 구조 부재

RED 증거는 `review/evidence/w1a-vs3/RED.md`에 다음을 기록한다.

- 명령
- exit code
- 수집/통과/실패 수
- 첫 named marker
- 해당 marker가 제품계약 부재를 검증한다는 설명
- 환경 blocker와 제품 RED의 명확한 분리

## 8. GREEN·완료 gate

1. 승인된 RED가 실제 제품 부재에서 실패한다.
2. 새 migration이 모든 lifecycle과 exact catalog 검사를 통과한다.
3. backend focused·전체 pytest, Ruff format/check, mypy가 통과한다.
4. OpenAPI 재생성 뒤 drift가 0이다.
5. frontend focused·전체 Vitest, lint, build가 통과한다.
6. 실제 PostgreSQL E2E가 workers 1의 3 viewport에서 통과한다.
7. onboarding 원자성·재입사와 periodic same-period 보존이 실제 DB에서 통과한다.
8. 완료/완료해제 audit, 권한, 동시성, stale version이 통과한다.
9. leak gate normal과 negative self-test가 통과한다.
10. 임시 DB·서버·listener·artifact가 모두 cleanup된다.
11. `git diff --check`가 0이고 stage/commit/push가 없다.
12. 구현자와 다른 검증자의 PASS 뒤 김부장이 최종판정한다.

## 9. 단계·소유권

### 단계 A — RED 계약

- 이루나: backend·DB·권한·동시성·migration RED
- 송루나: frontend·E2E·ABS·leak RED
- 김부장: RED 의미와 파일 경계 독립검증

### 단계 B — backend·DB 구현

- 김루나: migration, model, repository, service, API, backend tests
- 기존 `0001`~`0004`, frontend, RED evidence 직접 수정 금지

### 단계 C — 생성 타입·frontend 구현

- 김부장: OpenAPI 생성 명령 실행과 drift 확인
- 박루나: adapter, 화면, 상태관리, focused tests
- generated TypeScript 직접수정, backend/migration 수정 금지

### 단계 D — 교차검증·최종판정

- 이루나: DB invariant·권한·동시성·rollback 읽기 전용 검증
- 송루나: real-PG UI·문맥·민감정보·artifact 읽기 전용 검증
- REQUIRED_CHANGES는 원 구현 소유자에게 반환
- 김부장: 전체 gate 독립 재현, 증거 봉인, 최종판정

## 10. 사용자 결정

추가 사용자 결정은 필요하지 않다. exact 과목 7개, cycle, boolean-only 교육
상태, 재입사 의미와 금지범위는 정본에서 이미 확정됐다.

## 11. 착수·완료 판정

- 선행 `W1A-VS2`는 `PASS / GREEN_SEALED`다.
- `W1A-VS3` RED는 `review/evidence/w1a-vs3/RED.md`에 봉인됐다.
- 단계 B backend·DB, 단계 C frontend, 단계 D 교차검증과 김부장 전체 runtime
  gate가 모두 PASS했다.
- 최종 증거는 `review/evidence/w1a-vs3/GREEN.md`에
  `PASS / GREEN_SEALED`로 봉인됐다.
- `W1A-VS3 PASS` 뒤에도 건강검진·분기상담·초기이관/legacy mapping이 남으므로
  W1B 착수가 아니다.
