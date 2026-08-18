# W3 pseudonymous semantic fixture pack

이 디렉터리는 W3 계약·정책 테스트용 가명 fixture다. `v0.blocked`는 실제 형상 근거가
없던 역사 상태이고, `v1.approved`와 `workbooks/*.xlsx`는 형님이 2026-08-18 제공하면서
모든 이름과 번호가 가명·가짜라고 명시한 실제형 workbook의 sheet/header/열/type 근거다.

## 현재 상태

- `profiles/*.blocked.json`: 정본에 실제 workbook header profile 근거가 없던 역사 상태를
  보존한다.
- `profiles/*.approved.json`: 제공된 가명 실제형 workbook의 승인 profile이다.
- `cases/*.json`: header와 무관한 업무 의미·경계 입력이다. v1 바이트는
  덮어쓰지 않고 classifier 보정은 `source_intake_classification_v2`, 배열 재정렬은
  `source_intake_reorder_semantic_v2`, 새 receipt의 물리행 재정렬은
  `source_intake_physical_reorder_v3`로 추가한다.
- `expected/*.json`: 자동판단·검토대기·write-count 기대 결과다.
- `workbooks/*.xlsx`: 원본 bytes를 수정하지 않고 결정적 fixture 이름으로 복사한
  parser-ready 가명 실제형 workbook이다. 운영체제 suffix는 업무키가 아니다.

`declared_filename`은 정본이 정한 기본 파일명일 뿐 실제 fixture 파일명이거나 durable
업무키가 아니다. 원본 RFID 파일의 `(1)` suffix도 parser 결과·snapshot·occurrence
identity에 들어가지 않는다.

## 불변조건

- 원본행을 배열 순서나 row number만으로 durable 업무 identity로 사용하지 않는다.
- source snapshot identity는 `(source_type, target_date, content_digest)`다.
- receipt의 물리 행 주소와 업무 occurrence identity를 분리한다.
- 동일 digest/profile 재접수는 기존 성공 결과, retryable `FAILED`, `BLOCKED` 상태에 따라
  서로 다르게 분류한다.
- different digest는 과거 attempt 상태를 꾸미지 않은 closed
  `NO_PRIOR_ATTEMPT` 입력에서만 candidate가 된다. 이 classifier-only 상태는 DB
  attempt outcome으로 저장하지 않는다.
- 다른 digest는 성공 APPLY 전 candidate일 뿐이며 기존 active snapshot을 미리
  `SUPERSEDED`로 바꾸지 않는다.
- `BLOCKED`, `WARNING`, `REVIEW_PENDING`은 명시 confirm 전 업무 write 0건이다.
- RFID export가 여러 날짜를 포함해도 receipt의 모든 원본행을 보존한다. 사용자가 지정한
  대상일과 시작일이 같은 행만 하루 snapshot의 파생행이 되며 대상일 행이 없으면 BLOCK한다.
- W4 계산·청구·수납과 W5 범용 파일함·OCR·공식출력·제품복구는 이 pack의 범위가 아니다.

역사 semantic pack의 SHA-256·bytes는
`review/evidence/W3_20260817_PSEUDONYMOUS_SAMPLE_PACK.sha256`에서 동결한다. 새 workbook
profile slice는 별도 2026-08-18 manifest에서 동결하고 역사 manifest를 덮어쓰지 않는다.
