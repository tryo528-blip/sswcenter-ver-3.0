# W1A-VS2 공통 서비스·자격증·서비스 제공자격 상세 작업계획

> 문서 상태: `GREEN_SEALED`
>
> 작성일: 2026-07-27 KST
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 기준 commit: `728958d4357b12bf34996ce10221118238b67c20`
>
> 선행 gate: `W1A-VS1 FINAL PASS`
>
> 총괄·최종판정: 김부장(Codex 본진 / SOL Max)
>
> RED 검증 증거: `review/evidence/w1a-vs2/RED.md`
>
> GREEN 검증 증거: `review/evidence/w1a-vs2/GREEN.md`

## 1. 권위와 목표

이 계획은 다음 정본과 gate를 함께 적용한다.

- `docs/02_새프로젝트_기능요구사항_정리본_v1.0.md` §3.3
- `docs/03_기존_UI와_기능요구사항_화면별_변경표_v1.1.md` §3.4·§8~9
- `docs/04_DB_업무구조_최종설계_v4.7_PostgreSQL.md` §2·§3.3~3.5·§8.1·§14
- `docs/05_기술아키텍처_및_개발기준_v1.4.md` §4.8~4.9·§5~8·§14~16
- `docs/07_개발로드맵_및_결정현황_v1.0.md` §2~4
- `review/WAVE1_CLEAN_TEST_MATRIX.md` `W1-CMN-01`~`07`,
  `W1-STF-05`~`06`, `W1-ABS-13`·`15`~`17`
- `docs/AI_업무분담_운영규정_v2.2.md`

`W1A-VS2`의 목표는 W1A가 소유하는 공통 서비스 catalog와 서로 분리된
일반 자격증 사실·서비스 제공자격 기간을 실제 PostgreSQL, API, OpenAPI 생성
타입, React UI, 실제 브라우저까지 한 흐름으로 완성하는 것이다.

`W1A-VS2` 완료는 W1A 전체 완료가 아니다. 교육·건강검진·분기상담·초기 이관과
legacy mapping은 후속 W1A micro-slice에서 별도로 완료한다.

## 2. 범위

### 2.1 포함

1. 공통 서비스 catalog
   - 3개 `service_group`
   - 5개 `service_type`
   - W1A migration이 exact code·표시명을 seed
   - 일반 업무에서 삭제·코드변경 불가
   - W1D가 같은 catalog를 재사용할 수 있는 안정 ID
2. 일반 자격증 사실
   - `license_type`
   - `staff_license`
   - 자격종류·자격번호·발급일
   - 3개 이상 등록
   - 무효화·대체·감사·낙관적 잠금
3. 서비스 제공자격 기간
   - 직원·재직·서비스종류·시작일·선택 종료일
   - 선택적인 같은 직원 `source_license_id`
   - 재직기간 containment와 역방향 guard
   - 같은 직원·서비스종류 기간 중복 차단
   - 무효화·대체·종료·감사·낙관적 잠금
4. API·OpenAPI·생성 TypeScript
   - catalog 조회
   - 자격증과 서비스 제공자격의 서로 다른 named model·route·오류
   - `STAFF_VIEW` 조회와 `STAFF_MANAGE` 변경
5. React UI
   - 직원 상세 안의 `자격증`과 `서비스 제공자격` 별도 탭
   - 목록 문맥과 현재 직원 상세 유지
   - 409·422 구조화 오류와 권한 제어
6. 실제 PostgreSQL·브라우저·backup/restore·부재·누출 검증

### 2.2 제외

- `staff_legacy_mapping`과 초기등록 importer
- 신규·정기교육
- 건강검진 사실·대상상태
- 직원 분기상담
- W1B 수급자 이후 범위
- W1D 계약과 W1E 배정
- W1E `care_assignment` 역방향 guard의 실제 생성
- 자격증 유효 시작일·종료일·만료일
- 자격증 또는 검진 증빙 file FK
- 서비스 catalog 관리 UI·일반 수정 API
- 초기등록 workbook의 자격증 2개 제한을 일반 CRUD에 전파
- 미래 일정·업무카드·실제근무·청구 side effect

## 3. 확정 업무계약

### 3.1 공통 서비스 catalog

| 그룹 코드 | 그룹 표시명 | 서비스 코드 | 서비스 표시명 |
|---|---|---|---|
| `LONG_TERM_CARE` | 장기요양 | `HOME_CARE` | 방문요양 |
| `LONG_TERM_CARE` | 장기요양 | `HOME_BATH` | 방문목욕 |
| `LOCAL_CARE` | 지역돌봄 연계 | `TEMP_HOME_CARE` | 일시재가 |
| `LOCAL_CARE` | 지역돌봄 연계 | `HOSPITAL_ESCORT` | 병원동행 |
| `BARO_CARE` | 바로돌봄 | `BARO_CARE` | 바로돌봄 |

- migration에서 exact 3개 그룹·5개 서비스를 생성한다.
- code는 외부 업무계약이고 내부 bigint ID와 분리한다.
- `service_group`은 `id`, immutable `code`, `display_name`, `active`를 가진다.
- `service_type`은 `id`, `service_group_id`, immutable `code`,
  `display_name`, `active`를 가지며 그룹 code를 중복 저장하지 않는다.
- catalog 조회와 검증은 `service_type.service_group_id`를
  `service_group.id`에 join해 그룹 code를 얻는다.
- W1D는 새 catalog를 만들지 않고 같은 `service_type.id`를 사용한다.
- UI는 code를 임의 번역하지 않고 catalog의 표시명을 사용한다.

### 3.2 일반 자격증

- 일반 자격증 사실과 서비스 제공자격 기간은 서로 다른 원장이다.
- 요청은 `license_type_code`, `license_number`, `issued_date`를 받는다.
- 응답은 안정 `license_id`, 자격종류 code·표시명, 번호, 발급일, version,
  무효화·대체 이력 식별자를 제공한다.
- `license_number`는 공백만 허용하지 않되 번호의 법정 형식이나 checksum을
  새로 발명하지 않는다.
- 유효행의 `(license_type_id, license_number)`는 전역 unique다.
- 같은 직원은 3개 이상 자격증을 등록할 수 있다.
- 무효화는 연결된 서비스 제공자격을 자동종료하지 않는다.
- 정정은 원행을 침묵 수정하지 않고 원행 무효화와 replacement 사실 생성을
  한 transaction에서 처리한다.

### 3.3 서비스 제공자격

- 요청은 `employment_id`, `service_type_code`, `start_date`, 선택 `end_date`,
  선택 `source_license_id`를 받는다.
- source 자격증은 같은 직원의 유효 자격증만 선택할 수 있다.
- source 자격증은 선택 근거이며 제공자격 존재조건이 아니다.
- 자격증만 있는 상태와 자격증 없이 제공자격만 있는 상태를 모두 허용한다.
- 같은 자격증을 재입사 뒤 새 재직의 제공자격 근거로 재사용할 수 있다.
- 기간은 연결 재직 안에 완전히 포함되어야 한다.
- 재직기간 단축·무효화도 유효 제공자격을 orphan으로 만들 수 없다.
- 같은 직원·서비스종류의 유효 제공자격 기간은 겹치지 않는다.
- 제공자격 기간을 자격증 만료기간으로 표현하지 않는다.
- W1E가 아직 없으므로 배정 orphan guard는 만들지 않고 후속 migration에서
  추가할 부재계약만 유지한다.

## 4. DB·migration 계약

새 migration 후보:

`backend/alembic/versions/20260727_0004_w1a_staff_qualifications.py`

원칙:

- 적용된 `0001`~`0003`을 수정하지 않는다.
- `down_revision`은 `20260726_0003_w1a_staff`의 revision ID를 사용한다.
- 다음 테이블을 추가한다.
  - `service_group`
  - `service_type`
  - `license_type`
  - `staff_license`
  - `staff_service_qualification_period`
- exact `pk_`·`fk_`·`uq_`·`ck_`·`ix_`·`ex_`·`fn_`·`ct_` 명명계약을 지킨다.
- catalog 세 테이블은 `id` bigint identity PK, immutable unique `code`,
  `display_name`, `active`를 공통으로 갖는다. `service_type`만
  `service_group_id` FK를 추가하며 `group_code` 중복 컬럼은 만들지 않는다.
- `staff_license`는 `(staff_id, id)` unique를 명시해 same-staff source FK의
  target으로 사용한다.
- active license type+number uniqueness는 무효화행을 제외한다.
- 제공자격은 generated `daterange`와
  `ex_staff_service_qualification_period`를 사용한다.
- `ct_staff_service_qualification_within_employment`와 기존 재직 child reverse
  guard의 새 revision을 `DEFERRABLE INITIALLY DEFERRED`로 만든다.
- 부모·자식을 한 transaction에서 함께 정정한 최종상태는 허용한다.
- `erp_app`은 catalog 세 테이블에 SELECT만, `staff_license`와
  `staff_service_qualification_period`에 SELECT·INSERT·UPDATE만 가진다.
  다섯 테이블 모두 direct DELETE는 금지한다. `erp_backup`에는 SELECT만
  부여한다.
- downgrade/re-upgrade와 offline SQL 적용을 검증한다.
- W1A postcheck와 backup/restore 의미검사를 catalog·license·qualification까지
  확장한다.

## 5. API·OpenAPI 계약

### 5.1 경로

| 메서드 | 경로 | 목적 |
|---|---|---|
| GET | `/api/v1/catalogs/services` | exact 서비스 catalog 조회 |
| GET | `/api/v1/catalogs/license-types` | 활성 자격종류 조회 |
| GET | `/api/v1/staff/{staff_id}/licenses` | 자격증 사실·이력 조회 |
| POST | `/api/v1/staff/{staff_id}/licenses` | 자격증 사실 생성 |
| POST | `/api/v1/staff/{staff_id}/licenses/{license_id}/replacements` | 자격증 정정·대체 |
| POST | `/api/v1/staff/{staff_id}/licenses/{license_id}/invalidate` | 자격증 무효화 |
| GET | `/api/v1/staff/{staff_id}/service-qualifications` | 제공자격 기간·이력 조회 |
| POST | `/api/v1/staff/{staff_id}/service-qualifications` | 제공자격 생성 |
| POST | `/api/v1/staff/{staff_id}/service-qualifications/{qualification_id}/close` | 실제 종료일 기록 |
| POST | `/api/v1/staff/{staff_id}/service-qualifications/{qualification_id}/replacements` | 제공자격 정정·대체 |
| POST | `/api/v1/staff/{staff_id}/service-qualifications/{qualification_id}/invalidate` | 제공자격 무효화 |

### 5.2 권한·동시성

- `ADMIN`, 부여된 `STAFF_VIEW`, 부여된 `STAFF_MANAGE`는 조회할 수 있다.
- `ADMIN`과 부여된 `STAFF_MANAGE`만 변경할 수 있다.
- 미부여 `USER`의 조회·변경은 403이다.
- 모든 mutation은 CSRF와 `expected_row_version`을 검증한다.
- version 충돌은 409 `ROW_VERSION_CONFLICT`이고 사용자 입력을 보존한다.

### 5.3 안정 오류

- `STAFF_NOT_FOUND`
- `STAFF_LICENSE_NOT_FOUND`
- `STAFF_LICENSE_DUPLICATE`
- `LICENSE_TYPE_NOT_FOUND`
- `SERVICE_TYPE_NOT_FOUND`
- `STAFF_SERVICE_QUALIFICATION_NOT_FOUND`
- `STAFF_SERVICE_QUALIFICATION_CONFLICT`
- `STAFF_QUALIFICATION_SOURCE_LICENSE_MISMATCH`
- 기존 `STAFF_PERIOD_OUTSIDE_EMPLOYMENT`
- 기존 `ROW_VERSION_CONFLICT`
- 기존 `VALIDATION_ERROR`

raw constraint명·SQL·DSN·내부 예외는 오류 body와 로그에 노출하지 않는다.

### 5.4 named model·금지필드

- catalog, license, qualification의 request·response·list·error는 모두 named
  OpenAPI model이다.
- license와 qualification model을 합치지 않는다.
- 다음 property는 DB·OpenAPI·생성 TypeScript·DOM에 없어야 한다.
  - license expiry/start/end
  - 일반 CRUD `maxItems=2`
  - qualification의 `license_number`, `issued_date`
  - future schedule/assignment/file FK
  - legacy 직원키
- 생성 TypeScript는 `scripts/generate-openapi-types.ps1`로만 갱신한다.

## 6. UI·DOM 계약

- 기존 직원 목록과 같은-workspace 상세 구조를 유지한다.
- `자격증`과 `서비스 제공자격`을 서로 다른 탭·목록·폼으로 만든다.
- 자격증 폼은 자격종류·자격번호·발급일만 표시한다.
- 제공자격 폼은 재직·서비스종류·시작일·선택 종료일·선택 근거 자격증을
  표시한다.
- 근거 자격증은 현재 직원의 유효 자격증만 선택지에 보인다.
- 제공자격을 등록하기 위해 자격증 등록을 강제하지 않는다.
- 3개 이상의 자격증이 정상 표시·등록된다.
- 권한 없는 사용자는 mutation control을 볼 수 없어야 하고 백엔드도 403으로
  최종 차단한다.
- 409는 최신값 재조회·재적용 안내, 422는 필드와 허용 재직기간을 표시한다.
- 직원 전환·뒤로가기 뒤 검색·정렬·페이지·스크롤·선택 탭 문맥을 보존한다.
- 이름 선택과 탭 동작은 `window.open`을 호출하지 않는다.
- 1440×1000, 1440×900, 1366×768에서 가로 overflow가 없어야 한다.

## 7. RED-first 검증

제품 구현 전에 다음 테스트를 먼저 추가하고 exact named assertion에서
실패시킨다.

후보 파일:

- `backend/tests/test_w1a_vs2_semantics.py`
- `backend/tests/test_w1a_vs2_absence_contract.py`
- `backend/tests/test_w1a_vs2_openapi_contract.py`
- `backend/tests/test_w1a_vs2_api.py`
- `backend/tests/test_w1a_vs2_postgres.py`
- `frontend/src/test/W1AStaffQualifications.test.tsx`
- `frontend/e2e/w1a-staff-qualifications-real-pg.spec.ts`
- `scripts/test-w1a-vs2-postgres.ps1`

RED 필수 관찰:

1. `SEM/ABS` — license와 qualification 분리, 3/5 catalog, 금지필드 부재
2. `PG` — 새 revision 부재 marker, partial unique, overlap, same-staff FK,
   containment/reverse guard, deferrable same-transaction 정정
3. `API` — route/named error/권한/CSRF/version 계약 부재
4. `OA` — named model과 생성 타입 부재 또는 drift
5. `DOM` — 별도 두 탭·폼·3개 이상·오류상태 부재
6. `real PG E2E` — 자격증 3건과 자격증 없는 제공자격, 재입사 source 재사용
   흐름 부재

환경·도구·syntax·import 실패는 RED 증거가 아니다. 구현이 없어서 실패한
named assertion과 `W1A_VS2_*_MISSING` marker만 RED로 인정한다.

## 8. GREEN·완료 gate

같은 exact implementation SHA에서 다음을 모두 통과한다.

1. backend
   - Ruff format check와 lint
   - mypy
   - 전체 pytest
2. frontend
   - 전체 Vitest
   - lint
   - build
3. OpenAPI
   - temp 재생성 후 checked-in TypeScript drift 0
4. PostgreSQL
   - fresh base→head
   - `0003→0004`
   - `0004→0003→0004`
   - offline SQL 생성·빈 DB 적용
   - `erp_app`·`erp_backup` ACL
   - unique·overlap·wrong-staff·containment·reverse guard·rollback·동시성
5. 실제 브라우저
   - workers 1
   - 3 viewport
   - 직원 A 자격증 3건
   - 자격증만 보유
   - 자격증 없이 제공자격
   - 재입사 뒤 같은 source 자격증 재사용
   - 목록 문맥 유지와 popup 0
6. backup/restore
   - exact 3/5 catalog
   - license·qualification count/hash와 FK·constraint postcheck
7. 보안·부재
   - 합성자료만 사용
   - legacy key·평문 주민번호·금지필드가 로그·DOM·trace·artifact에 없음
8. Git
   - 정확한 SHA
   - `git diff --check`
   - clean tree
   - 독립 검증과 김부장 최종판정

## 9. 단계·소유권

### 단계 A — RED 계약

- 이루나: backend SEM/API/OA/PG RED와 PostgreSQL harness
- 송루나: frontend DOM·E2E·ABS·artifact RED
- 수정 가능 범위는 새 테스트·검증 script로 한정한다.
- 두 담당자는 같은 evidence 파일을 동시에 수정하지 않고 결과를 작업방
  최종보고로 반환한다. 김부장이 검증 뒤 `review/evidence/w1a-vs2/RED.md`를
  단독 작성한다.
- 제품 파일은 수정하지 않는다.

### 단계 B — backend·DB 구현

- 김루나: 새 migration, SQLAlchemy model, schema, repository, service, router,
  dependency·postcheck
- 적용된 migration과 frontend 제품 파일은 수정하지 않는다.
- RED 테스트의 업무기대값을 구현 편의로 약화하지 않는다.

### 단계 C — 생성 타입·frontend 구현

- 김부장: backend OpenAPI를 독립 생성해 기술계약과 drift를 확인
- 박루나: 생성 타입 기반 adapter, 직원 상세 두 탭·폼·상태, frontend unit test
- 생성 TypeScript 직접수정과 backend 파일 수정은 금지한다.

### 단계 D — 교차검증·최종판정

- 이루나: migration·DB invariant·권한·동시성·rollback
- 송루나: 실제 UI·목록문맥·민감정보·로그·artifact·3 viewport
- 김부장: diff 통합, 전체 runtime gate, 독립 결과 수용·반려, 최종판정

요셉은 새 고난도 DB 설계쟁점이 생길 때, 마르코는 고위험 결함판정이
애매할 때, 오푸스는 외부 독립감리가 필요할 때만 임시 투입한다. 현재 계획
작성만으로 이들을 자동 호출하지 않는다.

## 10. 사용자 확정 결정

### `OD-W1A-VS2-01` 최초 자격종류 catalog

사용자가 2026-07-27 KST에 최초 exact seed를 다음 3개로 확정했다.

| code | 표시명 |
|---|---|
| `CARE_WORKER` | 요양보호사 |
| `SOCIAL_WORKER` | 사회복지사 |
| `NURSE` | 간호사 |

최초 seed에는 요양보호사·사회복지사의 등급 구분, 간호조무사, 관리책임자,
관리책임자(시설장)를 넣지 않는다. 새 자격종류는 기존 code의 의미를 변경하지
않고 사용자 결정 뒤 새 catalog row로만 추가한다.

## 11. 착수·완료 판정

- 사용자 결정 완료: exact 3종 seed를 기준으로 RED 단계 착수 가능
- RED evidence 봉인 → 구현 → 교차검증 순서로 진행
- 실제 작업방 호출은 별도 사용자 지시나 허용된 전달 절차가 있을 때만 수행
- 실제 코드·diff·PostgreSQL·OpenAPI·브라우저 증거가 모두 없으면 완료 아님
- 2026-07-28 KST 실제 PostgreSQL·OpenAPI·frontend·3 viewport·leak gate와
  cleanup을 모두 통과해 `W1A-VS2 PASS / GREEN_SEALED`로 최종판정
- `W1A-VS2 PASS` 뒤에도 W1A 잔여 micro-slice가 남으므로 W1B 착수 아님
