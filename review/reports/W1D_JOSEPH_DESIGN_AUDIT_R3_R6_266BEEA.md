# W1D Joseph R3/R6 독립 설계·실행 RED 감사

## 1. 판정 요약

- 감사자: Joseph fallback independent auditor
- 감사 범위: W1D Phase 1 설계 + executable RED만. 제품 구현·migration·generated client·UI 구현은 범위 밖이며 시작하지 않았다.
- 감사 기준: 현재 바이트, codex/w1d-contract-transition, HEAD 266beeaa2d150371ccd1a0f26f69249eca86ba16
- 최종 판정: REQUIRED_CHANGES
- confirmed findings: BLOCKER 2, HIGH 6, MEDIUM 6, LOW 1 (총 15건)
- 이 판정은 Phase 1 설계/RED 승인도 아니며 W1D 제품 GREEN/PASS가 아니다.

R2 이후 일부 지적은 실제로 보강됐다. virgin counter None 선행조건과 product-first pg_00, 유효한 certification-date mutation commit, replacement 누락/부분/추가/중복/wrong-service/field 변조 matrix, open-ended conflict matrix, 전용 stale UI path, tablet page-B context.newPage(), winner response 대기와 loser exact 409 STALE가 현재 바이트에 존재한다. 그러나 아래 결함들이 future-GREEN을 false-pass 없이 강제하지 못한다.

## 2. 정체성·범위·상태

실제 확인값:

| 항목 | 값 |
|---|---|
| cwd | C:\sswcenter\2.1 |
| branch | codex/w1d-contract-transition |
| HEAD | 266beeaa2d150371ccd1a0f26f69249eca86ba16 |
| pre-report porcelain | 12개 untracked, tracked/staged delta 0 |
| 제품 구현 부재 | backend/app/domains/w1d, 20260730_0011_w1d_recipient_contract.py, frontend/src/services/w1dApi.ts, RecipientContractPanel.tsx 모두 absent |

읽은 기준 문서:

- README.md, docs/00_정본_문서_목록.md, docs/AI_업무분담_운영규정_v3.5.md
- review/packets/W1D_ASSIGNMENT_PACKET_v1.0.md, review/plans/W1D_CONTRACT_TRANSITION_PLAN.md, review/evidence/w1d/RED.md
- review/reports/W1D_JOSEPH_DESIGN_AUDIT_R2_266BEEA.md, review/environment/office/2026-07-30_W1D.md의 R2~R6 기록
- docs/02_업무규칙_계약_v1.1.md §4.1/§4.4/§6/§7, docs/03_UI_API_상호작용_계약_v1.2.md §4.1~§4.2/§5/§8, docs/04_데이터_DB_불변조건_v4.8_PostgreSQL.md §4.1/§5/§8/§10, docs/06_개발로드맵_결정현황_v1.2.md W1D 행, review/WAVE1_CLEAN_TEST_MATRIX.md의 W1-REC-03/W1-SIG-01/W1-CON-01~04/W1-TRN-01~04/W1-ABS-08~10

7개 감사 대상 SHA-256은 모두 expected와 일치했다.

| path | SHA-256 |
|---|---|
| review/plans/W1D_CONTRACT_TRANSITION_PLAN.md | 594f14ee736d71831f39ee9846ea54b05d3d1c82cdd2f855c300c5ce827b6dc0 |
| review/evidence/w1d/RED.md | 93527fed6d98671f2558f06eab809f90cea793e1c50de3f82d18d17db3711919 |
| backend/tests/test_w1d_contract.py | 1b8be350c9d6377ebb832d071290fca2b84ef80c49c6be0c84f014cf33e293d0 |
| backend/tests/test_w1d_postgres.py | 401bf48f237cd8b652989fc21005e69ebea6b7bbd968b620177e574cff174d08 |
| frontend/src/test/W1DContractTransition.test.tsx | e9c89b69dd7185ca5dc2dde252af7a5a44abcaa19054008d8aa7da593ff07e72 |
| frontend/e2e/w1d-contract-transition.spec.ts | 8b168277a43d4bdadd5f495d4dd7f7f04a290995227ecd87fa4cf8c29f2d8fbe |
| scripts/test-w1d-postgres.ps1 | b58aed1133f821d066b0ecd6629fb18be738038313aca810ede8390f1bc689cd |

## 3. 검사와 live evidence

실행한 read-only 검사:

| 명령/검사 | 결과 |
|---|---|
| strict UTF8Encoding(false,true) + trailing-whitespace scanner, exact 7 paths | UTF-8 errors 0, trailing whitespace 0, 7/7 |
| [System.Management.Automation.Language.Parser]::ParseFile, scripts/test-w1d-postgres.ps1 | exit 0, errors 0 |
| backend/.venv/Scripts/python.exe -c "import ast..." on two Python tests | exit 0, files 2/2 |
| backend/.venv/Scripts/ruff.exe check tests/test_w1d_contract.py tests/test_w1d_postgres.py | exit 1, 15 diagnostics |
| same Ruff command with --select F821,F841 | exit 1, 6 diagnostics; time F821 3건과 unused post_setup 1건 포함 |
| backend/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --collect-only tests/test_w1d_contract.py tests/test_w1d_postgres.py (cwd backend) | exit 0, 23 collected, 1 dependency warning |
| frontend/node_modules/.bin/playwright.cmd test e2e/w1d-contract-transition.spec.ts --list --workers=1 (cwd frontend) | exit 0, 9 tests/1 file |
| git diff --check | exit 0; tracked delta가 없어 untracked 7개를 포함하지 않음 |

R6 live PostgreSQL/FastAPI/Vite/Playwright는 현재 7개 SHA와 RED.md/office R6의 final SHA가 일치하므로 재실행하지 않았다. 공유 harness 중첩을 피하기 위한 exact-final-byte evidence 재사용이다. 기록된 R6 명령은 powershell -NoProfile -File .\scripts\test-w1d-postgres.ps1 -Port 55463 -BackendPort 18105 -FrontendPort 14205, wrapper exit 1, W1C-head harness exit 0, pg_00/product rest는 W1D revision 부재에 따른 product RED, 9개 W1B baseline marker, 3 scenarios × 3 projects의 product marker RED, listener/process/temp/artifact 0이다. 현재 read-only cleanup 확인에서도 R6 포트 listener 0, 외부 matching W1D process 0, frontend/test-results/playwright-report 없음이었다. 이 evidence는 제품 GREEN을 입증하지 않는다.

## 4. Confirmed findings

### BLOCKER

#### J-W1D-R3-B01 — pg_08 lock-wait monitor가 실행 불능

- 위치: backend/tests/test_w1d_postgres.py:17, :2217-2236
- 근거: monitor_both_waiting()이 time.time()/time.sleep()를 호출하지만 time을 import하지 않는다. Ruff F821이 같은 파일에서 3건을 재현했다. thread는 NameError로 종료하고 both_waiting을 세우지 못하므로 본문은 20초 후 W1D_TRN03_LOCK_WAIT_NOT_OBSERVED로 실패한다.
- 영향: blocker transaction 뒤 두 apply가 실제 wait_event_type='Lock'인지를 요구하는 R2-H02 핵심 RED가 future-GREEN에서 실행되지 않는다.
- correction: time import와 monitor thread exception channel을 추가하고, monitor 예외·join 미완료도 harness failure로 fail-closed한다. 실제 W1D revision에서 다시 1 success + 1 exact STALE 및 최종 row/audit 검사를 실행한다.

#### J-W1D-R3-B02 — wrapper가 cleanup 실패 뒤에도 GREEN을 출력할 수 있음

- 위치: scripts/test-w1d-postgres.ps1:666-689, :718-821
- 근거: W1D_POSTGRES_GREEN을 final cleanup 전에 출력한다. Playwright artifact 삭제 실패, temp 삭제 retry 실패, Postgres stop warning은 Write-Output만 하고 $ScriptExitCode를 실패로 바꾸거나 throw하지 않는다. listener/process 열거도 -ErrorAction SilentlyContinue라 query failure를 0으로 만들 수 있고, 최종 W1D_CLEANUP listener=... process=... temp=...는 판정을 바꾸지 않는다.
- 영향: 제품 stage가 모두 성공한 future-GREEN에서 artifact/temp/process/listener residual 또는 검사 오류가 있어도 exit 0과 GREEN marker가 공존할 수 있다. 이는 wrapper false-green이다.
- correction: 모든 stage와 cleanup/검사 완료 뒤에만 GREEN을 출력하고, artifact count·listener/process/temp residual·enumeration failure·cleanup warning을 harness failure와 nonzero exit로 승격한다.

### HIGH

#### J-W1D-R3-H01 — raw cross-group test가 실제 DB 동시 INSERT를 증명하지 않음

- 위치: backend/tests/test_w1d_postgres.py:2760-2825
- 근거: barrier는 각 worker가 engine/transaction을 만든 뒤가 아니라 raw_insert() 호출 전(:2786-2795)에만 있다. 두 INSERT의 DB overlap 또는 lock wait를 관측하지 않는다. 실패 판정도 SQLSTATE 23P01/정확한 constraint name 외에 오류 문자열의 "exclusion" substring을 허용한다.
- 영향: non-serialized trigger가 scheduling상 순차 실행되어도 1 commit + 1 failure로 false-pass할 수 있다. R2-H03의 concurrency-safe DB enforcement가 닫히지 않았다.
- correction: 두 raw connection을 먼저 열고 transaction을 시작한 뒤 insert barrier를 두고, parent-row lock wait를 pg_stat_activity로 관측한다. exact SQLSTATE/constraint name만 허용하고 same-group 2 commit도 같은 방식으로 확인한다.

#### J-W1D-R3-H02 — full ledger write-zero fingerprint가 실제 전체 원장을 봉인하지 않음

- 위치: backend/tests/test_w1d_postgres.py:442-502, :1986-2078, :2535-2540, :2580-2635
- 근거: _full_ledger_fingerprint()는 updated_at_utc, contract의 service_start_date, signer relationship/phone, replacement FK, actor/timestamp 및 audit before/after/actor/time 등을 읽지 않는다. cert-date/contract-date stale는 setup fingerprint를 저장만 하고(post_setup은 unused) apply 뒤 동일성 비교를 하지 않는다. token invalid/null/blank service path도 최종 contract count만 비교한다.
- 영향: preview/mismatch/stale/token/fault/ACL failure가 누락된 컬럼·row_version 외 metadata·audit field를 쓰고도 통과할 수 있다. pg_10의 10 seam rollback도 이 불완전한 fingerprint에 의존한다.
- correction: 각 negative/fault case마다 identity, cert, grade, contract의 전체 canonical columns와 recipient/counter/audit 전체 row delta를 snapshot하고 before/after byte-equivalent를 비교한다. 모든 stale dimension과 token path를 per-case write-zero로 봉인한다.

#### J-W1D-R3-H03 — aggregate audit의 event 수와 projection 값이 exact하지 않음

- 위치: backend/tests/test_w1d_postgres.py:1581-1678
- 근거: step_actions는 몇 개의 알려진 action code만 0인지 보며, audit_id_before 이후 전체 audit row가 정확히 1건인지 확인하지 않는다. before_json/after_json은 key 존재, after-only new_ids, canary 부재만 검사하고 stale hash, before/after periods/contracts/multiset/row_version의 값이 실제 persisted rows와 같은지 비교하지 않는다.
- 영향: 다른 action code의 추가 audit 또는 잘못된 비식별 projection이 aggregate 1건·actor/reason/source/request UUID·clock window 검사를 통과할 수 있다. R2-M02는 metadata 일부만 닫혔고 exact audit contract는 미폐쇄다.
- correction: apply 전후 audit row set 전체를 비교해 aggregate 한 건만 허용하고, persisted pre/post projection을 동일 canonical serializer로 생성해 JSON exact equality를 검사한다. new_ids는 after-only이며 response와 실제 row set 모두와 일치시킨다.

#### J-W1D-R3-H04 — transition preview/apply의 ACL·CSRF RED가 없음

- 위치: backend/tests/test_w1d_postgres.py:1817-1900, :3091-3159
- 근거: no-CSRF, no-permission, VIEW-only 검사는 contract collection POST만 호출한다. transition preview/apply 및 contract end에 대해 no-permission/VIEW-only 403, missing-CSRF 403, exact envelope와 write-zero를 호출하지 않는다.
- 영향: contract create만 보호하고 preview/apply를 노출하는 잘못된 router/policy도 RED를 통과할 수 있다. 계획 §2.4는 preview/apply를 RECIPIENT_MANAGE + CSRF mutation으로 봉인한다.
- correction: create/end/preview/apply 각 unsafe operation에 대해 unauth 401, no-permission/VIEW-only exact 403, no-CSRF exact 403, top-level envelope 및 전체 fingerprint write-zero를 독립 case로 추가한다.

#### J-W1D-R3-H05 — PostgreSQL/pytest/Playwright child에 wrapper-level timeout이 없음

- 위치: scripts/test-w1d-postgres.ps1:216-240, :559-560
- 근거: harness/product pytest와 npm Playwright를 &로 직접 실행하며 bounded process timeout/watchdog가 없다. 일부 test worker/expect에는 내부 timeout이 있지만 pytest collection/fixture/DB call 또는 npm process 자체의 hang을 wrapper가 제한하지 않는다.
- 영향: deadlock·hung child에서 wrapper가 종료·cleanup·분류에 도달하지 못해 gate가 무기한 대기하거나 외부 timeout 결과를 product evidence로 오인할 수 있다.
- correction: 각 child를 bounded process로 감시하고 timeout 시 process tree를 안전하게 종료한 뒤 W1D_HARNESS_*_TIMEOUT, residual 검사, nonzero exit을 보장한다.

#### J-W1D-R3-H06 — canonical preview hash 정의가 정본 04와 계획에서 충돌

- 위치: docs/04_데이터_DB_불변조건_v4.8_PostgreSQL.md:665-677, review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:221-277
- 근거: 정본 04 §10.1은 preview hash 입력에 “서비스별 대체계약 입력”을 명시한다. 계획의 DB-derived stale_hash projection은 사용자 replacement 본문을 제외하고, replacement는 HMAC token의 bound_replacements로만 봉인한다. 이는 보안상 합리적인 분리일 수 있지만 현재 정본을 덮을 최신 사용자 결정/개정은 제공되지 않았다.
- 영향: canonical_hash/stale_hash가 정본의 full preview hash인지 DB-only stale hash인지 구현자가 임의로 결정할 수 있어 STALE와 MISMATCH의 exact contract가 불명확하다.
- correction: 정본 소유자 승인으로 canonical_hash와 db_stale_hash를 분리해 둘지, full replacement input을 hash에 포함할지 명시하고 plan/RED/test의 이름·입력·비교 순서를 일치시킨다.

### MEDIUM

#### J-W1D-R3-M01 — OpenAPI success status와 error response binding이 느슨함

- 위치: backend/tests/test_w1d_contract.py:426-507, frontend/e2e/w1d-contract-transition.spec.ts:213-236
- 근거: OpenAPI RED는 mutation operation마다 200 또는 201 중 하나만 있으면 통과시키고, error code는 str(spec)에 문자열이 있는지만 본다. operation별 expected status와 409/422 response $ref/envelope binding은 검사하지 않는다. E2E winner도 status를 [200,201]로 허용한다.
- 영향: preview가 201, create가 200, error response가 설명 문자열에만 존재하는 drift도 통과할 수 있다.
- correction: create 201, preview/error/end/apply의 승인 status를 명시하고 모든 operation의 success/error status와 $ref를 exact 검사한다. apply 200/201 ambiguity도 먼저 봉인한다.

#### J-W1D-R3-M02 — list/get/end contract API의 executable RED가 부족함

- 위치: 계획 review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:72-111; 구조 검사 backend/tests/test_w1d_contract.py:370-448,645-653; runtime API는 backend/tests/test_w1d_postgres.py:1826-1900의 collection create에 한정
- 근거: list, item GET, end, expected_row_version stale 409의 실제 request/response와 DB 후조건을 호출하지 않는다. end_contract는 callable 존재만 검사한다.
- 영향: named route/schema만 있는 stub, end stale 무시, GET/list nullable/forbidden field drift가 product RED를 통과할 수 있다.
- correction: list/item GET, end success/stale, missing recipient/contract, row_version 증가와 error envelope를 real TestClient + PostgreSQL에서 추가한다.

#### J-W1D-R3-M03 — live E2E가 선언한 3 viewport와 winner response 전체를 봉인하지 않음

- 위치: frontend/playwright.config.ts:30-50, frontend/e2e/w1d-contract-transition.spec.ts:104-105,140-153,213-236
- 근거: config는 1440×1000/1440×900/1366×768 projects를 선언하지만 spec이 desktop/tablet/mobile 모두 setViewportSize()로 1440×900/1024×768/390×844를 덮어쓴다. tablet winner는 status, UUID, new cert/grade만 검사하고 new_contract_ids shape/rows는 live E2E에서 확인하지 않는다.
- 영향: 9 marker는 유지되지만 declared project viewport coverage가 실제와 다르고, winner response의 계약 ID 누락이 UI race RED를 통과할 수 있다.
- correction: project viewport를 유지하거나 의도한 scenario×viewport matrix를 명시하고, winner response의 exact new contract IDs 및 readback/DB 후조건을 E2E 또는 동일 gate에 연결한다.

#### J-W1D-R3-M04 — certification identity null 계약이 plan 내부에서도 일관되지 않고 RED가 없음

- 위치: review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:175-178,288-289
- 근거: §2.2는 exact 404 CERTIFICATION_IDENTITY_NOT_FOUND라고 봉인했지만 §2.3은 다시 “또는 동등 안정 코드”를 허용한다. 23개 PostgreSQL tests는 모두 transition identity를 먼저 생성하며 null identity preview/apply를 호출하지 않는다.
- 영향: identity 없는 수급자에서 404/code가 구현마다 달라도 RED가 통과한다.
- correction: “또는 동등”을 제거하고 preview/apply 각각 exact 404, top-level envelope, write-zero를 추가한다.

#### J-W1D-R3-M05 — W1-CON-02 free-text/Unicode와 API 오류 exactness가 실행되지 않음

- 위치: 계획 review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:89-94,594; backend/tests/test_w1d_postgres.py:742-838
- 근거: runtime round trip은 모든 optional 값을 null로만 만들고, reverse period는 error code/status를 확인하지 않는다. 임의 Unicode end_reason_text 성공과 API-level 422 VALIDATION_ERROR가 없다.
- 영향: fixed enum/default 없이 Unicode를 보존해야 하는 계약과 reverse period error envelope가 미래 구현에서 drift해도 RED가 통과할 수 있다.
- correction: null/Unicode/empty/free text create/end API, reverse period exact 422 code/envelope, initial empty end reason을 real PG/API로 추가한다.

#### J-W1D-R3-M06 — signer snapshot의 relationship field가 불변성으로 검사되지 않음

- 위치: backend/tests/test_w1d_postgres.py:966-1128
- 근거: empty/partial/full snapshot을 만들지만 full snapshot 후 검사는 signer name과 phone만 비교하고 signer_relationship_text == TEST_REL을 확인하지 않는다.
- 영향: relationship만 원본 변경이나 후속 mutation으로 바뀌는 구현이 snapshot RED를 통과할 수 있다.
- correction: empty/partial/full 각각 세 signer field의 persisted exact value를 확인하고 guardian/payer mutation 후 전체 tuple을 재조회한다.

### LOW

#### J-W1D-R3-L01 — RED evidence의 실행명령·marker 상태 기록이 packet 요구와 완전히 일치하지 않음

- 위치: review/evidence/w1d/RED.md:52-55, :14; packet review/packets/W1D_ASSIGNMENT_PACKET_v1.0.md:281-296; plan review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:678
- 근거: RED는 PS AST 0, Python AST 0, WS_CLEAN 7/7만 기록하고 해당 명령·개별 exit/count를 남기지 않는다. git diff --check는 untracked 파일을 검사하지 않으며 현재 7개 입력이 untracked다. 또한 RED terminal marker RED_VALID_PENDING_REAUDIT는 packet의 반환 형식 RED_VALID_PENDING_DESIGN_AUDIT | REQUIRED_CHANGES | BLOCK와 이름이 다르다.
- 영향: 현재 바이트의 실제 검사 결과와 RED 문서가 독립적으로 재현되지 않으며, phase marker 해석이 packet/plan 사이에서 흔들린다. 이번 감사의 strict scanner로는 7/7·0을 재현했지만 RED 자체의 봉인 증거는 아니다.
- correction: exact command/exit/count/first marker를 RED에 기록하고 untracked-safe scanner를 명시한다. terminal marker를 packet 반환 enum으로 통일하거나 별도 CORRECTION_PENDING_REAUDIT를 운영 정본에 추가한다.

## 5. R2 finding 폐쇄 상태

| R2 finding | R3 판단 |
|---|---|
| B01 W1C containment-invalid stale setup | setup mutation은 valid extend + commit으로 보강되어 CLOSED |
| H01 virgin counter | before_counter is None + wrapper product-first + 1→2/재계약 불변으로 CLOSED |
| H02 concurrent apply | blocker/pg_stat_activity 의도는 있으나 undefined time으로 NOT CLOSED |
| H03 raw cross-group concurrency | parent-lock 계획은 있으나 test 동시성 증명이 없어 NOT CLOSED |
| H04 replacement matrix | case matrix는 CLOSED; full write-zero fingerprint 때문에 exact gate는 NOT CLOSED |
| H05 10 apply fault seams | 10 label/marker loop는 CLOSED; full rollback assertion은 NOT CLOSED |
| H06 real-PG E2E | mocks/baseURL/winner-wait 구조는 CLOSED; viewport/response/wrapper gate는 PARTIAL |
| M01 service multiset stale | 실제 service id 변경과 stale code는 CLOSED; full fingerprint 의존성은 H02에 남음 |
| M02 preview/audit | metadata 일부는 CLOSED; full projection/event exactness는 NOT CLOSED |
| M03 token API/error | omit/null/blank per-path envelope는 보강; transition ACL·full snapshot은 NOT CLOSED |
| M04 stale UI | dedicated unit/E2E assertions는 CLOSED |
| M05 open-ended | same-service/cross-group/same-group matrix는 CLOSED |
| M06 ACL/envelope | create path는 보강; transition/end path coverage는 NOT CLOSED |
| M07 OpenAPI | item GET/ref/temp generator 구조는 보강; status/error refs exactness는 NOT CLOSED |
| M08 wrapper classification | harness precedence/baseline count는 보강; timeout/cleanup false-green은 NOT CLOSED |
| M09 process residual | data-dir/port matching은 보강; silent query failure/nonzero enforcement는 NOT CLOSED |
| L01 whitespace | 현재 bytes는 scanner로 clean; RED에 self-contained command evidence가 없어 PARTIAL |

## 6. Residual/implementation risk (confirmed defect와 분리)

- 제품 W1D module, migration 0011, generated client, API/UI가 아직 없는 것은 현재 Phase 1 범위에 맞는 정상 상태이며 제품 defect로 계산하지 않았다.
- R6 live run은 W1C head와 product-absent RED 분류만 증명한다. 실제 W1D migration/API/transaction/UI GREEN은 실행되지 않았고, implementation 이후 별도 exact-SHA full gate가 필요하다.
- transition token 전용 key와 CSRF/app secret 분리, DB trigger/exclusion 실제 catalog, benefit/approval을 apply 범위에서 제외한 운영상 잔여위험은 구현 감사에서 재확인해야 한다. benefit/approval 제외 자체는 정본 04 §10의 apply 범위와 일치한다.
- 현재 cleanup 관찰은 R6 증거 재사용 및 별도 read-only 상태 확인일 뿐 새 PostgreSQL/Playwright 실행이 아니다.
- frontend/node_modules는 기존 runtime dependency로 존재하고 root node_modules, Playwright result/report, R6 지정 listener와 외부 process는 확인되지 않았다. 기존 untracked governance/R6 파일은 삭제·정리하지 않았다.

## 7. Required correction gate

1. B01의 time/thread failure와 B02/H05 wrapper timeout·cleanup/nonzero semantics를 보정한다.
2. H01 raw cross-group와 pg_08 apply race를 실제 lock overlap으로 강제하고 exact SQLSTATE/loser write-zero를 검증한다.
3. H02/H03 기준으로 전체 ledger/audit snapshot·canonical before/after projection·전체 event delta를 봉인한다.
4. transition/end/list/get의 ACL·CSRF·status/error $ref·row-version behavior를 API/OpenAPI RED에 추가한다.
5. 정본 04와 stale hash/token split, identity-null code, apply status를 소유 문서에서 재봉인한다.
6. live E2E viewport/winner response와 signer/free-text/Unicode/null-identity cases를 보강하고, 그 뒤에만 새 exact final SHA에서 실 PG/FastAPI/Vite/Playwright gate를 재실행한다.

이 보고서 작성은 허용된 단일 감사보고서 경로에만 수행했다. stage/commit/push/pull/rebase/stash/branch 변경, worktree 생성, dependency 설치, 환경 영구변경, 제품·계획·RED·test·wrapper 파일 수정은 하지 않았다.

JOSEPH_W1D_REAUDIT_R3_RESULT=REQUIRED_CHANGES
