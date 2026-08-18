# W3 source-intake fast-track 현재 실행계획 — 2026-08-17

> 상태: `CURRENT_EXECUTION_PLAN / W3_DECISIONS_APPROVED / RED_A_GREEN / RED_B_TERRA_P2_HOST_GREEN / CANDIDATE_MANIFEST_REGENERATED / INDEPENDENT_REVIEW_PENDING`
> 기준 저장소: `/home/codexctl/workspace/sswcenter-3-0`
> 기준 branch / HEAD: `main` / `059ecf3dbfb54ac0a896303702d74ef190f8d984`
> 작업 방식: `REMOTE / Ubuntu Linux`
> Git 경계: `NO_MERGE`; stage·commit·push·branch/worktree 변경은 형님 명시 지시가 있을 때만 수행

## 0. 지위와 선행 봉인

이 파일은 W3 현재 실행만 소유한다. W2 current plan과 W3 승인 전 decision packet을
사후 수정하지 않는다.

- W2 승인 봉인: `review/evidence/W2_20260817_USER_APPROVAL_SEAL.md`
- W2 reviewed manifest: 98 entries,
  SHA-256 `9b549c3233505413f548232842d1d2ca8b69aa0587f65c9b5aa1936be1c2c597`
- W3 승인 대상 packet SHA-256:
  `b0b0ecdb00fa56fb1bed58cfd0af60cf9260c06d5b420c70ee9ebc95e5af8e47`
- W3 승인 기록: `review/evidence/W3_20260817_USER_DECISION_SEAL.md`
- 형님 승인 원문: `ㄱㄱ` — 직전 `추천안 전체 승인`의 승인으로 기록

W2 manifest는 봉인 시점의 역사 증거다. W3가 정본·코드 경로를 의도적으로 전진시킨
뒤에는 current bytes가 W2 manifest와 같다고 주장하지 않는다. W3 후보는 별도 manifest로
동결한다.

## 1. 확정 계약

| ID | 확정값 | 이 단계의 경계 |
|---|---|---|
| W3-01 | `FILE_ONLY` | 내부 RFID 수집 API 없음 |
| W3-02 | `SINGLE_STATEFUL_WORKSPACE` | UI는 후속; 상태와 command 분리 |
| W3-03 | `STABLE_MAPPING_ONLY` | 유일·유효 stable mapping만 자동 |
| W3-04 | `UNIQUE_ONLY_ELSE_REVIEW` | 0/N 후보 자동선택 금지 |
| W3-05 | `DUAL_IDENTITY` | raw row·snapshot·occurrence identity 분리 |
| W3-06 | `RAW_ROWS_PLUS_DERIVED_GROUP` | 원본행 보존; 불명확 그룹은 `BLOCKED_REVIEW` |
| W3-07 | `W3_PRIVATE_CONTENT_RECEIPT_TYPED_LINK` | W3 private foundation만 먼저 구현 |
| W3-08 | `VERSIONED_MANUAL_SUPPLEMENT` | 원본 수정·unlinked 보완 금지 |
| W3-09 | `REVIEW_PENDING` | 동률·정확한 중간값 자동변경 0건 |

## 2. 현재 범위와 완료조건

이번 첫 slice는 다음을 순서대로 닫는다.

1. W3 승인 기록과 정본 결정표
2. 가명 semantic sample·expected·blocked workbook profile과 hash manifest
3. RED-A: 영속성 없는 계획정정 proposal 순수함수
4. RED-B: 0028 source-intake foundation 계약
5. 0028 migration·model·postcheck·active-head 전환과 PostgreSQL lifecycle

parser·matcher·APPLY/reconciliation·command/API/UI는 이 첫 foundation 뒤의 별도
RED→GREEN 단계다. 실제 workbook header profile이 없으므로 parser 구현은 시작하지 않는다.

첫 slice 완료조건:

- 승인값과 W4/W5 제외가 정본·현재 계획에 일치
- sample manifest의 모든 경로·SHA-256·bytes exact; v1/v2 historical bytes는 덮어쓰지 않고
  새 classifier v2·physical reorder v3만 추가
- RED-A가 먼저 기대한 실패를 관찰하고 구현 뒤 targeted test GREEN
- RED-B가 먼저 기대한 실패를 관찰하고 0028 구현 뒤 unit·contract·실 PostgreSQL GREEN
- 0027 historical verifier와 0028 current-head/readiness 역할 분리
- W2 harness의 lifecycle DB는 exact 0027 historical, BrowserDatabase는 exact active 0028
- W0/W1/W2 회귀·cleanup·manifest/diff gate에 새 실패 없음
- W4/W5 경로 유입 0

## 3. 샘플·profile 계약

샘플 루트는 `backend/tests/fixtures/w3/`로 한다.

- `profiles/*.blocked.json`: 실제 sheet/header/type 근거 부재를
  `BLOCKED_HEADER_PROFILE_MISSING`으로 기록한다.
- `cases/*.json`: 개인정보 없는 semantic 입력 사례다. 실제 외부 workbook shape로
  주장하지 않는다.
- `expected/*.json`: normalized/decision/write-count 기대 결과다.
- 실제 parser-ready `.xlsx`는 승인된 가명 실형상 header profile을 얻은 뒤에만 추가한다.
- `review/evidence/W3_20260817_PSEUDONYMOUS_SAMPLE_PACK.sha256`는
  `status|sha256|bytes|path` 형식으로 fixture pack을 동결한다.
- 원본 receipt·content·row는 덮어쓰지 않고, expected와 profile도 변경 시 새 version으로
  추가한다.

필수 사례:

- 계획정정: 1,799/1,800초, 1초 부족, 30분 exact midpoint, 5분 후보 동률
- source intake: 성공 duplicate/no-op, retryable `FAILED`, `BLOCKED` 재업로드 거부,
  새 profile reparse, 다른 digest candidate, 성공 APPLY 전 supersede 0
- 원본행: 240분 2행·480분 1행, 재정렬, 동일시각 복수 occurrence
- matching: staff stable mapping과 수급자·서비스·일정 0/1/N
- supplement: 생성·취소·재보완·stale·확정월 거부

## 4. RED-A — proposal-only 계획정정

파일:

- `backend/app/domains/w3/plan_adjustment.py`
- `backend/tests/test_w3_rfid_plan_adjustment.py`
- `review/evidence/W3_20260817_RED_A.md`

`propose_plan_adjustment(...)`는 `rule_version`을 포함한 immutable candidate proposal 또는
`REVIEW_PENDING`을 반환한다. DB/session/repository/event/API/UI 의존성과 계획 변경판
채택은 금지한다.

테스트는 다음을 exact assert한다.

- 1,799초 초과는 기존 서비스시간 유지
- 1,800초 이상은 가까운 30분 증가후보
- 1초 부족도 실제 이하 30분 감소후보와 `ACTUAL_SHORTAGE_YELLOW_DOT`
- 선택된 서비스시간을 유지하는 5분 grid 중 시작·종료 오차 합 최소
- 30분 exact midpoint와 최소오차 후보 동률은 `REVIEW_PENDING`
- 입력 불변, 반복 호출 결정성, plan/event/audit write 0

## 5. RED-B — 0028 source-intake foundation

계약 테스트:

- `backend/tests/test_w3_0028_contract.py`
- `backend/tests/test_w3_0028_postcheck_unit.py`
- `backend/tests/test_w3_0028_postgres.py`
- `backend/tests/test_w3_source_intake_unit.py`
- `backend/tests/test_w3_wave_boundary_contract.py`
- `review/evidence/W3_20260817_RED_B.md`

제품 seam:

- `backend/alembic/versions/20260817_0028_w3_source_intake_foundation.py`
- `backend/app/db/w3_models.py`
- `backend/alembic/env.py` metadata import
- `backend/app/db/postcheck_current_0028.py`
- `backend/app/db/postcheck_dispatch.py` active revision 0028 only
- `backend/app/core/readiness.py` exact current 0028
- `backend/tests/test_schema_contract.py` W3 object enumeration
- `scripts/restore-drill.ps1` active 0028 / historical 0027 분리
- `scripts/test-w3-0028-postgres-linux.ps1` 0027→0028→0027→0028

W2 회귀 harness의 main lifecycle/restore DB는 exact 0027과 historical direct verifier를
사용한다. 현재 FastAPI/Vite/Chromium을 띄우는 별도 BrowserDatabase는 exact active 0028로
올려 현재 readiness를 통과한다. 제품 readiness test bypass는 두지 않는다.

Foundation이 고정할 계약:

- immutable private content → source snapshot → append-only receipt → import run/attempt
  composite lineage; matcher 전 target typed link 없음
- raw row 물리주소, source snapshot identity, 업무 occurrence identity 분리
- snapshot identity `(source_type, target_date, content_digest)`
- 동일 digest/profile 분기: 성공 결과 duplicate/no-op, retryable `FAILED` retry,
  `BLOCKED` 재업로드 우회 거부
- 동일 digest/new profile은 같은 snapshot reparse
- 다른 digest는 candidate이며 성공 APPLY 전 active 변경·`SUPERSEDED` 0건
- quarantine/legal hold 우선, 자동 GC 비활성
- `BLOCKED` run 부분적용 0건
- generic `target_type + target_id` 금지, matcher 전 W1/W2 reverse FK·target link도 없음

Versioned reconciliation·성공 APPLY 원자 swap·manual supplement command는 후속 RED다.

## 6. 후속 구현 순서

1. 실제 header profile 승인과 parser 정상·경계·오류 RED
2. 공단/RFID parser와 row 불변 계보
3. 직원 stable mapping → 수급자·서비스·일정 0/1/N matcher
4. actual-work evidence ledger와 source snapshot APPLY/reconciliation
5. plan-adjustment apply와 versioned manual supplement command
6. 승인된 API/OpenAPI
7. `SINGLE_STATEFUL_WORKSPACE` UI와 실제 browser 경합
8. 전체 PostgreSQL/restore/concurrency/workbook/browser/cleanup 및 W0~W2 회귀

## 7. 상태 의미와 운영 규칙

- `BLOCKED`: profile·계약·입력 결함 때문에 적용할 수 없으며 부분 적용 0건이다.
- `FAILED`: 실행 실패이며 retry 가능 여부를 별도 기록하고 직전 projection을 유지한다.
- `REVIEW_PENDING`: 안전한 자동선택이 없으며 사용자 명시 선택 전 write 0건이다.
- `WARNING`: 명시 confirm 전 write 0건이다.
- provider timeout·transport 오류·max-turns·중단은 PASS나 부분 PASS로 낮추지 않는다.
- provider 선언보다 현재 bytes, diff, 실행한 테스트와 cleanup 증거를 우선한다.
- DeepSeek는 형님 정책대로 비상용으로만 사용한다.

## 8. 실행 라운드

형님이 승인한 기본 순서를 따른다.

1. Luna max read-only 초안
2. Grok xhigh 테스트·read-only 검수
3. Grok xhigh FIX
4. Terra max 테스트·read-only 검수
5. Terra max FIX
6. Grok xhigh 재테스트·read-only 재검수
7. Grok xhigh FIX
8. Sol ultra 최종 read-only 검수

한 실행에는 한 actor와 한 action만 둔다. 구현/FIX와 REVIEW는 분리한다. 긴 migration,
PostgreSQL, browser는 처음부터 최대 turn·timeout을 주고, timeout 시 동일 결과를 PASS로
계산하지 않으며 현재 파일·process·listener·temp를 확인한 뒤 재개 또는 별도 actor로
복구한다.

## 9. 진행 ledger

| 단계 | 상태 | 증거·다음 행동 |
|---|---|---|
| Runtime | `PASS` | `SSWCENTER_RUNTIME_GREEN` |
| Luna 승인/fixture/transition 정찰 | `PASS` | read-only 3개 병렬 대조, 변경 0 |
| W3 결정 승인 | `APPROVED` | 형님 `ㄱㄱ`, 새 seal 작성 |
| 정본 반영 | `PASS` | docs 02·06 승인값 최소 반영; parent delta 85/98 + 의도 13 |
| sample pack | `SEMANTIC_BASELINE_READY` | 15 files, v1/v2 historical 보존 + classifier v2 + physical reorder v3, blocked profile + hash manifest; `.xlsx` 없음 |
| RED-A | `TARGETED_GREEN` | missing-module RED → 10 PASS, Ruff/format/mypy PASS |
| RED-B | `TERRA_P2_HOST_GREEN / CANDIDATE_MANIFEST_REGENERATED / INDEPENDENT_REVIEW_PENDING` | 숨은 무권한 `w3_*` 관계와 historical 0027 rogue second head false-green을 닫은 뒤 W3 lifecycle 23 live·restore·seal·cleanup 0, W2 rogue rejection·historical 29/1·active HTTP·real Chromium·restore·seal·cleanup 0을 재확인했다. 과거 nullable-ACL 및 첫 W2 scalar-oracle 실패는 아래 문제 ledger에 보존한다. 현재 바이트를 새 candidate manifest로 동결하고 독립 Grok/Terra와 Sol Ultra를 다음 gate로 둔다. |
| parser | `BLOCKED` | approved pseudonymous real-shaped header profile 필요 |
| matcher/APPLY/API/UI | `DEFERRED` | foundation과 parser 뒤 순차 진행 |
| Git | `NOT_REQUESTED` | stage/commit/push/merge 없음 |

## 10. 중간 문제 ledger

1. W2 reviewed manifest에 포함된 current plan을 W3 상태로 수정하면 W2 봉인 증거를
   훼손한다. 새 W3 current plan과 승인 봉인을 만들어 해결한다.
2. 정본에는 실제 workbook sheet/header/type profile이 없다. `.xlsx` header를 추측하지
   않고 blocked profile과 semantic expected만 먼저 동결한다.
3. `RAW_ROWS_PLUS_DERIVED_GROUP`는 선택됐지만 구체 grouping signature는 공식 식별자나
   승인된 sample 전까지 미확정이다. duration 합계만으로 자동 그룹화하지 않는다.
4. W3 active head 0028 전환 뒤 exact-0027 W2 browser DB는 현재 readiness를 통과할 수
   없다. W2 harness의 historical lifecycle DB와 active BrowserDatabase 역할을 분리한다.
5. RED-A 최초 pytest는 기존 Windows 임시경로 유입으로 capture cleanup
   `FileNotFoundError`가 났다. Linux `/tmp`·`-s`로 재실행해 실제 missing-module RED를
   분리했다.
6. 최초 RED-A static은 import-order 2건으로 실패했다. Ruff mechanical fix·format 후
   같은 범위의 check·format-check·mypy·pytest가 모두 PASS했다.
7. Grok REVIEW P2: same digest/profile 미지 상태가 `START_PROFILE_RUN`으로
   fail-open했다. 닫힌 attempt enum만 허용하고 hostile 상태는 ValueError로
   닫았다.
8. Grok REVIEW P3: v1 fixture 바이트를 덮어쓰지 않고 reorder semantic v2와
   matching/supplement loader 계약 테스트를 추가했다.
9. 0028 schema RED는 `app.db.postcheck_current_0028` missing-module로 먼저
   관찰했다. provider sandbox에는 pwsh가 없어 실 PostgreSQL/restore/2-connection
   증명은 host Codex 게이트로 남긴다.
10. 첫 host PostgreSQL은 `0027→0028→0027→0028`와 application ACL, cleanup
    listener/process/temp/git_delta=0을 통과했지만 current postcheck에서 CHECK 이름이
    naming convention으로 double-prefix된 것을 발견했다. PG GREEN을 주장하지 않고
    migration `op.f`, ORM `conv`, exact catalog test로 교정 후 재실행한다.
11. receipt가 content만 가리키고 attempt가 receipt를 가리키지 않아 duplicate/retry/
    `BLOCKED` receipt의 기존 success/run 계보와 mismatch 차단을 DB가 보장하지 못했다.
    여섯 table을 유지한 채 content/snapshot/receipt/run/attempt composite FK로
    동일성을 선언적으로 강제한다. snapshot profile은 제거하고 profile 소유자를 run으로
    단일화한다.
12. Terra FIX 종료 전 Ruff가 import order와 네 줄의 formatting drift를 보고했다.
    mechanical format 후 같은 scoped Ruff check/format-check가 PASS했고, 이 문제를
    PostgreSQL GREEN과 혼동하지 않는다.
13. CHECK 이름 교정 뒤 host PostgreSQL 재실행은 PG16 deparse가 migration 원문과
    표기만 다르다는 `CURRENT_0028_CHECK_MISMATCH`를 발견했다. `IN`→`ANY(ARRAY)`,
    `NOT LIKE`→`!~~`, `position` parenthesis, display-only `::text`만 canonical form으로
    고정하되 `CHECK(true)`·값 축소·missing/extra check를 허용하지 않도록 fake-catalog
    mutation test를 추가하고 재실행한다.
14. W2 host wrapper는 29개 historical DB test를 통과한 뒤 historical 0027 DB에서
    current FastAPI `eligible-assignees`를 호출해 `503 NOT_READY /
    alembic_revision_mismatch`를 관찰했다. cleanup은 0이었다. 0027 direct verifier와
    history DB는 보존하고, 해당 current-TestClient node는 historical run에서 explicit
    deselect한다. active 0028 BrowserDatabase의 dispatcher는 0028 marker와 current-head
    marker를 각각 확인하고, 새 active test가 `/health/ready`와 original HTTP node 전체
    (ADMIN/USER·CSRF·close-403·reassign/409/current response)를 실제
    FastAPI→service→PostgreSQL로 재실행한다. restore caller도 historical-0027 marker
    present/current-head marker absent를 직접 확인한다. production readiness bypass는
    금지한다.
15. split 보정 뒤 host W2 rerun은 historical `29 passed, 1 deselected`, active-0028
    dispatcher, original full HTTP contract `1 passed`, Chromium `1 passed`까지 통과했지만
    마지막 `W2_0027_POSTGRES_RESTORE_HISTORICAL_0027_MARKER_MISSING`에서 실패했다.
    cleanup은 `listener/process/temp/git_delta=0`이었다. 원인은 restore의 outer direct
    verifier gate가 0025/0026/0028만 포함하고 0027을 누락해 inner 0027 marker branch가
    unreachable했던 것이다. outer gate에 0027을 추가하고 caller-visible marker를 static
    assert했으며, host rerun 전까지 PASS로 낮추지 않는다.
16. main이 최종 W3 wrapper `0027→0028→0027→0028` 14 passed와 W2 wrapper
    historical 29 passed/1 deselected, active-0028 original HTTP 1 passed,
    real Chromium 1 passed를 닫고 restore/live/seal green, cleanup 0을 확인했다.
    이전 4회 실패는 실패로 유지한다. 이 증거를 `HOST_GREEN`으로 기록한다.
17. Grok REVIEW: `_canonical_check_definition`의 전역 `.lower()`가 quoted
    `'NONE'`/`'none'`, `'RFID'`/`'rfid'`, `'SUCCEEDED'`/`'succeeded'`를 같은
    CHECK로 정규화했다. quote-aware case fold로 고치고 fake-catalog mutation
    테스트를 추가한다. 실제 PG16 deparse와 기존 weakening 거부는 유지한다.
18. Grok REVIEW: parent W2 delta가 0028 전환으로 바뀐
    `test_foundation_0025_contract.py`와 `test_w1e_phase1_contract.py`를 빼
    87/11로 남아 있었다. 재계산 후 85/13/unauthorized 0으로 고친다. W2
    manifest/seal/current plan/W3 decision packet은 불변이다.
19. Grok REVIEW: W3 host restore caller가 generic `RESTORE_DRILL_OK`만 확인하고
    `SSWCENTER_CURRENT_0028_DB_POSTCHECK_OK`와
    `SSWCENTER_CURRENT_HEAD_POSTCHECK_OK`를 captured restore output에서 요구하지
    않았다. caller와 static 테스트를 추가한다.
20. Grok REVIEW: docs/06 W3-05·W3-07이 여전히 `schema 전`/`W3 DDL RED`였다.
    0028 schema foundation 완료, parser/matcher/APPLY 후속, header profile
    차단만 반영하고 범위를 넓히지 않는다.
21. Sol Ultra 최종 REVIEW `STATUS=FAIL`. P1: `_canonical_predicate` 전역
    `.lower()`가 quoted `ACTIVE`를 접음; snapshot/run table-wide UPDATE;
    CHECK가 table+name에 묶이지 않음; 열 ACL 미검사. P2: 여섯 표 exact
    catalog(type/null/default/identity/PK/explicit index) 부족; 0028
    revision verifier가 alembic_version 전체 행을 요구하지 않음; race
    oracle이 모든 Exception을 reject로 접음. P3: 0028 migration Ruff
    format, current plan stale `96/98 + 2`. 이전 host GREEN을 덮어쓰지
    않고 `FIX_REQUIRED / RETEST_REQUIRED`로 내린다. 긴 host wrapper는
    이 FIX에서 실행하지 않는다.
22. Sol finding FIX 뒤 첫 host W3 실행은 새 live node 18개와 wrapper의 과거 14개
    allowlist가 달라 `W3_0028_POSTGRES_NODE_DRIFT`로 cluster 시작 전에 실패했다.
    wrapper node 배열을 실제 test 함수 순서와 exact 동기화했다.
23. 다음 host W3 실행은 owner의 정상 ACL까지 exact app/backup ACL에 포함해
    `CURRENT_0028_TABLE_RELACL_MISMATCH`로 실패했다. table owner만 제외하고 PUBLIC과
    예상 밖 role grant는 계속 검사하도록 고쳤으며 cleanup은 0이었다.
24. 다음 host W3 실행은 17 passed 뒤 새 ACL test가 이미 커밋된 `DIGEST_C`를
    재사용해 unique fixture 충돌로 1 failed였다. 전용 `DIGEST_D`로 분리했고 cleanup은
    0이었다.
25. 현재 바이트에서 main이 W3 lifecycle + 18 live PG + restore/live/seal + bounded
    stop + cleanup 0과, W2 historical 29 passed/1 deselected + active-0028 full HTTP 1 +
    real Chromium 1 + restore/live/seal + cleanup 0을 확인했다. Sol 실패 기록은 유지하며
    새 candidate manifest와 Sol Ultra read-only 재검수를 다음 gate로 둔다.
26. Terra 독립 REVIEW `STATUS=FAIL`. Residual 1 P1: table/identity sequence owner를
    exact `erp_owner`와 `OWNED BY table.id`로 검사하지 않고 owner ACL만 제외했다.
    Residual 2 P2: W3 identity sequence relacl과 공유 `erp` schema ACL의
    PUBLIC/third-party/grant-option/unexpected grantor 전수 검사가 없다. Residual 3
    P2: PK `condeferrable`/`condeferred`와 non-constraint index 전수
    (AM/key/INCLUDE/partial/expression/hash) exactness가 부족하다. 이전 host GREEN을
    덮어쓰지 않고 `FIX_REQUIRED / RETEST_REQUIRED`로 내린다.
27. 이 Grok FIX 중 focused pytest가 두 번 실패했다. (a) `OWNER TO erp_owner`를
    loop f-string으로 한 줄만 남겨 contract가 `count == 6`에서 실패. (b) 주석의
    `ALTER SEQUENCE` 문자열이 executable 부재 검사와 충돌. 여섯 table의 명시
    `ALTER TABLE ... OWNER TO erp_owner`와 executable-only 검사로 고쳤다. 같은
    라운드에서 Ruff format-check 2파일도 실패했고 mechanical format 후 PASS했다.
    이 중간 실패를 host/live GREEN으로 낮추지 않는다.
28. Codex host의 첫 focused pytest는 다른 정적 gate와 병렬 실행 중 capture 임시파일
    `FileNotFoundError`로 exit 1, `no tests ran`이었다. capture를 끈 `-s` 직렬 재실행은
    76 passed/21 live-PG skipped였다. 이어 W3 lifecycle 21 live passed,
    restore/live/seal/bounded-stop/cleanup 0과 W2 historical 29 passed/1 deselected,
    active-0028 full HTTP 1 passed, real Chromium 1 passed, restore/live/seal/cleanup 0을
    확인했다. 이 증거는 독립 Grok/Terra 재검수와 Sol Ultra 전의 host GREEN이다.
29. Terra 독립 REVIEW Finding A P2: `_acl_non_owner_drifts`가 sequence/schema
    owner-self 일반 권한 집합을 무시해 부분/적대 non-grantable owner row가
    false-green할 수 있다. owner ACL은 없거나 PG16 canonical 전체 집합
    (sequence SELECT/UPDATE/USAGE, schema CREATE/USAGE, grantor=erp_owner,
    grantable=false)만 허용해야 한다.
30. Grok 독립 REVIEW Finding B P2: table relacl과 column attacl이 grantor를
    보지 않는다. table non-owner는 erp_app SELECT+INSERT / erp_backup SELECT
    (grantor=erp_owner, no grant option). owner는 없거나 PG16 table owner 전체
    집합. column은 snapshot.status·import_run.status만 erp_app UPDATE from
    owner이며 나머지 non-owner column ACL은 비어야 하고, 물질화된 owner
    column ACL은 없거나 SELECT/INSERT/UPDATE/REFERENCES 전체 집합만 허용한다.
31. Grok 독립 REVIEW Finding C P3: append-only permission oracle이
    ProgrammingError|IntegrityError를 SQLSTATE 없이 받아 receipt DELETE가
    FK 23503만으로도 통과할 수 있다. 모든 문은 42501이어야 한다.
32. 이 세 finding으로 상태를 `FIX_REQUIRED / RETEST_REQUIRED`로 내린다. 이전
    host 수치는 덮어쓰지 않지만 현재 최종 HOST_GREEN/PASS로 유지하지 않는다.
33. 이 Grok FIX 중 첫 Ruff check가 leftover `_acl_non_owner_drifts`(F821)와
    E501/format-check 2파일로 실패했다. helper 교체와 mechanical format 후
    scoped Ruff는 PASS했다. pwsh 부재로 ensure/verify-runtime과 PowerShell
    AST는 실행하지 않았고 runtime GREEN을 선언하지 않는다. focused pytest는
    70 passed/22 live skipped, broader 82 passed/23 skipped다. 긴 host W3/W2
    wrapper는 실행하지 않았다.
34. Codex host가 exact ACL patch를 재실행했다. `0027→0028→0027→0028`와
    application ACL, bounded stop, cleanup listener/process/temp/git_delta=0은
    통과했지만 current postcheck가 live nodes 전에
    `psycopg.errors.InvalidParameterValue: ACL arrays must be one-dimensional`로
    실패했다. `_verify_w3_column_attacl_entries`의
    `aclexplode(COALESCE(attribute_row.attacl, {}::aclitem[]))`가 NULL attacl을
    0차원 빈 배열로 치환한 것이 원인이다. 이 실패와 cleanup 0은 유지한다.
    이 Grok FIX는 column/table/sequence/schema 질의를
    `LEFT JOIN LATERAL aclexplode(<acl_column>)` 직접 호출로 바꾸고, column
    owner live mutation을
    `GRANT SELECT (status), INSERT (status), UPDATE (status), REFERENCES (status)`로
    고치며 fake/catalog가 그 SQL 형태를 고정한다. live node 22개는 그대로다.
    pwsh 부재로 ensure/verify-runtime은 실행하지 않았고 runtime GREEN을
    선언하지 않는다. focused pytest는 71 passed/22 live skipped, broader
    83 passed/23 skipped다. 긴 host wrapper는 실행하지 않았으며 상태는
    `FIX_REQUIRED / RETEST_REQUIRED`다.
35. nullable ACL FIX 뒤 Codex host 재실행은 W3 lifecycle 22 live passed,
    restore/live/seal/bounded-stop/cleanup 0을 통과했다. 이어 W2 historical
    29 passed/1 deselected, active-0028 full HTTP 1 passed, real Chromium 1 passed,
    restore/live/seal/cleanup 0도 통과했다. 이 결과는 FIX-3 host GREEN이며 최종
    봉인은 아니다. 새 candidate manifest와 독립 Grok/Terra review, Sol Ultra를
    다음 gate로 둔다.
36. W3 candidate manifest 첫 교체는 같은 path를 delete+add하는 `apply_patch` 형식이
    거부되어 파일 무변경으로 끝났다. 전체 `Update File` diff로 재시도해 성공했고,
    ledger 반영 뒤 동일 140-path scope를 최종 재생성해 status/hash/bytes mismatch 0,
    extra 0, missing 0을 독립 review 시작조건으로 둔다.
37. Terra 독립 REVIEW P2: current 0028 `_verify_tables()`가 privilege-filtered
    `information_schema.tables`를 사용해 `erp_app` 권한이 없는 rogue `w3_*`
    관계를 못 볼 수 있었다. `pg_class + pg_namespace`와 exact relkind
    `r/p/v/f`로 전환하고 fake catalog, erp_app 42501, dispatcher marker-absence
    live node를 추가했다. 격리 one-node PostgreSQL은 1 passed, listener/temp 0이다.
38. Terra 독립 REVIEW P2: historical 0027 verifier가 scalar 첫 revision만 읽어
    rogue second head를 비결정적으로 통과할 수 있었다. 전체 revision 집합이 정확히
    `[0027]`일 때만 통과하도록 바꾸고 W2 historical harness에 rogue 삽입, 양 marker
    부재, 정리 뒤 sole-head 복구 oracle을 넣었다. 단위 26 passed, Ruff/mypy/PS AST는
    녹색이며 긴 W2 host 검증은 다음 gate다.
39. Terra REVIEW P3: 진행 ledger의 RED-B 행이 이미 끝난 FIX-3 host 재실행을
    `live wrapper 재실행 전`으로 잘못 표시했다. 과거 nullable ACL 실패는 문제 34에
    그대로 두고, 현재 행은 FIX-3 host GREEN과 새 Terra P2 fix의 host-retest 대기로
    분리해 바로잡았다.
40. 합산 focused pytest 첫 실행은 제품 실패가 아니라 parent W2 delta의 위 두
    intentional path SHA/bytes가 새 P2 수정 전 값이라 1 failed, 83 passed,
    24 skipped였다. current bytes로 두 delta row를 갱신한 뒤 동일 test를 재실행한다.
41. parent delta 갱신 뒤 합산 focused는 84 passed, 24 expected live-PG/harness
    skipped로 녹색이었다. W3 host는 `0027→0028→0027→0028`, 새 hidden-relation을
    포함한 23 live passed, restore/live/seal, bounded stop, cleanup
    listener/process/temp/git_delta=0을 통과했다.
42. 첫 W2 host 재실행은 rogue head를 정상 거부하고 정리했지만 sole revision query가
    한 문자열일 때 `$RestoredRevisions.Count`를 찾지 못해 StrictMode
    `ParentContainsErrorRecordException`으로 실패했다. wrapper cleanup 네 항목은 0이었다.
    Grok xhigh FIX는 10분/12-turn 상한 안에서 `max turns reached`로 실패했으나 종료 직전
    두 파일 patch를 남겼다. provider 상태는 PASS로 세지 않고 현재 바이트를 Codex가
    단위 2 passed, Ruff, PS AST로 재검증했다.
43. 배열 전체 pipeline을 `@(...)`로 정규화한 뒤 W2 host를 처음부터 재실행했다.
    rogue second head rejection marker, historical 29 passed/1 deselected, active-0028
    full HTTP 1 passed, real Chromium 1 passed, restore/live/seal, cleanup 네 항목 0이
    모두 녹색이다. 이 결과 뒤 parent delta와 candidate manifest를 current bytes로
    재생성하고 독립 검수를 다시 시작한다.
44. 첫 manifest exact verifier는 선언 경로 추출에 `/^[ #]/!p`를 써서 status가
    공백으로 시작하는 tracked-modified 58개 경로까지 헤더로 오인했고 `extras=58`을
    잘못 보고했다. candidate drift가 아니며, 헤더만 제외하는 `/^#/!p`로 고친
    동일 검사는 current scope 141 entries, status/hash/bytes mismatch 0, extras 0,
    missing 0이다. 이 ledger 반영 뒤 manifest를 한 번 더 재생성한다.
