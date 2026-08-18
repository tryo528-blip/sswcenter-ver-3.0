# W1E 0026 후보 봉인 전 동시성·오류 매핑 Addendum

> 상태: current 0026 candidate addendum. historical 0012 packet/plan은 덮어쓰지 않는다.
> 대상 head: `20260814_0026_w1e_care_assignment_family_relationship_lock`

## 1. 계약 결정

1. 사전 overlap precheck는 **422 `CARE_ASSIGNMENT_PERIOD_CONFLICT`**.
2. DB exclusion 또는 실제 race loser는 **409 `CARE_ASSIGNMENT_CONCURRENT_CONFLICT`**.
3. contract/position/qualification reverse guard는 각각
   **409 `CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN`**,
   **409 `CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN`**,
   **409 `CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN`**.
4. 역순 날짜는 **422 `VALIDATION_ERROR`**.

FAMILY는 relationship snapshot과 contract/employment containment만 적용하고,
GENERAL만 position/qualification containment를 적용한다.

FAMILY relationship blank-check의 정본 trim 집합은 ASCII 6문자다:
SPACE, HT, LF, CR, FF, VT (`" \t\n\r\f\v"`). API/service
`strip(FAMILY_RELATIONSHIP_TRIM_CHARS)`, ORM metadata, 0026 CHECK/precheck,
postcheck exact CHECK가 같은 집합을 쓴다. Python 기본 `str.strip()`과
PostgreSQL 기본 `btrim`(공백만)은 정본이 아니다. NBSP 등 Unicode
whitespace는 의미 있는 내용으로 남기며, 확장하려면 별도 계약 변경이 필요하다.
0026 migration의 PostgreSQL E-string은 VT를 `\\v`가 아니라 `\\x0b`로 쓴다.
PostgreSQL은 `\\v`를 세로 탭으로 해석하지 않아 문자 `v`를 트림하게 된다.

## 2. Lock contract

현재 0026 upgrade는 단일 global mutex 대신 **fine-grained optimistic/fail-fast**
protocol을 `CREATE OR REPLACE FUNCTION`으로 추가한다. lock key는
`pg_try_advisory_xact_lock(hashtextextended(...))` transaction-scoped non-waiting
advisory lock이다.

- `erp.fn_w1e_lock_contract_path(bigint)` : `erp.w1e.contract` key를 non-waiting으로
  획득한다. 이미 소유한 transaction이 있으면 SQLSTATE `55P03`, message
  `CARE_ASSIGNMENT_CONCURRENT_CONFLICT`를 raise한다.
- `erp.fn_w1e_lock_employment_path(bigint)` : `erp.w1e.employment` key를 같은
  방식으로 획득한다.
- `erp.fn_w1e_lock_assignment_path(bigint, bigint)` : contract id → employment id
  순서로 위 두 helper를 호출한다. 재진입 시 이미 보유한 xact lock은 유지된다.
- `erp.fn_w1e_lock_contract_assignment_edges(bigint)` : affected contract의
  committed active assignment edge에서 **distinct contract id ascending**을 먼저,
  이어서 **distinct employment id ascending**을 lock한다. committed edge가 없으면
  contract parent-domain lock을 유지해 uncommitted assignment INSERT와 fail-fast로
  충돌한다.
- `erp.fn_w1e_lock_employment_assignment_edges(bigint, bigint)` : affected
  staff+employment의 committed active assignment edge에서 **distinct contract id
  ascending**을 먼저 lock하고, 그다음 **항상 `p_employment_id`** employment-domain
  lock을 잡는다. `p_employment_id`는 이 경로에서 고정이므로 두 번째 employment-edge
  SELECT와 `locked_edge` fallback을 쓰지 않는다.

### Transaction-wide lock order

- 모든 W1E write path는 **contract-domain lock을 ascending contract id로 먼저**,
  그다음 **employment-domain lock을 ascending employment id로** 잡는다.
- 모든 획득은 `pg_try_advisory_xact_lock`이므로, 필요한 key가 이미 잠겨 있으면
  그 자리에서 `55P03`으로 abort한다. 한 transaction이 partial set을 든 채
  대기하지 않으므로 row별 역전이 있어도 `40P01` cycle이 생기지 않는다.
- assignment INSERT/UPDATE는 단일 edge이므로 **contract lock → employment lock**
  순서다.
- `recipient_contract` reverse update는 committed edge가 있으면 affected
  contract의 distinct contract id ascending을 먼저, 이어서 distinct
  employment id ascending을 잡고, 없으면 contract parent-domain lock만 유지한다.
- `staff_employment`, `staff_position_period`, `staff_service_qualification_period`
  reverse update는 affected staff+employment의 distinct contract id ascending을
  먼저 잡고, 이어서 **항상 `p_employment_id`** employment-domain lock을 잡는다.

### Final validation and user-visible outcome

lock 취득 후 각 guard는 항상 최신 committed state를 다시 SELECT한다. READ COMMITTED
에서 lock 획득 statement 이후의 SELECT는 새 snapshot을 사용하므로, lock을 먼저
commit한 상대의 결과는 재검증에 보이고, lock을 나중에 시도한 상대는 재검증 전에
`55P03`으로 탈락한다. application precheck는 그대로 유지하지만 최종 저장의
atomicity는 이 DB trigger 재검증이 담당한다.

- lock loss는 SQLSTATE `55P03` **그리고** message
  `CARE_ASSIGNMENT_CONCURRENT_CONFLICT`일 때만 W1E assignment와
  W1D/Staff parent reverse 모두 HTTP `409 CARE_ASSIGNMENT_CONCURRENT_CONFLICT`로
  매핑한다. application `lock_timeout`/`FOR UPDATE NOWAIT` 등 다른 `55P03`은
  이 코드로 재표시하지 않는다. 매핑은 SQLAlchemy `orig`/`diag`/`__cause__`를
  포함한 nested DBAPI 층을 본다.
- 서로 다른 contract/employment 도메인의 실제 W1E write는 각자의 exact
  advisory key를 동시에 든 채 overlap한 뒤 둘 다 commit해야 한다. 폐기된
  `erp.w1e.global` key를 들고 한 쪽이 통과하는 것만으로는 증명으로 쓰지 않는다.
- W1E assignment deferred guard가 lock 획득 후 재검증에서 `23514`를 raise한
  경우는 곧 precheck 이후 상대가 먼저 commit해 상태가 바뀐 race이므로
  `409 CARE_ASSIGNMENT_CONCURRENT_CONFLICT`로 매핑한다. 직접 invalid input은
  기존 precheck `422`가 먼저 막는다.
- parent reverse guard의 `23514` orphan/outside-period는 기존 orphan 코드
  (`CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN` 등)로 유지한다.
- 관련 없는 contract/employment 도메인은 서로 다른 key를 쓰므로 동시에 진행할 수
  있다. 같은 contract 또는 employment 도메인을 공유하면 정확히 한쪽만 commit하거나
  늦은 쪽이 final validation으로 탈락하며, orphan은 남지 않는다.
- 읽기 전용 SELECT는 advisory lock을 잡지 않는다. 기존 replacement
  `expected_row_version` 동작과 OpenAPI 409/422 설명은 그대로 유지한다.

## 3. Postcheck 갱신

`backend/app/db/postcheck_current_0026.py`는 이제 0012 body가 아니라 현재 0026
migration의 실제 function body와 lock helper body를 exact/fail-closed로 비교한다.
폐지된 `fn_w1e_lock_global` 이름과 `erp.w1e.global` body marker가 catalog에
남아 있거나 부활하면 `CURRENT_0026_W1E_FORBIDDEN_LOCK_REMNANT`로 fail-closed한다.
lock helper는 pronargs만 보지 않고 exact argument type OID vector와 argument
name/type 문자열까지 검사하고, 예상 이름에 overload가 하나라도 더 있으면
fail-closed한다. 또한 `proretset`, `provolatile`, `proisstrict`,
`proparallel`, `proleakproof`, `proacl`, `erp_app` EXECUTE ACL/grant-option을
검사해 명시적 ACL drift와 함수 속성 drift를 거부한다. 기존 0012 body oracle은
historical oracle로 보존한다. W1E constraint trigger function도 같은 exact
catalog 검사를 적용한다: `provolatile` `v`, `proisstrict` false,
`proparallel` `u`, `proleakproof` false, `proretset` false, `proacl` null,
`SECURITY INVOKER`, no `proconfig`, table owner, `erp_app` EXECUTE(grant
option 없음)를 fail-closed로 확인한다.

`erp.care_assignment_id_seq`는 care_assignment table owner와 동일한 owner여야
하고 `erp_app`은 정확히 `USAGE, SELECT`만 가져야 한다. `erp_backup` role이
있으면 0012와 같이 정확히 `SELECT`만 허용한다. `UPDATE`(setval)와 grant
option, `erp_app` role 누락, backup USAGE/UPDATE/SELECT 제거는 fail-closed로
거부한다. identity sequence는 테이블에 묶여 있어 `ALTER SEQUENCE ... OWNER`를
live로 주입할 수 없고, owner 검사는 catalog 비교로만 유지한다. 추가로
`relacl`/`aclexplode`를 검사해 owner entry와 조건부 `erp_app`(USAGE+SELECT,
no grant option), 조건부 `erp_backup`(SELECT only, USAGE revoked, no grant
option) 외의 grantee/privilege/grant-option drift(PUBLIC, 제3 role 포함)를
fail-closed한다. owner-grantee ACL row는 skip하지 않고
`grantee=sequence_owner`일 때 `grantor=sequence_owner`와 no grant option을
요구한다. non-owner ACL row의 grantor도 sequence owner여야 하고, 존재하는
`erp_app`/`erp_backup`은 exploded privilege set이 정확히 그 집합과 같아야
한다. effective `has_sequence_privilege`만으로 exact ACL 검사를 대체하지
않는다.

`scripts/verify-runtime.ps1`의 npm 버전 문자열은 SemVer 2.0.0이다.
major/minor/patch leading zero, 비어 있는 prerelease/build identifier,
numeric prerelease leading zero는 거부한다. `/usr/bin/printf`처럼 basename이
`npm`이 아닌 executable도 계속 거부한다.

## 4. REVERSE_MUTUAL_VERIFICATION_AFTER_GROK 반영

- Linux-only Python test harness는 `npm.cmd`를 가정하지 않는다. non-Windows는
  `shutil.which("npm")`과 canonical `/usr/local/bin/npm` fallback으로 해석하고,
  Windows에서만 `npm.cmd`/`npm.exe`를 시도한다. TypeScript 생성과 byte/contract
  단언은 유지한다.
- W1E repository의 `assignment_overlaps_active`는
  `exclude_assignment_id=None`을 `CAST(:exclude_assignment_id AS bigint)`로
  명시해 PostgreSQL `AmbiguousParameter`를 방지한다.
- HTTP→service→repository→real PostgreSQL→audit integration은 exact 23-node
  live harness node `test_w1e_0026_pg_http_create_replace_through_real_service_and_audit`
  로 닫는다. FastAPI route/dependency/service/repository와 `erp_app` role을
  실제로 사용하고 authentication identity만 dependency override한다.

## 5. CLOSING_MUTUAL_VERIFICATION 반영

- W1E deferred assignment `23514`는 constraint 이름이 없어도 flush/commit에서
  `409 CARE_ASSIGNMENT_CONCURRENT_CONFLICT`다. 직접 입력 422는 application
  precheck만 사용한다.
- `55P03` 식별은 `diag.message_primary` 또는 SQLAlchemy/DBAPI 첫 줄의 exact
  message만 인정한다. wrapper·SQL 부분문자열은 사용하지 않는다.
- HTTP live node는 settings/runtime engine username이 `erp_app`인지,
  `get_w1e_service`/`get_db_session`이 override되지 않았는지, `erp_app`
  연결의 `current_user`와 기록 가시성을 확인한다.
- `assignment_overlaps_active` SQL은 `CAST(:exclude_assignment_id AS bigint)`를
  NULL 판정과 id 비교에 모두 쓰며, create(`None`)와 replace(실 id)가 같은
  SQL에 다른 bind만 넣는다.

## 6. F14_TRANSIENT_DISAPPEARANCE_LIVE_PROOF 반영

- `test_w1e_0026_pg_employment_lock_helper_always_locks_employment_path`는
  empty-edge와 ordinary with-edge만 직접 관측한다. transient disappearance는
  더 이상 이 노드가 주장하지 않는다.
- 새 live node
  `test_w1e_0026_pg_employment_helper_transient_disappearance_still_locks_employment`가
  다음 exact sequence를 강제한다.
  1. production employment helper의 첫 contract-edge SELECT가 committed C1을
     관측한다.
  2. test-only `fn_w1e_lock_contract_path` instrumentation이 C1 contract-lock
     호출 지점에서 explicit advisory test gate로 결정적으로 멈춘다. gate 관측
     시점에 committed edge가 남아 있고 helper는 production C/E key를 아직
     들지 않으며, 무관 C blocker는 없다.
  3. 별도 transaction이 관측된 assignment edge를 물리 DELETE하고 commit한다.
     helper는 여전히 같은 exact test-gate ungranted wait에 남아 있다.
  4. helper가 C1 지점을 통과해 재개된다.
  5. edge가 없어진 뒤에도 helper가 exact `p_employment_id` E key를 요청하는지
     별도 exact E-key blocker가 conflict 시점에도 유지된 채 stable
     `55P03`/`CARE_ASSIGNMENT_CONCURRENT_CONFLICT`로 강제·관측한다. C/E/test-gate
     domain hash는 서로 충돌하지 않는다.
  6. test-only `CREATE OR REPLACE` instrumentation은 restoration-guaranteed
     scope 안에 둔다. cleanup는 assertion으로 복원을 건너뛰지 않는다. gate와
     E blocker를 항상 해제하고, bounded join 후 필요하면 exact helper
     backend를 cancel하며, isolated ephemeral PG(`/tmp/sswcenter-w1e-0026-pg-*`)
     에서만 terminate한다. 그 다음 연결을 닫고 advisory/PID/residue가 없는 것을
     확인한 뒤 `pg_get_functiondef` 원본 DDL을 복원하고
     `to_jsonb(pg_proc)::text`로 OID/owner/ACL/cost/rows/support/args/defaults/
     body/config/flags를 비교한 다음 `verify_current_0026`을 통과시킨다.
     40P01/orphan/residue는 0이다. 복원과 postcheck가 끝난 뒤에만 primary
     또는 cleanup 실패를 표면에 낸다.
- production employment helper body는 수정하지 않는다. gate는
  `fn_w1e_lock_contract_path`에만 일시 주입하고 시나리오 종료 후 복원한다.
- cleanup의 최종 `verify_current_0026`은 실패 시 `SystemExit`를 사용할 수 있으므로
  `Exception`으로 한정해 잡지 않는다. `SystemExit`의 타입·메시지는 기존 primary와
  cleanup evidence에 함께 보존하고, `KeyboardInterrupt`만 모든 복구 시도 뒤 다시
  전달한다.
