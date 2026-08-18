# W3 workbook parser·matcher·persistent workspace 현재 실행계획 — 2026-08-18

> 상태: `PROFILE_GREEN / 0029_GREEN / LIVE_GREEN / REVIEW_GREEN / FINAL_SEAL_READY`
> 기준 저장소: `/home/codexctl/workspace/sswcenter-3-0`
> branch: `codex/debt-preseal-20260818`
> Git 경계: 이 요청에서 stage·commit·push·merge 없음

## 완료 범위

1. 제공된 가명 workbook 두 개의 exact profile, fail-closed OOXML preflight, raw row
   계보, normalized row, occurrence signature/ordinal을 고정했다.
2. NHIS 910 raw row→887 derived group과 RFID 선택일 파생을 삭제 없이 구현했다.
3. generic target pair 없이 recipient·certification·staff·employment·service·contract·
   assignment·W2 schedule typed FK를 갖는 exact child migration `0029`를 구현했다.
4. preview→resolve→confirm→APPLY 상태기계와 source/date apply-control 직렬화,
   immutable actual-work revision reconciliation, append-only supplement/plan-adjustment를
   구현했다.
5. APPLY 직전에 확정월과 저장된 typed link를 재검증하고, RFID 일정은 선택일의 KST
   일자·월에 묶었다.
6. command key는 resource row lock 뒤 전역 transaction advisory lock으로 직렬화한다.
   동일 payload 재시도는 같은 결과, 다른 payload는 최신 workspace를 포함한 409다.
7. dataful `0029→0028→0029` 재승격에서 남아 있는 ACTIVE/APPLIED 계보로 apply-control을
   복구한다.
8. FILE_ONLY API 7개 경로, generated OpenAPI type, 단일 `/io` 상태 workspace와 390px
   모바일 command 흐름을 구현했다.

## 완료 증거

- runtime: `SSWCENTER_RUNTIME_GREEN`
- W3 0029 live PostgreSQL: 5 passed, migration 왕복, dataful reupgrade, backup/restore,
  cleanup all zero
- W3 0028 historical PostgreSQL: 34 passed, restore/cleanup green
- W0 current head: 3 passed
- W1E 0026: 23 passed
- W2 0027: 29 passed + current-0029 HTTP 1 passed + real Chromium 1 passed
- official supported backend gate: 622 passed, 205 skipped
- frontend: 27 files / 271 tests, lint, build, W3 Chromium 390×844 passed
- independent review round 1: Grok finding 9건 중 승인 범위 8건 교정,
  APPLIED 재활성 제안 1건은 승인된 단방향 상태기계 밖으로 기각
- independent review round 2: Grok post-fix `NO FINDINGS` (P0–P3 없음)

## 기록한 중간 문제

- pytest 기본 capture 임시파일 오류는 `-s`로 재현 분리했고 공식 `scripts/test.ps1`에도
  `-s`를 고정했다.
- Chromium 첫 실행은 호스트 공유 라이브러리 부재로 실패했다. 준비된 로컬 라이브러리
  경로로 실행한 뒤 실제 390px app-shell overflow를 찾아 수정했다.
- 백엔드 병렬 검증 첫 명령은 cwd에 `backend/`를 중복해 즉시 실패했고 올바른 경로로
  재실행했다.
- W1E를 다른 PostgreSQL 하네스와 병렬 실행했을 때 타 하네스 프로세스를 잔여물로
  오인했다. 단독 재실행에서 23 passed와 cleanup all zero를 확인했다.
- DeepSeek review는 tool-turn 초과 1회와 900초 초과 1회로 유효 결과가 없었다.
  성공으로 계산하지 않고 Grok의 독립 post-fix review를 별도 수행했다.

## 비차단 잔여 경계

- `APPLIED A→B→A` 재활성은 승인된 단방향 상태기계에 rollback/reactivate command가
  없어 이번 범위 밖이다.
- APPLY typed-link 재검증과 commit 사이에 W1 원장이 별도 transaction으로 무효화되는
  극단적 TOCTOU를 막는 다중 원장 lock protocol은 승인 패킷 밖의 후속 hardening 후보다.
- NHIS 경로는 parser/group/matcher 계약과 지원 회귀는 녹색이나, 이번 live APPLY의
  고강도 경합 시나리오는 RFID 중심이다.

## 최종봉인 직전 남은 순서

1. current candidate manifest 70개 경로 exact SHA/bytes gate 재확인
2. clean process/listener/temp 및 `git diff --check`
3. 형님의 별도 Git 지시가 있을 때만 stage·commit·push

현재 구현 범위는 W3 최종봉인 후보이며 W4/W5는 비범위다.
