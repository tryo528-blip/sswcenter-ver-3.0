# W1E 3라운드 트러블 중심 핸드오프

작성일: 2026-08-15 (Asia/Seoul)
정본: `/home/codexctl/workspace/sswcenter-3-0`
범위: W1E 요양보호사 담당 배정 백엔드

## 결론

- 3라운드 흐름을 완료했다: `DeepSeek 수정 → Grok 검수` × 3.
- 1라운드 Grok: `FAIL`.
- 2라운드 Grok: `REQUIRED_CHANGES`.
- 3라운드 DeepSeek: 코드·테스트 수정은 했지만 provider sandbox의 의존성 부족으로 `BLOCKED`.
- 3라운드 Grok: `PASS`.
- 형님 지시에 따라 Codex 최종검수는 수행하지 않았다.
- W1E 봉인·Git stage/commit/push는 하지 않았다.

## 오늘의 핵심 트러블

### 1. Windows 사본과 Linux 정본 혼선

- Windows `C:\sswcenter\3.0`은 Linux 제품 정본이 아닌 별도 사본이다.
- 실제 프로젝트 정본은 `/home/codexctl/workspace/sswcenter-3-0`이다.
- 초기에 Windows cwd를 먼저 확인해 W1E 파일이 없는 사본을 본 것이 진행 혼선의 원인이었다.
- Windows 사본은 수정·삭제하지 않았다.

### 2. Grok 인증 경로 혼선

- Grok은 API 키가 아니라 월구독 `monthly_subscription_device_auth`다.
- 잘못된 Windows `Set-AiWorkbenchKey.ps1 -Provider grok` 창은 `Grok API 키`를 요구하므로 사용하지 않고 닫았다.
- Linux `ssw-agent status`에서는 Grok 월구독 인증이 정상이며 `auth_ready=true`였다.
- 이후 Grok 호출은 Linux 공식 runner `/home/codexctl/.local/bin/ssw-agent`로 수행했다.

### 3. provider sandbox와 개발환경 불일치

- provider sandbox에서 `backend/.venv`가 외부 Python symlink로 해석되어 `pytest`·`ruff`를 사용할 수 없었다.
- sandbox 내부에서 `/usr/bin/python3`는 프로젝트 의존성을 갖지 않았다.
- provider 환경의 DNS/network 차단으로 의존성 재설치도 실패했다.
- `pwsh`도 provider sandbox에서 없어 OpenAPI generator `-Check`를 실행하지 못했다.
- 실 PostgreSQL 환경변수와 W1E gate가 없어 PG 테스트도 실행하지 못했다.

### 4. 정본 범위 해석 충돌

- 초기 Grok은 FAMILY에도 position/qualification guard를 요구했다.
- 정본 W1E plan/matrix와 historical 0012는 해당 guard를 GENERAL 범위로 명시한다.
- 최종 Grok이 FAMILY position/qualification 미적용을 blocker가 아니라고 정정했다.

## 현재 반영된 주요 변경

- W1E care-assignment API/domain/repository 구현.
- `as_of` 날짜 조회와 inclusive start/end semantics.
- 정상 사전검증 overlap `422 / CARE_ASSIGNMENT_PERIOD_CONFLICT`.
- 동시 DB exclusion conflict `409 / CARE_ASSIGNMENT_CONCURRENT_CONFLICT`.
- SQLSTATE `23P01` conflict mapping 보강.
- FAMILY 관계 snapshot current-head forward check 및 historical migration 보존.
- create/replace lineage·row version·CSRF·side-effect behavior 테스트 추가.
- OpenAPI generated TypeScript 갱신.
- Linux/Windows generator 경로 조합 보정.
- W1E contract/unit/behavior/PG 테스트 파일 추가·수정.

## 검수·증거 상태

- 3라운드 Grok 최종 read-only 판정: `PASS`.
- Grok가 확인한 정적 증거: `git diff --check`, AST, whitespace/conflict scan 통과.
- Grok가 확인한 계약: `as_of`, 422/409 분리, create/replace lineage, stale row version, CSRF, no staff-replacement side effect, 0026 gate의 truthful skip.
- 미검증: pytest, ruff 실행 결과, OpenAPI `-Check`, 실 PostgreSQL 0026 CHECK/exclusion/trigger, mypy.
- Grok의 남은 낮은 우선순위 지적: `backend/tests/test_w1e_phase1_behavior.py`의 fake audit가 `action_code`를 보존하지 않아 해당 assertion이 약함.

## 다음 할 일

1. Linux 정본에서 project-local Python 3.11 venv와 pytest/ruff를 provider sandbox가 볼 수 있게 복구한다.
2. W1E contract/unit/behavior 테스트와 ruff를 실행한다.
3. `pwsh ... scripts/generate-openapi-types.ps1 -Check` 또는 동등한 Linux generator check를 실행한다.
4. 실 PostgreSQL 0026 gate를 켜서 FAMILY CHECK·exclusion·postcheck를 실행한다.
5. fake audit의 `action_code` 보존을 보강한 뒤, 형님 승인 후에만 W1E 봉인 여부를 판단한다.
6. Git 변경은 형님이 별도로 요청할 때까지 건드리지 않는다.

## 재개 시 고정할 것

- 작업 OS: Ubuntu Linux
- 작업 정본: `/home/codexctl/workspace/sswcenter-3-0`
- provider runner: `/home/codexctl/.local/bin/ssw-agent`
- Grok 인증: 월구독 device auth
- 현재 단계: W1E 백엔드, W1F 아님
- 현재 판정: Grok PASS / Codex 최종검수 미실행 / 봉인 전

