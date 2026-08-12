# W1A 직원 최소 vertical slice 상세 작업계획

> 문서 상태: `W1A_VS1_FINAL_PASS`
>
> 작성자: Codex
>
> 작성일: 2026-07-26 KST
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 계획 기준 SHA: `73ee1c3887de9cfe5af9ceea01724c24d0144ce7`
>
> 최종 구현 SHA: `55130af1dc3244c391bca11471323e6b22061c3f`

> 최종 실행 결과(2026-07-27): 원격 WIP commit
> `c4ee9f1420e0c9d3d97f01fc835c7d9495974008`을 기준으로
> `docs/AI_업무분담_운영규정_v2.2.md`를 적용한다. 김부장이 단일 창구·
> 오케스트레이터·최종판정자를 맡고, 김루나·박루나·이루나·송루나 상시
> 실무자 풀에 backend·frontend·정합성·누출검증을 비중복 배정한다. 요셉과
> 마르코는 상시 단계가 아니라 호출조건이 충족될 때만 임시 투입하고,
> 오푸스는 가장 어려운 독립 구현 또는 외부감리 중 하나만 맡는다. 아래의
> 과거 요셉·마르코·Opus 라운드는 역사적 기술 증거일 뿐 현재 고정 절차가
> 아니다. 모든 발견사항은 원 소유자 보정과 교차검증을 거쳤으며 김부장이
> 최종 구현 SHA에서 전체 runtime을 재검증해 `PASS`로 판정했다.

## 1. 권위와 목표

이 계획은 다음 정본을 함께 적용한다.

- `docs/07_개발로드맵_및_결정현황_v1.0.md` §2~§4, 특히 §3 W1A
- `review/WAVE1_CLEAN_TEST_MATRIX.md` §12~§14
- 위 문서가 연결한 업무·UI·DB·보안 정본
- `docs/AI_업무분담_운영규정_v2.32.md`

이번 작업단위의 식별자는 `W1A-VS1`이다. 목표는 test matrix §12가 지정한
가장 작은 직원 수직 slice를 실제 PostgreSQL, API, OpenAPI 생성 타입, React UI,
실제 브라우저 E2E까지 한 흐름으로 완성하는 것이다.

`W1A-VS1` 완료는 W1A 전체 완료나 Wave 1 완료를 뜻하지 않는다. test matrix
§13의 나머지 W1A 범위와 §14의 Wave 1 통합 종료 gate는 후속 작업에서 별도로
완료·봉인한다.

## 2. 범위

### 2.1 포함

1. 직원 identity
   - 직원 내부 PK와 재직 ID·재직번호 분리
   - Wave 0 `staff.display_name`과 `staff.memo` 보존
   - 결정적 직원 목록과 목록 유지형 상세
2. 최초 재직과 재입사
   - 신규 직원과 최초 재직 원자 생성
   - 퇴사일로 재직상태 계산
   - 기존 직원의 재입사 시 새 재직 ID와 새 재직번호 발급
   - 재직기간 중복과 동시 재입사 번호 경쟁 차단
3. 직종과 업무역할
   - `staff_position_period`와 `staff_operational_role_period`를 별도 계약으로 유지
   - 두 기간이 재직기간 안에 완전히 포함되는 순방향 검사
   - 재직기간 단축·무효화 시 자식기간을 재검사하는 역방향 검사
4. 전화번호
   - 화면용 원문과 `phone_normalized` projection을 같은 transaction에서 저장
   - 한국 국내번호와 `+82`/`0082` 동치 처리
   - 빈 값은 두 컬럼 모두 `NULL`
   - 비한국 국제번호·내선·오염문자·길이 오류는 422
5. 주민등록번호
   - 신규 일반직원 등록 시 필수
   - 기존 Wave 0/bootstrap 직원은 민감행 0개 허용
   - 업무검증 후 AES-256-GCM 암호화
   - 일반 응답·UI에는 `birth_date` 기반 mask만 노출
   - ADMIN·`STAFF_MANAGE` 전용 POST reveal, CSRF, 현재 PIN step-up, `no-store`
   - 성공 1회당 `access_event` 정확히 1건
6. 공통 계약
   - 권한·CSRF·`row_version`
   - 표준 성공/오류 named model
   - `/api/v1` 경로
   - OpenAPI에서 생성한 checked-in TypeScript
   - 합성자료만 사용하는 실제 PostgreSQL 및 브라우저 검증

### 2.2 제외

다음은 이번 `W1A-VS1`에서 구현하거나 임의 확정하지 않는다.

- 초기 직원 이관기와 `staff_legacy_mapping`
- W1A 공통 service catalog
- 일반 자격증과 서비스 제공자격
- 신규·정기교육
- 건강검진 사실·대상상태
- 직원 분기상담
- 수급자 이후 W1B~W1F 제품 범위
- Wave 2 이후 업무정책·일정·RFID·청구
- 파일함·첨부·OCR 상세설계 및 구현
- 주민번호 HMAC key의 온라인 dual-key rotation
- 민감행이 0개인 기존/bootstrap 직원에게 주민번호를 사후 추가하는 API·UI
- 구 Wave 1·2 코드, migration, DTO, 생성 타입 또는 component 반입

위 제외항목용 table, FK, route, OpenAPI property, UI stub도 미리 만들지 않는다.

## 3. 고정 업무 불변조건

### 3.1 직원·재직

- `staff.id`는 직원 identity이고 재입사에도 유지된다.
- 재입사는 기존 직원에 새 `staff_employment`를 추가한다.
- 재직번호는 사용자가 입력하지 않으며 기존 `business_number_counter`를
  transaction-safe하게 사용한다.
- 같은 직원의 유효 재직기간은 겹칠 수 없다.
- 별도 근무상태 컬럼을 추가하지 않고 조회일과 `end_date`로 상태를 계산한다.
- `display_name`, `memo`의 컬럼·nullability·기존 값을 보존한다.
- 변경 가능한 `staff`, `staff_employment`, 직종기간, 역할기간에는 양의
  `row_version`을 두고 mutation에서 예상 version을 검사한다.

### 3.2 직종·업무역할 기간

- 직종과 업무역할은 서로 다른 모델·API field·UI section이다.
- 기존 `(staff_id, employment_id)` 복합 FK를 유지한다.
- 다음 DB object 이름을 exact 계약으로 사용한다.
  - `ct_staff_position_within_employment`
  - `ct_staff_operational_role_within_employment`
  - `ct_staff_employment_child_periods_reverse_guard`
  - 각 constraint trigger와 같은 stem의 `fn_` function
- constraint trigger는 모두 `DEFERRABLE INITIALLY DEFERRED`다.
- 자식 insert/update뿐 아니라 부모 재직기간 update·무효화도 검사한다.
- 한 transaction에서 부모와 자식을 함께 일관된 최종상태로 바꾸는 것은 허용한다.
- 범위 위반은 raw constraint명이 아닌 안정 오류
  `STAFF_PERIOD_OUTSIDE_EMPLOYMENT` 409로 매핑한다.

### 3.3 전화 정규화 v1

- 입력 양끝 공백을 제거한 원문을 `staff.phone`에 보존한다.
- 공백, 하이픈, 마침표, 괄호만 구분자로 제거한다.
- 국내 입력은 `0`으로 시작하는 숫자 9~11자리다.
- 국제 입력은 `+82` 또는 `0082` 뒤 선행 `0` 없는 숫자 8~10자리다.
- projection은 국내 선행 `0`을 제거한 `+82`와 나머지 숫자의 결합이다.
- `010-1234-5678`, `+82 10 1234 5678`, `0082-10-1234-5678`은 모두
  `+821012345678`이다.
- 빈 입력은 원문과 projection 모두 `NULL`이다.
- projection에는 nullable non-unique index를 두며 일반 응답에는 반환하지 않는다.

### 3.4 주민등록번호

- 허용 입력은 숫자 13자리 또는 `YYMMDD-XXXXXXX`뿐이다.
- 정규화 후 앞 6자리 달력날짜와 7번째 숫자의 세기·성별이 요청의
  `birth_date`, `sex_code`와 일치해야 한다.
- `9/0`은 1800년대, `1/2/5/6`은 1900년대, `3/4/7/8`은 2000년대이고,
  홀수는 남성, 짝수는 여성이다.
- checksum 불일치만으로는 거부하지 않는다.
- 일반 mask는 복호화 없이 `birth_date`에서 `YYMMDD-*******`로 만든다.
- 평문, mask 문자열, 암호 재료를 `staff`나 일반 DTO에 저장하지 않는다.

`erp.staff_sensitive_identity`는 다음 exact 계약을 가진다.

- `staff_id`: PK/FK, 직원당 0..1
- `resident_number_ciphertext`: nonempty `bytea`
- `resident_number_nonce`: 정확히 12-byte
- `resident_number_key_version`: 양의 integer
- `resident_number_lookup_hmac`: 정확히 32-byte, unique
- `encrypted_at_utc`, `updated_at_utc`, `row_version`
- exact checks/index:
  - `ck_staff_sensitive_identity_ciphertext_nonempty`
  - `ck_staff_sensitive_identity_nonce_length`
  - `ck_staff_sensitive_identity_key_version_positive`
  - `ck_staff_sensitive_identity_lookup_hmac_length`
  - `uq_staff_sensitive_identity_lookup_hmac`

암호 protocol은 다음과 같다.

- AES keyring의 각 key는 정확히 32-byte이고 versioned다.
- 매 암호화마다 CSPRNG 12-byte nonce를 새로 만든다.
- AAD는 UTF-8
  `staff:{staff_id}:resident-number:v{key_version}`다.
- lookup은 AES key와 분리된 안정 32-byte key의 HMAC-SHA-256 결과를 사용한다.
- 직원 row를 flush하여 `staff_id`를 얻은 뒤 같은 service transaction에서
  암호화·민감행 insert·최초 재직·선택 직종/역할 insert까지 수행한다.
- 어느 단계든 실패하면 전체를 rollback한다.
- secret은 DB·Git·일반 설정파일에 넣지 않는다. 환경설정은 운영에서 외부
  credential 공급이 없으면 시작을 거부하고, test/development는 합성 전용
  secret만 허용한다.

### 3.5 reveal

- 경로는 `POST /api/v1/staff/{staff_id}/sensitive-identity/reveal`이다.
- ADMIN 또는 `STAFF_MANAGE` permission을 가진 현재 계정만 허용한다.
- CSRF와 현재 로그인 계정 PIN을 모두 검증한다.
- 성공 응답에 `Cache-Control: no-store`를 설정한다.
- 성공 transaction 안에서 `access_event`를 정확히 1건 기록한다.
- event에는 대상 직원, 행위자, 시각, 행위코드만 기록하고 평문·PIN·암호재료는
  어떤 JSON/detail에도 기록하지 않는다.
- 실패한 reveal에는 성공 access event를 기록하지 않는다.
- 프론트는 reveal 응답을 TanStack Query cache에 넣지 않는다. 대화상자를 닫거나
  화면을 이탈하면 평문 상태와 DOM을 즉시 폐기한다.

current-PIN step-up과 audit의 exact 순서는 다음과 같다.

1. session에서 얻은 현재 `account_id`로 활성 `user_account`를 직접 조회하고 다른
   계정이나 PIN lookup HMAC로 대체하지 않는다.
2. 이미 잠긴 계정은 `ACCOUNT_LOCKED` 423으로 거부한다.
3. 현재 계정의 `pin_hash`와 PIN을 검증한다. 실패는 기존 계정의 연속 실패횟수에
   포함하고 5회부터 15분 잠금을 적용하며 실패 `auth_event`를 commit한다.
   실패 PIN, 주민번호, hash는 event나 로그에 넣지 않는다.
4. 성공 step-up은 과거 로그인 실패횟수를 reset하지 않는다. reveal 대상 민감행을
   읽고 AAD를 포함해 복호화한다.
5. key version 부재, 인증 tag 불일치, ciphertext 이상은
   `SENSITIVE_IDENTITY_DECRYPTION_FAILED` 500으로 처리한다. 평문을 응답·로그·성공
   access event에 남기지 않는다.
6. 복호화 성공 뒤 같은 service transaction에 성공 `access_event` 1건을 insert하고
   commit한다. commit 성공 뒤에만 메모리의 평문으로 response를 구성한다.
   commit 실패 시 response를 만들지 않고 전체 rollback한다.
7. 실패 응답은 `Cache-Control: no-store`를 포함하며 재시도는 일반 API 재요청으로만
   한다. 서버 내부 자동 재시도는 하지 않는다.

## 4. 사용자 확정 권한 계약

정본은 모든 mutation의 권한검사와 관리자 reveal을 요구하지만 직원 일반 CRUD의
세부 역할별 권한명과 직원정보 열람범위는 고정하지 않았다. 사용자는 2026-07-26
정본의 “관리자 reveal” 범위를 `STAFF_MANAGE`까지 명시적으로 확장하고 다음 계약을
확정했다.

| action | ADMIN | `STAFF_VIEW` | `STAFF_MANAGE` | 그 외 활성 USER |
|---|---:|---:|---:|---:|
| 직원 목록·상세 masked 조회 | 허용 | 허용 | 허용 | 거부 |
| 일반정보(`name`, `phone`, `address`, `display_name`, `memo`) 수정 | 허용 | 거부 | 허용 | 거부 |
| 재직·직종·역할 생성·종료·정정 | 허용 | 거부 | 허용 | 거부 |
| 주민번호를 포함한 신규 직원 등록 | 허용 | 거부 | 허용 | 거부 |
| 주민번호 최초 입력·향후 정정 | 허용 | 거부 | 허용 | 거부 |
| 주민번호 reveal | 허용 | 거부 | 허용 | 거부 |

- `STAFF_VIEW`, `STAFF_MANAGE` definition은 idempotent seed하되 기존 USER에게
  자동 부여하지 않는다.
- `STAFF_MANAGE`는 masked 조회를 내포한다.
- `birth_date`, `sex_code`는 주민번호 검증과 결합된 identity field이므로 독립적인
  일반정보 수정에 포함하지 않는다. 주민번호 정정 기능을 후속 micro-slice에서
  구현할 때 ADMIN과 `STAFF_MANAGE`가 주민번호와 함께 바꾸는 원자 command로 다룬다.
- W1A-VS1은 정본 §12의 주민번호 신규 입력과 reveal까지만 구현한다. 기존 0행
  직원의 사후 입력과 기존 민감행 정정 API·UI는 §2.2대로 이번 slice에서 제외하지만,
  후속 구현 시에도 ADMIN·`STAFF_MANAGE` 동등 권한이라는 owner policy를 유지한다.
- 프론트 control 숨김은 UX일 뿐이며 백엔드가 매 요청을 최종 판정한다.
- 신규 직원 등록은 주민번호가 필수인 원자 command이며 ADMIN과
  `STAFF_MANAGE`가 실행한다.

## 5. DB·migration 계획

exact revision `20260726_0003_w1a_staff` 하나를 Wave 0 head
`20260724_0002` 뒤에 추가한다.

1. `staff.phone_normalized` nullable column과 non-unique index 추가
2. `staff_sensitive_identity`와 exact constraint·unique 생성
3. `staff_employment`, `staff_position_period`,
   `staff_operational_role_period`에 `row_version`, `updated_at_utc`,
   `updated_by_account_id`를 추가하고 직종·역할에는 `created_by_account_id`도
   추가한다. 기존 재직은 `created_by_account_id`를, 기존 직종·역할은 부모 재직의
   `created_by_account_id`를 created/updated actor로 backfill한다.
   `updated_at_utc`는 기존 `created_at_utc`, `row_version`은 1로 backfill한 뒤
   모두 `NOT NULL`로 봉인한다. 임의 migration 계정은 만들지 않는다.
4. 직종·역할 순방향 containment function/constraint trigger 생성
5. 재직 부모 역방향 guard function/constraint trigger 생성
6. owner가 확정한 permission definition을 idempotent seed
7. exact 운영 역할 `erp_owner`, `erp_app`, `erp_backup`에 최소 권한 부여
8. downgrade에서 위 항목만 정확한 역순으로 제거

migration은 다음 경로를 검증한다.

- 빈 임시 cluster의 `base→head`
- Wave 0 head `20260724_0002→W1A-VS1 head`
- `W1A-VS1 head→20260724_0002→W1A-VS1 head`
- offline SQL 생성과 빈 DB 적용
- application role로 API와 제약 테스트
- `display_name`·`memo` 값 hash와 nullability 불변

DB는 원자성·기간·unique·동시성의 최종 방어선이다. API는 DB object 이름을
클라이언트 계약으로 사용하지 않고 도메인 오류로 변환한다.

검증기는 다음과 같이 분리·합성한다.

- `backend/app/db/postcheck.py`의 Wave 0 invariant(table·constraint·index·singleton·
  UTC)는 새 head에서도 재사용하되 exact revision과 permission 수 검사는 인자로
  분리한다. `verify-wave0-db.ps1`은 `20260724_0002`와 기존 permission 4개를 계속
  exact 검증한다.
- `backend/app/db/postcheck_w1a_vs1.py`와
  `scripts/verify-w1a-vs1-db.ps1`은 `20260726_0003_w1a_staff`, 새 table·column·
  trigger·index·permission, 평문 컬럼 0건을 exact 검증한다.
- `scripts/test-w1a-vs1-postgres.ps1`은 임시 cluster에 `erp_owner`, `erp_app`,
  `erp_backup`을 test-only password로 생성하고 운영과 같은 repository grant SQL을
  실제 실행한다. `erp_owner`로만 migration한다.
- 애플리케이션 암호화 구조이므로 `erp_app`에는 `staff_sensitive_identity`의
  `SELECT`, `INSERT`, `UPDATE`와 필요한 sequence 권한을 허용한다. `DELETE`,
  `TRUNCATE`, schema DDL, grant 변경, `audit_event`·`access_event` 삭제는 거부한다.
  민감정보의 업무권한 경계는 서버의 service/dependency이며 DB credential은
  브라우저나 사용자에게 노출하지 않는다.
- `erp_backup`은 backup/검증에 필요한 `SELECT`만 허용하고 DML·DDL을 거부한다.
  harness는 각 역할의 허용·거부표와 실제 API transaction을 모두 검증한다.
- restore manifest의 revision이 `20260724_0002`이면 Wave 0 postcheck,
  `20260726_0003_w1a_staff`이면 Wave 0 invariant와 W1A-VS1 postcheck를 차례로
  실행한다. 알 수 없는 revision은 성공으로 간주하지 않고 명시적으로 실패한다.
- 기존 `scripts/test-ephemeral-postgres.ps1`의 Wave 0 exact 실행은 유지하고,
  W1A 검증기는 별도 script에서 fresh, 0002→0003, 0003→0002→0003,
  offline SQL, app-role 경로를 실행한다.

## 6. 백엔드 구조와 transaction

다음 모듈 경계를 사용한다.

- `backend/app/domains/staff/schemas.py`: 요청·응답 named model
- `backend/app/domains/staff/policies.py`: 주민번호·전화 업무검증과 mask
- `backend/app/domains/staff/crypto.py`: AES-GCM/HMAC와 keyring 검증
- `backend/app/domains/staff/repository.py`: SQLAlchemy 조회·쓰기, `commit()` 금지
- `backend/app/domains/staff/service.py`: transaction 소유, 오류 매핑, audit/access
- `backend/app/api/staff.py`: `/api/v1` route와 dependency 조합

service만 transaction 경계를 소유한다. repository는 flush할 수 있지만 commit하지
않는다. constraint/driver 예외 전문, DSN, 주민번호와 PIN은 로그나 응답에 남기지
않는다.

### 6.1 경로·envelope·type 소유권

| 범위 | 경로 | 성공·오류 계약 | TypeScript 소유권 |
|---|---|---|---|
| 기존 Wave 0 인증·health | 기존 `/api/auth/**`, `/health/live`, `/health/ready` 유지 | 기존 response 및 FastAPI `detail` 유지 | 기존 `frontend/src/services/api.ts` 수동 타입 유지 |
| W1A 직원 | `/api/v1/staff/**` | named success와 `error.code`, `error.message`, `field_errors`, `details`, `request_id` | 생성 파일과 그 파생 adapter |

- request ID middleware는 모든 요청에 ID와 `X-Request-ID` header만 부여하고 body를
  바꾸지 않는다. W1A staff service/route에서 발생한 domain 오류만 새 named
  exception mapper로 변환하며 기존 auth의 status·body·cookie/CSRF 계약을 바꾸지
  않는다.
- 생성 타입은 `frontend/src/generated/sswcenter-api.ts` 하나가 소유하며 직접
  수정하지 않는다. 기존 auth 타입은 이 slice에서 생성 타입으로 옮기지 않는다.
- W1A API client가 수동 직원 DTO를 새로 만들 수 없도록 lint/contract test한다.
- Wave 0 auth·health·bootstrap test를 회귀 gate로 유지한다.

### 6.2 command API

API는 다음과 같다.

- `POST /api/v1/staff`
  - 직원+민감행+최초 재직+선택 초기 직종/역할 원자 생성, 201
- `GET /api/v1/staff`
  - 검색·페이지·결정적 정렬, 200
- `GET /api/v1/staff/{staff_id}`
  - 직원, masked identity, 전체 재직, 별도 직종/역할, 200
- `PATCH /api/v1/staff/{staff_id}`
  - `expected_staff_row_version`으로 `name`, `phone`, `address`, `display_name`,
    `memo`만 수정, 200. `birth_date`, `sex_code`, 주민번호 field는 허용하지 않는다.
- `POST /api/v1/staff/{staff_id}/employments`
  - `expected_staff_row_version`을 검사하고 재입사·새 재직번호를 원자 생성, 201
- `POST /api/v1/staff/{staff_id}/employments/{employment_id}/close`
  - `end_date`, `end_reason_code`, `expected_employment_row_version`,
    열린 직종·역할별 expected version을 받는다.
  - 열린 자식기간을 같은 `end_date`로 닫고 부모를 닫는 단일 transaction이다.
    하나라도 version 불일치·기간 위반이면 아무 행도 바꾸지 않고 409다.
- `POST /api/v1/staff/{staff_id}/employments/{employment_id}/replacements`
  - 잘못 기록된 재직기간을 정정한다. old row를 무효화하고 replacement row를
    만들며 자식 replacement 전체를 같은 transaction에서 처리한다.
- `POST /api/v1/staff/{staff_id}/employments/{employment_id}/positions`
  - `expected_employment_row_version`을 검사하고 직종기간 생성, 201
- `POST /api/v1/staff/{staff_id}/employments/{employment_id}/positions/{period_id}/close`
  - expected period version으로 최초 종료, 200
- `POST /api/v1/staff/{staff_id}/employments/{employment_id}/positions/{period_id}/replacements`
  - old 직종기간 무효화+replacement 생성, 201
- `POST /api/v1/staff/{staff_id}/employments/{employment_id}/operational-roles`
  - `expected_employment_row_version`을 검사하고 역할기간 생성, 201
- `POST /api/v1/staff/{staff_id}/employments/{employment_id}/operational-roles/{period_id}/close`
  - expected period version으로 최초 종료, 200
- `POST /api/v1/staff/{staff_id}/employments/{employment_id}/operational-roles/{period_id}/replacements`
  - old 역할기간 무효화+replacement 생성, 201
- `POST /api/v1/staff/{staff_id}/sensitive-identity/reveal`
  - ADMIN·`STAFF_MANAGE` current-PIN step-up, 200 + no-store

모든 기존행 mutation은 request의 expected `row_version`과 잠근 현재값을 비교한다.
최초 종료는 현재 row의 `end_date`와 actor/time/version만 바꾸며, 이미 확정된 값을
고치는 정정은 원행을 `invalidated_at_utc` 처리하고 replacement를 새로 만든다.
모든 생성·종료·정정은 current account를 actor로 기록하고 `audit_event`를 같은
transaction에 기록한다. service는 command 전체에서 한 번만 commit하며 어느 자식
처리라도 실패하면 전체 rollback한다.

`GET /api/v1/session-capabilities`는 현재 session에 대해
`staff.view`, `staff.manage`, `staff.sensitive_identity.reveal` boolean만
반환한다. ADMIN bypass도 이 응답에 계산되어 나타난다. 응답은
`Cache-Control: no-store`이며 TanStack Query, browser storage, service worker에
cache하지 않는다. UI는 Staff workspace 진입·window focus마다 새로 조회하고
component unmount·login·logout 때 메모리 값을 폐기한다. mutation 403을 받으면
즉시 capability를 재조회해 control을 갱신한다. 이 응답은 UI control을 위한 것이고
직접 API 호출의 backend permission 검사를 대체하지 않는다. 기존 `/api/auth/me`
body는 변경하지 않는다.

code 경계는 다음과 같이 봉인한다.

- `position_code`의 DB check와 create/replacement request enum은 기존 exact 다섯 값
  `CARE_WORKER`, `SOCIAL_WORKER`, `MANAGER`, `NURSE`, `OTHER`다.
- 정본에 업무역할 catalog가 아직 없으므로 `role_code`는 이번 slice에서 enum이나
  새 catalog를 발명하지 않는다. 기존 `MANAGEMENT_FUNCTION`은 유지하고 API는
  trim·uppercase된 `^[A-Z][A-Z0-9_]{0,49}$` code를 받는다. UI는 code를 표시·입력할
  수 있지만 label catalog를 주장하지 않는다. DB에는 API와 같은 형식의 exact
  `ck_staff_operational_role_period_role_code_format` CHECK를 둔다. catalog 확정은
  W1A 후속 micro-slice다.
- `staff.sex_code` DB exact CHECK는 `ck_staff_sex_code`이며
  `MALE`, `FEMALE`, 합성 회귀 전용 `TEST`만 허용한다.
- 일반 직원 create request의 `sex_code` enum은 `MALE`, `FEMALE`다. 기존
  `/api/auth/bootstrap`은 Wave 0 합성 test를 보존하기 위해
  `MALE`, `FEMALE`, `TEST` named enum을 사용하되 `TEST`는 development/test
  환경에서만 허용하고 운영에서는 422로 거부한다. 일반 W1A API는 `TEST`를
  생성하지 않는다.

성공·오류는 모두 named model이다. 오류 envelope는 `error.code`, 한국어
`error.message`, `field_errors`, `details`, `request_id`를 갖는다.

최소 안정 오류코드는 다음과 같다.

- `STAFF_EMPLOYMENT_PERIOD_CONFLICT` 409
- `STAFF_PERIOD_OUTSIDE_EMPLOYMENT` 409
- `ROW_VERSION_CONFLICT` 409
- `RESIDENT_NUMBER_DUPLICATE` 409
- `RESIDENT_NUMBER_INVALID` 422
- `PHONE_NUMBER_INVALID` 422
- `CURRENT_PIN_INVALID` 422
- `ACCOUNT_LOCKED` 423
- `SENSITIVE_IDENTITY_DECRYPTION_FAILED` 500
- `STAFF_NOT_FOUND` 404
- `PERMISSION_REQUIRED` 403
- `UNEXPECTED_SERVER_ERROR` 500

## 7. OpenAPI와 생성 TypeScript

FastAPI OpenAPI를 유일한 기술 원본으로 사용한다.

- 직원, 민감 mask, 재직, 직종기간, 업무역할기간, page, 오류를 별도 named
  schema로 만든다.
- 일반 schema 어디에도 평문 주민번호, ciphertext, nonce, HMAC, key version,
  legacy key, `phone_normalized` property가 없어야 한다.
- reveal의 평문은 전용 response schema에만 존재하며 operation은 POST로 분리한다.
- backend schema를 임시 파일에 생성하고 `openapi-typescript`로 TypeScript를
  재생성하는 script를 추가한다.
- 생성 결과를 checked-in 파일과 UTF-8/LF 기준으로 비교하는 check mode를 둔다.
- 생성 파일에는 generated header를 두고 직접 수정하지 않는다.
- UI request/response 타입은 생성 타입에서 파생한다.

## 8. UI 계획

현재 정적 placeholder인 `StaffPage`를 실제 목록+상세 workspace로 교체한다.

- 직원 이름을 활성 control로 표시하고 선택하면 같은 작업영역의 detail만 바꾼다.
- 목록 component는 unmount하지 않으며 검색·정렬·페이지·선택 상태를 URL/query
  state로 유지한다.
- 이름 클릭에 `window.open`을 연결하지 않는다.
- 목록에는 이름, 현재 재직번호/상태, 현재 직종, 현재 역할 요약, 표시용 전화만
  노출한다.
- 상세에는 기본정보, masked 주민번호, 최초·과거 재직, 직종기간, 역할기간을
  서로 분리해 표시한다.
- 신규 직원 등록, 재직 종료, 재입사, 직종/역할 추가에 명시적 저장 버튼과
  중복 제출 방지를 둔다.
- 서버 성공 전에 최종 저장처럼 표시하지 않는다.
- 409에서는 작성값을 보존하고 최신값 재조회 안내를 제공한다.
- 422 field error를 해당 입력에 연결한다.
- 권한 없는 mutation/reveal control은 숨기되 백엔드 검사에 의존한다.
- reveal dialog는 경고와 현재 PIN을 요구하고, 응답을 cache/URL/form default에
  저장하지 않으며 닫을 때 즉시 폐기한다.
- legacy key, 평문 주민번호, 별도 근무상태, 미래 일정 action은 DOM에 없다.

민감정보 artifact 계약은 다음과 같다.

- backend `SensitiveDataFilter`가 key 이름뿐 아니라 하이픈 유무 주민번호 패턴,
  `resident_number`, `current_pin`, cipher/nonce/HMAC field를 redact한다.
- request validation, exception mapper, SQLAlchemy/driver 예외, test reporter 어디에도
  request body나 raw constraint/parameter 전문을 그대로 기록하지 않는다.
- 주민번호와 PIN을 다루는 Playwright project는 `trace: off`, `video: off`,
  `screenshot: off`로 실행한다. 민감 값을 입력하기 전후의 일반 UI만 별도 비민감
  test에서 캡처할 수 있다.
- DOM test와 E2E failure reporter는 입력값 대신 synthetic case ID만 출력한다.
- redaction unit test와 의도적 API/E2E 실패 뒤 workspace·Playwright output·PG log의
  13자리 및 하이픈 주민번호 검색 0건을 gate로 둔다.

## 9. test-first 실행 순서

이 절은 구현 전 RED를 만들 당시의 승인 순서를 기록한다. 당시 마르코 PASS
또는 REQUIRED_CHANGES 반영 완료 전에는 아래 테스트나 제품 코드를 작성하지
않았다. 현재는 RED-only commit 뒤 구현 보정·반대심사 단계다.

### 9.1 Codex 본진 RED 테스트 작성

Codex 본진이 구현 전에 다음 test-only 파일을 먼저 작성한다.

- `backend/tests/test_w1a_staff_semantics.py`
- `backend/tests/test_w1a_staff_absence_contract.py`
- `backend/tests/test_w1a_staff_openapi_contract.py`
- `backend/tests/test_w1a_staff_postgres.py`
- `backend/tests/test_w1a_staff_api.py`
- `frontend/src/test/W1AStaffPage.test.tsx`
- `frontend/e2e/w1a-staff-real-pg.spec.ts`
- 실행 전용 `scripts/generate-openapi-types.ps1`
- 실행 전용 `scripts/test-w1a-vs1-postgres.ps1`
- 실행 전용 `scripts/test-w1a-vs1-red.ps1`

1. `SEM/ABS/OA`
   - PK/재직번호, 직종/역할 분리
   - 금지 legacy/근무상태/평문 주민번호 property 부재
   - `display_name`·`memo` 보존
   - 전화 허용/거부 표
   - 주민번호 형식·달력·세기·성별과 checksum-only 비거부
2. 실제 `PG`
   - 직원+민감행+최초 재직 원자성
   - 중복 재직, 종료 후 재입사, 동시 재입사 번호 경쟁
   - 직종/역할 containment와 reverse guard
   - 부모·자식 동시 정정 성공
   - 전화 projection
   - 민감행 0..1, 길이, unique, nonce/ciphertext, AAD 이동실패
   - 중복 HMAC race 1 success
   - 평문 컬럼·값 0건
3. `API`
   - auth, `STAFF_VIEW`/`STAFF_MANAGE`/ADMIN permission, CSRF, version
   - create/list/detail/general-info update/rehire/end/position/role
   - 201/200/403/404/409/422 envelope와 결정적 정렬
   - legacy·암호재료·전화 projection 비노출
   - 일반 mask
   - ADMIN·`STAFF_MANAGE` 신규등록·reveal 동등 허용, `STAFF_VIEW`와 일반 USER 거부
   - reveal current PIN, no-store, event 정확히 1건
4. `OpenAPI generation`
   - named model과 금지 property 부재
   - temp 재생성 결과와 checked-in 파일 일치
5. `DOM`
   - 목록 유지형 상세, popup 0건
   - 재직/직종/역할 분리, masked identity, 권한·오류 상태
6. 실제 `PG E2E`
   - 등록+최초 재직
   - mask 확인
   - 재직 종료
   - 같은 직원 재입사
   - 직원 ID 유지와 새 재직 ID/번호
   - 목록 복귀 문맥 유지와 popup 0
   - ADMIN·`STAFF_MANAGE` reveal과 평문 폐기
   - 종료 postcheck

RED 실행은 “테스트 자체 오류”가 아니라 미구현 계약 때문에 실패해야 한다. Codex는
각 command, exit code, 핵심 failure를 확인한 뒤에만 구현 전환을 승인한다.

RED 명령과 최초 기대실패는 exact 다음과 같다.

| 순서 | 작업경로·명령 | 최초 기대실패 |
|---:|---|---|
| 1 | `backend`; `.venv\Scripts\python.exe -m pytest -q tests/test_w1a_staff_semantics.py tests/test_w1a_staff_absence_contract.py tests/test_w1a_staff_openapi_contract.py` | 민감행/model·`/api/v1/staff` OpenAPI·금지/필수 계약 미구현 assertion |
| 2 | repository root; `powershell -NoProfile -File scripts/test-w1a-vs1-postgres.ps1 -RedOnly` | revision/table/trigger/app-role 계약 미구현 assertion |
| 3 | `backend`; `.venv\Scripts\python.exe -m pytest -q tests/test_w1a_staff_api.py` | 직원 route가 404이고 named envelope가 없어 contract assertion 실패 |
| 4 | repository root; `powershell -NoProfile -File scripts/generate-openapi-types.ps1 -Check` | checked-in W1A schema 부재/drift |
| 5 | `frontend`; `npm.cmd exec vitest -- run src/test/W1AStaffPage.test.tsx --environment jsdom` | 정적 placeholder가 목록유지형 상세·form·권한·오류 DOM 계약을 만족하지 못함 |
| 6 | repository root; `powershell -NoProfile -File scripts/test-w1a-vs1-postgres.ps1 -E2ERedOnly` | 실제 PG의 직원 API/UI flow 미구현으로 Playwright contract 실패 |

- 각 test는 수집·fixture 시작에 성공한 뒤 named assertion에서 실패해야 한다.
  syntax/import/config/port 충돌/도구 부재는 RED 증거가 아니라 test 결함이다.
- `review/evidence/w1a-vs1/RED.md`에 기준 SHA, UTC/KST 시각, exact command,
  exit code, 최초 failing test 이름과 민감값을 제거한 핵심 failure를 기록한다.
- RED 단계에는 위 test·test harness·증거와 승인된 계획/검토 기록만 존재해야 하며
  migration, domain, route, generated type, 제품 UI 구현을 포함하지 않는다.
- Codex가 tree와 증거를 대조한 뒤
  `test(w1a): define staff vertical slice RED contracts`라는 RED-only commit을
  만들고 SHA를 기록한다. 그 commit 이전 또는 같은 commit에 제품 구현을 넣지 않는다.

### 9.2 구현 순서

RED 확인 뒤 Codex 본진이 아래 계층 순서를 관리하고, 각 구현 작업방은 배정된
계층과 파일만 구현한다.

1. DB: migration → SQLAlchemy model → 실제 PG 제약/동시성/rollback
2. API: policies/crypto → repository → service transaction → route/error
3. OpenAPI: named schema와 contract test
4. 생성 TypeScript: temp generation → checked-in update → drift check
5. UI: generated type 기반 client → 목록/상세/forms/reveal
6. 실제 PG E2E와 postcheck

다음 계층으로 이동할 때 바로 앞 계층의 관련 테스트가 GREEN이어야 한다.

## 10. 검증 명령과 증거

정확한 명령은 구현 시 repository script와 test selector에 맞춰 기록하되, 최소
증거는 다음을 포함한다.

- backend lint/type/unit/API/OA/ABS
- 임시 PostgreSQL fresh/upgrade/downgrade/re-upgrade/offline SQL
- application role constraint/concurrency/rollback
- frontend unit/DOM/lint/build
- OpenAPI→TypeScript 독립 재생성 diff 0
- 실제 임시 PostgreSQL+API+브라우저 E2E
- 1440×1000, 1440×900, 1366×768 overflow/민감정보 검사
- Wave 0 회귀 테스트
- 합성자료·안전한 임시 경로 검사
- exact implementation SHA와 clean tree

각 증거에는 commit SHA, 실행시각, 명령, exit code, 요약을 기록한다. screenshot만,
mock-only 브라우저, SQLite/in-memory 대체는 PASS 증거가 아니다.

`W1A-VS1`에서는 §14의 전체 W1A catalog/license/training 및 W1D, Wave 1 전체
backup/restore 통합 gate를 완료했다고 주장하지 않는다. 다만 이 slice가 변경한
직원 identity·재직·전화·mask와 `display_name`·`memo`에 대한 restore postcheck
확장 가능성을 막지 않고, W1F 통합 시 검증할 항목을 추적한다.

## 11. 현재 단계 담당·파일 소유권

아래는 `c4ee9f1420e0c9d3d97f01fc835c7d9495974008` 기준 W1A 검증 단계의
활성 배정이다. 고정 팀을 구성하지 않고 독립 작업조각이 있는 역할만
투입한다. 정확한 작업방·완료조건은
`review/packets/W1A_INTERNAL_VALIDATION_ASSIGNMENT_v2.2.md`에 기록한다.

### 김부장 — Codex 본진

- 모델: `gpt-5.6-sol / max`
- 담당: 배정표, 파일 충돌 통제, Git·worktree·환경·PostgreSQL 통합,
  전체 증거 취합, 최종 runtime 확인, 수용·기각·재작업·완료 판정
- 직접 수정 허용: 기계적 통합, Git·DB·환경·migration 통합, 아주 작은 수정,
  긴급 장애와 최종 연결 작업
- 금지: 루나에게 배정 가능한 기능·검증 전체를 본진이 독점

### 김루나

- 모델: Luna Max
- 범위: backend·API·DB·service logic과 관련 unit/static 검사
- 우선 검토: migration, error mapper, RRN policy, staff service transaction
- 다른 루나의 frontend·독립 검증 파일을 동시에 수정하지 않는다.

### 박루나

- 모델: Luna Max
- 범위: frontend·화면·상태관리·API adapter와 frontend unit/build
- 우선 검토: AuthProvider, StaffPage, staffApi, 지연 응답과 account switch
- backend·PostgreSQL 검증 파일을 동시에 수정하지 않는다.

### 이루나

- 모델: Luna Max
- 범위: test·권한·동시성·데이터 정합성 검증
- 우선 검토: backend 전체, OpenAPI drift, PostgreSQL actor/time/counter/
  replacement/audit rollback, omission 422
- 제품 결함을 발견하면 재현 증거와 담당 파일을 김부장에게 반환한다.

### 송루나

- 모델: Luna Max
- 범위: 회귀·UI 동작·민감정보·로그·누출 검증
- 우선 검토: RRN 공통 벡터, tracked/staged/unstaged/untracked scan,
  gzip/text fail-closed, negative leak self-test, 3-viewports Playwright
- 제품 결함을 발견하면 재현 증거와 담당 파일을 김부장에게 반환한다.

### 요셉

- 모델: SOL xhigh
- 현재 배정: `N/A`
- 호출조건: 내부 검증에서 새 DB·transaction 설계 선택이 발생하거나 루나들이
  두 차례 이상 해결하지 못한 핵심 난제가 생긴 경우

### 마르코

- 모델: SOL xhigh
- 현재 배정: 내부 검증 결과가 나온 뒤 고위험 차단 결함의 유효성·심각도를
  판정하는 임시 독립 검증
- 직접 제품 수정과 상시 검수단계는 금지

### 오푸스

- 모델: Claude Code High
- 현재 배정: 내부 검증과 필요시 마르코 의견 뒤 외부 독립감리 후보
- 같은 W1A 결과의 구현과 최종감리를 모두 맡기지 않는다.

### AGY

- 모델: Flash High
- 현재 배정: `N/A`
- 대량 반복 테스트·로그 수집·증거정리가 별도 작업조각으로 확정될 때만 투입

## 12. 단계별 배정·독립 작업방 전달 규칙

- 실제 담당과 모델은 사용자 최신 지시와
  `docs/AI_업무분담_운영규정_v2.32.md`를 적용한다.
- 김부장은 전체 대화가 아니라 역할별 목표·기준 SHA·파일 경계·완료조건·
  필수검증·반환형식을 전달한다.
- 1차 내부검증은 김루나·박루나·이루나·송루나의 비중복 범위로 진행한다.
- 결함은 김부장이 중복 여부와 소유 파일을 판정한 뒤 해당 구현 담당자에게
  돌려보낸다.
- 새 고난도 설계가 필요할 때만 요셉을 호출한다.
- 고위험 결함 판정이 어렵거나 내부 의견이 충돌할 때만 마르코를 호출한다.
- 외부 독립성이 필요하거나 내부에서 두 차례 해결하지 못한 경우 오푸스를
  구현 또는 감리 중 하나로 호출한다.
- 반복량이 많은 독립 작업만 AGY에 배정하고 Codex 측이 결과를 표본검수한다.
- 과거 요셉·마르코·Opus 보고서는 회귀 증거일 뿐 현재 고정 라운드가 아니다.

## 13. 단계 완료조건

Codex는 아래를 모두 확인해야 `W1A-VS1`만 완료로 판정한다.

1. 역사적 요셉·마르코 계획 검토와 RED-only commit이 구현보다 먼저 존재한다.
2. `c4ee9f1`의 실제 diff가 역할별로 검토되고 변경 파일과 위험이 설명됐다.
3. 김루나·박루나·이루나·송루나의 배정 범위에 실제 실행 증거가 있다.
4. 발견된 구현 결함이 원래 담당자에게 반환되어 보정·재검증됐다.
5. DB→API→OpenAPI→생성 TypeScript→UI 순서와 각 계층 GREEN 증거가 있다.
6. 실제 PostgreSQL에서 원자성·기간·동시성·AAD·평문 부재가 검증됐다.
7. 실제 브라우저에서 등록→종료→재입사→목록 문맥 유지와 reveal이 검증됐다.
8. OpenAPI 재생성 diff가 0이고 lint·format·type·build가 모두 통과한다.
9. Wave 0 회귀가 없다.
10. 합성자료만 사용했고 exact SHA에서 전체 필수 테스트가 PASS하며 tree가 clean하다.
11. W1A의 권한·개인정보·동시성·migration 위험에 대해 필요시 마르코의
    독립 검증의견과 오푸스 외부감리 결과를 확보했다.
12. 김부장이 요구사항·diff·전체 테스트·독립 검증을 최종심사해 승인했다.
13. W1A 후속 micro-slice, Wave 2+, 파일함·OCR 정책을 이번 결과로 확정하지 않았다.

## 14. 요셉 1차 검토 처리

상세 원문은 `review/reports/w1a-vs1-joseph-round1.md`에 기록했다.

| finding | Codex 처리 | 상태 |
|---|---|---|
| F01 권한정책 | §4의 owner 확정 action matrix와 별도 결정기록에 반영 | 해결 |
| F02 종료·정정 | §6.2에 재직·직종·역할 close/replacement, expected version, atomic child close, audit/rollback 확정 | 반영 |
| F03 reveal | §3.5에 현재계정·실패잠금·decrypt·audit commit-before-response 확정 | 반영 |
| F04 민감 artifact | §8에 log redaction, Playwright artifact off, 유출검색 test 확정 | 반영 |
| F05 API 공존 | §6.1에 경로·envelope·type ownership과 Wave 0 보존범위 확정 | 반영 |
| F06 capability | §6.2에 owner 권한표 기반 session-capabilities와 cache/backend 검사 확정 | 해결 |
| F07 PG harness | §5에 exact W1 postcheck, app-role allowed/denied, revision-aware restore 확정 | 반영 |
| F08 code 경계 | §6.2에 직종 enum, role code 비-catalog 경계, 합성 `TEST` 경계 확정 | 반영 |
| F09 기존 0-row | §2.2에서 사후 주민번호 추가 API/UI를 명시적 제외 | 반영 |
| F10 RED 재현 | §9.1에 exact 파일·명령·expected failure·증거·RED-only commit 확정 | 반영 |

요셉은 위 반영내용과 기각근거·새 문제만 2차 검토한다. 요셉 2차 검토 전에는
마르코에게 넘기지 않는다.

## 15. 요셉 2차 검토 처리

상세 원문은 `review/reports/w1a-vs1-joseph-round2.md`에 기록했다. 운영규정상 요셉
검토는 최대 2라운드이므로 아래 필수수정을 반영한 최종안을 마르코에게 넘긴다.

| finding | Codex 최종 처리 | 상태 |
|---|---|---|
| F05 / R2-N01 health | §6.1을 실제 `/health/live`, `/health/ready` exact 경로로 수정 | 해결 |
| F06 / R2-N02 capability | version 없는 cache를 제거하고 no-store·진입/focus 재조회·403 갱신으로 수정 | 해결 |
| F07 / R2-N03 app role | exact `erp_owner`/`erp_app`/`erp_backup`과 app-layer crypto에 필요한 민감 DML 허용·DELETE/DDL 거부표로 수정 | 해결 |
| F08 role/sex | API와 같은 role regex DB CHECK, `MALE/FEMALE/TEST` DB CHECK와 환경별 bootstrap 경계 확정 | 해결 |

## 16. 최종 판정 시 경계와 후속 범위

1. 원격 WIP `c4ee9f1`의 보정은 역할별 검토·원 소유자 수정·교차검증을 거쳐
   최종 구현 SHA `55130af1dc3244c391bca11471323e6b22061c3f`에 반영됐다.
2. 인증 취소·RRN 판별·leak gate·PostgreSQL rollback은 전체 회귀,
   실제 PostgreSQL, 3-viewports Playwright와 artifact 포함 누출검사에서
   재검증됐다.
3. 과거 `W1A_MARCO_*`·`W1A_OPUS_*` 패킷의 역할배정은 역사 기록이며 현재
   담당자를 정하는 자료로 사용하면 안 된다.
4. URL 검색·정렬·pagination·현재 직종/역할·누락 command UI는 이번
   `W1A-VS1` 밖의 후속 제품 범위다.
5. 이번 판정은 `W1A-VS1` 완료만 뜻하며 W1A 전체 catalog·license·training,
   W1B 이후 범위나 Wave 2를 완료했다고 주장하지 않는다.

현재 `W1A-VS1`의 차단 결함은 없다.

## 17. 역사적 마르코 RED 진입 심사

상세 원문은 `review/reports/w1a-vs1-marco-final.md`에 기록했다.

- 판정: `PASS`
- 요셉 1차 F01~F10: 모두 해결
- 요셉 2차 필수수정: 모두 해결
- 추가 사용자 결정: 없음
- 당시 다음 허용 단계: RED 테스트·harness·증거 작성
- 현재 운영 전환 뒤 의미: RED-only commit 전 계획 승인 기록이며 현재 구현
  결과의 승인이나 최종심사를 대신하지 않음
- 아직 금지되는 단계: RED 실패와 증거를 Codex가 확인하기 전 제품 구현

## 18. 현재 구현 보정 심사

아래 Opus 구현·마르코 심사 기록은 2026-07-27 조직재편 전의 역사적 실행
기록이다. 이후 배정은 §20을 적용한다.

- Opus 1차 구현: 전용 worktree WIP, 세션 한도 뒤 재개 필요
- 마르코 1차 반대심사: `REQUIRED_CHANGES`
  (`review/reports/w1a-vs1-marco-opus-round1.md`)
- Opus 지적 보정: 03:50 `--effort high` 재개에서 부분 보정 후 새 세션 한도로
  중단한 뒤 08:50에 재개해 M1~M9를 보정하고 전체 GREEN 증거 제출
  (`review/packets/W1A_OPUS_ROUND1_RETURN_PACKET.md`)
- 마르코 2차 반대심사: `REQUIRED_CHANGES`
  (`review/reports/w1a-vs1-marco-opus-round2.md`)
- Opus 2차 지적 보정: 09:52 세션 한도로 부분 중단. 체크포인트와 현재
  leak gate 실패를 반환 패킷 §7에 기록했고 13:50 재개 대기
  (`review/packets/W1A_OPUS_ROUND2_RETURN_PACKET.md`)
- Codex 본진 최종심사·승인: `PASS`
  (`55130af1dc3244c391bca11471323e6b22061c3f`,
  `review/evidence/w1a-vs1/GREEN.md`)

## 19. 폐기된 과거 역할 교체 결정

아래 결정은 당시 실행이력을 설명하기 위해서만 보존한다.
`docs/AI_업무분담_운영규정_v2.2.md` 시행으로 현재 역할배정 효력을 잃었다.

- 마르코(`gpt-5.6-sol / max`): 최고난도 설계·구현·자기 범위 테스트 담당
- Opus(`claude --model opus --effort high`): 구현 결과의 독립 반대심사·레드팀
  담당. 원칙적으로 제품 코드와 테스트를 수정하지 않는다.
- Codex 본진: 배정·통합·전체 검증·최종심사 담당
- 기존 W1A Opus 구현 기록과 실제 WIP는 보존하고, 영구 교체 이후의 보정·구현
  소유권만 기존 마르코 작업방으로 이전한다. 마르코는 Opus WIP를 그대로
  이어서 작업하며 처음부터 재작성하지 않는다.
- Opus 심사와 마르코 보정은 최대 2라운드로 운영한다.

이 목록은 현재 작업지시로 사용하지 않는다.

## 20. 2026-07-27 최신 조직재편 적용

현재 W1A는 다음 원칙으로 진행한다.

- 김부장(Codex 본진 / SOL Max): 단일 창구, 분배, Git·DB·환경·통합,
  증거 취합, 최종판정
- 김루나(Luna Max): backend·API·DB·service logic
- 박루나(Luna Max): frontend·화면·상태관리
- 이루나(Luna Max): test·권한·동시성·데이터 정합성
- 송루나(Luna Max): 회귀·UI·민감정보·로그·누출
- 요셉(SOL xhigh): 새 고난도 설계가 필요할 때만 임시 호출
- 마르코(SOL xhigh): 고위험 결함판정이 필요할 때만 임시 독립검증
- 오푸스(Claude Code High): 가장 어려운 독립 구현 또는 외부감리
- AGY(Flash High): 반복량이 많은 저위험 실무와 증거정리

고정 1팀·2팀, 요셉팀·마르코팀 상시운영, `요한` 명칭과 이 배정에 충돌하는
과거 규칙은 폐기한다.

## 21. W1A-VS1 최종 완료판정

- 판정일: 2026-07-27 KST
- 최종 구현 SHA: `55130af1dc3244c391bca11471323e6b22061c3f`
- 담당별 최종판정: 김루나·박루나·이루나·송루나 `PASS`
- 김부장 최종판정: `PASS`
- backend: Ruff format/check, mypy, 51 passed / 12 skipped
- frontend: 9 files / 54 tests, lint, production build
- OpenAPI: checked-in TypeScript drift 0
- PostgreSQL: fresh/upgrade/downgrade/re-upgrade/offline SQL, 권한·동시성·
  rollback·backup postcheck `PASS`
- 브라우저: 1440×1000, 1440×900, 1366×768, workers=1, 3/3 `PASS`
- artifact: 두 manifest, 7개 파일 hash 검증, temp manifest 0
- 누출검사: self-test와 artifact 포함 247 files `GREEN`
- 종료검사: PostgreSQL test port와 FastAPI test port listener 0

정확한 명령과 증거는 `review/evidence/w1a-vs1/GREEN.md`를 따른다.
