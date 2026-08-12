# W1C Marco Final Counter-Review — e1f5e39

## 1차 판정

- 반대검토 SHA: `e1f5e39fb94ba73a81638fbf118aa2746daaed5c`
- 작업방: 사용자에게 보이는 독립 마르코 Codex 작업방
- 판정: `MARCO_W1C_FINAL_BLOCK`
- finding: HIGH `1`, MEDIUM `2`
- W1C 자체 재현: PostgreSQL/API `6 passed`, postcheck·app-role·인증/권한/CSRF,
  OpenAPI·mypy·계약·프런트 집중·Playwright `9 passed`
- 정리: 임시 cluster, listener, artifact 잔여 `0`, detached worktree clean

## Finding 1 — HIGH: W1B 격리 포트가 Playwright/Vite에 전달되지 않음

### 재현

마르코는 포트 충돌을 피하려고 W1B 하네스의 `Port`, `BackendPort`,
`FrontendPort`를 모두 비기본 값으로 실행했다. 하네스는 FastAPI를 전달받은
backend 포트에서 시작했지만 다음 두 설정은 고정값을 사용했다.

- `frontend/playwright.config.ts`: base URL과 Vite web server를 `4173`으로 고정
- `frontend/vite.config.ts`: `/api`·`/health` proxy 대상을 `8000`으로 고정

그 결과 W1B 브라우저 3건이 전달받은 backend가 아닌 고정 주소로 bootstrap status를
요청해 `W1B_E2E_BOOTSTRAP_STATUS_FAILED`, `0 passed / 3 failed`가 됐다.
Regina도 `55490/18090/14190`에서 같은 결과를 재현했고, cleanup은 정상 통과했다.

### 보정

- W1B 하네스가 Playwright 자식 프로세스에
  `SSWCENTER_E2E_BACKEND_PORT`·`SSWCENTER_E2E_FRONTEND_PORT`를 전달한다.
- Playwright와 Vite config가 환경변수를 10진 TCP 포트로 검증하고, 범위
  `1..65535` 밖이거나 숫자가 아니면 fail-close한다.
- Playwright base URL·web server 명령과 Vite API proxy가 같은 전달값을 사용한다.
- web server는 `--strictPort`로 요청한 포트를 조용히 바꾸지 못하게 한다.

### 폐쇄 검증

비기본 포트 `55491/18091/14191`에서 실제 W1B 하네스를 다시 실행했다.

- Playwright: `3 passed`, failed/skipped/errors `0`
- DB postcheck: before/after 모두 통과
- leak gate: `296` files, green
- PostgreSQL/backend/frontend listener: 모두 `0`
- Playwright artifact·임시 cluster: 모두 `0`
- 최종 marker: `W1B_E2E_GREEN`

## Finding 2 — MEDIUM: broad Ruff format gate 불일치

마르코 실행에서 `ruff check`는 통과했지만 `ruff format --check app tests`는
`test_w1b_red.py`를 재포맷 대상으로 보고했다. Regina가 같은 broad 명령을
재실행하자 `test_schema_contract.py`도 함께 확인됐다.

두 파일에 공식 Ruff formatter를 적용했다. 의미 변경 없이 줄바꿈과 method-chain
배치만 정리했으며 W1B 정적 회귀는 `7 passed / 4 deselected`다.

- `ruff check --no-cache app tests`: 통과
- `ruff format --check app tests`: `84 files already formatted`

## Finding 3 — MEDIUM: 최종 exact SHA 증적 역할 불명확

기존 GREEN의 `기준 SHA`는 누적 diff 시작점 `5980602...`였지만 필드명이 이를
설명하지 않았다. `REAUDIT_B6D49AD.md`도 이미 evidence commit `e1f5e39...`이
생성된 뒤에도 evidence commit 생성을 미래 절차로 남겼다.

보정 후 GREEN은 다음을 별도 필드로 구분한다.

- 누적 diff 기준 SHA
- 요셉·Opus 기술 재감사 코드 SHA
- 마르코 1차 반대검토 SHA
- 현재 최종 후보는 문서를 포함하는 Git `HEAD`이며, reviewer가
  `git rev-parse HEAD`와 clean worktree로 확인한다는 절차

commit은 자신을 포함하는 SHA를 자기 본문에 기록할 수 없으므로 이 방식이
self-reference 없이 exact 후보를 봉인한다. `REAUDIT_B6D49AD.md`도
`e1f5e39...`의 실제 반대검토 결과와 이 문서로 이어지는 폐쇄 체인을 기록하도록
수정했다.

## 전체 재검증

| Gate | 결과 |
|---|---|
| W1C PostgreSQL/API | `6 passed`, `W1C_POSTGRES_GREEN` |
| W1C DB postcheck | `W1C_DB_POSTCHECK_OK` |
| W1C Playwright | 3 viewport, `9 passed` |
| 비실DB 백엔드 | `134 passed`, `44 skipped`, `4 deselected` |
| mypy | `44 source files`, 통과 |
| broad Ruff check / format | 통과 / `84 files already formatted` |
| W1B 정적 | `7 passed`, `4 deselected` |
| W1B 비기본 포트 실DB/브라우저 | `3 passed`, `W1B_E2E_GREEN` |
| 전체 프런트 공식 명령 | 1 worker, `16 files / 98 passed` |
| 프런트 lint / build | 통과 / `151 modules transformed` |
| OpenAPI drift | `OPENAPI_TYPES_UP_TO_DATE` |

## 남은 절차

이 보정과 문서를 포함하는 새 Git `HEAD`를 exact SHA로 commit한 뒤, 같은 마르코
독립 작업방에서 HIGH/MEDIUM finding이 모두 닫혔는지 재검토해야 한다. 승인 전까지
Regina의 최종 `PASS`는 보류한다.
