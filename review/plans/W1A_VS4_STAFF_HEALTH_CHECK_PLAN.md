# W1A-VS4 직원 건강검진 상세 작업계획

> 문서 상태: `PASS / GREEN_SEALED / COMPLETE`
>
> 작성일: 2026-07-28 KST
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 기준 commit: `728958d4357b12bf34996ce10221118238b67c20`
>
> 선행 gate: `W1A-VS3 PASS / GREEN_SEALED`
>
> 총괄·최종판정: 김부장(Codex 본진 / SOL Max)
>
> RED 검증 증거: `review/evidence/w1a-vs4/RED.md`
>
> GREEN 검증 증거: `review/evidence/w1a-vs4/GREEN.md`

## 1. 권위와 목표

이 계획은 다음 정본과 검증표의 건강검진 계약만 하나의 micro-slice로 고정한다.

- `docs/02_새프로젝트_기능요구사항_정리본_v1.0.md` §3.3
- `docs/03_기존_UI와_기능요구사항_화면별_변경표_v1.1.md` §3.5
- `docs/04_DB_업무구조_최종설계_v4.7_PostgreSQL.md` §3.6
- `docs/05_기술아키텍처_및_개발기준_v1.4.md`
- `docs/07_개발로드맵_및_결정현황_v1.0.md`
- `review/WAVE1_CLEAN_TEST_MATRIX.md`
  `W1-STF-08`, `W1-CMN-04`~`07`, `W1-ABS-13`·`16`
- `docs/AI_업무분담_운영규정_v2.32.md`

목표는 건강검진을 아래 두 원장으로 분리해 완성하는 것이다.

1. 직원의 실제 건강검진 사실 원장
2. 이미 부여된 대상별 건강검진 상태 원장

자동 대상판정과 `target_key` 생성규칙은 공식 원문이 동결되지 않았으므로 W1에서
만들지 않는다. 이 미결은 원장과 exact 3상태 의미를 제거하는 근거가 아니다.

`W1A-VS4` 완료는 W1A 전체 완료가 아니다. 직원 분기상담과 초기 직원 이관·
legacy mapping은 후속 micro-slice에서 계속한다.

## 2. 포함 범위

### 2.1 건강검진 사실

`staff_health_check`는 다음을 제공한다.

- 안정 ID
- `staff_id`
- nullable `employment_id`; 값이 있으면 같은 직원 재직
- 필수 `check_date`
- nullable `check_type_code`
- nullable `result_note`
- 생성·변경 행위자, UTC timestamp, `row_version`
- 무효화·대체 이력과 audit

같은 직원의 같은 날짜 복수 사실을 허용한다. 따라서
`(staff_id, check_date)` unique를 만들지 않는다.

### 2.2 대상별 상태

`staff_health_check_requirement`는 다음을 제공한다.

- 안정 ID와 `staff_id`
- nullable same-staff `employment_id`
- 안정 `target_key`
- 필수 `target_rule_version_code`
- exact status `COMPLETE` / `INCOMPLETE` / `EXEMPT`
- nullable same-staff `health_check_id`
- nullable `exempt_reason_text`
- 생성·변경 행위자, UTC timestamp, `row_version`
- 무효화·대체 이력과 audit

유효행은 `(staff_id, target_key)`별 최대 1개다.

상태 truth table:

```text
COMPLETE:
  health_check_id NOT NULL
  exempt_reason_text IS NULL

INCOMPLETE:
  health_check_id IS NULL
  exempt_reason_text IS NULL

EXEMPT:
  health_check_id IS NULL
  exempt_reason_text nonblank
```

`health_check_id`는 같은 직원의 유효 건강검진 사실만 연결할 수 있다.

### 2.3 API·OpenAPI

건강검진 사실 CRUD와 대상별 상태 조회·변경은 분리된 route와 named model을
사용한다.

- fact list/create/update/invalidate
- requirement list/update/invalidate
- `expected_row_version` stale conflict는 stable 409
- field-level validation은 422
- ADMIN·granted `STAFF_MANAGE`는 write
- ADMIN·granted `STAFF_VIEW`는 read
- ungranted USER는 read/write 모두 거부
- unsafe mutation은 session·CSRF를 모두 요구

W1 public API는 requirement 자동생성, `target_key` 생성, D-day와 task를
제공하지 않는다. 테스트의 상태행 fixture는 합성 `target_key`와 합성
`target_rule_version_code`를 trusted repository/DB setup으로만 넣고, 이를
제품 자동생성 route로 만들지 않는다.

OpenAPI는 fact와 requirement model을 분리하고 exact status enum과 조건부
nullable 의미를 설명한다. task/evidence/file/attachment property는 없다.

### 2.4 UI

직원 상세에 독립 `검진` tab을 추가한다.

- `검진사실` 영역: 검진일, 선택 검진유형, 선택 결과메모, 선택 재직
- `대상별 상태` 영역: target, rule version, exact 3상태, 상태별 조건부 fact·
  면제사유
- COMPLETE: 같은 직원 fact 선택
- INCOMPLETE: fact·면제사유 없음
- EXEMPT: nonblank 면제사유
- VIEW는 read-only, MANAGE·ADMIN만 mutation
- loading·empty·error·403·409·422와 성공 재조회
- 직원 A↔B, 검색·정렬·page·scroll·tab·browser-back 문맥
- session 변경·logout·AbortSignal·query/mutation cache 격리

공식 기준이 동결되기 전에는 자동 대상생성, 신규입사/기존/재입사 판정,
D-day, 업무카드와 첨부 UI를 만들지 않는다.

## 3. 명시적 제외

- 건강검진 자동 대상판정
- `target_key` 생성 알고리즘
- 실제 법정 시행일·주기·D-day 계산
- task·업무카드·notification side effect
- 증빙·file·attachment FK, API, OpenAPI, UI
- 과거 건강검진 초기 이관
- 직원 분기상담
- Wave 2 요양보호사 교체상담
- 디자인·page size·내부 사용성 조정

## 4. Migration·DB 계약

새 revision은 `20260728_0006_w1a_staff_health_check`로 만든다. 기존
`0001`~`0005`는 수정하지 않는다.

필수 검증:

- fresh base→head
- `0005→0006`
- `0006→0005→0006`
- offline SQL 생성·빈 DB 적용
- exact constraint/index/trigger/function naming
- same-staff employment·fact 복합 FK
- 같은 날짜 복수 fact
- active target unique와 동시 duplicate race
- 모든 valid/invalid status truth table
- stale version, invalidation/replacement, audit
- audit 실패와 fact/requirement mutation exact rollback
- restore drill과 `W1A_VS4_DB_POSTCHECK_OK`
- VS1·VS2·VS3 PostgreSQL 회귀

## 5. RED 계약

### 5.1 Backend·PostgreSQL RED

실제 service·FastAPI·PostgreSQL 경로로 다음 제품 부재를 named
`W1A_VS4_*` marker에서 실패시킨다.

- `0006` migration·model·OpenAPI 부재
- same-date multiple fact, wrong-staff employment/fact
- requirement status truth table
- active target duplicate race
- stale 409, audit와 exact rollback
- ADMIN·VIEW·MANAGE·ungranted·CSRF·422
- 미승인 generator/task/file side effect 부재

환경 traceback, import/collection 실패와 test 자체 SQL·가짜 예외로 만든 결과는
유효 RED가 아니다.

### 5.2 Frontend·E2E·ABS RED

actual render/fetch/mutation과 fresh real PostgreSQL browser 경로로 다음을
검증한다.

- 독립 `검진` tab과 두 영역
- fact same-date 복수와 선택 재직
- existing requirement 3상태 truth table과 조건부 fields
- VIEW read-only, MANAGE·ADMIN write
- 409·422·403 상태 보존과 성공 재조회
- A↔B·검색·정렬·page·실제 scroll·tab·browser-back
- session/cache/abort 경계
- 자동 대상·D-day·task·첨부·민감정보·내부 오류 DOM/cache/log/artifact 0
- workers 1의 `1440x1000`, `1440x900`, `1366x768`

## 6. 단계·소유권

### 단계 A — RED

- 이루나: backend·PostgreSQL·migration·ACL·동시성 RED
- 송루나: frontend·E2E·ABS·leak RED
- 김부장: 파일 경계·marker 의미·실행결과 독립검증과 RED 봉인

### 단계 B — backend·DB 구현

- 김루나: `0006`, model, repository, service, API, postcheck·restore
- 기존 migrations, 봉인 RED, frontend 수정 금지

### 단계 C — 생성 타입·frontend 구현

- 김부장: OpenAPI 생성 타입 재생성과 drift 확인
- 박루나: adapter, 검진 tab, 상태관리, 구현 focused tests
- generated TypeScript 직접수정, backend/migration 수정 금지

### 단계 D — 교차검증·최종판정

- 이루나: DB invariant·권한·동시성·rollback 읽기 전용 검증
- 송루나: real-PG UI·문맥·민감정보·artifact 읽기 전용 검증
- REQUIRED_CHANGES는 원 구현 소유자에게 반환
- 김부장: 전체 runtime gate 독립 재현과 GREEN 봉인

## 7. 완료 gate

1. 두 RED가 환경 오류가 아닌 제품 부재 named marker에서 실패한다.
2. migration lifecycle·offline·postcheck·restore가 통과한다.
3. 실제 PostgreSQL invariant·race·ACL·audit·rollback이 통과한다.
4. backend focused·전체, Ruff, mypy가 통과한다.
5. OpenAPI 생성 타입 drift가 0이다.
6. frontend focused·전체, lint, build가 통과한다.
7. fresh real-PG Playwright 3 viewport가 workers 1로 통과한다.
8. leak negative self-test와 normal gate가 통과한다.
9. artifact/media/leak와 temp DB/server/listener/test-results가 0으로 cleanup된다.
10. `git diff --check`가 0이고 stage·commit·push가 없다.
11. 두 독립 교차검증 뒤 김부장이 최종판정한다.

## 8. 사용자 결정

추가 사용자 결정은 필요하지 않다. 사실·상태 원장과 exact 3상태는 확정됐고,
공식 원문이 필요한 자동 대상판정은 명시적으로 제외한다.

## 9. 착수·완료 판정

- 선행 `W1A-VS3`는 `PASS / GREEN_SEALED`다.
- `W1A-VS4` RED는 `review/evidence/w1a-vs4/RED.md`에 봉인됐다.
- 단계 B backend·DB, 단계 C frontend, 단계 D 이루나·송루나 교차검증과
  김부장 전체 runtime gate가 모두 PASS했다.
- 실제 PostgreSQL 16/16과 실제 PG Playwright 3/3, frontend 79/79,
  leak self-test·normal gate 및 cleanup을 통과했다.
- 최종 증거는 `review/evidence/w1a-vs4/GREEN.md`에
  `PASS / GREEN_SEALED`로 봉인됐다.
- `W1A-VS4 PASS` 뒤에도 분기상담·초기이관/legacy mapping이 남으므로
  W1B 착수가 아니다.
