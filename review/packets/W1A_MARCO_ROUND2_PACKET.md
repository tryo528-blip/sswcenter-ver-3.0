# W1A-VS1 마르코 2차 반대심사 패킷

> 역사 기록: 2026-07-27 영구 역할 교체 전의 마르코 2차 반대심사
> 전달자료다. 이후 최고난도 구현은
> `review/packets/W1A_MARCO_IMPLEMENTATION_PACKET.md`를 사용하고, Opus가
> 독립 읽기 전용 반대심사를 맡는다. 이 문서의 당시 심사 결과와 증거는
> 변경하지 않는다.

## 1. 심사 역할

- 심사자: 기존 마르코 작업방 (`gpt-5.6-sol / max`)
- 심사 대상:
  `C:\Users\USER\.codex\worktrees\opus-w1a-019f9e39`
- 성격: Opus 보정 결과에 대한 2차이자 마지막 반대심사
- 금지: 파일 수정, Git stage/commit/push/reset, 새로운 기획 작성,
  별도 작업방·하부·보조·병렬 에이전트 생성
- Codex 본진이 최종 완료판정을 담당한다. 마르코는 구현을 대신하지 않는다.

## 2. 반드시 대조할 자료

1. `review/packets/W1A_OPUS_HARDENING_PACKET.md`
2. 루트 저장소의
   `review/packets/W1A_OPUS_ROUND1_RETURN_PACKET.md`
3. 루트 저장소의
   `review/reports/w1a-vs1-marco-opus-round1.md`
4. 대상 worktree의 staged baseline, unstaged Opus WIP, untracked 3개 파일

staged diff는 기존 W1A baseline이고, Opus의 1차 심사 후 보정은 unstaged diff와
untracked 파일이다. 둘을 합친 최종 결과가 사용자 요구사항과 정본을 충족하는지
심사한다.

## 3. Opus 최종 보정 요약

- M1: replacement를 required-nullable로 바꾸고 생략 422와 명시적 null 제거를
  API·OpenAPI·실제 PostgreSQL에서 검증
- M2: 중복 ID, 전체 제거, 일부 대체, replacement link, audit
  actor/time/version, mutation 이후 실패의 전체 rollback을 실제 PostgreSQL에서
  검증
- M3: AuthGate 밖 auth-aware cache boundary로 logout/account switch 시
  직원·capability cache 제거. 초기 identity 설정 시 정상 fetch를 취소하던
  race도 보정
- M4: 완성된 exception/traceback 문자열과 Uvicorn error 경로까지 RRN
  redaction
- M5: workspace, app/error/access 및 회전 로그, PostgreSQL 로그,
  Playwright 산출물을 포함하는 독립 leak gate 추가
- M6: schema, surviving table 전체, sequence 전체 ACL fingerprint와 Wave0
  zero-grant precondition 검증
- M7: UI가 서버 `current_employment` projection을 사용하며 날짜 경계 fixture
  추가
- M8: normalize-before-validate와 OpenAPI role pattern을 함께 보존하고 공식
  TypeScript 재생성 drift 0
- M9: Ruff format 보정

Opus unstaged 변경 17개:

- `backend/alembic/versions/20260726_0003_w1a_staff.py`
- `backend/app/api/w1a_errors.py`
- `backend/app/core/logging.py`
- `backend/app/domains/staff/schemas.py`
- `backend/app/domains/staff/service.py`
- `backend/tests/test_logging.py`
- `backend/tests/test_w1a_staff_api.py`
- `backend/tests/test_w1a_staff_integration_postgres.py`
- `backend/tests/test_w1a_staff_openapi_contract.py`
- `backend/tests/test_w1a_staff_semantics.py`
- `frontend/src/context/AuthProvider.tsx`
- `frontend/src/generated/sswcenter-api.ts`
- `frontend/src/pages/StaffPage.tsx`
- `frontend/src/services/staffApi.ts`
- `frontend/src/test/W1AStaffPage.test.tsx`
- `scripts/test-w1a-vs1-postgres.ps1`
- `scripts/test-w1a-vs1-red.ps1`

Opus untracked 변경 3개:

- `backend/tests/test_w1a_staff_current_projection.py`
- `frontend/src/test/AuthCacheBoundary.test.tsx`
- `scripts/verify-w1a-vs1-leak-gate.ps1`

## 4. Codex 본진 독립 재검증 증거

검증일: `2026-07-27 KST`

- staged/unstaged `git diff --check`: 모두 exit 0
- backend:
  - Ruff format: 42 files already formatted
  - Ruff check: PASS
  - mypy: 29 source files PASS
  - pytest: `56 passed, 14 skipped`
- frontend:
  - Vitest: 10 files, `41 passed`
  - oxlint: PASS
  - TypeScript/Vite build: PASS
- OpenAPI 공식 생성기 `-Check`: `OPENAPI_TYPES_UP_TO_DATE`
- 독립 leak gate: 50 files, 0건
- 실제 PostgreSQL 전체 harness:
  - fresh upgrade, Wave0→W1A preserved values
  - downgrade→Wave0, re-upgrade, offline SQL apply
  - owner tests `6 passed`
  - app-role integration tests `8 passed`
  - backup/restore와 W1A postcheck
  - leak gate 52 files, 0건
  - 최종 `W1A_POSTGRES_HARNESS_OK`
- 실제 PostgreSQL Playwright:
  - workers=1, 3 viewports, `3 passed`
  - W1A DB postcheck PASS
  - leak gate 54 files, 0건

## 5. 집중 공격 항목

1. M1~M9가 테스트 이름만 추가된 것이 아니라 실제 결함을 막는지
2. Auth cache boundary가 초기 로그인 fetch를 취소하지 않으면서
   logout/account switch/지연 응답을 모두 봉인하는지
3. RRN 탐지 휴리스틱이 실제 유출을 놓치거나 일반 epoch를 과검출하지 않는지
4. downgrade ACL fingerprint가 W1A 외 선행 권한을 파괴하거나 누락하지 않는지
5. PostgreSQL rollback 테스트가 첫 mutation 이후 실패를 실제로 발생시키는지
6. 생성 OpenAPI와 런타임 normalization·required-nullable 계약이 동일한지
7. GREEN 명령이 누락된 코드 경로나 산출물을 숨기지 않는지
8. 정본 요구사항과 구현·테스트 증거 사이에 새 회귀나 미해결 위험이 있는지

## 6. 반환 형식

- 판정:
  - `PASS`
  - `REQUIRED_CHANGES`
  - `OWNER_DECISION_REQUIRED`
- 차단 결함: 파일과 근거를 포함
- 중요 권고
- 후속 개선
- M1~M9 각 항목의 `해결 / 미해결 / 증거불충분`
- 파일 수정 없이 심사 보고만 반환

새 차단 결함이 있으면 원 구현자인 Opus에게 반환한다. 마르코나 Codex 본진이
대신 수정하지 않는다.
