# W1D Joseph R2 독립 설계 재감사

- 감사자 역할: Joseph fallback independent auditor
- 실행 표면: Codex Desktop 독립 작업
- task id: `019fb2f5-adc2-74c2-bb06-20ec7d7a2fd6`
- 모델 / 추론: `gpt-5.6-sol` / `max`
- 실행 위치: `C:\sswcenter\2.1` saved project, local checkout
- 시작 / 종료: `2026-07-30 21:17:53 +09:00` / `2026-07-30 21:37:07 +09:00`
- duration: `1,154,064 ms`
- 기준 HEAD: `266beeaa2d150371ccd1a0f26f69249eca86ba16`
- 기준 branch: `codex/w1d-contract-transition`
- 권한: strictly read-only
- 테스트 / 서버 / 네트워크 / 추가 agent: 실행하지 않음
- 최종 판정: `JOSEPH_W1D_REAUDIT_R2_RESULT=REQUIRED_CHANGES`

## 스냅샷 확인

Regina가 감사 종료 직후 다시 계산한 입력 SHA-256은 다음과 같다.

| path | SHA-256 |
|---|---|
| `review/packets/W1D_ASSIGNMENT_PACKET_v1.0.md` | `6a64ed0c62b3c69e26f30ecea07e415f5c66f7055d923fc5a80df98318ba75c9` |
| `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md` | `e62e6b915fca7b1a8520d215947d967c310511419b9e6c0b958adc2dab6d5399` |
| `review/evidence/w1d/RED.md` | `515402690cf13e3c23c0c83ac0f01acf5235a2b3d0ec6e4d7c0fc08af38805f9` |
| `backend/tests/test_w1d_contract.py` | `4d8f183817dca5cd99453315990fa1b65c79983e71d997f2705751ef969539bd` |
| `backend/tests/test_w1d_postgres.py` | `64937e2f0722adabd83692a10213588873baa49e9912c3ddef2cbe73441286a8` |
| `frontend/src/test/W1DContractTransition.test.tsx` | `7f91327335b918ef941697655e9ba4ed7d60ae8a6fcd0fbc772ed7e658eca7fa` |
| `frontend/e2e/w1d-contract-transition.spec.ts` | `3c381111971218a170010d253f74eae818048be818b927df09b06ff7f91d4504` |
| `scripts/test-w1d-postgres.ps1` | `7f633a4f7fc6a1515c142e6d6f355ae36be99bc5717e899dbe732b9abda07ec9` |
| `review/reports/W1D_OPUS_DESIGN_AUDIT_CORRECTED_266BEEA.md` | `3bd129ef379fb4629a242e801f8fae406296312fd9276e09e104c86ec8ff3e46` |

초기 독립 작업 전달문과 Joseph 최종 응답 부록에는 wrapper SHA가
`...15c1425e6...`로 적힌 전사 오타가 있었다. 감사 시작 직후 별도 정정 메시지로
정확한 `...15c142e6...` 값을 전달했고 Joseph은 정정값과 실제 파일의 일치를
중간 상태에서 확인했다. 위 표는 Regina가 감사 종료 후 실제 파일에서 다시 계산한
권위값이다. 이 문구 오타는 파일 drift가 아니다.

감사 종료 직후 상태:

- tracked delta `0`
- staged delta `0`
- 감사 전과 동일한 W1D untracked 입력 11개
- direct Joseph CLI, Grok, Claude 관련 process `0`
- port `55444/4173` listener `0`
- root `node_modules`, `frontend/test-results`, `frontend/playwright-report` 없음

## Findings

### BLOCKER

#### J-W1D-R2-B01 — 인증기간 stale 준비 자체가 W1C 제약을 위반

- 위치:
  `backend/tests/test_w1d_postgres.py:1793`,
  `backend/tests/test_w1d_postgres.py:1921`,
  `backend/alembic/versions/20260730_0010_w1c_certification_ledgers.py:292`,
  `backend/alembic/versions/20260730_0010_w1c_certification_ledgers.py:312`
- 영향: 인증·등급을 모두 `2036-12-31`까지 만든 뒤 인증만
  `2036-11-30`으로 축소한다. `DEFERRABLE INITIALLY IMMEDIATE` containment
  trigger가 이 UPDATE를 즉시 거부하므로 apply와
  `CERTIFICATION_TRANSITION_STALE` 검증에 도달하지 못한다. 올바른 제품도
  GREEN이 불가능하다.
- 필수 보정: 등급을 계속 포함하는 유효한 인증 날짜 변경, 예를 들면 시작일을
  앞당기거나 종료일을 늘리는 mutation을 사용한다.
- 필수 RED: 준비 mutation commit 성공을 먼저 단정하고, 이후 apply가 정확히
  STALE이며 준비 mutation만 유지되고 전환 신규 인증·등급·계약·감사 write는
  `0`임을 전체 fingerprint로 증명한다.

### HIGH

#### J-W1D-R2-H01 — N1의 fresh-cluster 최초 absent-row 발급이 실행 계약으로 강제되지 않음

- 위치:
  `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:209`,
  `backend/tests/test_w1d_postgres.py:413`,
  `scripts/test-w1d-postgres.ps1:224`
- 영향: 테스트는 `before_counter`가 이미 존재해도 baseline으로 수용한다. 향후
  W1D migration이 `RECIPIENT_NO/0`을 seed하거나 다른 product test가 먼저 번호를
  발급해도 N1이 통과한다. 현재 0001~0010과 harness에는 실제 seed/발급이 없고
  DELETE도 `0`건이지만 future-GREEN 방어가 아니다.
- 필수 보정: virgin cluster에서 `before_counter is None`을 필수 단정하고 wrapper가
  `pg_00`을 product 첫 단계로 명시 실행한다.
- 필수 RED: `None → 1`, 두 compatible service 성공, 계약 정확히 2건, 두 번째
  수급자 발급 `1 → 2`, 전역 unique·monotonic, 재계약 무증가를 순차 단정한다.

#### J-W1D-R2-H02 — N3의 두 apply가 실제 lock race임을 보장하지 않고 최종 인증·등급도 확인하지 않음

- 위치:
  `backend/tests/test_w1d_postgres.py:1683`,
  `backend/tests/test_w1d_postgres.py:1695`,
  `backend/tests/test_w1d_postgres.py:1734`
- 영향: preview 두 개는 한 session에서 순차 생성되고 worker에는 barrier나
  lock-wait 관측점이 없다. 무잠금 구현도 scheduling이 순차이면
  `1 success / 1 STALE`로 통과할 수 있다. 최종 검사는 기존 종료일·신규 계약
  1·감사 1뿐이어서 새 인증 또는 새 등급을 누락한 구현도 통과한다.
- 필수 보정: 두 별도 session이 apply 경계에 동시에 도달하도록 barrier/test
  seam을 두고 두 번째 transaction의 recipient lock 대기를 관측한다.
- 필수 RED: 승자 응답 ID와 정확히 1개의 새 인증·등급·계약, 기간·등급·containment,
  패자 write `0`, aggregate audit `1`을 모두 단정한다.

#### J-W1D-R2-H03 — cross-group DB trigger 설계가 concurrent INSERT를 직렬화하지 않음

- 위치:
  `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:345`,
  `docs/04_데이터_DB_불변조건_v4.8_PostgreSQL.md:616`,
  `backend/tests/test_w1d_postgres.py:636`
- 영향: 계획된 trigger는 기존 계약을 조회할 뿐 recipient/advisory lock을 취하지
  않는다. `READ COMMITTED`에서 서로 다른 group의 두 concurrent insert는 상대방의
  미커밋 행을 보지 못해 둘 다 성공할 수 있다. RED도 순차 호출뿐이다.
- 필수 보정: trigger 내부에서 동일 recipient parent row를 고정 순서로 잠그거나
  동등한 concurrency-safe DB constraint를 설계한다.
- 필수 RED: service를 우회한 두 raw connection의 overlapping cross-group INSERT에서
  정확히 `1 commit / 1 constraint failure`, same-group 서로 다른 서비스에서는
  `2 commit`을 강제한다.

#### J-W1D-R2-H04 — W1-TRN-02 replacement 완전성 RED가 빈 배열 한 경우뿐

- 위치:
  `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:305`,
  `backend/tests/test_w1d_postgres.py:1046`,
  `review/WAVE1_CLEAN_TEST_MATRIX.md:197`
- 영향: 누락 전체만 검증하므로 추가·중복·잘못된 service·다른
  `ended_contract_id`·서명 token에 바인딩된 사용자 필드 변경을 허용하는 구현도
  통과할 수 있다.
- 필수 보정: token intent와 exact 배열/multiset 비교 범위를 RED와 일치시킨다.
- 필수 RED: 누락·부분·추가·중복·wrong service와 각 bound field 변조가 모두
  정확한 `CERTIFICATION_TRANSITION_REPLACEMENT_MISMATCH`이고
  STALE/TOKEN_INVALID가 아니며 전체 DB fingerprint가 동일해야 한다.

#### J-W1D-R2-H05 — W1-TRN-04의 단계별 rollback 주장이 실행되지 않음

- 위치:
  `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:441`,
  `backend/tests/test_w1d_postgres.py:1311`,
  `review/WAVE1_CLEAN_TEST_MATRIX.md:199`
- 영향: 열 개 apply seam 중 `after_end_grade` 하나만 실행한다. 종료 후 commit,
  신규 인증/등급/계약 사이 commit, 감사 전후 commit 같은 부분 transaction 구현이
  통과할 수 있다.
- 필수 보정: 모든 봉인 label을 fresh case로 parameterize한다.
- 필수 RED: 각 label마다 인증·등급·계약·recipient·counter·audit 전체 fingerprint와
  행 수가 fault 전 상태와 동일해야 한다. 별도 `after_contract_insert` seam의
  계약·recipient_no·counter rollback 검사는 현재 존재하며 적절하다.

#### J-W1D-R2-H06 — Playwright가 실제 PostgreSQL/FastAPI E2E가 아니라 전면 mock

- 위치:
  `frontend/e2e/w1d-contract-transition.spec.ts:43`,
  `review/packets/W1D_ASSIGNMENT_PACKET_v1.0.md:225`,
  `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:553`
- 영향: `**/api/**`를 모두 `page.route`로 응답하므로 backend·migration·auth·CSRF·
  transaction이 없어도 UI만 구현되면 GREEN이다. 계획의 real-PG 발급·snapshot·
  경쟁·rollback E2E 매핑은 실행되지 않는다.
- 필수 보정: mock browser test는 UI test로 분리하고 isolated PG + 실제 FastAPI +
  frontend를 사용하는 live E2E를 추가한다.
- 필수 RED: 실제 로그인/CSRF, 최초 번호발급, 최소 계약,
  preview/apply/stale/rollback을 세 viewport에서 검증하고 DB 후조건까지 확인한다.

### MEDIUM

#### J-W1D-R2-M01 — service multiset stale가 service를 바꾸지 않음

- 위치: `backend/tests/test_w1d_postgres.py:1943`
- 영향: SQL은 `start_date`만 바꾸므로 contract-period stale의 중복 사례다.
  HOME_CARE multiset은 그대로여서 service projection 누락 구현이 통과한다.
- 필수 보정/RED: 유효한 HOME_CARE→HOME_BATH 변경 또는 compatible service 추가로
  실제 multiset을 변경하고, 변경 전후 multiset 차이·정확한 STALE·부분 write `0`을
  단정한다.

#### J-W1D-R2-M02 — preview write 0과 audit metadata 검사가 불완전

- 위치:
  `backend/tests/test_w1d_postgres.py:959`,
  `backend/tests/test_w1d_postgres.py:978`,
  `backend/tests/test_w1d_postgres.py:1122`
- 영향: `before_audit`는 계산 후 사용되지 않고 fingerprint는 세 원장의
  `id,row_version`만 포함한다. preview audit·identity·recipient·counter write가
  통과할 수 있다. `MAX(audit_event.id)` window 자체는 wall-clock보다 안전하지만
  success audit의 `occurred_at_utc`, `reason_code`, `created_from`, `request_id`와
  응답 correlation의 일치를 확인하지 않는다.
- 필수 보정/RED: preview 전후 관련 전체 테이블과 audit/counter snapshot을 비교하고,
  aggregate event의 actor·time·target·reason·request correlation을 정확히 단정한다.

#### J-W1D-R2-M03 — required-nullable token의 API 계약과 error-path write 0이 끝까지 실행되지 않음

- 위치:
  `backend/tests/test_w1d_contract.py:291`,
  `backend/tests/test_w1d_postgres.py:1531`,
  `backend/tests/test_w1d_postgres.py:1606`
- 영향: standalone Pydantic model은 omit 거부/null 허용을 확인하고 direct service는
  null/blank의 PREVIEW_REQUIRED를 확인한다. 실제 apply API에서 omit→정확한
  `VALIDATION_ERROR` envelope는 호출하지 않고 write `0`도 contract count만 본다.
- 필수 보정/RED: TestClient로 omit/null/blank를 각각 호출하여 exact top-level
  envelope와 field error를 확인하고, 인증·등급·계약·recipient·counter·audit 전체
  snapshot 동일성을 단정한다.

#### J-W1D-R2-M04 — stale UI 검증이 comment-only 조건문

- 위치:
  `frontend/src/test/W1DContractTransition.test.tsx:307`,
  `frontend/e2e/w1d-contract-transition.spec.ts:138`
- 영향: unit mock apply는 성공하며 stale banner를 apply 전에 조회한 뒤 존재할 때만
  확인한다. E2E mock도 stale을 반환하지 않는다. preview/token/confirmation을
  유지하는 UI가 통과한다.
- 필수 보정/RED: apply 409 STALE 전용 case에서 preview·checkbox·token 폐기,
  apply disabled, “다시 미리보기” 안내를 무조건 단정한다.

#### J-W1D-R2-M05 — open-ended 계약 충돌 matrix가 없음

- 위치:
  `backend/tests/test_w1d_postgres.py:655`,
  `review/WAVE1_CLEAN_TEST_MATRIX.md:208`
- 영향: open-ended 계약 생성은 다른 테스트에 있지만 이후 same-service/cross-group
  overlap 차단을 검증하지 않는다. NULL 상한 range를 잘못 구현해도 통과할 수 있다.
- 필수 보정/RED: open-ended base 뒤 same-service와 cross-group 미래 계약은 정확한
  409, 허용 same-group 조합은 성공하도록 추가한다.

#### J-W1D-R2-M06 — 권한과 표준 error envelope RED가 느슨함

- 위치:
  `backend/tests/test_w1d_postgres.py:1364`,
  `backend/tests/test_w1d_postgres.py:1390`,
  `backend/app/api/dependencies.py:218`
- 영향: 미인증과 ADMIN CSRF만 테스트하며 무권한 계정 403은 없다. code 추출도
  표준 `error`뿐 아니라 legacy `detail`을 허용한다.
- 필수 보정/RED: no-permission 및 VIEW-only 계정의 mutation이 exact
  `403 PERMISSION_REQUIRED`, DB write `0`이어야 하며 top-level
  `error/field_errors/details/request_id` 구조만 허용한다.

#### J-W1D-R2-M07 — OpenAPI route binding과 생성 TypeScript 일치가 강제되지 않음

- 위치:
  `backend/tests/test_w1d_contract.py:361`,
  `backend/tests/test_w1d_contract.py:438`
- 영향: named schema 존재와 generator 파일 존재만 검사한다. apply route가 다른 body
  model을 사용하거나 생성 client가 stale/수동수정이어도 통과한다.
- 필수 보정/RED: 각 operation의 request/response `$ref`를 exact 검사하고 승인
  generator를 임시 출력으로 실행해 tracked 생성물과 byte-equivalence를 확인한다.

#### J-W1D-R2-M08 — future-GREEN wrapper의 product/harness 분리가 유지되지 않음

- 위치:
  `scripts/test-w1d-postgres.ps1:210`,
  `scripts/test-w1d-postgres.ps1:233`
- 영향: 현재 revision-mismatch 경로는 `1 harness + 9 product`로 정확히 분리된다.
  revision 일치 후에는 전체 10개를 다시 실행해 harness failure도 product failure로
  분류한다.
- 필수 보정/RED: harness 1회, virgin-counter `pg_00` 1회, 나머지 product 8회를
  명시 분리하고 각 단계 exit/marker 분류를 검증한다.

#### J-W1D-R2-M09 — wrapper의 process residual 계수가 실제 postgres process를 찾지 못함

- 위치: `scripts/test-w1d-postgres.ps1:286`
- 영향: `postgres.exe`의 `Path`는 `$PostgresBin` 아래이지 `$ClusterRoot` 아래가
  아니므로 `StartsWith($ClusterRoot)` 필터는 항상 빗나간다. CIM 종료가 실패해도
  `process=0` false pass가 가능하다.
- 필수 보정/RED: 종료 후 `Win32_Process.CommandLine`의 정확한 `$DataDirectory`
  또는 port를 기준으로 잔여를 다시 열거하고, 실패 시 harness failure로 판정한다.

### LOW

#### J-W1D-R2-L01 — `git diff --check`가 untracked W1D 파일을 검사하지 않음

- 위치: `review/evidence/w1d/RED.md:175`
- 영향: 현재 W1D 산출물은 전부 untracked여서 exit `0`은 이 파일들의 whitespace
  증거가 아니다.
- 필수 보정/RED: stage 없이 각 allowlist 파일에 `git diff --no-index --check`
  또는 동등한 read-only 검사 결과를 남긴다.

## 폐쇄 판정

- `N2`: CLOSED. `2026-11-01..11-30`과 `2026-12-01..12-31`은 채택한
  `[start,end+1)`에서 인접·비중복이며 재계약 성공·번호 불변·counter 무증가
  단정이 있다.
- 기존 `B1`: grade→cert 종료 순서와 exact 종료일 유지.
- 기존 `B2`: STALE/MISMATCH 선행순위 분리는 유지됐으나 replacement 전체 matrix는
  `J-W1D-R2-H04`로 미완료.
- 기존 `H3`, `M1`, `M3`의 핵심 보정 유지.
- `after_contract_insert` seam과 contract·recipient_no·counter rollback 검사 유지.
- `MAX(audit_event.id)` baseline 방식 자체는 안전. event/write 범위는
  `J-W1D-R2-M02`로 부족.
- `N1`, `N3`: NOT CLOSED.

## 질문과 구현감사 잔여

- `certification_number=null` 전환의 exact 오류 문자열이 계획에서
  “또는 동등 안정 코드”로 남아 있다.
- `audit_correlation_id`가 event bigint인지 request UUID인지 계획의
  `event id / request_id` 표현을 하나로 봉인해야 한다.
- 실제 구현은 각 호출에서 commit하는 기존 W1C service 메서드를 조합하면 안 된다.
  W1D 단일 transaction 안에서 원장을 직접 조작해야 한다.
- 전환 token key의 CSRF/app secret 분리는 구현감사 대상이다.
- 제품 revision 부재로 인한 현재 RED와 Regina의 기존 실행 결과는 결함으로
  계산하지 않았다.

## 결론

BLOCKER `1`, HIGH `6`, MEDIUM `9`, LOW `1`이 확인됐다. 결함은 설계·RED
보정으로 해결 가능하므로 감사 자체를 `BLOCK`하지는 않지만, 구현 경계 재봉인과
제품 구현 시작은 승인하지 않는다.

`JOSEPH_W1D_REAUDIT_R2_RESULT=REQUIRED_CHANGES`
