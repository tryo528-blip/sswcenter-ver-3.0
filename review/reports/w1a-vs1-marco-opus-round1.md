# W1A-VS1 마르코 Opus 보정 1차 반대심사

> 심사일: 2026-07-26 KST
>
> 심사자: 마르코 (`gpt-5.6-sol / max`)
>
> 심사 대상: Claude CLI Opus 5의 W1A hardening WIP
>
> 대상 worktree:
> `C:\Users\USER\.codex\worktrees\opus-w1a-019f9e39`
>
> 판정: `REQUIRED_CHANGES`

이 문서는 최종승인이 아닌 2라운드 중 1차 반대심사 기록이다. staged diff는
Codex 본진이 전달한 baseline이고, unstaged diff와 untracked 파일만 Opus
실제 WIP로 심사했다. URL 검색·pagination·누락 command UI 전체는 이번 Opus
패킷 밖이라 심사에서 제외했다.

마르코는 심사 중 파일 수정·stage·commit·push를 하지 않았다.
`git diff --check`는 PASS 상태였다.

## 차단 결함

### M1. replacement 생략이 명시적 제거로 처리됨

- 분류: 확정 / 패킷 C
- 근거:
  - `backend/app/domains/staff/schemas.py:113`
  - `backend/app/domains/staff/service.py:784`
  - `frontend/src/generated/sswcenter-api.ts:696`
- 내용: `replacement: ... | None = None`이라 필드 자체를 생략해도
  `replacement=None`으로 수락된다. 생성 TypeScript도 optional field로
  노출한다.
- 영향: 클라이언트 직렬화 누락만으로 기존 직종·역할이 삭제되어
  “replacement 또는 명시적 제거” 계약을 위반한다.
- Opus 필수 보정: nullable이지만 required인 field 또는 명시적 action
  discriminator를 사용한다. 필드 누락은 422, 명시적 `null`만 제거됨을
  API·OpenAPI·실제 PostgreSQL에서 검증한다.

### M2. replacement PostgreSQL 테스트가 핵심 결함을 검출하지 못함

- 분류: 확정 테스트 차단 / 패킷 C
- 근거: `backend/tests/test_w1a_staff_integration_postgres.py:295`
- 내용: stale와 누락 요청은 mutation 전에 실패하면서 rollback 검증으로
  기록됐다. 중복 ID, 전체 명시 제거, 첫 자식 생성 뒤 두 번째 자식 실패의
  실제 rollback, 기존행 actor/time/version 증가를 검증하지 않는다.
- 영향: link·audit 일부가 맞아도 원자성이나 파괴적 제거 회귀가 숨을 수 있다.
- Opus 필수 보정: 실제 PostgreSQL에서 중복 ID, 전체 `null` 제거, 일부 대체,
  두 번째 자식 실패 뒤 부모·자식·audit·counter 전부 원복,
  `updated_by/updated_at/row_version` 증가를 각각 독립 검증한다.

### M3. unmount·logout에서 직원 Query cache가 남음

- 분류: 확정 / 패킷 A
- 근거:
  - `frontend/src/pages/StaffPage.tsx:45`
  - `frontend/src/pages/StaffPage.tsx:88`
  - `frontend/src/components/auth/AuthGate.tsx:9`
- 내용: unmount cleanup은 reveal 요청만 abort한다. logout의 loading 전환으로
  `StaffPage`가 먼저 unmount되어 page 내부 auth-ID effect와
  `queryClient.clear()`가 실행되지 않는다. 다음 계정의 새 mount도 이전 ID를
  알 수 없다.
- 영향: 이전 계정 직원 목록·상세가 Query cache에 남아 다음 계정 화면에
  순간 노출될 수 있다.
- Opus 필수 보정: `AuthGate` 밖의 auth-aware cache boundary 또는 보장된
  logout/login cleanup에서 직원·capability cache를 제거한다. 계정 A cache
  선적재→logout→계정 B login, 페이지 이탈, 지연 reveal 응답을 실제
  AuthProvider 구조로 테스트한다.

### M4. 예외 traceback과 Uvicorn 오류 로그에 주민번호가 노출됨

- 분류: 확정 / 패킷 B
- 근거:
  - `backend/app/core/logging.py:75`
  - `backend/app/core/logging.py:151`
  - `backend/app/core/logging.py:173`
  - `backend/tests/test_logging.py:82`
- 재현: 7번째 자리 `9`인 합성 주민번호를 `ValueError` 메시지에 넣고
  `logger.exception()`을 format하면 평문이 남고 redaction marker는 없다.
  filter는 `record.msg`만 바꾸며 formatter가 뒤에 붙이는 `exc_info`는 처리하지
  않는다. Uvicorn 자체 handler에도 같은 filter가 없다.
- 영향: 안전한 HTTP catch-all 응답과 별개로 stderr·app/error log에 평문이
  남을 수 있다.
- Opus 필수 보정: 완성된 로그 문자열 전체를 치환하는 formatter를 적용하고
  Uvicorn error handler에도 같은 보호를 연결한다. 실제 Uvicorn subprocess와
  `logging.exception()`의 stdout/stderr·회전 로그에서 0/9 하이픈·비하이픈
  합성값 0건을 검증한다.

### M5. 유출 gate가 workspace와 application log를 검사하지 않음

- 분류: 확정 / 패킷 B
- 근거:
  - `scripts/test-w1a-vs1-red.ps1:123`
  - `scripts/test-w1a-vs1-red.ps1:148`
  - `scripts/test-w1a-vs1-postgres.ps1:313`
- 내용: RED script는 지정된 일부 파일과 Playwright 디렉터리만 읽고 GREEN
  실행용 독립 gate가 아니다. 전체 PostgreSQL harness는 PG log만 검사하고
  app/error/access log와 workspace는 검사하지 않는다. `\b` 경계는 underscore
  인접값도 놓친다.
- 영향: 현재 “0 files”와 PostgreSQL PASS가 실제 애플리케이션 로그·workspace
  유출 부재를 증명하지 못한다.
- Opus 필수 보정: 독립 실행 가능한 GREEN leak gate를 만들고 관련
  tracked/untracked workspace 텍스트, app log, PG log, Playwright output을
  검사한다. 실패 메시지에는 실제 민감값을 출력하지 않는다.

### M6. ACL fingerprint가 schema·sequence 권한을 비교하지 않음

- 분류: 확정 테스트 차단 / 패킷 D
- 근거:
  - `scripts/test-w1a-vs1-postgres.ps1:335`
  - `backend/alembic/versions/20260726_0003_w1a_staff.py:271`
- 내용: fingerprint가 일부 table CRUD만 비교하고 schema `USAGE`, 모든
  sequence `USAGE/SELECT`, 나머지 Wave0 table을 누락한다.
- 영향: downgrade가 schema 또는 sequence grant를 남겨도 harness가 PASS할
  수 있다.
- Opus 필수 보정: surviving schema/table/sequence 전체 ACL을 upgrade 전후
  exact fingerprint하고 downgrade 뒤 동일함과 W1A 권한 배정·definition
  제거를 검증한다. 현재 revoke와 dependent row 삭제 순서 자체에서는 확정
  코드 결함을 찾지 못했다.

### M7. UI가 서버 current projection을 사용하지 않음

- 분류: 확정 / 패킷 E
- 근거:
  - `frontend/src/pages/StaffPage.tsx:170`
  - `backend/app/domains/staff/service.py:328`
  - untracked `backend/tests/test_w1a_staff_current_projection.py`
- 내용: 백엔드는 inclusive 날짜 기준을 적용하지만 UI는 `end_date === null`인
  첫 재직을 active로 간주한다. 오늘 종료 재직과 미래 시작 open 재직에서
  서버·UI 판정이 달라진다.
- 영향: 현재 재직 표시와 종료·재입사 action이 서버 계약과 어긋난다.
- Opus 필수 보정: `detail.current_employment`를 기준으로 UI를 동작시키고
  과거·미래·시작/종료 경계 fixture를 추가한다. untracked projection test를
  최종 변경 파일 목록에 포함한다.

### M8. role OpenAPI pattern 누락과 checked-in TypeScript drift

- 분류: 확정 / 패킷 F
- 근거:
  - `backend/app/domains/staff/schemas.py:40`
  - `backend/tests/test_w1a_staff_openapi_contract.py:97`
  - `scripts/generate-openapi-types.ps1:71`
- 내용: runtime은 trim·uppercase normalization을 하지만 실제 OpenAPI의
  `role_code`에는 regex `pattern`이 없다. 독립 `-Check`도 exit 1이다.
- 영향: runtime 계약과 OpenAPI 생성 원본이 다르고 checked-in TypeScript를
  신뢰할 수 없다.
- Opus 필수 보정: normalize-before-validate를 유지하면서 JSON Schema
  pattern도 보존하고 lowercase/trim/invalid/length 계약을 테스트한다. 정식
  생성기를 실행해 drift 0을 만든다. `MALE|FEMALE|TEST` 응답 enum은 확인됐다.

### M9. Ruff format gate 실패

- 분류: 확정 완료조건 차단
- 근거:
  - `backend/app/domains/staff/service.py:827`
  - `backend/tests/test_w1a_staff_integration_postgres.py:276`
- 내용: `ruff format --check app tests`가 두 파일 때문에 exit 1이다.
- Opus 필수 보정: formatter 적용 뒤 format/check/mypy/backend 전체를
  재실행한다.

## 중요 권고

1. 현재 raw 13자리 redaction은 epoch 형태의 비-RRN 숫자도 과검출한다.
   logging과 artifact gate가 숫자 경계와 YYMMDD·세기코드 유효성을 확인하는
   공통 후보 판별기를 사용하고 timestamp·긴 숫자·underscore 인접값을
   양성·음성 테스트하는 것이 안전하다.
2. catch-all은 `/api/v1`와 reveal뿐 아니라 Wave0 auth body/header/cookie,
   non-API 예상 밖 오류, body `request_id`와 `X-Request-ID` 동일성을 직접
   봉인해야 한다.
3. downgrade의 광범위한 revoke는 “Wave0 runtime role 선행 grant 0”을
   전제로 한다. 이것이 정본 불변조건인지 확인하여 precondition으로 검증한다.

## 후속 개선

- current projection의 `as_of`를 응답 구성 전체에서 한 번만 계산하여 자정
  경계의 이론적 불일치를 제거한다.
- A~F별 테스트 이름과 명령을 Opus 최종보고에 매핑한다.

## Opus 반환 체크리스트

1. replacement item을 필수 nullable 또는 명시적 action으로 바꾼다.
2. 누락·중복·stale·전부 제거·일부 대체·link·actor/time/version·
   post-mutation rollback PostgreSQL 테스트를 추가한다.
3. unmount/logout/account switch에서 직원·capability cache를 제거하고
   실제 auth 전환 테스트를 추가한다.
4. 최종 formatted log와 Uvicorn error 경로까지 redaction한다.
5. workspace·app log·PG log·Playwright output 독립 GREEN leak gate를 만든다.
6. ACL fingerprint를 schema·전체 surviving table·sequence로 확장한다.
7. UI가 서버 `current_employment`를 사용하게 하고 untracked projection test를
   회수 목록에 포함한다.
8. role OpenAPI pattern과 exact enum·normalization 테스트를 보강한다.
9. OpenAPI TypeScript를 정식 생성기로 재생성하여 `-Check` drift 0을 만든다.
10. Ruff format 뒤 backend/frontend/PostgreSQL/E2E/leak gate 전체 증거를
    제출한다.
