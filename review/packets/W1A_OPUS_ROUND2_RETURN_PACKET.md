# W1A-VS1 Opus 2차 반대심사 반환 패킷

> 상태: 2026-07-27 영구 역할 교체로 구현 패킷에서 보류된 역사 기록.
> 이후 Opus는 읽기 전용 반대심사만 수행하고, 최고난도 구현은 기존 마르코
> 작업방에 배정한다.

## 1. 담당과 실행

- 담당: Claude CLI Opus 5
- 모델·추론강도: `--model opus --effort high`
- 대상 worktree:
  `C:\Users\USER\.codex\worktrees\opus-w1a-019f9e39`
- staged index는 Codex 전달 baseline이다. reset하거나 다시 stage하지 않는다.
- 현재 unstaged 17개와 untracked 3개를 이어서 보정한다.
- 금지:
  - agent/subagent 생성
  - Git stage/commit/push/reset
  - 정본, 계획, 검토 패킷, 심사 보고서 수정
  - W1A 밖 리팩터링
  - 최종승인 선언

## 2. 먼저 읽을 자료

1. 루트 저장소
   `review/reports/w1a-vs1-marco-opus-round2.md`
2. 루트 저장소
   `review/packets/W1A_MARCO_ROUND2_PACKET.md`
3. 루트 저장소
   `review/packets/W1A_OPUS_ROUND1_RETURN_PACKET.md`
4. 대상 worktree
   `review/packets/W1A_OPUS_HARDENING_PACKET.md`

## 3. 반드시 보정할 차단점

### A. 인증 query 취소·제거 경계

- TanStack Query의 `signal`을 직원 목록, 상세, capability 요청에 끝까지
  전달한다.
- StaffPage 이탈 시 해당 query를 cancel하고 cache에서 remove한다.
- logout, 직접 account switch, 페이지 이탈 각각에서 이전 계정의 진행 중
  요청과 cache가 남지 않아야 한다.
- 계정 A 요청의 성공과 401을 각각 defer한 뒤 계정 B 전환 후 해제해도:
  - 계정 B 세션 유지
  - 계정 A 자료 0건
  - 미완료 요청 0건
  - 전역 unauthorized event의 오염 0건
  이어야 한다.

### B. RRN 후보 판별

- logging과 leak gate에 같은 의미의 판별 규칙과 공통 테스트 벡터를 적용한다.
- 하이픈 바로 뒤, underscore 인접, 여러 일반 구분자, raw/hyphenated,
  0~9 코드, 긴 숫자를 모두 검증한다.
- 실제 2024년을 포함한 여러 정상 epoch milliseconds를 RRN으로 오인하지
  않는다.
- raw 13자리와 epoch가 겹치는 경우 안전성과 오탐 방지를 동시에 만족하는
  문맥 기반 판정 또는 명시적 보수 정책을 코드와 테스트에서 일관되게
  적용한다.
- 실패 출력에 실제 후보 문자열을 노출하지 않는다.

### C. leak gate 범위와 fail-closed

- `git ls-files`를 기준으로 tracked, staged/unstaged 변경, untracked 파일을
  모두 포함한다.
- `.venv`, `node_modules`, build, cache 등 명확한 비대상만 제외한다.
- migration, W1A error handler, AuthProvider, 생성 OpenAPI TypeScript,
  staff API adapter 등 현재 누락된 WIP 파일이 반드시 scan에 포함돼야 한다.
- app/error/access와 회전 gzip, PostgreSQL log, Playwright output을 유지한다.
- 텍스트나 gzip 읽기 실패는 gate 실패로 처리한다.
- 임시 유출 fixture를 각 surface에 넣었을 때 non-zero가 되는 self-test를
  추가한다.

### D. 실제 PostgreSQL 증거 강화

- 서로 다른 계정 A와 B를 사용해 생성자와 교정 actor가 달라짐을 검증한다.
- 부모와 모든 관련 자식의 정확한 actor와 증가한 `updated_at_utc`를
  검증한다.
- 첫 mutation 후 두 번째 mutation 실패 전후
  `BusinessNumberCounter.last_sequence` exact 동일성을 검증한다.
- replacement와 audit 행이 전부 원복됨을 검증한다.
- omission 422도 실제 PostgreSQL 통합 흐름에 추가한다.

## 4. 중요 보강

- 실제 non-API 예외를 발생시켜 catch-all 보존을 회귀 테스트한다.
- 손상된 gzip이 gate를 실패시키는지 테스트한다.
- 테스트 주석과 실제 assertion이 일치하도록 정리한다.

## 5. 완료조건

- 위 A~D와 중요 보강이 코드와 회귀 테스트로 해결된다.
- backend Ruff format/check, mypy, 전체 pytest가 통과한다.
- frontend 전체 unit, lint, build가 통과한다.
- OpenAPI 공식 생성기 `-Check`가 drift 0이다.
- 실제 PostgreSQL 전체 harness가 통과한다.
- 실제 PostgreSQL Playwright 3 viewports, workers=1이 통과한다.
- 새 leak gate가 전체 범위를 검사해 0건이고 RED self-test가 누출을
  검출한다.
- staged와 unstaged `git diff --check`가 통과한다.

## 6. 반환 형식

- 변경 파일 전체
- A~D와 중요 보강 각각의 코드·테스트 대응
- 정확한 명령, exit code, 결과
- leak gate가 실제로 포함한 파일 수와 누락 방지 증거
- 남은 위험
- stage, commit, push, 최종승인 없음

마르코는 이미 두 차례 반대심사를 완료했다. 이 보정 뒤에는 Codex 본진이
독립 검증과 최종심사를 수행한다. 결함을 본진에 넘기지 말고 Opus가 직접
보정한다.

## 7. 2026-07-27 09:52 재개 체크포인트

Opus를 `--model opus --effort high`로 재개해 2차 차단점 보정을 진행했으나
09:52 KST에 Claude 세션 한도에 도달했다. CLI가 안내한 다음 reset 시각은
`2026-07-27 13:50 KST`다. 최종보고는 제출되지 않았다.

이 호출에서 새로 확인된 untracked WIP:

- `scripts/w1a-rrn-detector.ps1`
- `scripts/w1a-rrn-vectors.json`

기존 unstaged 17개와 untracked 3개도 그대로 보존되어 있다. staged baseline은
변하지 않았다.

Codex 본진의 중단 직후 읽기 전용 체크포인트 검증:

- unstaged `git diff --check`: PASS
- backend:
  - Ruff format/check: PASS
  - mypy: PASS
  - pytest: `54 passed, 14 skipped`
- frontend:
  - Vitest: 10 files, `44 passed`
  - lint: PASS
  - build: PASS
- OpenAPI 공식 생성기 `-Check`: PASS
- 새 leak gate: FAIL
  - `verify-w1a-vs1-leak-gate.ps1:129`
  - `[System.IO.Path]::GetExtension($relative)`에 불법 경로 문자가 전달됨
- 실제 PostgreSQL 전체 harness와 Playwright는 이번 부분 보정 뒤 아직
  재실행하지 않음

13:50 재개 시 WIP를 되돌리지 말고 Opus가 leak gate 경로 수집 오류를 직접
원인 규명·보정한다. 이어 A~D, negative self-test, 실제 PostgreSQL,
Playwright와 전체 완료조건을 마치고 최종보고를 제출한다. Codex 본진은 이
결함을 대신 구현하지 않는다.
