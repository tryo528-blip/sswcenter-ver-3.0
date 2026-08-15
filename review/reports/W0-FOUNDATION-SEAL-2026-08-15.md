# W0 Foundation Seal — 2026-08-15

## 판정

**W0 기반시설 봉인 가능 — PASS**

이번 봉인은 Linux canonical repository에서 수행했다.

~~~text
PROJECT_ROOT=/home/codexctl/workspace/sswcenter-3-0
BASE_SHA=a55d25d64ea571acf94ca2cbfbfd38bf4eb5e4bf
BRANCH=main
MODE=REMOTE
~~~

Grok이 W0 candidate를 구현했고, Codex가 current byte·diff·runtime evidence를 독립 검수한 뒤 필요한 수정과 재검증을 수행했다. provider의 완료 선언만으로 판정하지 않았다.

## W0 변경·검수 범위

| 항목 | 결과 |
|---|---|
| U-02 인증 validation 오류 안전성 | auth/bootstrap validation response가 입력값·민감정보를 재반사하지 않도록 고정, 테스트 통과 |
| U-03 로그인 실패 상태 | 401·423·429, loading 종료, stale 401 경합 상태를 UI·접근성 상태로 검증 |
| U-04 로그 cap | handler 소유 prefix만 prune하며 다른 handler 파일을 지우지 않도록 수정·검증 |
| U-05 readiness/write gate | /health/ready는 current 0025 postcheck를 요구하고, 읽기 외 HTTP 요청은 postcheck 실패 시 session·product mutation 전에 503 |
| U-06 PIN redaction | 공백·화살표·구조화 로그·exception traceback PIN 표현을 redaction하고 일반 숫자 보존 |
| U-07 audit 불변성 | DB trigger 방식은 추가하지 않고 application-role ACL 방식을 선택. audit/access/auth/system-run event의 UPDATE/DELETE/TRUNCATE를 erp_app에서 회수하고 실계정으로 거부를 검증 |
| U-21 W0 shell E2E | W0 spec을 전용 npm gate에 연결하고 3 viewport에서 15/15 통과 |
| U-24 release gate | OpenAPI drift, frontend lock, backend transitive hash lock을 gate에 연결 |
| Linux 검증환경 | PowerShell·Python venv·PostgreSQL·Playwright 사용자 영역 실행환경과 고정 경로를 정본에 기록 |

W0 외 W1/W2 기능 구현·acceptance·release 승인은 이번 봉인 범위가 아니다.

## 실행 증거

### Foundation gate

~~~text
pwsh -NoProfile -File scripts/test.ps1 -FoundationOnly
W0 release gate: 3 passed
OPENAPI_TYPES_UP_TO_DATE
Ruff: passed
mypy: Success, no issues found in 6 source files
backend: 178 passed, 16 skipped
frontend lint: 0 errors, 5 pre-existing warnings
frontend unit: 25 files passed, 232 passed
frontend build: passed
W0 Playwright E2E: 15 passed
exit=0
~~~

### Isolated PostgreSQL live gate

~~~text
pwsh -NoProfile -File scripts/test-w0-postgres-linux.ps1
Alembic: base -> 20260813_0025_w1_relationship_lock_contract_correction
SSWCENTER_CURRENT_0025_DB_POSTCHECK_OK
SSWCENTER_CURRENT_HEAD_POSTCHECK_OK
live tests: 3 passed
W0_POSTGRES_LIVE_GREEN
W0_POSTGRES_CLEANUP listener=0 process=0 temp=0 git_delta=0
W0_POSTGRES_SEAL_GREEN
exit=0
~~~

The live test used only a loopback PostgreSQL cluster under /tmp/sswcenter-w0-pg-*. It did not use an operating database or production data. It verified revision drift blocks login writes before session creation and that the erp_app role cannot rewrite or delete append-only event ledgers.

### Provider and workspace boundary

~~~text
ssw-agent status: exit=0
  project_root=/home/codexctl/workspace/sswcenter-3-0
  work_mode=REMOTE
  grok installed/pinned/auth/policy: true
  deepseek auth: true
  bubblewrap/project_only: true

ssw-agent self-test: exit=0
  all required project-write, provider-isolation, credential-read-block,
  git-write-block, system-write-block and path-guard checks: true

git diff --check: exit=0
~~~

## Git 판정

- 형님 요청에 따라 이 candidate를 봉인 커밋한다.
- push는 수행하지 않는다.
- 기존 Linux 작업환경 전환 변경, provider 실행경로 정본 변경, legacy warpper·deepseek_runner·프로젝트 route skill 제거는 이번 환경 전환 범위에 포함하여 함께 봉인한다.
- 기존 W1/W2 dirty product work를 임의로 정리하거나 reset하지 않았다.

## 남은 별도 항목

- 전체 repository의 W1/W2 범위에는 기존 mypy·historical contract debt가 남아 있다. 이는 W0 봉인 실패가 아니라 별도 slice의 후속 작업이다.
- W0 U-07에서 DB trigger 강제 방식은 선택하지 않았다. trigger 의무화가 필요하면 별도 migration·contract decision으로 다룬다.
- 운영 수용·실제 계정/장비/사내망 evidence는 이 개발용 W0 봉인 보고서의 범위를 넘는다.
