# FOUNDATION-0025 current-head init·복구 구현 패킷 v1.0

> 상태: `PREPARATION_ONLY / EXECUTION_REQUIRES_ROUTE_AND_CLEAN_CANDIDATE`
> 작성일: 2026-08-14 KST
> 작성 기준 branch/HEAD: `main` / `b1cd055ea92ad5cf9558009e2a270147acf17d6f`
> 소유 이슈: `U-09 → U-08`
> 선행 이슈: `U-10` `SATISFIED_BY_PR_1` (PR #1 병합; W0 전체 acceptance/release approval 아님)
> 기술 근거: [`W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md`](../reports/W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md)

## U-10 계보와 현재 head 고정

현재 main과 Git object를 직접 대조한 U-10 계보는 다음과 같다.

```text
db8b5ca (역사적 unsealed WIP)
→ 65afdaf (독립 후보)
→ 9147ed9 (PR #1 병합)
→ b1cd055 (current main)
```

따라서 이 패킷의 U-10 선행 조건은 `SATISFIED_BY_PR_1`로 갱신한다. PR #1 병합은 W0
전체 acceptance, W1F PASS, Wave 승격 또는 release approval이 아니며, live acceptance와
release approval은 별도 동일-SHA 실행·독립검수·운영 증거로만 판정한다.

현재 저장소의 실제 Alembic head는
`20260813_0025_w1_relationship_lock_contract_correction`이다. current migration
디렉터리에 0026~0028 Python migration은 없다. 다른 문서의 0026/0027/0028 head 표기는
역사적 원문의 `KNOWN_FALSE_CLAIM`으로만 보존·격리하며 이 패킷의 현재 사실이나
retarget 근거로 사용하지 않는다.

U-01 PIN 정본은 `c5cecd2` PR #2 commit으로 current main에 병합되어
`SATISFIED_BY_PR_2` 상태다. PR #2 병합도 W0 전체 acceptance, W1F PASS, Wave 승격 또는
release approval이 아니며, 이 패킷은 live acceptance를 선언하지 않는다.

## 결론 — exact 0025 초기화와 복원만 먼저 정상화한다

이 패킷은 현재 Alembic head
`20260813_0025_w1_relationship_lock_contract_correction`의 개발 초기화와 공식 복원을
fail-close로 연결한다. 구현 순서는 반드시 다음과 같다.

```text
U-10 PR #1 병합 후보의 current-main 반영 확인
→ U-09 revision dispatcher + init_development
→ U-08 exact 0025 backup + restore
```

FOUNDATION-0025는 **W1F 재봉인 패킷이 아니다.** W1E 제품 공백 U-12/U-13/U-14/U-15와
W2 제품 공백을 닫지 않으므로 이 패킷의 PASS를 W1F PASS, Wave 2 승격, release acceptance로
표현하지 않는다.

## 현재 실패가 구조적으로 재현되는 이유

1. `backend/app/db/init_development.py:12,99-102`는 `upgrade head` 뒤
   `postcheck_w1a_vs1`을 호출한다.
2. 그 역사 postcheck의 revision set은 `backend/app/db/postcheck_w1a_vs1.py:905-924`에서
   0019까지이고 0025를 거부한다.
3. current checker `backend/app/db/postcheck_current_0025.py:17,124-129,322-332`는 이미
   존재하고 W2 격리 PG 하네스에서 직접 호출되지만 development init과 공식 restore가
   소비하지 않는다.
4. `scripts/restore-drill.ps1:56-77`의 allowlist도 0019에서 끝나므로 0025 backup
   manifest를 복원 전에 거부한다.

따라서 U-09를 먼저 닫아 신뢰할 current-head 검사 진입점을 만든 뒤, U-08 restore가 같은
진입점과 exact marker를 소비해야 한다.

## 실행 전 필수 조건

다음 조건 중 하나라도 충족되지 않으면 구현을 시작하지 않고 `BLOCKED`로 보고한다.

1. 형님이 `<장소>-<오퍼레이터>-<라이터>!` 라우트를 명시한다. 이 패킷은 장소·오퍼레이터·
   라이터를 추론하지 않는다.
2. 승인된 별도 구현 task/thread와 Git worktree를 사용한다. 현재 본진은 다수의 기존
   dirty 변경을 가지고 있으므로 구현·검증 worktree로 사용하지 않는다.
3. U-10은 `SATISFIED_BY_PR_1`로 확인되어야 한다. 이는 PR #1 병합 상태만 뜻하며, W0
   전체 acceptance·W1F PASS·release approval이나 live 운영 증거를 대신하지 않는다.
4. worktree의 `git rev-parse --show-toplevel`, branch, HEAD, status와 아래 write 대상의
   시작 SHA-256을 기록한다.
5. `alembic heads`와 migration 디렉터리의 단일 head가 exact 0025다. 현재 확인값은
   `20260813_0025_w1_relationship_lock_contract_correction`이며 0026~0028은 현재
   migration에 없다. 0026 이상이 생겼으면 이 패킷을 자동 retarget하지 않고 새 버전을
   만든다.
6. PostgreSQL·Python·PowerShell 실행경로와 임시 포트가 준비됐으며 운영 DB·운영 파일·
   실제 개인정보를 사용하지 않는다.

## 목표와 완료 정의

### U-09 개발 초기화

- `upgrade head`가 만든 실제 revision을 한 행·한 값으로 읽는다.
- exact 0025는 `postcheck_current_0025`로 보내고 성공 marker
  `SSWCENTER_CURRENT_0025_DB_POSTCHECK_OK`를 관찰한다.
- revision 누락, 복수행, 알 수 없는 future revision은 marker 없이 실패한다.
- 기본 `postgres` maintenance DB fingerprint는 초기화 전후 동일하다.
- 실제 `backend/.env`가 아닌 격리된 임시 작업사본에서만 init runtime을 시험한다.

### U-08 공식 복원

- exact 0025 manifest만 새 current-head branch로 허용한다.
- 0020~0024는 revision별 verifier 없이 일괄 allowlist하지 않는다.
- 기존 0002~0019 역사 지원과 marker 강제를 약화하지 않는다.
- custom-format dump와 manifest·bundle hash를 검증하고 새 review DB와 새 temp data root에
  복원한다.
- 복원 후 U-09 dispatcher와 exact 0025 marker를 필수 확인한다.
- 복원 전후 deterministic synthetic row의 full-row canonical hash와 synthetic file
  SHA-256이 동일하다.
- 성공 뒤 listener, child process, temp root, review DB, backup/restore artifact 잔존이
  모두 0이다.

## exact write allowlist

구현자는 다음 6개 경로만 쓸 수 있다.

1. `backend/app/db/postcheck_dispatch.py` — 신규 exact revision dispatcher
2. `backend/app/db/init_development.py` — `upgrade head` 뒤 dispatcher 사용
3. `scripts/restore-drill.ps1` — exact 0025 branch와 marker 강제
4. `backend/tests/test_foundation_0025_contract.py` — 신규 RED-first 정적·동적 계약
5. `scripts/test-foundation-0025-postgres.ps1` — 신규 격리 init·backup·restore Grade 5 gate
6. `review/environment/home/2026-08-14_FOUNDATION_0025.md` — 신규 append-only 실행 원장

새 dispatcher가 current checker의 명백한 계약 누락을 발견하더라도
`postcheck_current_0025.py`를 자동 수정하지 않는다. finding과 실패 증거를 기록하고 별도
repair packet을 요청한다.

## 절대 금지 경로와 행위

다음 경로는 이 패킷에서 수정하지 않는다.

```text
backend/alembic/versions/**
backend/app/db/postcheck.py
backend/app/db/postcheck_w1a_vs1.py
backend/app/db/postcheck_current_0025.py
backend/app/db/models.py
backend/app/db/seed_*.py
backend/app/api/**
backend/app/domains/**
backend/tests/test_w1f_contract.py
scripts/backup-postgres.ps1
scripts/test-w1f-postgres.ps1
frontend/**
docs/**
requirements*.txt
lockfile, dependency, environment, .env, credential
기존 dirty WIP
```

금지 행위:

- migration 추가·수정·downgrade 의미 변경
- 역사 postcheck의 지원 revision이나 marker 의미 변경
- 0020~0024 또는 unknown future revision을 검사 없이 허용
- 실제 `backend/.env`, 운영 DB, 기존 PostgreSQL cluster, 운영 data root 사용
- test 삭제·skip·xfail·assertion 약화로 GREEN 생성
- Git stage·commit·push·pull·checkout·reset·clean·rebase
- provider에 저장소 경로·URL·credential·셸·도구 권한 전달

Git 작업은 형님의 별도 명시 요청이 있을 때만 수행한다.

## RED-first 계약

첫 write는 `backend/tests/test_foundation_0025_contract.py` 하나뿐이다. 다른 허용 경로를
고치기 전에 아래 의미의 RED를 실행하고 실제 실패 marker를 원장에 기록한다.

| ID | RED 의미 | 초기 기대 |
|---|---|---|
| F25-01 | init이 아직 역사 `postcheck_w1a_vs1`을 직접 호출 | `FOUNDATION_0025_INIT_DISPATCHER_MISSING` |
| F25-02 | exact revision dispatcher 부재 | `FOUNDATION_0025_DISPATCHER_MISSING` |
| F25-03 | revision 누락·복수·future fail-close 계약 부재 | 각 경우 성공 marker 없이 실패 |
| F25-04 | restore가 exact 0025 manifest를 artifact stage 전에 거부 | `FOUNDATION_0025_RESTORE_REVISION_REJECTED` |
| F25-05 | restore의 exact current marker 강제 부재 | `FOUNDATION_0025_RESTORE_MARKER_GUARD_MISSING` |
| F25-06 | 0020~0024가 계속 unsupported | 초기부터 PASS인 ABS 회귀 |
| F25-07 | 기존 0019와 대표 역사 revision의 지원·marker 보존 | 초기부터 PASS인 ABS 회귀 |

정적 문자열 검사는 보조 증거다. F25-03은 가짜 DB connection/result를 이용해 dispatcher의
분기를 실행하고, F25-04는 synthetic manifest로 restore가 실제 artifact stage까지
진입하는지 확인한다. 최종 판정은 격리 PostgreSQL과 실제 dump→restore가 소유한다.

## 구현 계약 1 — revision dispatcher와 development init

`postcheck_dispatch.py`는 다음만 소유한다.

1. 현재 connection에서 `erp.alembic_version.version_num`을 정확히 하나 읽는다.
2. exact 0025를 `postcheck_current_0025.verify_current_0025()`로 보낸다.
3. checker 성공 뒤 dispatcher marker를 하나 출력한다. current checker의 기존 marker도
   보존한다.
4. revision 누락·복수·unknown은 구체적인 failure marker와 nonzero exit로 종료한다.
5. prefix·날짜·숫자 비교로 future revision을 추정하지 않는다.
6. credential·전체 URL·secret을 출력하지 않는다.

`init_development.py`는 기존 안전경계를 보존한다.

- development 환경과 loopback PostgreSQL만 허용
- maintenance DB에 schema/table/revision 흔적을 남기지 않음
- target `sswcenter_dev` 외 임의 DB를 만들거나 덮지 않음
- `upgrade head` 성공 뒤 dispatcher를 호출하고, dispatcher 실패 시 `.env`를 갱신하지 않음
- 설정 cache와 process environment를 시험 종료 뒤 원래 상태로 복구

## 구현 계약 2 — exact 0025 restore

`restore-drill.ps1`의 current branch는 다음을 지킨다.

1. supported revision에 exact
   `20260813_0025_w1_relationship_lock_contract_correction` 하나만 추가한다.
2. pg_restore가 새 review DB에 성공한 뒤 process-local DB URL로 dispatcher를 실행한다.
3. child stdout/stderr와 exit를 모두 관찰하고
   `SSWCENTER_CURRENT_0025_DB_POSTCHECK_OK`가 없으면 실패한다.
4. DB URL과 password를 command line·로그·manifest에 넣지 않는다.
5. dump SHA, bundle SHA, 상대경로 escape, 기존 target overwrite, maintenance DB, review data
   root overwrite 거부를 보존한다.
6. 실패 시에도 자신이 만든 review DB와 temp data root만 제거한다. 기존 경로는 삭제하지
   않는다.
7. terminal `RESTORE_DRILL_OK`는 postcheck, DB full-row hash, file hash 검증 뒤에만 출력한다.

## Grade 5 실행 하네스

`scripts/test-foundation-0025-postgres.ps1`은 다음 순서를 한 번에 재현한다.

1. `-ExpectedSha`와 시작 clean tree를 fail-close 확인한다.
2. 충돌 없는 전용 loopback port와 전용 temp cluster를 만든다.
3. 필요한 role과 새 개발-init DB를 준비한다.
4. 격리된 backend 사본·임시 `.env`에서 development init을 실행한다.
5. revision exact 0025와 current postcheck marker, maintenance fingerprint 불변을 확인한다.
6. 최소 synthetic rows와 `blobs` 또는 `official-documents` 아래 synthetic file을 만든다.
7. full-row `to_jsonb(row)` 기반 canonical hash와 file SHA-256을 기록한다.
8. 기존 `backup-postgres.ps1`로 backup을 만들고 수정된 `restore-drill.ps1`로 새 review
   DB/data root에 복원한다.
9. 복원 revision·postcheck marker·full-row hash·file hash가 원본과 일치하는지 확인한다.
10. 시작/종료 HEAD, status, allowlist path hash를 대조한다.
11. 모든 child를 bounded timeout으로 종료하고 cleanup count를 출력한다.

성공 marker는 다음 순서를 따른다.

```text
FOUNDATION_0025_INIT_GREEN
FOUNDATION_0025_BACKUP_GREEN
FOUNDATION_0025_RESTORE_GREEN
FOUNDATION_0025_CLEANUP listener=0 process=0 temp=0 database=0 artifact=0 git=0
FOUNDATION_0025_POSTGRES_GREEN
```

`FOUNDATION_0025_POSTGRES_GREEN`은 마지막 marker다. cleanup 하나라도 0이 아니거나
시작·종료 SHA가 다르면 출력하지 않는다.

## 테스트·검수 등급

이 슬라이스의 최고 위험이 migration lifecycle·backup/restore이므로 다음 등급을 사용한다.

```text
TEST_GRADE=5
REVIEW_GRADE=5
FAST_REQUESTED=off
FAST_ACTUAL=UNVERIFIED
GIT=MANUAL_ONLY
```

Codex 오퍼레이터인 경우 room-3이 자기 전용 worktree에서 Grade 5 시험을 직접 수행하고,
room-6이 별도 worktree에서 read-only Grade 5 검수를 수행한다. 방을 만들 때는 room-1
canary부터 확인하며 현재 dirty candidate를 포함해야 할 때만 승인된 `working-tree`
starting state를 사용한다. 검수방은 구현 파일을 수정하지 않는다.

필수 검증 묶음:

| 단계 | 범위 | PASS 기준 |
|---|---|---|
| static | Python import/compile, PowerShell AST, focused contract | error 0, RED 의미 보존 후 GREEN |
| PG integration | fresh base→0025 init, dispatcher branch | exact revision·marker·maintenance 불변 |
| recovery | 실제 backup→새 DB/data root restore | DB/file hash 일치, current postcheck marker |
| regression | 기존 0002~0019 restore contract | 지원·marker 약화 0, 0020~0024/future 거부 |
| hygiene | start/end SHA·status·hash·cleanup | allowlist만 변경, 잔존 0, `git diff --check` exit 0 |
| independent review | recovery/security/adversarial | false GREEN·path escape·secret leak·unsafe cleanup finding 0 |

## 판정 규칙

- `PASS`: U-09 dispatcher와 init, U-08 actual dump→restore, 동일 SHA, clean candidate,
  cleanup 0, 독립 Grade 5 검수가 모두 통과했다.
- `FAIL`: 제품·하네스 결함이 재현되거나 assertion/marker/hash가 불일치한다.
- `BLOCKED`: route·candidate·PostgreSQL 환경·U-10 선행 후보·required evidence가 없다.
- 환경 failure를 제품 PASS로 낮추지 않는다.
- static PASS나 W2-F의 과거 PG 결과를 현재 restore PASS로 대체하지 않는다.

## 종료 보고 형식

```text
STATUS=PASS|FAIL|BLOCKED
ROUTE=<형님이 명시한 route>
REPOSITORY_ROOT=<승인된 implementation worktree>
START_HEAD=<sha>
END_HEAD=<sha>
ALEMBIC_HEAD=<revision>
CHANGED_PATHS=<exact allowlist subset>
TEST=<command, exit, count, marker>
RESTORE=<manifest revision, before/after DB hash, file hash, marker>
CLEANUP=<listener/process/temp/database/artifact/git counts>
REVIEW=<Grade 5 verdict and findings>
GIT=NOT_REQUESTED|REQUESTED_RESULT
UNVERIFIED=<remaining evidence>
```

이 패킷 작성 자체에서는 제품 코드, 테스트, DB, 서버, worktree와 Git ref를 변경하지 않는다.
