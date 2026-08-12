# W1A-VS6 직원 legacy mapping·합성 one-off 이관 계획 (구현 전 RED)

상태: `RED_VALID_PENDING_PRODUCT`

## 1. 기준과 소유권

- 기준 브랜치: `wip/w1a-office-handoff`
- 기준 SHA: `6db858ac687f6db183a3a4b2b271ad3c0f5ddbb9` (`6db858a`, VS5 frontend 완료 기준)
- 정본: `docs/AI_업무분담_운영규정_v2.32.md`
- 담당: 송루나 — 구현 전 독립 RED 작성 및 증빙
- 구현자: 김부장 배정 후 별도 지정. 이 문서와 RED 테스트는 구현자가 수정하지 않는다.
- 이번 턴의 신규 파일 allowlist는 assignment packet과 일치한다. 제품 코드, 기존 테스트, 프런트엔드, 문서 원문, migration, Git 상태는 수정하지 않는다.

## 2. 범위와 경계

VS6는 잔여 W1A 운영명이다. 범위는 다음 두 가지뿐이다.

1. `erp.staff_legacy_mapping` 내부 원장
2. 공개 HTTP/API/OpenAPI/UI가 없는 합성 one-off 초기 직원 이관 서비스

이관 입력은 메모리에서만 조립하고, 테스트와 로그·에러·결과에는 합성 표식 외의 개인정보나 비밀을 남기지 않는다. 일반 직원 응답·검색·정렬·export와 공개 OpenAPI에는 legacy key, mapping, import route/property를 넣지 않는다.

## 3. DB 계약

새 Alembic revision은 다음을 만족해야 한다.

- revision `20260728_0008_w1a_staff_legacy_mapping`
- `down_revision = 20260728_0007_w1a_staff_quarterly_consultation`
- additive migration이며 기존 migration을 수정하지 않는다.
- 테이블 `erp.staff_legacy_mapping`
- `id`는 `bigint identity` primary key
- `source_system_code`, `legacy_staff_key`, `staff_id`는 NOT NULL
- `staff_id`는 `erp.staff.id`를 참조하고 `ON DELETE RESTRICT`를 사용한다.
- `source_row_fingerprint`는 선택적 fingerprint 저장 칼럼이며 원문 행이나 PII를 저장하지 않는다.
- 기존 fact ledger와 같은 invalidation/replacement/audit metadata를 갖는다: `invalidated_at_utc`, replacement mapping FK, 생성·수정 actor/time, positive `row_version`.
- 활성 행만 대상으로 `(source_system_code, legacy_staff_key)` partial unique index를 둔다. predicate는 `invalidated_at_utc IS NULL`이다.
- PK/FK/UQ/CK/IX naming은 기술 정본의 접두 규칙을 따른다.
- `erp_app`은 필요한 runtime SELECT/INSERT/UPDATE와 mapping identity sequence만, `erp_backup`은 SELECT만 가진다. runtime role에서 DELETE/TRUNCATE/DDL 권한은 없다.
- `downgrade()`는 0007로 되돌리고 0008 객체·index·권한을 완전히 제거한다. 0007 이하 객체와 자료를 조용히 삭제하지 않는다.

다음 구조는 이번 slice에서 금지한다: `import_run`, `import_row`, staging/filebox/blob/OCR/document/generation/evidence 구조, 파일·첨부 FK, Wave 5 run/file 경로, 공개 import/mapping 테이블.

## 4. 내부 one-off 서비스 계약

구현은 `app.domains.staff.legacy_import`의 `prepare`/`apply` 또는 이름이 명확히 동등한 내부 인터페이스를 제공한다. 이 모듈은 router에 연결하지 않는다.

허용되는 각 행의 입력 필드는 정확히 다음뿐이다.

```text
legacy_staff_key
name
resident_number       # 기존 AES-256-GCM crypto 경로로 즉시 암호화
address
phone
employment_start_date
employment_end_date
position
licenses              # 0..2; type, number, issued_date만
```

별칭, 별도 고용형태/재직상태, 계좌·급여·보험·퇴직금, 서비스 단가, unused old column, 과거검진, care-change, file/document/OCR 값은 입력·DTO·변환·저장하지 않는다. `display_name`과 `memo`가 이미 있는 staff를 갱신하는 경우에도 기존 값을 보존한다.

`prepare`는 값·행·PII를 반환하거나 출력하지 않고 다음 요약만 반환한다.

- 포함 건수와 제외 건수
- 안정적인 reason code별 건수
- optional fingerprint/row identity는 값이 아닌 내부 처리용

필수 reason code 예시는 `ALREADY_MAPPED`, `DUPLICATE_SOURCE_KEY`, `INVALID_REQUIRED_FIELD`, `INVALID_DATE_RANGE`, `TOO_MANY_LICENSES`, `STAFF_MATCH_MISSING`, `STAFF_MATCH_AMBIGUOUS`이다. 이미 활성 mapping이 있는 key는 `ALREADY_MAPPED`로 제외하고, 한 batch 안에서 중복된 `(source_system_code, legacy_staff_key)`는 모호하므로 그 key의 모든 행을 `DUPLICATE_SOURCE_KEY`로 제외한다. reason code는 입력값·legacy key·이름을 포함하지 않는다.

`apply`는 prepare에서 포함된 전체 행을 하나의 DB transaction으로 반영한다. 직원·민감 identity·선택 employment/position/license·mapping·audit 중 하나라도 실패하면 전체 transaction으로 rollback하여 0건이 남아야 한다. 적용 후 재실행은 활성 mapping을 만들지 않고 `ALREADY_MAPPED`를 반환한다. 일반 license CRUD는 3개 이상을 계속 허용하며, `maxItems=2`는 one-off import 입력에만 존재한다.

## 5. 검증 매트릭스

`backend/tests/test_w1a_vs6_semantics.py`는 migration/model/audit/replacement/partial-unique의 정적 계약을 검증한다. 부재 시 collection error 대신 `W1A_VS6_MIGRATION_MISSING` 등 안정 marker로 실패한다.

`backend/tests/test_w1a_vs6_import_contract.py`는 allowlist·금지 필드·요약 only·중복/재실행 reason code·atomic apply·crypto/표시값 보존·공개 surface 미연결을 검증한다. 공개 OpenAPI에 import route가 없음을 별도 확인한다.

`backend/tests/test_w1a_vs6_postgres.py`는 isolated PostgreSQL에서 다음을 검증한다.

- 0007→0008 fresh upgrade, 0008 downgrade/re-upgrade, offline SQL apply
- bigint/NOT NULL/FK/partial unique 및 invalidated replacement
- `erp_app` 최소 권한, `erp_backup` SELECT-only, DDL/DELETE/TRUNCATE 거부
- partial unique 동시 race에서 한 건만 active
- staff FK와 mapping FK 무결성
- 합성 허용 입력, resident crypto 저장 shape, licenses 0/1/2 및 3개 일반 CRUD 분리
- active rerun/배치 duplicate의 counts/reason codes와 값·PII 미출력
- apply 중 한 건 오류의 exact 0-row rollback
- 기존 `display_name`/`memo`와 resident ciphertext/lookup hash 보존
- dump/restore 후 revision·mapping·보존값 postcheck

`backend/tests/test_w1a_vs6_absence_contract.py`는 일반 staff API/OpenAPI/UI/search/export에 legacy surface가 없고, 금지된 Wave 5/import/OCR/file 구조 및 alias/status/payroll 등 입력이 생기지 않았음을 확인한다. 프런트엔드는 read-only로만 검사한다.

## 6. RED 및 실행 게이트

기준 SHA에서 제품 부재의 첫 marker는 `W1A_VS6_MIGRATION_MISSING`이어야 한다. import/환경/하네스 오류를 제품 RED로 기록하지 않는다. 테스트 수집은 0 collection error여야 하며, absence 검사는 migration 부재에서도 실행·통과해야 한다.

실행 명령:

```text
backend\\.venv\\Scripts\\python.exe -m pytest --collect-only -q backend/tests/test_w1a_vs6_semantics.py backend/tests/test_w1a_vs6_import_contract.py backend/tests/test_w1a_vs6_postgres.py backend/tests/test_w1a_vs6_absence_contract.py
backend\\.venv\\Scripts\\python.exe -m pytest -q backend/tests/test_w1a_vs6_semantics.py backend/tests/test_w1a_vs6_import_contract.py backend/tests/test_w1a_vs6_postgres.py backend/tests/test_w1a_vs6_absence_contract.py
backend\\.venv\\Scripts\\python.exe -m ruff format --check <VS6 files>
backend\\.venv\\Scripts\\python.exe -m ruff check <VS6 Python files>
backend\\.venv\\Scripts\\python.exe -m compileall -q <VS6 Python files>
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/test-w1a-vs6-postgres.ps1
```

PowerShell harness는 fresh temporary PostgreSQL 17 cluster만 사용한다. 종료 시 database, role-independent temporary files, offline SQL, backup/restore data, artifact/media/temp directory, process/listener를 정리하고 `*_TEMP_CLUSTER_REMAINING=0`, `*_LISTENER_REMAINING=0`을 출력한다. 구현 전에는 0008 부재를 제품 marker로 기록하고, backend product/PG gate가 없는 경우를 harness failure로 바꾸지 않는다.

## 7. 완료 판정

이 계획의 구현 전 증거는 GREEN이 아니다. 기준 SHA에서 migration 부재 marker가 재현되고 collection/정적 검사/absence/cleanup 결과가 기록되면 `RED_VALID_PENDING_PRODUCT`로 반환한다. 제품 구현 후 김부장이 동일 테스트와 별도 독립 검증을 통해 GREEN을 판정한다.
