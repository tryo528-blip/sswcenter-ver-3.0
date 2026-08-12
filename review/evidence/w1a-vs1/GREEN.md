# W1A-VS1 최종 GREEN 증거

> 판정: **PASS**
>
> 판정일: 2026-07-27 KST
>
> 최종 구현 SHA: `55130af1dc3244c391bca11471323e6b22061c3f`
>
> 최종판정자: 김부장(Codex 본진 / SOL Max)

## 1. 판정 범위

이 문서는 `W1A-VS1` 직원 최소 vertical slice의 hardening과 최종 runtime
검증만 승인한다. W1A 전체 catalog·license·training, W1B 이후 micro-slice,
Wave 2, 파일함·OCR 범위를 완료했다고 주장하지 않는다.

검증자료는 모두 합성자료이며 실제 개인정보·secret·실데이터를 저장소나
보고서에 포함하지 않았다.

## 2. 담당별 독립 결과

| 담당 | 최종판정 | 검증 범위 |
|---|---|---|
| 김루나 | PASS | backend·API·DB·service logic, RRN fail-closed |
| 박루나 | PASS | frontend·상태관리·logout·account transition |
| 이루나 | PASS | 권한·동시성·PostgreSQL·artifact·누출 게이트 재심사 |
| 송루나 | PASS | 제품 교차검증·민감정보·40-vector·누출검사 |

발견된 결함은 본진이 대신 제품 코드를 고치지 않고 원 소유자에게 반환했다.
수정 결과는 다른 담당자의 교차검증과 본진의 실제 통합 실행을 통과했다.

## 3. backend·OpenAPI

작업경로: `backend`

| 명령 | Exit | 결과 |
|---|---:|---|
| `.venv\Scripts\python.exe -m ruff format --check .` | 0 | 46 files |
| `.venv\Scripts\python.exe -m ruff check .` | 0 | PASS |
| `.venv\Scripts\python.exe -m mypy app` | 0 | 29 source files |
| `.venv\Scripts\python.exe -m pytest -q` | 0 | 51 passed, 12 skipped |

작업경로: repository root

| 명령 | Exit | 결과 |
|---|---:|---|
| `powershell.exe -NoProfile -File scripts/generate-openapi-types.ps1 -Check` | 0 | `OPENAPI_TYPES_UP_TO_DATE` |

## 4. frontend

작업경로: `frontend`

| 명령 | Exit | 결과 |
|---|---:|---|
| `npm.cmd test` | 0 | 9 files, 54 tests |
| `npm.cmd run lint` | 0 | PASS |
| `npm.cmd run build` | 0 | TypeScript·Vite, 147 modules |

## 5. 실제 PostgreSQL·브라우저

작업경로: repository root

| 명령 | Exit | 결과 |
|---|---:|---|
| `scripts/test-w1a-vs1-postgres.ps1 -ArtifactOutputPath <dedicated-temp-root>` | 0 | fresh/upgrade/downgrade/re-upgrade/offline SQL, 권한·정합성·backup postcheck, `W1A_POSTGRES_HARNESS_OK` |
| `scripts/test-w1a-vs1-postgres.ps1 -E2ERedOnly -ArtifactOutputPath <dedicated-temp-root>` | 0 | 실제 PostgreSQL+FastAPI+Playwright 3/3 |

Playwright project:

- `chromium-1440x1000`: PASS
- `chromium-1440x900`: PASS
- `chromium-1366x768`: PASS
- CLI와 config 모두 `workers=1`

종료 뒤 PostgreSQL test port는 `no response`, FastAPI test port listener는
0개였다.

## 6. artifact·민감정보

- PostgreSQL 전체 harness manifest: 4 files, 모든 SHA-256 일치
- E2E harness manifest: 3 files, 모든 SHA-256 일치
- `.w1a-manifest.tmp.json`: 0
- artifact는 저장소 밖 전용 임시경로에 보존했고 Git에는 포함하지 않았다.

| 명령 | Exit | 결과 |
|---|---:|---|
| `scripts/verify-w1a-vs1-leak-gate.ps1 -SelfTest` | 0 | negative child gate·fail-closed PASS |
| `scripts/verify-w1a-vs1-leak-gate.ps1 -ArtifactRoot <two-roots>` | 0 | 247 files, `W1A_LEAK_GATE_GREEN` |
| 3개 PowerShell AST + strict UTF-8 JSON parse | 0 | PASS |
| RRN 공통 vector parity | 0 | 40 total, 32 sensitive, 8 negative |

검사 범위에는 tracked, staged, unstaged, untracked, ignored runtime,
PostgreSQL temp, explicit artifact root, text와 gzip이 포함된다.

## 7. Git·최종판정

- `git diff --check`: PASS
- secret, `.env`, venv, dependency cache, `node_modules`, `dist`, DB 파일,
  실제 개인정보: staged 대상 0
- 구현 commit과 review-only 완료기록 commit은 분리한다.

요구사항, 실제 diff, 담당별 독립검증, 전체 테스트와 runtime 증거를 종합해
김부장은 `W1A-VS1`을 **PASS**로 판정한다.
