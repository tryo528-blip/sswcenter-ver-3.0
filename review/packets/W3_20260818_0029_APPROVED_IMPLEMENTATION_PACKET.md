# W3 0029 승인 구현 패킷 — 2026-08-18

> 상태: `USER_APPROVED / CODEX_IMPLEMENTING`
> 작업 브랜치: `codex/debt-preseal-20260818`
> actor/action: `CODEX / IMPLEMENT`
> 승인 발화: `딱히문제없어보이는데 일단 승인`

## 1. 승인 해석과 범위

형님의 승인은 직전 제시한 W3 추천안, 즉 0028 source-intake foundation 위에
정규화 결과·결정·typed link를 영속화하고, 명시 confirm 뒤에만 원자 APPLY하며,
이를 `SINGLE_STATEFUL_WORKSPACE`로 제공하는 0029 구현 승인으로 해석한다.

포함 범위:

1. 승인된 `nhis-schedule-xlsx-v1`, `rfid-xlsx-v1`의 FILE_ONLY 접수와 private 저장
2. raw physical row, normalized occurrence, NHIS derived group의 분리 영속화
3. `STABLE_MAPPING_ONLY`와 `UNIQUE_ONLY_ELSE_REVIEW`의 재현 가능한 match decision
4. W1/W2 대상별 nullable typed FK 묶음과 fail-closed 일관성 제약
5. 같은 `(source_type, target_date)` apply control row 잠금과 성공 APPLY 원자 swap
6. RFID actual-work revision, 시작전송 수기보완 event, 계획정정 adoption event
7. 권한·CSRF·row version·멱등키·구조화 409/422 계약
8. FILE_ONLY API/OpenAPI와 단일 상태형 입출력 작업공간 UI
9. migration downgrade/restore, PostgreSQL 동시성, HTTP workbook, Chromium 회귀

제외 범위:

- 이름·전화번호를 identity 또는 자동 tie-break로 사용
- 내부 RFID 수집 API, Download Inbox Agent, 외부 업무 API
- W4 수가·청구·수납 계산
- W5 OCR·범용 파일함·public URL
- 원본 bytes/원본 RFID 시각의 수정 또는 과거 revision 삭제
- 현재 두 가명 workbook 사이에 존재하지 않는 연결의 발명

## 2. exact 0029 schema

0028의 여섯 table은 유지하고 `w3_import_run.row_version`만 추가한다. 0029가 새로
소유하는 table은 다음 열 개다.

```text
erp.w3_import_run_event
erp.w3_normalized_nhis_row
erp.w3_normalized_rfid_row
erp.w3_nhis_group
erp.w3_nhis_group_member
erp.w3_match_decision
erp.w3_apply_control
erp.w3_actual_work_revision
erp.w3_manual_supplement_event
erp.w3_plan_adjustment_event
```

- normalized row와 group은 import run 및 0028 source row에 `ON DELETE RESTRICT`로
  연결한다.
- match decision은 generic `target_type + target_id`를 갖지 않는다. recipient,
  certification period, staff, employment, staff stable mapping, service type,
  recipient contract, care assignment, W2 schedule의 명시적 FK만 갖는다.
- `AUTO_MATCH`만 typed FK 묶음이 완전할 수 있고 `REVIEW_PENDING/BLOCKED`는 업무
  대상 FK를 비워 자동 채택을 막는다.
- apply control은 `(source_type, target_date)` PK이며 active snapshot/run을 typed FK로
  가리킨다. APPLY는 이 행을 먼저 `FOR UPDATE`로 잠근다.
- actual-work는 immutable revision이다. 현재 projection은 partial unique index로
  하나만 허용하고 교체 시 옛 revision을 `superseded_at_utc`로 닫은 뒤 새 revision을
  추가한다. 삭제하지 않는다.
- supplement와 plan-adjustment는 append-only event다. 원본 RFID row나 bytes를
  갱신하지 않는다.
- event/normalized/decision/revision table은 app에 UPDATE/DELETE/TRUNCATE를 주지
  않는다. apply control 및 import run은 필요한 열만 column UPDATE로 제한한다.
- `erp_backup`은 SELECT only다.

## 3. 상태와 command

```text
RECEIVED -> PARSING -> PREVIEW_READY -> CONFIRMED -> APPLYING -> APPLIED
                 \-> BLOCKED                         \-> FAILED
```

- upload는 preview 생성까지의 한 command다. parser BLOCK은 업무 write 0건이다.
- confirm은 `expected_row_version`과 preview digest를 검증하고 immutable run event를
  남긴다.
- apply는 confirmed run만 받으며 같은 source/date를 직렬화한다.
- blocking/review decision이 하나라도 있으면 apply는 422로 거부되고 기존 active
  snapshot/current facts는 유지된다.
- 성공 transaction만 candidate snapshot 활성화, 옛 active snapshot supersede,
  current actual-work revision reconciliation, apply control 교체, APPLIED event를 함께
  commit한다.
- 409는 최신 workspace와 current row version을 반환한다. UI는 사용자의 선택·파일명·
  날짜를 지우지 않고 새 snapshot을 다시 보여준다.
- 같은 command idempotency key의 동일 payload 재시도는 같은 결과를 반환한다. 같은
  key의 다른 payload는 409다.

## 4. exact HTTP surface

```text
GET  /api/v1/w3/workspace?source_type=...&target_date=...
POST /api/v1/w3/import-runs                         multipart FILE_ONLY
POST /api/v1/w3/import-runs/{run_id}/confirm
POST /api/v1/w3/import-runs/{run_id}/apply
POST /api/v1/w3/import-runs/{run_id}/decisions/{decision_id}/resolve
POST /api/v1/w3/actual-work/{revision_id}/supplements
POST /api/v1/w3/actual-work/{revision_id}/plan-adjustments
```

- read는 `W3_VIEW` 또는 `W3_MANAGE`, mutation은 `W3_MANAGE`와 CSRF가 필요하다.
- multipart는 `.xlsx` 하나, approved source type, selected target date만 받는다.
- content bytes, storage locator, 원본 path, 직원 전화, 내부 legacy key는 응답·URL·DOM·
  download에 내보내지 않는다.
- resolve는 사용자가 보낸 typed IDs를 서버가 다시 검증해 정확히 하나의 유효 조합일
  때만 새 immutable decision을 만든다. 배열 첫 항목 채택은 없다.

## 5. UI 완료조건

`/io` 하나가 source/date/file 선택, preview 상태, warning/block/review 개수,
confirm/apply command, current active snapshot, 최신 run history를 같은 상태 흐름으로
표시한다. OCR 행과 정적 가짜 수집표는 제거한다.

- command 중 중복 제출을 막는다.
- `REVIEW_PENDING`이 있으면 apply 버튼을 닫고 이유를 표시한다.
- 409 뒤 서버 최신상태를 표시하되 사용자의 선택값을 보존한다.
- 시작전송은 `종료X · HH:mm`으로 표시한다.
- 390px viewport에서 수평 overflow 없이 핵심 command를 사용할 수 있어야 한다.

## 6. 완료 증거

1. RED 계약을 먼저 기록
2. exact 0029 migration/ORM/current postcheck/schema enumeration
3. 0028 -> 0029 -> 0028 -> 0029 lifecycle 및 restore
4. parser/matcher/reconciliation/supplement/plan-adjustment unit
5. live PostgreSQL 원자성·동시 apply·rollback·ACL
6. 실제 가명 workbook HTTP와 current pair의 `REVIEW_PENDING`
7. OpenAPI generated type check, frontend unit/build, Chromium
8. W0~W2 supported regression
9. 독립 review 두 라운드와 finding 교정
10. current candidate manifest와 모바일 HTML 보고서

이 패킷은 형님의 승인 범위를 구체화한 구현 경계이며, 테스트가 모두 끝나기 전에는
W3 최종봉인을 주장하지 않는다.
