# W1A-VS6 assignment packet — 직원 legacy mapping·합성 one-off 이관

상태: 구현 전 RED 전용

## 기준

- 저장소: `C:\project sswcenter\sswcenter ver2.1\sswcenter-ver-2.1-office`
- branch/base: `wip/w1a-office-handoff` / `6db858ac687f6db183a3a4b2b271ad3c0f5ddbb9` (`6db858a`, VS5 frontend 완료 기준)
- 정본: `docs/AI_업무분담_운영규정_v2.32.md`
- 계획: `review/plans/W1A_VS6_STAFF_LEGACY_IMPORT_PLAN.md`
- 담당: 송루나
- 판정자: 김부장(Codex 본진)

## 작업 목적

W1A 잔여 micro-slice의 구현 전 RED를 고정한다. 공개 HTTP/UI 없이 내부 구조화 record인 `staff_legacy_mapping`과 합성 one-off 초기 직원 이관 계약만 다룬다.

## 필수 계약

- Alembic `20260728_0008_w1a_staff_legacy_mapping`, parent `20260728_0007_w1a_staff_quarterly_consultation`
- `erp.staff_legacy_mapping`: bigint PK, source system/key NOT NULL, staff FK, optional source fingerprint, creation/invalidation/replacement audit, active `(source_system_code, legacy_staff_key)` partial unique
- active rerun: `ALREADY_MAPPED`; batch duplicate key: 해당 key 전체 제외 및 `DUPLICATE_SOURCE_KEY`
- prepare 결과: 포함/제외 counts와 stable reason codes만, key/name/PII·원문행 출력 금지
- apply: 포함행 전체 단일 transaction, 한 건 실패 시 0건 rollback
- 기존 resident AES-256-GCM crypto 경로 사용, plaintext 로그/응답/fixture/snapshot 금지
- 기존 `display_name`/`memo` 보존
- one-off input allowlist: legacy key, name, resident number, address, phone, employment start/end, position, licenses 최대 2개(type/number/issued date)
- 금지: alias, employment type/status, account/payroll/insurance/severance, service unit price, unused/old fields, past health, care-change, file/attachment/document/OCR/import-run/staging/filebox
- 일반 license CRUD 3+ 및 public OpenAPI maxItems=2 부재
- 일반 staff API/OpenAPI/UI/search/export에 mapping/legacy key/import route/property 0

## 신규 파일 allowlist

이번 작업에서 쓸 수 있는 파일은 다음뿐이다. 필요하지 않은 optional frontend absence 파일은 만들지 않는다.

1. `review/plans/W1A_VS6_STAFF_LEGACY_IMPORT_PLAN.md`
2. `review/packets/W1A_VS6_ASSIGNMENT_PACKET_v2.32.md`
3. `backend/tests/test_w1a_vs6_semantics.py`
4. `backend/tests/test_w1a_vs6_import_contract.py`
5. `backend/tests/test_w1a_vs6_postgres.py`
6. `backend/tests/test_w1a_vs6_absence_contract.py`
7. `scripts/test-w1a-vs6-postgres.ps1`
8. `review/evidence/w1a-vs6/RED.md`

제품/backend/generated/migration/기존 테스트/기존 프런트엔드/문서 원문은 수정하지 않는다. Git stage/commit/push/pull/reset/rebase/checkout/stash도 실행하지 않는다.

## RED 실행 요구

- missing module/migration은 importlib/spec/file detection과 안정 marker로 보고하여 pytest collection error를 만들지 않는다.
- 첫 제품 marker 권장값: `W1A_VS6_MIGRATION_MISSING`
- fresh isolated PostgreSQL 17에서 0007→0008, downgrade/re-upgrade, offline SQL, ACL, FK, partial unique race, atomic rollback, display_name/memo 및 resident hash 보존, dump/restore/postcheck를 준비한다.
- synthetic values only. 실제 개인정보·비밀·운영 DB·공유 listener를 사용하지 않는다.
- 정상 RED와 harness/environment failure를 구분하고, temp DB/server/listener/artifact/media를 종료·정리한다.
- RED.md에는 기준 SHA, 변경 파일, 명령별 exit/passed/failed/skipped/collection, 첫 marker, cleanup, 남은 위험을 정확히 기록한다.

## 반환 형식

`RED_VALID` 또는 `RED_VALID_PENDING_PRODUCT`만 보고한다. GREEN은 선언하지 않는다. 변경 파일, 실행 명령과 정확한 결과, first marker, 설계상 남은 위험, Git 미실행 및 기존 사용자 변경 보존을 포함한다.
