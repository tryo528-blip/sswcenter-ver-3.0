# W3 Fast Track 의사결정 패킷

- 작성 기준일: 2026-08-17
- 상태: `W3_FAST_TRACK_STARTED / USER_DECISIONS_REQUIRED / NO_PRODUCT_IMPLEMENTATION_YET`
- 계보(불변): 최초 산출 `CODEX/IMPLEMENT`. 이후 packet-only 정정 `CODEX(Terra)/FIX`, `GROK/FIX`.
- 현재 게이트: `USER_DECISIONS_REQUIRED`. 이 정정은 패킷 문구만 고치며 W3 결정 승인·제품 구현을 주장하지 않는다.
- 선행 승인: 형님 `승인 w3로 간다`
- 작업 방식: `REMOTE / Ubuntu Linux`
- 범위: W3 공단 일정·RFID 입력, 결정적 매칭, 실제업무 증거사실, 정정·무효화·대체
- 비범위: W4 계산·청구·수납, W5 범용 파일함·OCR·공식 출력·복구

## 1. 목적과 진행 게이트

W2 1A scoped 봉인이 승인되었으므로 W3 fast track을 시작한다. 다만 W3에는 데이터 식별·중복·매칭·보존·정정 결과를 바꾸는 미결정이 남아 있다. 아래 `W3-01`~`W3-09`를 승인하고 가명 실형상 샘플의 기대 결과를 고정하기 전에는 migration, model, endpoint, 자동적용 로직을 만들지 않는다.

승인 방법은 다음 중 하나다.

- 추천안을 모두 채택: `추천안 전체 승인`
- 일부만 변경: 예) `W3-02 IMPORT_RUN_CENTERED, W3-09 SHORT_BIAS, 나머지 추천안 승인`
- 보류할 항목 지정: 예) `W3-06은 샘플 보고 결정, 나머지 추천안 승인`

## 2. 다시 열지 않는 W3 불변조건

다음은 이미 정본에서 확정되었으므로 선택지가 아니다.

1. 공단 일정 원본의 동일 행을 자동 삭제하거나 하나로 합치지 않는다.
2. RFID 입력은 사용자가 지정한 날짜의 하루 snapshot이며 파일 내용으로 대상 날짜를 재검증한다.
3. 같은 날짜의 변경 파일은 이전 snapshot을 대체하되 이전 원본·접수·처리 이력은 보존한다.
4. 시작 전송만 있으면 `종료X · HH:mm`으로 표시하고, 종료 보완은 원본 수정이 아니라 별도 수기일정 변경판으로 기록한다.
5. 실제 시작·종료 시각은 초 단위로 보존한다. Excel 총분은 참고값일 뿐이다.
6. 공단 계획 snapshot은 비교자료이며 실제 제공시간의 근거로 승격하지 않는다.
7. 일정 정정 알고리즘은 `rule_version`을 입력받는 결정적 순수함수로 구현한다.
8. `BLOCK`은 run 전체의 부분적용을 금지하고, `WARNING`은 명시적 검토 후에만 적용한다.
9. 원본 bytes와 원본행은 불변이며 정규화·판단·사용자 결정·적용 결과를 별도 계보로 남긴다.

## 3. 추천 결정 묶음

| ID | 추천값 | 한 줄 원칙 |
|---|---|---|
| W3-01 | `FILE_ONLY` | RFID는 파일 입력으로 계약을 먼저 고정 |
| W3-02 | `SINGLE_STATEFUL_WORKSPACE` | 한 화면에서 계획/확정 상태와 명령을 엄격히 분리 |
| W3-03 | `STABLE_MAPPING_ONLY` | 승인된 유일·유효 외부키 매핑만 자동채택 |
| W3-04 | `UNIQUE_ONLY_ELSE_REVIEW` | 모든 유효조건을 통과한 후보가 정확히 하나일 때만 자동매칭 |
| W3-05 | `DUAL_IDENTITY` | 원본행·source snapshot·업무 occurrence identity를 분리하고 대체는 성공 APPLY만 |
| W3-06 | `RAW_ROWS_PLUS_DERIVED_GROUP` | 원본행을 보존하고 검증된 규칙으로만 파생 그룹 생성 |
| W3-07 | `W3_PRIVATE_CONTENT_RECEIPT_TYPED_LINK` | W3 최소 저장·접수·typed FK만 구현 |
| W3-08 | `VERSIONED_MANUAL_SUPPLEMENT` | 시작전송 보완은 감사 가능한 변경판으로 누적 |
| W3-09 | `REVIEW_PENDING` | 동률·정확한 중간값은 자동 변경 0건 |

## 4. 항목별 결정

### W3-01 RFID 내부 API 초기 활성화

- 선택지: `FILE_ONLY` / `FILE_AND_INTERNAL_API`
- 추천: `FILE_ONLY`
- 이유: `.xlsx` 입력으로 parser, snapshot 대체, 멱등, 오류·격리 계약을 먼저 고정해야 잘못된 업무사실이 API를 통해 빠르게 확산되는 것을 막을 수 있다.
- 승인 시 구현 경계: 내부 API adapter 경계는 설계할 수 있지만 route, credential, 운영 자동수집은 비활성으로 둔다.
- 추가 증거: 가명 RFID workbook. API 동시 활성화 선택 시 공식 payload, 인증, 재전송, 오류 계약도 필요하다.

### W3-02 계획·확정 입력 UX

- 선택지: `SEPARATE_SCREENS` / `SINGLE_STATEFUL_WORKSPACE` / `IMPORT_RUN_CENTERED`
- 추천: `SINGLE_STATEFUL_WORKSPACE`
- 이유: 하나의 run 계보 안에서 계획·확정, preview·confirm, 잠금 상태를 비교하기 쉽다. 단, 상태 표식·권한·command는 섞이지 않도록 분리한다.
- 고정 안전조건: 확정월은 읽기 전용이며, 상태전이는 명시적 command와 감사이력을 갖는다.
- 추가 증거: 월별 실제 운영 순서, 확정 담당자, 확정 취소 허용 여부, 모바일 사용 흐름.

### W3-03 RFID 직원 자동매칭

- 선택지: `STABLE_MAPPING_ONLY` / `NAME_PHONE_EXACT` / `ALL_MANUAL_REVIEW`
- 추천: `STABLE_MAPPING_ONLY`
- 이유: 승인된 외부키↔직원 매핑이 대상일에 유일하고 유효한 경우만 자동채택한다. 이름·전화는 후보 검색 보조값으로만 사용한다.
- 검토대기 조건: 0건, 다건, 퇴사·비활성, 외부키 재사용, 유효기간 불일치.
- 추가 증거: 가명 매핑, 동명이인, 전화 변경, 퇴사, 외부키 재사용 사례.

### W3-04 수급자·서비스·일정 다건매칭

- 선택지: `UNIQUE_ONLY_ELSE_REVIEW` / `DETERMINISTIC_COMPOSITE_RANK` / `ALL_MANUAL_REVIEW`
- 추천: `UNIQUE_ONLY_ELSE_REVIEW`
- 이유: 계약·인정·배정·대상일·서비스·시간 조건을 모두 통과한 후보가 정확히 하나일 때만 자동매칭한다. 다건 tie 규칙은 실제 형상 샘플로 입증된 뒤 별도 rule version으로 승격한다.
- 금지: 금액·청구 유불리를 tie-break로 사용하거나 배열 순서의 첫 후보를 채택하는 행위.
- 추가 증거: 복수 계약·서비스·인접/중첩 일정, 0/1/N 후보와 기대 매칭.

### W3-05 RFID 대체키·동일시각 occurrence

- 선택지: `DUAL_IDENTITY`
- 추천: `DUAL_IDENTITY`
- 원본행 identity: `receipt + sheet + source_row_number`. 이는 해당 receipt 안의 물리 원본행 주소이며 durable 업무 identity가 아니다.
- source snapshot identity: `source_type + target_date + content_digest`. 같은 세 값은 하나의 source snapshot이다. `parser_profile_version`은 snapshot identity에 넣지 않는다.
- 접수 불변: 모든 upload/receipt는 불변 receipt 사실이다. digest·parser profile이 같든 다르든 새 receipt 사실을 지우거나 덮어쓰지 않는다.
- 동일 digest + 동일 parser profile 재접수: 새 receipt는 항상 보존한다. 모든 동일 profile 재접수를 no-op로 단정하지 않는다. 분기는 기존 성공 profile 결과 유무와 직전 시도 상태에 따른다.
- 동일 digest + 동일 parser profile + 동등한 성공 profile 결과 존재: 기존 duplicate/no-op. 새 receipt를 기존 snapshot과 기존 성공 profile 결과에 연결한다. parse 추가와 업무 apply 추가는 0건이며 새 APPLY-capable run을 시작하지 않는다.
- 동일 digest + 동일 parser profile + 성공 결과 없음 + 직전 시도가 재시도 가능 `FAILED`: 새 receipt는 같은 snapshot에 남긴다. 이전 run/attempt는 모두 보존한 채 명시적 새 retry attempt를 허용한다. apply idempotency key는 retry 사이에서도 같다. 업무 apply 전에는 명시 confirm이 필요하다. 실패/rollback은 직전 현재 projection을 유지한다.
- 동일 digest + 동일 parser profile + `BLOCKED`: 같은 bytes/profile을 다시 올려 우회할 수 없다. profile 또는 content 정정, 또는 명시적 review/unblock 계약이 필요하다.
- 동일 digest + 더 새 parser profile: 같은 snapshot의 reparse run이다. 새 snapshot이 아니고 snapshot `SUPERSEDED` 사유도 아니다. 이전 run의 정규화결과·판단·사용자결정·적용이력은 보존한다. 명시 confirm 전 apply 추가 0건, snapshot `SUPERSEDED` 0건이다. 명시 confirm이 성공하면 이전 적용 사실을 versioned reconciliation한다. 옛 fact revision은 보존하고 현재 projection만 원자적으로 교체하며, 현재 적용 사실을 중복 insert하지 않는다. `BLOCKED`/`FAILED`/rollback은 직전 현재 적용 사실을 유지한다.
- 다른 digest: receipt/parse/preview 단계에서는 후보 snapshot일 뿐이다. 현재 active snapshot을 미리 `SUPERSEDED`로 바꾸지 않는다.
- 성공 APPLY만, 같은 transaction에서, 적용 사실을 version-reconcile하고 후보를 활성화하며 직전 active snapshot을 `SUPERSEDED`로 표시할 수 있다. `BLOCKED`/`FAILED`/rollback은 직전 active snapshot과 직전 현재 적용 사실을 유지한다.
- 같은 `(source_type, target_date)`의 동시 confirm/apply는 정규 lock으로 직렬화하고, active snapshot과 현재 적용 사실 집합을 각각 최대 1개로 강제한다.
- 업무 occurrence: 정규화 signature와 원본 순서에 따른 occurrence ordinal
- 제외안: `SOURCE_ROW_NUMBER_AS_DURABLE_KEY`. row number는 재정렬·재수신을 가로지르는 durable identity가 될 수 없다.
- 제외안: `BUSINESS_SIGNATURE_COLLAPSE`. 원본 동일 행 자동삭제 금지와 정당한 복수행 보존을 위반하므로 승인 선택지가 아니다.
- 금지: 운영체제가 붙인 `(1)`, `(2)` 파일명을 업무키로 사용하거나 동일시각·동일내용의 정당한 복수행을 자동 병합하는 행위.
- 추가 증거: 동일 digest·동일 profile의 성공 결과 재업로드 no-op, 동일 digest·동일 profile의 재시도 가능 `FAILED` retry, 동일 digest·동일 profile의 `BLOCKED` 우회 거부, 동일 digest·새 parser profile 재처리와 confirm reconciliation, 다른 digest 후보의 조기 `SUPERSEDED` 0건, 성공 APPLY 원자 swap, `BLOCKED`/`FAILED`/rollback 유지, 두 연결 동시 apply, 행 재정렬, 동일시각 복수행.

### W3-06 공단 수가행 업무그룹화

- 선택지: `RAW_ROWS_PLUS_DERIVED_GROUP` / `MANUAL_GROUP_ONLY`
- 추천: `RAW_ROWS_PLUS_DERIVED_GROUP`
- 이유: 원본행은 언제나 개별 보존하고, 공식 식별자 또는 승인된 가명 샘플의 결정적 signature가 있을 때만 별도 derived group을 만든다.
- 제외안: `HEURISTIC_DURATION_GROUP`. 시간 합계만으로 원본행을 자동 병합할 수 있으므로 승인 선택지가 아니다.
- 모호한 결과: `BLOCKED_REVIEW`; 합계나 예상 서비스시간으로 원본을 대체하지 않는다.
- 추가 증거: 240분 2행, 480분 1행, 같은 날 복수 서비스, 인접·비인접 행, 순서 변경과 기대 그룹.

### W3-07 content·접수·업무연결

- 선택지: `W3_PRIVATE_CONTENT_RECEIPT_TYPED_LINK` / `POSTGRES_BYTEA_TYPED_LINK`
- 추천: `W3_PRIVATE_CONTENT_RECEIPT_TYPED_LINK`
- 구조: digest 기반 불변 private content → 별도 receipt → W3 import run → 대상별 typed FK.
- 운영조건: quarantine와 legal hold가 GC보다 우선하고, 보존기간 승인 전 자동 GC는 비활성으로 둔다. publish 실패·재시도·고아 reconciliation을 명시한다.
- 제외안: `SHARED_W5_DOCUMENT_VERSION`. W5 범용 파일함을 선구현하므로 승인 선택지가 아니다.
- 금지: 범용 `target_type + target_id` 연결, W5 범용 파일함 선구현, 원본 bytes 공개 URL 저장.
- 추가 증거: 월별 파일 수·크기, 보존 법적근거, 접근권한표, 실패·고아·재시도 사례.

### W3-08 시작전송 수기보완

- 선택지: `VERSIONED_MANUAL_SUPPLEMENT`
- 추천: `VERSIONED_MANUAL_SUPPLEMENT`
- 이유: RFID 원본은 불변으로 두고 연결된 수기일정 변경판에 사유, 작성자, 시각, 근거, `row_version`을 기록한다. 취소·대체 역시 event로 남긴다.
- 제외안: `UNLINKED_MANUAL_SCHEDULE`. 원본 RFID와 보완·취소·대체의 연결 계보 및 감사를 끊으므로 승인 선택지가 아니다.
- 제외안: `IN_PLACE_RFID_EDIT`. 원본 bytes·원본행 불변조건을 위반하므로 승인 선택지가 아니다.
- 검증조건: stale 갱신 차단, 확정월 변경 차단, 이전판 삭제 금지, 원본과 supplement 계보 유지.
- 추가 증거: 시작만 있음, 종료 보완, 보완 취소, 재보완, stale, 확정월 거부의 기대 결과.

### W3-09 정정 후보 동률·30분 중간값

- 선택지: `SHORT_BIAS` / `LONG_BIAS` / `REVIEW_PENDING`
- 추천: `REVIEW_PENDING`
- 이유: 근거 없는 자동 bias는 계획과 후속 계산 결과를 바꾼다. 동률·정확한 중간값에서는 자동 변경을 0건으로 하고, 사용자의 명시 선택과 감사를 요구한다.
- 추가 증거: 1,799/1,800초 경계, 1초 부족, 정확한 중간값, 5분 후보 동률, 기대 선택.

## 5. 가명 실형상 샘플 팩

민감정보가 없는 가명 파일과 expected 결과를 hash manifest로 동결한다.

1. 공단 일정: 240/480분, 동일·복수행, 재정렬, 잘못된 sheet/header/type.
2. RFID: 정상 종료, 시작만, 초 단위 경계, 동일 digest·동일 profile의 성공 결과 재접수 no-op, 동일 digest·동일 profile의 재시도 가능 `FAILED` retry, 동일 digest·동일 profile의 `BLOCKED` 우회 거부, 동일 digest·새 parser profile 재처리, 다른 digest 후보와 성공 APPLY 원자 swap, 실패 rollback.
3. 매칭: 동명이인, 전화 변경, 복수 계약·서비스·일정, 0/1/N 후보.
4. 수기보완: 생성·취소·대체·stale·확정월 거부.
5. 정정: 1,799/1,800초, 1초 부족, 정확한 중간값, 후보 동률.
6. 각 샘플: parser profile, expected normalized rows, `WARNING/BLOCK`, 동일 digest·동일 profile 분기(성공 no-op / 재시도 가능 `FAILED` / `BLOCKED`), 적용 결과 0/N건.

실제 운영 파일을 그대로 저장소에 넣지 않는다. 원본 형상만 유지한 가명 샘플과 기대 결과를 사용한다.

## 6. 승인 뒤 구현 순서

1. `W3-01`~`W3-09` 결정값과 W4/W5 제외를 정본·현재 계획에 반영한다.
2. 가명 샘플, expected 결과, 공식근거를 hash manifest로 동결한다.
3. 첫 RED-A를 영속성 없는 정정 순수함수 계약으로 제한한다. 구현 seam은 `backend/app/domains/w3/plan_adjustment.py`의 `propose_plan_adjustment(...)`다. 이 함수는 candidate proposal 또는 `REVIEW_PENDING`만 반환하며 DB write·event 생성·계획 변경판 채택을 하지 않는다. `backend/tests/test_w3_rfid_plan_adjustment.py`에서 1,799/1,800초, 1초 부족, 5분 최소오차 후보, 정확한 중간값·동률, `rule_version`, 입력 불변성·결정성을 고정한다. I/O·matcher·API·UI는 포함하지 않는다.
4. 첫 RED-B를 W3 source-intake foundation 계약으로 제한한다. `backend/tests/test_w3_0028_contract.py`, `backend/tests/test_w3_0028_postcheck_unit.py`, `backend/tests/test_w3_0028_postgres.py`, `backend/tests/test_w3_source_intake_unit.py`, `backend/tests/test_w3_wave_boundary_contract.py`에서 불변 private content → receipt → import run → typed FK, 원본행/source snapshot/업무 occurrence 불변 identity, 동일 `source_type+target_date+content_digest`의 단일 snapshot 분류, 동일 digest·동일 parser profile 재접수의 세 갈래 분류(동등한 성공 profile 결과의 duplicate/no-op, 성공 결과 없는 재시도 가능 `FAILED`의 같은 snapshot retry-eligible, `BLOCKED`의 같은 bytes/profile 재업로드 우회 금지), 동일 digest·새 parser profile의 같은 snapshot reparse 분류, 다른 digest의 후보 분류와 조기 `SUPERSEDED` 0건, active snapshot 최대 1개 불변조건, quarantine·legal hold, 부분적용 0건, ACL·downgrade를 먼저 고정한다. parser·matcher·apply·endpoint·UI와 versioned reconciliation/원자 swap은 포함하지 않는다. 모든 동일 profile 재접수를 no-op로 분류하지 않는다.
5. `0028_w3_source_intake_foundation` migration과 `backend/app/db/w3_models.py`만 이 단계에서 제품 schema를 연다. exact seam은 다음과 같다.
   - `backend/alembic/env.py`에 W3 model을 등록한다.
   - `backend/tests/test_schema_contract.py`의 metadata import와 `EXPECTED_CURRENT_TABLES` enumeration을 0028 객체로 갱신한다.
   - `backend/app/db/postcheck_current_0028.py`를 current postcheck/active marker로 둔다. active marker는 `SSWCENTER_CURRENT_0028_DB_POSTCHECK_OK`와 `SSWCENTER_CURRENT_HEAD_POSTCHECK_OK`다.
   - `backend/app/db/postcheck_current_0027.py`는 explicit/direct historical 0027 verifier로 남긴다. historical 0027 marker는 `SSWCENTER_CURRENT_0027_DB_POSTCHECK_OK`를 유지하고 current-head marker를 내지 않는다.
   - `backend/app/db/postcheck_dispatch.py`의 `ACTIVE_REVISION`은 0028만 가리킨다. dispatcher는 0028만 current-head로 검증하고, historical 0027 검증은 `postcheck_current_0027` 직접 호출로 남긴다.
   - `backend/app/core/readiness.py`는 0028 current postcheck로 옮긴다.
   - `scripts/restore-drill.ps1`은 0028 restore만 active dispatcher/current-head marker를 허용하고, 0027 restore는 historical 0027 직접 verifier/marker만 허용하며 current-head marker가 나오면 fail-closed한다. 0026/0025 historical 직접 경로는 유지한다.
   - `scripts/test-w2-0027-postgres-linux.ps1`의 두 데이터베이스 역할을 분리한다. 메인 lifecycle/restore 데이터베이스는 exact 0027 revision을 pin하고 historical 0027 직접 verifier/marker만 사용한다. 현재 FastAPI/Vite/Chromium을 띄우는 별도 BrowserDatabase는 exact active 0028로 upgrade하고 active dispatcher/readiness를 사용한다. 이렇게 해야 현재 `/health/ready`가 통과하고 W2 API/UI가 current-head 회귀로 남는다. 제품 readiness는 엄격히 유지하며 test bypass/injection을 두지 않는다. 이 harness 전체를 0027-only라고 쓰지 않는다.
   - `backend/tests/test_w2_official_card_assignee_contract.py`, `backend/tests/test_w0_readiness_write_gate.py`와 관련 active-head/historical 기대는 0028 active / 0027 historical로 전환한다. 0027 객체 검증은 historical 0027 verifier를 직접 호출한다.
   - W3 lifecycle harness `scripts/test-w3-0028-postgres-linux.ps1`은 0027→0028→0027→0028을 증명한다.
6. RED-A를 만족하는 `propose_plan_adjustment(...)`만 구현하고 rule version별 expected 결과를 고정한다. 이 단계에서는 proposal을 채택하거나 어떤 plan row도 변경하지 않는다.
7. 공단·RFID parser의 정상·경계·오류 RED를 원본행 불변 방식으로 추가하고 구현한다. `.xlsx` 대상일 재검증, 동일 digest·동일 profile의 성공 결과 재접수 duplicate/no-op, 동일 digest·동일 profile의 재시도 가능 `FAILED` retry 분류, 동일 digest·동일 profile의 `BLOCKED` 우회 거부, 동일 digest·새 profile reparse, 다른 digest의 후보 snapshot(이 단계에서는 `SUPERSEDED` 0건), `(1)/(2)` 비키, 초 단위 시각, 시작만 `종료X`, `BLOCK` 부분적용 0건을 포함한다. 모든 동일 profile 재접수를 no-op로 쓰지 않는다.
8. 직원 → 수급자·서비스·일정 순서의 0/1/N fail-closed matcher RED와 구현을 진행한다.
9. 실제업무·실제 서비스의 증거사실 원장과 snapshot 대체 event를 구현한다. 대체 event는 성공 APPLY와 같은 transaction에서만 직전 active snapshot을 `SUPERSEDED`로 표시한다.
10. `backend/tests/test_w3_source_snapshot_apply_contract.py`에서 source snapshot APPLY 계약을 고정하고 구현한다. 이 RED는 동일 digest·동일 profile의 성공 결과 duplicate no-op, 동일 digest·동일 profile의 재시도 가능 `FAILED` retry(이전 run/attempt 보존, retry 사이 안정적인 apply idempotency key, 업무 apply 전 명시 confirm, 실패/rollback 시 직전 현재 projection 유지), 동일 digest·동일 profile `BLOCKED`의 같은 bytes/profile 재업로드 우회 금지, 동일 digest·새 profile confirm의 versioned reconciliation, 다른 digest 성공 APPLY의 원자 swap, `BLOCKED`/`FAILED`/rollback 유지, 같은 `(source_type, target_date)` 두 연결 동시 apply 직렬화를 포함한다. RED-B에 apply·reconciliation·원자 swap을 넣지 않는다.
11. `backend/tests/test_w3_plan_adjustment_apply_contract.py`에서 정정·수기보완·무효화·대체 command의 권한·row version·감사·동시성 RED를 고정하고 구현을 진행한다. apply command는 같은 transaction에서 계약·인정·배정·시간충돌·수동보호·확정월을 재검증한 뒤에만 계획 변경판과 감사를 채택하며, 어느 gate라도 실패하면 변경·감사 모두 0건이어야 한다.
12. 승인된 API/OpenAPI와 UX·입력경로를 마지막으로 연결한다.
13. PostgreSQL migration/restore/concurrency, 실제 workbook, 브라우저, cleanup 경합과 W0/W1/W2 회귀를 검증한다.

## 7. 완료조건

W3 구현 완료는 단순 parser 성공이 아니다. 다음을 모두 충족해야 한다.

- 원본 content·receipt·row·snapshot·처리이력의 불변 계보
- 동일 digest·동일 profile의 성공 결과 no-op, 재시도 가능 `FAILED` retry, `BLOCKED` 우회 금지, 같은 snapshot 재처리, 성공 APPLY만의 원자 대체와 부분적용 0건
- 직원·수급자·서비스·일정의 0/1/N fail-closed 매칭
- 실제 시각의 초 단위 보존과 계획 snapshot 비승격
- 수기보완·정정·무효화·대체의 version·감사·동시성
- migration lifecycle·restore·직접 SQL·2-connection race 검증
- API/OpenAPI·실 workbook·브라우저·cleanup 검증
- W4 계산·청구·수납과 W5 파일함·OCR가 diff에 유입되지 않음

## 8. 정본 근거

- `review/plans/CURRENT_W2_SEAL_TO_W3_FAST_TRACK_20260817.md`
- `docs/02_업무규칙_계약_v1.1.md` §10
- `docs/04_데이터_DB_불변조건_v4.8_PostgreSQL.md` §12
- `docs/05_기술_보안_파일처리_아키텍처_v1.5.md` §6
- `docs/06_개발로드맵_결정현황_v1.2.md` §7

이 패킷은 W2 검수 후보 manifest 이후에 작성된 W3 전환 산출물이며, W2 봉인 대상 98개 파일에는 포함되지 않는다.
