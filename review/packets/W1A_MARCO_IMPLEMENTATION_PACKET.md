# W1A-VS1 마르코 최고난도 구현 전달 패킷

> 상태: **SUPERSEDED / 역사 기록**
>
> `docs/AI_업무분담_운영규정_v2.2.md` 시행으로 이 문서의 마르코 상시 구현
> 배정은 폐기됐다. 아래 차단사항과 테스트 요구는 기술 증거로만 보존하고,
> 현재 담당은 `review/plans/W1A_STAFF_VERTICAL_SLICE_PLAN.md` §11·§20을
> 따른다.
>
> 마르코는 **Opus가 작업하던 기존 W1A WIP를 그대로 인수해 이어서** 기존
> 독립 작업방에서 보정한다. 새로 처음부터 구현하지 않으며, Opus WIP를
> reset·checkout·삭제하지 않는다. 새 작업방, 하부·보조·병렬 에이전트,
> stage·commit·push는 금지한다.

## 담당

- 담당: 마르코 독립 작업방
- 모델: `gpt-5.6-sol / max`
- 역할: W1A-VS1 최고난도 구현·설계·자기 범위 테스트
- 금지: 정본·README·계획·검토 패킷·심사 보고서 수정, 최종 승인 선언

## 기준 자료

1. `review/plans/W1A_STAFF_VERTICAL_SLICE_PLAN.md`
2. `review/reports/w1a-vs1-marco-opus-round2.md`
3. `review/packets/W1A_OPUS_ROUND2_RETURN_PACKET.md`
4. Opus 전용 worktree
   `C:\Users\USER\.codex\worktrees\opus-w1a-019f9e39`의 실제 diff와 W1A
   변경 파일

이전 Opus 구현·마르코 심사 결과는 역사 증거다. 현재 구현 소유권만 Opus에서
마르코로 이전하며, Opus의 기존 staged/unstaged/untracked WIP를 모두 보존한
상태에서 이어간다. 먼저 WIP diff와 체크포인트를 대조한 뒤 남은 차단사항만
보정한다.

## 구현할 차단사항

### A. 인증 경계

- 직원 목록·상세·capability query에 `AbortSignal`을 끝까지 전달한다.
- StaffPage 이탈, logout, 직접 account switch에서 진행 중 요청을 취소하고
  직원·capability cache를 제거한다.
- 계정 A의 지연 success/401이 계정 B 세션·자료·unauthorized event를
  오염시키지 않음을 테스트한다.

### B. RRN 후보 판별

- logging과 leak gate가 동일한 공통 규칙·벡터를 사용한다.
- 하이픈·underscore·구분자 인접, raw/hyphenated, `0`~`9` 코드, 긴 숫자를
  검증한다.
- 정상 epoch milliseconds 오탐과 실제 RRN 누락을 함께 방지하고 후보 원문을
  실패 출력에 노출하지 않는다.

### C. leak gate

- tracked/staged/unstaged/untracked를 모두 수집하고 명확한 build/cache만
  제외한다.
- app/error/access, 회전 gzip, PostgreSQL log, Playwright output을 검사한다.
- 텍스트·gzip read/압축 해제 실패는 fail-closed로 gate 실패 처리한다.
- 각 surface의 임시 유출 RED self-test를 둔다.

### D. 실제 PostgreSQL 증거

- 서로 다른 actor A/B, 정확한 actor·`updated_at_utc`·version을 검증한다.
- 두 번째 mutation 실패 전후 `BusinessNumberCounter.last_sequence`가
  exact 동일한지 확인한다.
- replacement와 audit 행이 모두 rollback되는지 확인하고 omission 422를
  실제 PG 통합 흐름에 포함한다.
- non-API catch-all 회귀와 손상 gzip 실패 회귀를 추가한다.

## 완료조건

- 위 A~D와 중요 보강이 코드와 회귀 테스트로 해결된다.
- backend Ruff format/check·mypy·전체 pytest PASS
- frontend Vitest·lint·build PASS
- OpenAPI 공식 생성기 `-Check` drift 0
- 실제 PostgreSQL harness와 workers=1 Playwright 3 viewport PASS
- leak gate GREEN 및 RED self-test 검출
- `git diff --check` PASS

## 반환 형식

- 변경 파일 전체
- A~D 및 중요 보강별 코드·테스트 대응
- 명령별 exit code와 핵심 결과
- leak gate 파일 수·누락 방지·fail-closed 증거
- 남은 위험

결과는 최종 승인이 아니라 Opus 독립 심사로 넘길 구현 증거다. Opus 1차에서
차단 결함이 나오면 마르코는 반대의견·수용/기각 근거를 명시하고 최대
2라운드까지 직접 보정·재검증한다. Opus 2차 심사 뒤 Codex 본진이 독립
검증·통합·최종심사를 한다.
