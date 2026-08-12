# W1A-VS5 직원 분기상담 상세 작업계획

> 문서 상태: `STAGE_A_RED_SEALED`
>
> 작성일: 2026-07-28 KST
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 기준 commit: `4adc6a63f7482e1e4e2470f9e4c072ed1cb229de`
>
> 선행 gate: `W1A-VS4 PASS / GREEN_SEALED`
>
> 총괄·최종판정: 김부장(Codex 본진 / SOL Max)
>
> 외부 1차 설계: Grok Build `grok-4.5`, 단일 주 세션·read-only 2-track fan-out,
> exit 0, `/check-work` 최종 PASS

## 1. 권위와 목표

이 계획은 다음 정본의 직원 분기상담 계약만 하나의 micro-slice로 고정한다.

- `docs/02_새프로젝트_기능요구사항_정리본_v1.0.md` §3.3
- `docs/03_기존_UI와_기능요구사항_화면별_변경표_v1.1.md` §3.5·§8·§9
- `docs/04_DB_업무구조_최종설계_v4.7_PostgreSQL.md` §3.6
- `docs/05_기술아키텍처_및_개발기준_v1.4.md`
- `docs/07_개발로드맵_및_결정현황_v1.0.md` W1A
- `review/WAVE1_CLEAN_TEST_MATRIX.md`
  `W1-STF-09`, `W1-CMN-04`~`07`, `W1-ABS-16`·`17`
- `docs/AI_업무분담_운영규정_v2.32.md`

목표는 직원·달력연도·분기별 상담 사실/상태 원장을 독립 DB·API·OpenAPI·UI로
완성하는 것이다. Wave 2의 실제 급여제공 기반 요양보호사 교체상담과
table·FK·status·API·화면·감사를 공유하지 않는다.

`W1A-VS5` 완료는 W1A 전체 완료가 아니다. 초기 직원 이관·
`staff_legacy_mapping`과 W1A 전체 통합 gate가 후속으로 남는다.

## 2. DB 계약

새 revision은 `20260728_0007_w1a_staff_quarterly_consultation`로 만든다.
적용된 `0001`~`0006`은 수정하지 않는다.

`staff_quarterly_consultation`:

- `id` bigint PK
- `staff_id` FK → `staff.id`
- `calendar_year` 정수 NOT NULL; 정본에 없는 임의 min/max를 추가하지 않음
- `quarter_no` 정수 `1`~`4` CHECK
- exact status `COMPLETE` / `INCOMPLETE` / `EXEMPT`
- nullable `counseling_date`, `content`
- nullable `incomplete_reason_text`, `exempt_reason_text`
- 생성·변경 행위자, UTC timestamp, 양수 `row_version`
- `invalidated_at_utc`, nullable self-FK
  `replacement_staff_quarterly_consultation_id`

상태 truth table:

```text
COMPLETE:
  counseling_date NOT NULL
  content nonblank
  incomplete_reason_text IS NULL
  exempt_reason_text IS NULL

INCOMPLETE:
  incomplete_reason_text nonblank
  counseling_date IS NULL
  content IS NULL
  exempt_reason_text IS NULL

EXEMPT:
  exempt_reason_text nonblank
  counseling_date IS NULL
  content IS NULL
  incomplete_reason_text IS NULL
```

nonblank는 DB에서 `btrim(value) <> ''`로 강제한다. 유효행은
`(staff_id, calendar_year, quarter_no)`별 최대 1개이며 partial unique는
`invalidated_at_utc IS NULL`에만 적용한다.

`calendar_year`·`quarter_no`는 생성 후 row identity로 취급해 PATCH로
변경하지 않는다. 잘못된 key는 무효화·대체가 아니라 기존 행 무효화 뒤 새 key
create로 정정한다.

## 3. 변경·무효화·감사

- PATCH는 status와 네 조건부 필드, `expected_row_version`만 받는다.
- content와 두 reason은 최대 4000자로 제한한다.
- stale `expected_row_version`은 안정 409다.
- invalidate/replace 요청은 `expected_row_version`과 대체 status·조건부
  필드를 받는다.
- invalidate/replace는 한 transaction에서 기존 행 잠금·version 확인,
  기존 행 무효화, 같은 staff/year/quarter의 새 active replacement 생성,
  기존 행의 replacement FK 연결과 두 audit insert를 수행한다.
- audit 실패 시 기존 행·replacement·audit 모두 exact rollback한다.
- 일반 update와 invalidate/replace는 각각 독립 audit action을 남긴다.

제안 audit action:

- `STAFF_QUARTERLY_CONSULTATION_CREATE`
- `STAFF_QUARTERLY_CONSULTATION_UPDATE`
- `STAFF_QUARTERLY_CONSULTATION_INVALIDATE`
- `STAFF_QUARTERLY_CONSULTATION_REPLACEMENT_CREATE`

## 4. API·OpenAPI 계약

직원 scoped route:

- GET/POST `/api/v1/staff/{staff_id}/quarterly-consultations`
- PATCH
  `/api/v1/staff/{staff_id}/quarterly-consultations/{consultation_id}`
- POST
  `/api/v1/staff/{staff_id}/quarterly-consultations/{consultation_id}/invalidate`

Named models:

- `QuarterlyConsultationStatus`
- `StaffQuarterlyConsultationCreateRequest`
- `StaffQuarterlyConsultationUpdateRequest`
- `StaffQuarterlyConsultationReplaceRequest`
- `StaffQuarterlyConsultationResponse`
- `StaffQuarterlyConsultationListResponse`

ADMIN·granted `STAFF_VIEW`·granted `STAFF_MANAGE`는 read할 수 있다.
ADMIN·granted `STAFF_MANAGE`만 mutation할 수 있고 unsafe mutation은
session·CSRF를 모두 요구한다. ungranted USER는 read/write 모두 거부한다.

stable 오류:

- missing row/staff: 404
- active duplicate와 stale version: 409
- wrong-staff row: 409
- 상태 truth table·quarter·field validation: field-level 422
- raw constraint·SQL·내부 식별자 비노출

OpenAPI에는 exact enum과 조건부 필드 설명을 넣고
care-change·file·evidence·attachment property를 두지 않는다.

## 5. UI 계약

직원 상세에 독립 `분기상담` tab을 추가한다.

- 연도·분기·상태를 표시한다.
- COMPLETE는 상담일·처리내용만 필수/표시한다.
- INCOMPLETE는 미완료 사유만 필수/표시한다.
- EXEMPT는 면제 사유만 필수/표시한다.
- 상태 변경 시 다른 조건부 입력값은 UI state와 payload에서 함께 비운다.
- VIEW는 read-only, MANAGE·ADMIN만 create/update/invalidate/replace한다.
- loading·empty·error·403·409·422와 성공 재조회가 있어야 한다.
- 실패 시 직원·검색·정렬·page·scroll·tab·입력 상태를 보존한다.
- 직원 A↔B, browser-back, session/logout, `AbortSignal`,
  직원별 query/mutation cache 격리를 검증한다.
- 제목·메뉴·API에 `교체상담`, Day 14/15, 실제급여제공을 넣지 않는다.
- file·evidence·attachment 제어를 만들지 않는다.

## 6. 단계·소유권

### 단계 A — RED

- 이루나: migration·DB truth table·active race·ACL·rollback·OpenAPI·ABS RED
- 송루나: tab·조건부 UI·권한·상태보존·real-PG E2E·leak RED
- 김부장: marker 의미·파일 경계·실행결과 독립검증과 RED 봉인

### 단계 B — backend·DB 구현

- 김루나: `0007`, model, repository, service, API, postcheck·restore
- 기존 migrations, 봉인 RED, frontend 수정 금지

### 단계 C — 생성 타입·frontend 구현

- 김부장: OpenAPI 생성 타입 재생성과 drift 확인
- 박루나: generated adapter, 분기상담 tab·폼·상태관리
- generated TypeScript 직접수정, backend/migration 수정 금지

### 단계 D — 교차검증·최종판정

- 이루나: DB invariant·권한·동시성·rollback 읽기 전용 검증
- 송루나: real-PG UI·문맥·민감정보·artifact 읽기 전용 검증
- 결함은 원 구현 소유자에게 반환
- 김부장: 전체 runtime gate 독립 재현과 GREEN 봉인

## 7. RED 계약

backend RED는 환경·import·collection 실패가 아니라 실제 product path의
stable `W1A_VS5_*` marker에서 실패해야 한다.

- migration/model/table 부재
- exact 3상태 valid/invalid truth table
- active unique와 실제 duplicate race
- immutable year/quarter update shape
- stale 409, wrong-staff, field-level 422
- invalidate/replacement와 audit exact rollback
- ADMIN·VIEW·MANAGE·ungranted·CSRF
- named OpenAPI model·route
- care-change/file/evidence/attachment 부재
- fresh/lifecycle/offline/postcheck/restore/cleanup

frontend RED는 actual render/fetch/mutation과 fresh real PostgreSQL browser
경로로 독립 tab, 세 상태의 조건부 필드, 권한, 오류 상태보존, 성공 재조회,
A↔B·검색·정렬·page·실제 scroll·tab·browser-back, session/cache/abort,
care-change/file/민감정보 부재를 검증한다.

## 8. 완료 gate

1. RED가 환경 오류가 아닌 제품 부재 named marker에서 실패한다.
2. `0007` lifecycle·offline·postcheck·restore가 통과한다.
3. 실제 PostgreSQL truth table·race·ACL·audit·rollback이 통과한다.
4. backend focused·전체, Ruff, mypy가 통과한다.
5. OpenAPI 생성 타입 drift가 0이다.
6. frontend focused·전체, lint, build가 통과한다.
7. fresh real-PG Playwright 3 viewport가 workers 1로 통과한다.
8. leak negative self-test와 normal gate가 통과한다.
9. artifact/media/temp DB/server/listener/test-results가 0으로 cleanup된다.
10. `git diff --check`가 0이다.
11. 구현자와 다른 검증자의 PASS 뒤 김부장이 최종판정한다.

## 9. 명시적 제외

- 초기 직원 이관·`staff_legacy_mapping`
- Wave 2 care-change 상담·실제급여제공·Day 14/15
- file·evidence·attachment
- 건강검진 자동 대상·D-day·task
- W1B 이후 구조
- 디자인 폴리시와 page size 조정

추가 사용자 결정은 필요하지 않다. 정본에 없는 연도 범위는 강제하지 않고,
key immutable과 replace payload는 기존 W1A ledger·audit 원칙 안에서
김부장이 구현계약으로 확정한다.
