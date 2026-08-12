# W1A-VS1 Claude Opus 5 최고난도 보정 패킷

> 역사 기록: 2026-07-27 영구 역할 교체 전 Opus 구현 배정의 패킷이다.
> 이후 최고난도 구현은 마르코가 맡고 Opus는 이와 같은 범위의 독립
> 반대심사만 수행한다.

## 1. 역할과 실행

- 담당: Claude Opus 5
- 호출: Claude CLI `--model opus --effort high`
- 운영 추론강도: High
- 역할: W1A의 보안·데이터 무결성·migration 계약을 직접 구현하고 테스트한다.
- 금지: 하부 agent/subagent 생성, 다른 작업방 호출, Git stage/commit/push,
  정본·계획 재작성, W1A 밖의 리팩터링, 최종승인

### 현재 추론강도

2026-07-26 사용자 최신 지시에 따라 세션 한도 뒤 재개 호출을 포함한 모든
Opus 호출에 `--effort high`를 사용한다. 별도 사용자 지시가 있을 때까지
이 설정을 유지한다.

이 worktree의 현재 staged 상태는 Codex 본진 working tree의 전달용 baseline이다.
기존 staged 변경을 수정하거나 reset하지 말고, Opus 변경만 unstaged diff로 남긴다.

## 2. 기준

- 원본 branch: `wave1/w1a-staff-vertical-slice`
- 기준 HEAD: `6c153cc4c8eb1939c4d3abf72001397158a1da96`
- 승인 계약:
  - `review/plans/W1A_STAFF_VERTICAL_SLICE_PLAN.md`
  - `review/reports/w1a-vs1-owner-permission-decision.md`
  - `review/reports/w1a-vs1-joseph-round1.md`
  - `review/reports/w1a-vs1-joseph-round2.md`
- 현재 구현은 baseline에 포함돼 있다.
- 김루나는 별도 worktree에서 Playwright 3-viewports 직렬화를 구현했다.
  해당 E2E는 본진 원본 환경에서 `3 passed`와 W1A DB postcheck GREEN을
  확인했다.

## 3. 구현 범위

### A. reveal 및 인증 경계의 민감정보 수명

- reveal 요청의 PIN과 응답 평문 주민번호를 TanStack Query
  query/mutation cache에 넣지 않는다.
- 직접 요청과 `AbortController` 또는 동등한 요청 세대 통제로 close, unmount,
  logout, 계정 전환 뒤 늦은 응답이 평문 state를 다시 채우지 못하게 한다.
- close/unmount/auth transition에서 PIN·평문·직원/capability cache를 폐기한다.
- 로그·URL·form default·브라우저 저장소에 평문을 두지 않는다.
- cache와 DOM에서 평문이 0건임을 테스트한다.

### B. 주민번호 redaction과 유출 gate

- 유효 정책이 허용하는 7번째 자리 `0`~`9` 중 실제 허용 코드 전체를
  하이픈/비하이픈 redaction과 artifact 검색이 잡아야 한다.
- `0`과 `9`를 포함한 단위시험과 workspace·Playwright output·PostgreSQL log
  유출검색 gate를 추가한다.
- 실패 메시지에 실제 주민번호 문자열을 출력하지 않는다.

### C. 재직 replacement의 자식 동시성·연결·audit

- 재직 정정 request가 각 기존 직종/업무역할 period의
  `old_period_id + expected_row_version + replacement 또는 명시적 제거`를
  모호하지 않게 표현해야 한다.
- 부모와 모든 자식 row version을 잠금 뒤 비교한다.
- old child를 invalidate하고 새 child를 만들 때 `replacement_id`를 연결한다.
- 모든 기존행 mutation의 actor/time/version과 감사 event를 남긴다.
- 빈 목록이 자동복사인지 전부 제거인지 모호하지 않게 한다.
- stale child, 전체 제거, 일부 대체, 성공 연결, transaction rollback을
  실제 PostgreSQL에서 검증한다.

### D. downgrade 데이터·ACL 역순 제거

- 실제 `STAFF_VIEW`/`STAFF_MANAGE` 권한 배정 행이 있는 상태에서도
  `20260726_0003_w1a_staff` downgrade가 FK 실패 없이 계약대로 동작해야 한다.
- W1A가 추가한 dependent `account_permission` 행을 명시적 정책과 순서로
  제거한 뒤 permission definition을 제거한다.
- W1A upgrade가 추가한 `erp_app`/`erp_backup` schema/table/sequence ACL을
  downgrade에서 정확히 revoke한다.
- 실제 권한 배정 후 downgrade→Wave0 postcheck→re-upgrade와 ACL 전후 비교
  테스트를 추가한다.

### E. 오류 envelope와 현재 projection

- `/api/v1`의 예상 밖 오류를 내부정보 없이
  `UNEXPECTED_SERVER_ERROR + request_id` envelope로 반환한다.
- reveal 예상 밖 오류도 `Cache-Control: no-store`를 유지한다.
- Wave0 auth 오류 body는 바꾸지 않는다.
- current employment/position/role은
  `start_date <= as_of <= end_date 또는 end_date null` 기준을 적용하고
  deterministic tie-breaker를 둔다.
- 과거 종료, 미래 시작, 기간 경계 테스트를 추가한다.

### F. OpenAPI exact code 경계

- 응답 `sex_code`가 `MALE | FEMALE | TEST` exact enum으로 생성되게 한다.
- role code는 trim·uppercase 정규화 뒤 형식검사를 수행한다.
- OpenAPI와 checked-in TypeScript를 재생성하고 drift 0을 확인한다.

## 4. 수정 가능 범위

- `backend/alembic/versions/20260726_0003_w1a_staff.py`
- `backend/app/api/staff.py`
- `backend/app/api/w1a_errors.py`
- `backend/app/core/logging.py`
- `backend/app/db/models.py`
- `backend/app/domains/staff/**`
- 위 계약의 backend test
- `frontend/src/App.tsx`
- `frontend/src/context/AuthProvider.tsx`
- `frontend/src/pages/StaffPage.tsx` 중 reveal·auth 경계와 current projection
- `frontend/src/services/api.ts`
- `frontend/src/services/staffApi.ts`
- `frontend/src/generated/**`
- 위 계약의 frontend test
- `scripts/test-w1a-vs1-red.ps1`
- `scripts/test-w1a-vs1-postgres.ps1`
- `scripts/verify-w1a-vs1-db.ps1`

## 5. 변경 금지 범위

- 정본 `docs/**`, `README.md`
- `review/**`
- Playwright viewport/worker 설정과 E2E 수명주기 본문
- URL 기반 검색·정렬·pagination·누락 command UI 전체 구현
- Wave0 migration 재작성
- Git index와 commit history

## 6. 완료조건

- 각 A~F 요구사항의 코드와 회귀 테스트가 있다.
- 가능한 backend/frontend 정적·단위 테스트를 실행한다.
- PostgreSQL/E2E가 환경 때문에 실행 불가하면 설치나 우회 대신 정확한
  전제조건과 미실행 명령을 보고한다.
- `git diff --check`가 통과한다.
- 최종 보고에 변경 파일, 요구사항별 구현, 실행 명령·결과, 남은 위험을 적는다.
- 최종승인을 선언하지 않는다.
