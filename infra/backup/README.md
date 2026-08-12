# 백업·복원 계약

현재 head revision ``20260806_0015_recipient_status_tag``까지 지원한다.

- `scripts/backup-postgres.ps1`은 PostgreSQL custom-format dump, Alembic revision,
  `blobs/`·`official-documents/` 파일, 개별 파일 hash, 전체 SHA256 목록을 새로운
  디렉터리에 생성한다. `postgres`, `template0`, `template1`은 거부한다.
- `scripts/restore-drill.ps1`은 manifest를 검증하고 이름이 `_review`로 끝나는 새
  데이터베이스와 새 `sswcenter-restore-review-*` 파일 루트에만 복원한다.
  복원된 데이터베이스는 revision별 정확한 postcheck marker
  (예: ``W1E_DB_POSTCHECK_OK``, ``STAFF_CONTINUING_EDUCATION_DB_POSTCHECK_OK``,
  ``RECIPIENT_PLAN_NOTIFICATION_DB_POSTCHECK_OK``,
  ``RECIPIENT_STATUS_TAG_DB_POSTCHECK_OK``)가 출력되어야만 성공으로
  간주한다. revision ``20260806_0015_recipient_status_tag``에서는
  ``erp.recipient.recipient_status`` 컬럼(NOT NULL, server default ACTIVE,
  CHECK ACTIVE|ENDED|WAITING)을 postcheck가 검증한다. 파일 hash까지 통과한 뒤,
  별도 보존 옵션이 없으면 검증 DB와 파일을 제거한다.
- 테스트 하네스는 격리 PostgreSQL에서 합성 seed를 백업하고 실제 복원 훈련을
  실행한다.

운영 백업 대상은 설정된 백업 루트 또는 별도 이동식 저장장치여야 한다. 저장소
경로를 운영 백업 대상으로 사용하지 않는다. 복원 훈련이 성공하기 전에는 백업
성공으로 기록하지 않는다.
