# W1E 0026 현재 후보 실행계획

> 상태: `CURRENT_CANDIDATE / PRE-SEAL`
> 작성일: 2026-08-16 KST
> 대상 head: `20260814_0026_w1e_care_assignment_family_relationship_lock`
>
> 이 문서는 역사적인 W1E 0012 설계·RED 문서를 대체하지 않는다. 현재 3.0
> 후보의 실제 API/service/FAMILY/실 PostgreSQL 범위를 별도로 승인·검증하기 위한
> current addendum 계획이다.

## 1. 현재 계약

- application overlap precheck: `422 CARE_ASSIGNMENT_PERIOD_CONFLICT`
- PostgreSQL exclusion 또는 실제 동시성 패배: `409 CARE_ASSIGNMENT_CONCURRENT_CONFLICT`
- contract reverse: `409 CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN`
- position reverse: `409 CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN`
- qualification reverse: `409 CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN`
- 역순 날짜: `422 VALIDATION_ERROR`
- FAMILY: 관계 스냅샷 + 계약·재직 기간 포함만 검사
- FAMILY blank-check 정본 trim 집합: ASCII SPACE/HT/LF/CR/FF/VT.
  Unicode whitespace는 트림하지 않는다. API/service, ORM metadata, 0026
  CHECK, postcheck exact CHECK가 같은 집합을 쓴다.
- GENERAL: 계약·재직 + CARE_WORKER 직종·서비스 제공자격 포함 검사

상세 계약 및 lock order는
[`W1E_0026_CANDIDATE_ADDENDUM.md`](../packets/W1E_0026_CANDIDATE_ADDENDUM.md)에 둔다.

## 2. 구현 범위

1. 0026 current migration의 transaction-scoped non-waiting advisory lock helper와
   exact current-body postcheck. 모든 W1E write path는 **ascending contract-domain
   lock 전부를 먼저**, 이어서 **ascending employment-domain lock**을
   `pg_try_advisory_xact_lock`으로 잡는다. lock loss는 SQLSTATE `55P03` **그리고**
   message `CARE_ASSIGNMENT_CONCURRENT_CONFLICT`로 fail-fast하고, partial set을
   든 채 대기하지 않으므로 multi-edge/multi-row에서 `40P01` cycle이 없다.
   contract helper는 committed assignment edge가 있으면 distinct contract id를
   ascending으로 먼저, distinct employment id를 ascending으로 잡고, 없으면
   contract parent-domain lock을 유지한다. employment helper는 distinct contract
   id를 ascending으로 먼저 잡고 **항상 `p_employment_id`** employment-domain
   lock을 잡는다. uncommitted assignment는 parent SELECT에 보이지 않으므로
   edge-only lock은 금지한다. lock 취득 후 각 guard가 최신 committed state를
   재검증해 READ COMMITTED snapshot timing을 정확히 처리한다.
   `erp_app` role 누락과 `erp.care_assignment_id_seq` owner/`erp_app`
   USAGE+SELECT/`erp_backup` SELECT-only 및 relacl/aclexplode PUBLIC·제3
   role drift, lock helper와 W1E trigger function의
   `proretset`/`provolatile`/`proisstrict`/`proparallel`/`proleakproof`/
   `proacl`/EXECUTE ACL drift도 exact postcheck로 fail-closed한다.
   sequence ACL은 owner entry를 skip하지 않고 grantee=owner·grantor=owner·
   no grant option일 때만 허용하며, 비owner row는 grantor=owner와 조건부
   `erp_app`/`erp_backup` exact privilege set만 허용한다. FAMILY CHECK
   정규화기는 PostgreSQL이 넣는 `::text` display cast만 제거하고 임의의
   `::type`은 보존한다.
2. W1E CRUD/replacement/audit, W1D·Staff reverse error mapping, API/OpenAPI
   descriptions와 generated TypeScript
3. FAMILY relationship check 및 GENERAL-only position/qualification guards
4. 0026→0025→0026 lifecycle, ACL/postcheck mutation, 23-node live PostgreSQL
   harness와 contract/employment/contract-qualification 2-session barrier race,
   employment helper empty-edge/with-edge non-waiting employment-lock fail-fast
   regression, multi-row assignment fine-grained fail-fast regression(정확한
   advisory lock key 관측), unrelated-domain old-global-key non-blocking
   regression, disjoint contract/employment 두 실제 W1E write overlap+both
   commit, global helper/key remnant postcheck 거부, real HTTP create/replace
   through FastAPI route/dependency/service/repository/erp_app audit integration
5. 실행환경 preflight: `ensure-runtime.ps1` → `verify-runtime.ps1`.
   `-NpmExecutable` basename, 해결된 `node`와 같은 디렉터리, npm SemVer 2.0.0
   (major/minor/patch leading zero 금지, prerelease/build identifier 비어 있지
   않음, numeric prerelease leading zero 금지)를 fail-closed로 검증한다.
   Linux `/usr/local/bin/npm` 고정과 npm 바이너리/lock 해시는 현재 계약이
   아니며 Windows `npm.cmd`를 깨지 않기 위해 넣지 않는다.

## 3. 검증 gate

- `backend/.venv` Python 3.12.3, lock sync, `SSWCENTER_RUNTIME_GREEN`
- W0 readiness + W1D/W1E targeted pytest(batch-deferred commit flush-only 회귀 포함), Ruff check/format, scoped mypy
- OpenAPI exact `-Check` generation
- live PG lifecycle, postcheck, 23 nodes, cleanup all zero
- npm SemVer 2.0.0 helper/behavior tests, including `/usr/bin/printf` rejection
- Linux-only npm launcher resolution never assumes `npm.cmd`
- `git diff --check`
- fresh clean worktree Sol Ultra independent review before seal

## 4. Finding IDs와 현재 판정

| ID | 항목 | 현재 판정 |
|---|---|---|
| W1E-0026-F01 | 0012 plain SELECT write-skew | 0026 reverse edge lock + 2-session live PASS |
| W1E-0026-F02 | W1D reverse orphan 500 | 409 mapping + targeted PASS |
| W1E-0026-F03 | Staff position/qualification reverse 500 | 409 mapping + targeted PASS |
| W1E-0026-F04 | FAMILY CHECK/postcheck drift | exact postcheck + mutation/live PASS |
| W1E-0026-F05 | OpenAPI generated drift | generator `OPENAPI_TYPES_UP_TO_DATE` |
| W1E-0026-F06 | canonical runtime drift | 이 GROK sandbox는 `pwsh` 부재와 `/usr/local/bin/node` Permission denied로 canonical `ensure-runtime.ps1`/`verify-runtime.ps1` GREEN 미선언. 공유 venv Python 3.12.3/pytest 9.1.1/Ruff 0.16.0/mypy 2.3.0와 psql 16.14는 확인. 3.11 compatibility remains unverified |
| W1E-0026-F07 | lock helper integer overload evades pronargs | exact argument OID/name + overload rejection live PASS |
| W1E-0026-F08 | verify-runtime accepts wrong npm executable | basename + node-sibling + SemVer 2.0.0 fail-closed; exact path/lock hash not required |
| W1E-0026-F09 | uncommitted assignment vs parent success/success | empty-edge parent-domain lock + 2-session live PASS |
| W1E-0026-F10 | FAMILY trim set API vs DB mismatch | canonical ASCII 6-char set across API/service/ORM/0026/postcheck + live/contract PASS |
| W1E-0026-F11 | multi-edge employment parent lock `C1,E` while waiting `C2` deadlocks with assignment `C2 → E` (40P01) | contract-domain ascending-first redesign + isolated PG multi-edge deadlock regression PASS |
| W1E-0026-F12 | sequence ACL and lock-helper pg_proc properties can drift past postcheck | exact sequence owner + erp_app USAGE+SELECT + erp_backup SELECT-only + proretset/volatility/strict/parallel/leakproof/EXECUTE ACL fail-closed + live savepoint mutation PASS |
| W1E-0026-F13 | verify-runtime npm regex accepted `01.2.3`, `1.2.3-01`, `alpha..1` | SemVer 2.0.0 parser + official grammar regex + helper/behavior tests PASS |
| W1E-0026-F14 | employment helper transient edge disappearance skips E-lock → C2→E assignment + parent shrink write-skew | employment helper always locks `p_employment_id` after ascending contract locks; empty-edge/with-edge blocker regression is preserved, and dedicated live node `test_w1e_0026_pg_employment_helper_transient_disappearance_still_locks_employment` forces the exact transient sequence: production helper first SELECT observes committed C1 → test-only contract-path gate pauses before/at the C1 contract-lock call while the edge still exists and helper holds neither production C nor E → separate transaction physically deletes the edge and commits → helper is still on the exact gate → resume still requests exact E under the still-held exact E blocker with stable 55P03/message, no unrelated C blocker, no domain-hash collision; cleanup is fail-safe (always restore `pg_get_functiondef` + `to_jsonb(pg_proc)::text` identity, then `verify_current_0026`) before surfacing primary/cleanup errors. 23-node live PASS |
| W1E-0026-F15 | `_strip_harmless_display_casts` removes arbitrary `::type` (`::date`) and can normalize a different CHECK to expected | strip only PostgreSQL display `::text`; unit (`::date`/`::varchar`/`::pg_catalog.text`) + live date-cast mutation fail-closed PASS |
| W1E-0026-F16 | W1E trigger function catalog misses provolatile/proisstrict/proparallel/proleakproof/proacl/EXECUTE ACL drift | exact trigger-function catalog attrs including `proretset` false + erp_app EXECUTE/grant-option fail-closed; live adversarial mutation PASS |
| W1E-0026-F17 | sequence ACL effective-privilege check misses PUBLIC/third-role grants and can skip owner-grantee rows | relacl/aclexplode exact grantee/privilege/grantor=owner/grant-option/exact-set check; owner row는 grantee=owner·grantor=owner·no grant option일 때만 허용; live PUBLIC + third-role + owner-grantor/owner-grant-option mutation PASS |
| W1E-0026-F18 | DEFERRABLE FOR EACH ROW assignment trigger가 한 transaction의 여러 row를 `C1,E,C2` 순서로 처리해 assignment `C2→E`와 40P01 deadlock | fine-grained non-waiting `pg_try_advisory_xact_lock` + `55P03` fail-fast. multi-row live regression이 C2를 든 blocker 앞에서 T1이 C1/E를 exact key로 보유하고 C2에서 즉시 `55P03`으로 실패하는 것을 관측. no 40P01 PASS |
| W1E-0026-F19 | W1E `_flush`/`_commit` leftover race/guard SQLSTATE → 500 | leftover `40P01`과 deferred assignment `23514`는 409. W1E lock loss는 `55P03`+exact message만 409. 무관 `lock_timeout`/`NOWAIT` 55P03은 재표시하지 않음. nested orig/diag/cause 검사. W1D/Staff/batch-deferred 동일. targeted + contract PASS |
| W1E-0026-F20 | 단일 `erp.w1e.global` mutex가 무관한 W1E write까지 직렬화 | global mutex 제거. old global key non-blocking 회귀는 유지하되 충분 증거가 아님 |
| W1E-0026-F21 | employment helper가 non-waiting으로 바뀐 뒤에도 항상 `p_employment_id`를 시도하는지 | empty-edge/with-edge 각각 employment key를 blocker로 잡고 `55P03` fail-fast를 exact SQLSTATE/message로 관측 + exact body postcheck PASS |
| W1E-0026-F22 | unrelated-domain 증거가 obsolete global key를 든 채 한쪽 write만 통과하는 약한 증명 | 두 실제 W1E INSERT를 disjoint C/E에서 barrier로 overlap시키고 exact advisory key 동시 보유·ungranted wait 0·both commit를 live 관측 PASS |
| W1E-0026-F23 | W1E/W1D/Staff가 모든 SQLSTATE `55P03`을 care-assignment 409로 재표시 | application `lock_timeout=5s`의 lock timeout/`FOR UPDATE NOWAIT`는 500으로 남김. helper RAISE message가 있을 때만 409. nested DBAPI 층 검사 + unit PASS |
| W1E-0026-F24 | postcheck가 resurrected `fn_w1e_lock_global` / `erp.w1e.global` remnant를 거부하지 않음 | catalog name+body marker fail-closed `CURRENT_0026_W1E_FORBIDDEN_LOCK_REMNANT` + live CREATE mutation PASS |
| W1E-0026-F25 | W1D contract test가 Ubuntu에서 hardcoded `npm.cmd`를 호출해 `No such file or directory: npm.cmd`로 실패 | test harness가 non-Windows에서 `shutil.which("npm")`→canonical `/usr/local/bin/npm` 순서로 해석하고 TypeScript 생성·byte/contract 단언은 유지. 회귀 test 추가 + W1D contract 11 passed |
| W1E-0026-F26 | W1E repository `assignment_overlaps_active`가 `exclude_assignment_id=None`을 untyped parameter로 PostgreSQL에 보내 `AmbiguousParameter` 500 | SQL을 `CAST(:exclude_assignment_id AS bigint)`로 고정. real HTTP create through service/repository가 이 경로를 통과해 201 확인 |
| W1E-0026-F27 | deferred assignment `23514`를 constraint_name 없이 메시지 폴백만 보면 422로 남아 현재 409 race 계약과 어긋남 | flush/commit 메시지 폴백을 `CARE_ASSIGNMENT_CONCURRENT_CONFLICT` 409로 고정. 직접 입력 422는 precheck가 유지. unit+deferred-flush 회귀 PASS |
| W1E-0026-F28 | `is_w1e_advisory_lock_loss`가 `str(layer)` 부분문자열을 보면 wrapper/SQL에 코드가 섞인 무관 `55P03`을 409로 재표시할 수 있음 | `diag.message_primary` 또는 SQLAlchemy 첫 줄 exact match만 인정. W1D/Staff IntegrityError 경로도 같은 식별자. 적대 unit PASS |
| W1E-0026-F29 | HTTP live node가 settings/engine username `erp_app`과 service/session override 부재를 단언하지 않음 | settings URL·runtime engine·`current_user`·erp_app SELECT visibility와 `get_w1e_service`/`get_db_session` override 거부를 추가. 23-node live PASS |
| W1E-0026-F30 | `exclude_assignment_id` CAST가 None/실 id 두 SQL 경로를 결정적으로 고정하는 회귀가 없음 | repository SQL CAST 2회·create None/replace real id bind unit + source contract PASS |
| W1E-0026-G01 | persistent candidate SHA manifest | generated at `review/evidence/W1E_20260816_CURRENT_CANDIDATE_MANIFEST.sha256`; regenerate after any byte change |
| W1E-0026-G02 | HTTP→service→repository→real PG→audit integration | closed: `test_w1e_0026_pg_http_create_replace_through_real_service_and_audit` is an exact 23-node live harness node using FastAPI TestClient + real dependency/service/repository + erp_app role; verifies lineage/row_version/audit actions/version-conflict rollback, settings/engine username, and app-role readback |
| W1E-0026-G03 | repository-wide suite/full mypy/3.11 | current acceptance follow-up; scoped gate only |
| W1E-0026-G04 | R2 opener order vs 운영표준 | 실제 양 라운드 opener는 Grok→DeepSeek. 제품 결함이 아니며 봉인 근거로 쓰지 않는다 |
| W1E-0026-G05 | fresh Sol Ultra independent review | GROK F14 closing FIX와 Codex cleanup `SystemExit` 보존 수정 이후 새 worktree 재검수 전. `FINAL_SOL_PENDING`, 봉인하지 않는다 |

## 5. Seal conditions

봉인은 다음 모두가 현재 바이트에서 다시 확인될 때만 가능하다.

- current candidate manifest와 이 finding table의 SHA·경로가 일치
- W1E-0026-F01~F30 재검증 및 cleanup zero
- W1E-0026-G01~G05의 범위·미검증 상태를 Sol Ultra가 독립적으로 확인(G02는 closed)
- 새 worktree의 Sol Ultra가 `PASS`하고 형님이 정본 승격을 승인
- 운영표준 R2 opener 교대(DeepSeek→Grok)와 실제 ledger(Grok→DeepSeek) 편차는
  이미 발생한 거버넌스 기록이며, 이 편차를 숨기거나 seal로 바꾸지 않는다

stage·commit·push·정본 승격은 형님 명시 없이는 수행하지 않는다.
