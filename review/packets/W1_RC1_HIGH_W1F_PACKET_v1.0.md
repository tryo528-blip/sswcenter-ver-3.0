# W1 v3.8-rc1 HIGH 파일럿 — W1F 통합·복구 봉인 패킷 v1.0

> 봉인 시각: 2026-08-01T22:52:36.3252554+09:00
> 기준 branch: `codex/w1e-assignment`
> 기준 SHA: `bee6ae0b51871f4b8e34e4cb5b0dbc69a2dfc5d4`
> 운영 정본: `docs/AI_업무분담_운영규정_v3.7.md`
> 시범 규칙: `docs/AI_업무분담_운영규정_v3.8-rc1.md`
> 제품 gate: `docs/06_개발로드맵_결정현황_v1.2.md` §3.2,
> `review/WAVE1_CLEAN_TEST_MATRIX.md` §14

## 1. 목표와 사용자 가치

W1F는 Wave 0부터 W1E까지의 현재 제품을 한 exact SHA에서 통합 봉인한다. 이 HIGH
파일럿의 구현 경계는 현재 W1 head의 backup/restore와 복구 후 postcheck 공백이다.

사전 대조에서 다음 실제 공백을 확인했다.

- `scripts/restore-drill.ps1`은 W1C revision까지만 지원하고 W1D/W1E manifest를
  `Unsupported backup Alembic revision`으로 거부한다.
- `backend/app/db/postcheck_w1a_vs1.py`는 W1D/W1E revision marker와 구조 검사를 하지
  않는다.
- W1 head에서 합성 의미자료와 파일 bundle을 함께 backup→새 review DB/data root로
  restore하고 count/hash를 대조하는 W1F 전용 live gate가 없다.

완료 시 운영 DB·실제 개인정보를 사용하지 않고도 W1 head 복구 가능성, W1A 의미자료와
파일 무결성, W1D/W1E schema·ACL 존재를 재현할 수 있어야 한다.

## 2. 위험등급과 impact tag

- 위험등급: `HIGH`
- impact tag: `MIGRATION`, `DB`, `AUTH/PII`, `API_CONTRACT`, `UI/E2E`, `DATA_LOSS`
- lineage 병렬 candidate 상한: `1`
- 단일 제작자: Claude Code / Opus, effort `high`
- Regina는 패킷·통합·실행·Git만 소유하며 제품 보정 writer와 겹치지 않는다.
- DeepSeek는 제작 완료 후 read-only adversarial sidecar 한 번만 허용한다. 이 결과는
  사용자 표시 별도 작업방 독립검수로 세지 않는다.

## 3. exact write scope

제작자가 수정할 수 있는 경로는 다음 다섯 개뿐이다.

1. `backend/tests/test_w1f_contract.py` — RED-first 계약과 회귀
2. `backend/app/db/postcheck_w1a_vs1.py` — W1D/W1E exact revision postcheck
3. `scripts/restore-drill.ps1` — W1D/W1E restore support와 marker 강제
4. `scripts/test-w1f-postgres.ps1` — exact-SHA synthetic backup/restore live gate
5. `review/environment/office/2026-08-01_W1F.md` — append-only raw evidence/trouble

이 패킷, migration, ORM/model, API/domain, frontend, generated client, 기존 W1A~W1E
wrapper, dependency/lockfile, `.env*`와 credential 파일은 수정하지 않는다. 다른 제품 결함이
발견되면 현재 candidate를 실패로 봉인하고 별도 repair packet 전에는 수정하지 않는다.

## 4. RED 무결성

제작자의 첫 write는 `backend/tests/test_w1f_contract.py`뿐이다. 제품·restore·postcheck·
live wrapper를 수정하기 전에 다음 exact command를 실행한다.

```powershell
Set-Location C:\sswcenter\2.1\backend
.\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_w1f_contract.py
```

초기 기대는 `5 collected / 1 passed / 4 failed / 0 skipped / 0 error`, exit `1`이다.
고정 test node는 다음과 같다.

1. W1D manifest가 unsupported-revision 단계 전에 통과하는 동적 PowerShell probe
2. W1E manifest가 unsupported-revision 단계 전에 통과하는 동적 PowerShell probe
3. postcheck가 W1D/W1E exact revision별 verifier와 marker를 제공하는 계약
4. `scripts/test-w1f-postgres.ps1`의 exact-SHA·합성자료·count/hash·cleanup 계약
5. 기존 W1C restore 지원과 marker가 유지되는 ABS 회귀 — 초기부터 PASS

구현 뒤 test 이름·초기 실패 의미·W1C ABS를 약화하지 않는다. 보정이 필요하면 test diff와
이유를 원장에 기록한다. regex/source 검사는 보조 증거이며 W1D/W1E manifest probe와 최종
PostgreSQL restore는 동적이어야 한다.

## 5. 구현 계약

### 5.1 postcheck

- exact revision `20260730_0011_w1d_recipient_contract`와
  `20260801_0012_w1e_care_assignment`를 명시적으로 지원한다.
- W1D에서는 `recipient_contract`, W1E에서는 `care_assignment`의 핵심 catalog,
  named constraint/trigger/function, `erp_app` write-without-delete,
  `erp_backup` SELECT-only를 검사한다.
- W1E head는 W1D와 모든 이전 W1 verifier도 함께 실행한다.
- 성공 marker는 exact `W1D_DB_POSTCHECK_OK`, `W1E_DB_POSTCHECK_OK`다.
- 기존 W1A~W1C marker·검증을 보존하고 알 수 없는 future revision을 W1A 성공으로
  낮추지 않는다.

### 5.2 restore drill

- W1D/W1E manifest revision을 allowlist에 추가하고 해당 postcheck marker를 강제한다.
- maintenance DB, 기존 target overwrite, unsafe data-root prefix, escaped manifest/dump/
  bundle path와 hash mismatch 거부를 유지한다.
- W1D/W1E에서 marker가 없거나 postcheck가 실패하면 restore 성공을 선언하지 않는다.

### 5.3 W1F live restore gate

- `-ExpectedSha`를 필수로 받고 시작·종료 HEAD가 exact SHA와 같고 tracked/untracked/staged
  상태가 clean인지 fail-close 확인한다.
- PostgreSQL 17 전용 temp cluster, 전용 port, `_review` DB, process-local TEMP/data/artifact
  root만 사용한다. 운영 DSN, `.env`, 실제 PII, 기존 PostgreSQL cluster를 사용하지 않는다.
- fresh `base→head`, W1D boundary downgrade/re-upgrade, offline SQL empty-DB apply를
  수행한다.
- 합성 W1A 자료에는 최소 staff identity 1, 보존 `display_name`/`memo`, employment 1,
  position 1, 일반 license 3, service qualification 1, training seed와 completion 1을
  포함한다. 평문 주민번호는 만들지 않는다.
- backup 전 canonical count/value hash와 synthetic file SHA-256을 기록하고,
  `backup-postgres.ps1`→`restore-drill.ps1` 뒤 새 DB/data root에서 정확히 대조한다.
- W1D/W1E postcheck marker를 모두 관찰하고 W1D/W1E table·backup ACL을 확인한다.
- 모든 child process는 bounded timeout, stdout/stderr 분리 drain, wait/dispose를 거친다.
- 성공 marker 순서는 stage evidence 뒤 `W1F_POSTGRES_GREEN`이 마지막이다. listener,
  PostgreSQL/PowerShell/Python child, temp root, review DB, backup·restore artifact 잔존은 `0`.

## 6. candidate 통합 gate

제품 candidate commit 뒤 같은 clean exact SHA에서 순차 실행한다. 한 live wrapper가 진행
중일 때 다른 PostgreSQL/browser wrapper를 병렬 실행하지 않는다.

1. PowerShell 5.1 AST: 변경된 두 `.ps1`과 기존 호출 wrapper errors `0`.
2. focused contract: `5/5`, failed/skipped/error `0`.
3. backend: Ruff format/check, mypy, 명시적 non-live SEM/API/OA/ABS 회귀 exit `0`.
   전체 inventory는 봉인 전 `304 collected`, warning `1`이었다.
4. OpenAPI: `scripts/generate-openapi-types.ps1 -Check`, marker
   `OPENAPI_TYPES_UP_TO_DATE`.
5. frontend: full Vitest, TypeScript production build, oxlint; Playwright 전체 discovery
   workers `1`, collection 감소·skip 증가 없음.
6. Wave 0: `scripts/test-ephemeral-postgres.ps1 -Port 55432`.
7. W1A: `scripts/test-w1a-vs6-postgres.ps1 -Port 55439 -ExpectGreen`.
8. W1B: `scripts/test-w1b-postgres.ps1 -Port 55440 -BackendPort 18090
   -FrontendPort 14190`.
9. W1C: `scripts/test-w1c-postgres.ps1 -Port 55441`.
10. W1D: `scripts/test-w1d-postgres.ps1 -Port 55442 -BackendPort 18092
    -FrontendPort 14192`.
11. W1E: `scripts/test-w1e-postgres.ps1 -ExpectedSha <candidate> -Port 55443`.
12. W1F restore: `scripts/test-w1f-postgres.ps1 -ExpectedSha <candidate> -Port 55444`.
13. final leak/plaintext scan, reserved listeners/process/temp/artifact `0`, `git diff --check`
    exit `0`, exact SHA와 clean tree.

어느 필수 gate도 이전 slice의 역사적 GREEN으로 대체하지 않는다. 환경이나 harness
failure도 PASS로 낮추지 않고 `BLOCK` 또는 `FAIL`로 분리한다.

## 7. provider와 독립검수

- Claude 실행은 정본 절대경로 `C:\Users\USER\.local\bin\claude.exe`와 호출 직전
  `--version` exit `0`을 사용한다. PATH lookup 실패는 미설치 근거가 아니다.
- Claude는 위 다섯 경로의 단일 writer다. stage·commit·push·dependency 설치·secret
  접근·subagent·외부 MCP를 금지한다.
- DeepSeek sidecar는 candidate bytes의 restore/postcheck/timeout/cleanup 경계를
  read-only로 반대심사한다. 수정 권한은 없다.
- 최종 독립검수는 별도 사용자 표시 Codex 작업방, fresh clean worktree, exact candidate,
  read-only/no-subagent로 수행한다. 첫 PASS 뒤 migration/DATA_LOSS/live DB 경계에 대한
  fresh 2차 검수를 한 번 허용한다.
- 최종 판정은 `PASS|REQUIRED_CHANGES|BLOCK`. 두 reviewer PASS 전 W1F PASS, Wave 1
  종료, tag, v3.8 승격을 선언하지 않는다.

## 8. 기준선과 측정

가장 가까운 v3.7 HIGH 기준선은 W1D final integration pilot이다. 기록된 wall-clock은
`40m45s`, input `12,909,458`, cached input `12,324,096`, output `111,119`, reasoning
`47,780`, total `13,020,577` tokens이며 실제 비용은 `uninstrumented`다. W1F 범위가 더
넓으므로 직접 동등 비교의 한계를 명시한다.

이번 파일럿은 다음을 기록한다.

- 총 wall-clock, Claude 제작 active time, DeepSeek sidecar time, Regina 통합·live gate
  time, 독립검수 time
- provider별 호출·turn·retry·무패치·handoff, token/cost 또는 `uninstrumented`
- RED/GREEN 수치, 각 gate command/exit/count/marker, finding과 repair round
- exact changed paths/SHA, cleanup, local/upstream/remote 상태

품질 gate가 모두 통과해도 비용이 `uninstrumented`면 비용 개선은 입증되지 않는다. MEDIUM과
HIGH가 끝난 뒤 품질·시간·비용을 함께 평가하기 전 v3.8을 정본으로 승격하지 않는다.

## 9. 비범위와 중지조건

- Wave 2+ 제품 구조, migration, API, UI 선구현 금지
- 실제 고객 데이터·운영 DB·운영 파일·secret 접근 금지
- dependency/environment/global PATH 변경 금지
- 실패한 gate를 skip·xfail·marker 완화로 통과시키기 금지
- 서로 다른 구조적 `REQUIRED_CHANGES`가 두 차례 연속이면 자동 세 번째 보정을 중지하고
  사용자에게 재설계 승인을 요청한다.
