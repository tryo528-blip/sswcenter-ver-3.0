# W1A-VS1 내부 실무 검증 배정표 v2.2

> 배정일: 2026-07-27 KST
>
> 상태: **COMPLETED / FINAL PASS**
>
> 운영정본: `docs/AI_업무분담_운영규정_v2.2.md`
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 기준 commit: `c4ee9f1420e0c9d3d97f01fc835c7d9495974008`
>
> 최종 구현 commit: `55130af1dc3244c391bca11471323e6b22061c3f`
>
> 총괄·최종판정: 김부장(Codex 본진 / SOL Max)

## 1. 목표

사무실에서 반영된 W1A hardening WIP가 기존 차단사항을 실제로 해결하는지
backend, frontend, PostgreSQL, 민감정보·누출의 네 독립 범위로 검증한다.

이번 wave는 읽기 전용 검증이다. 구현 결함이 확인되기 전에는 제품 파일을
수정하지 않는다.

## 2. 역할별 배정

| 담당 | 모델 | 작업방 | 검증 범위 |
|---|---|---|---|
| 김루나 | Luna Max | `019fa2db-d4ca-7621-9e3d-b6d0d45292e2` | backend·API·DB·service logic |
| 박루나 | Luna Max | `019fa2dc-007e-78b2-b683-c0c408a625f6` | frontend·화면·상태관리·API adapter |
| 이루나 | Luna Max | `019fa2dc-2c9a-7a51-83f8-1704c1b2320b` | test·권한·동시성·PostgreSQL 정합성 |
| 송루나 | Luna Max | `019fa2dc-58b2-7e72-8073-be5d78ac3bee` | 회귀·UI·민감정보·로그·누출 |

## 3. 공통 금지

- 제품·테스트·정본 파일 수정
- Git stage·commit·push·reset
- 같은 파일을 다른 담당자와 중복 수정
- 다른 작업자 생성
- 실제 개인정보·secret 출력
- 실행하지 않은 검사를 GREEN으로 보고

## 4. 담당별 완료조건

### 김루나

- migration, W1A error mapper, logging, policies, schemas, service diff 검토
- Ruff format/check, mypy, backend pytest 실행
- RRN, required-nullable·422, rollback, actor·timestamp·audit 근거 제출

### 박루나

- AuthProvider, StaffPage, api/staffApi, generated type diff 검토
- frontend Vitest, lint, build 실행
- AbortSignal, unmount cache, logout·A→B·지연 success/401 격리 근거 제출

### 이루나

- 실제 PostgreSQL harness와 migration·ACL·rollback 검사
- A/B actor, timestamp, row version, counter, replacement·audit rollback,
  omission 422 근거 제출
- 환경 prerequisite가 없으면 정확한 blocker 제출

### 송루나

- Python/PowerShell RRN 의미와 공통 vector 검토
- Git 전체파일 scan, text/gzip fail-closed, negative leak self-test 실행
- 가능하면 workers=1·3 viewport Playwright 및 DOM/cache/log 잔존 확인

## 5. 반환 형식

- 판정
- 실행한 명령과 exit code
- 테스트·검사 수
- 차단 결함·중요 권고·후속 개선
- 파일과 줄 근거
- 수정이 필요할 경우 정확한 파일 소유범위
- 남은 위험

## 6. 다음 단계

김부장이 네 결과를 취합해 중복·오탐·파일 소유권을 판정한다. 실제 결함은
해당 루나에게 수정 패킷으로 반환한다.

- 새 고난도 설계가 필요할 때만 요셉을 호출한다.
- 고위험 결함의 유효성 판정이 필요할 때만 마르코를 호출한다.
- 외부 독립성이 필요하면 오푸스에게 구현 또는 감리 중 하나만 맡긴다.
- 반복량이 큰 별도 작업이 생길 때만 AGY를 호출한다.

## 7. 완료 결과

| 담당 | 최종 결과 | 핵심 증거 |
|---|---|---|
| 김루나 | PASS | backend 51 passed, 12 skipped; RRN 후보 0; Ruff·mypy PASS |
| 박루나 | PASS | frontend 54 tests; lint·build PASS; logout·account transition 회귀 PASS |
| 이루나 | PASS | PostgreSQL 정합성·artifact·leak gate 독립 재심사 PASS |
| 송루나 | PASS | 제품 교차검증 PASS; 40-vector·artifact 누출검사 보정 PASS |
| 김부장 | FINAL PASS | 실제 PostgreSQL 전체 harness, Playwright 3 viewport, artifact 포함 leak gate 최종 GREEN |

발견된 결함은 원 소유자에게 반환해 보정했고 다른 담당자의 교차검증을
통과했다. 상세 최종 증거는 `review/evidence/w1a-vs1/GREEN.md`에 기록한다.
