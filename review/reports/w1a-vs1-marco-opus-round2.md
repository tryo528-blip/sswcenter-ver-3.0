# W1A-VS1 마르코 Opus 보정 2차 반대심사

> 심사일: 2026-07-27 KST
>
> 심사자: 마르코 (`gpt-5.6-sol / max`)
>
> 대상:
> `C:\Users\USER\.codex\worktrees\opus-w1a-019f9e39`
>
> 판정: `REQUIRED_CHANGES`

이 문서는 Opus 결과에 대한 2차이자 마지막 마르코 반대심사 기록이다.
최종승인은 Codex 본진이 담당한다. 마르코는 파일 수정, stage, commit, push,
reset을 하지 않았다.

## 차단 결함

### R2-M3. 페이지 이탈과 지연 인증 요청이 봉인되지 않음

- 직원·capability query가 TanStack Query의 `signal`을 소비하지 않고,
  `staffApi`도 목록·상세·capability fetch에 `AbortSignal`을 전달하지 않는다.
- `StaffPage` unmount cleanup은 reveal만 abort한다. 페이지 이탈 시 직원
  목록·상세 cache가 남는다는 사실을 기존 테스트 주석도 인정한다.
- `queryClient.clear()` 뒤에도 신호를 소비하지 않은 HTTP 요청이 계속될 수
  있다. 이전 계정의 지연 401이 전역 unauthorized event를 발생시키면 새 계정
  세션에도 영향을 줄 수 있다.
- 필수 보정:
  - 인증 종속 query에 `signal`을 끝까지 전달
  - 페이지 cleanup에서 직원·capability query 취소·제거
  - 계정 A의 성공·401 응답을 defer한 뒤 페이지 이탈 또는 logout,
    계정 B login, A 응답 해제 순으로 검증
  - 직접 A→B 전환도 별도 검증

### R2-M4M5. RRN 휴리스틱이 실제 후보를 놓치고 epoch를 과검출함

- Python logging과 PowerShell leak gate가 동일한 잘못된 경계를 사용한다.
- 일반적인 2024년 epoch milliseconds가 RRN으로 과검출된다.
- 하이픈 바로 뒤의 실제 하이픈형 후보가 누락된다.
- underscore 인접 후보는 탐지된다.
- 기존 음성 테스트는 월이 유효하지 않은 epoch 하나만 사용해 일반적인
  epoch 충돌을 잡지 못한다.
- 필수 보정:
  - Python과 PowerShell이 공유하는 경계 테스트 벡터 마련
  - 여러 epoch, 모든 구분자, 0~9 코드, raw/hyphenated, 장문 숫자 포함
  - raw 13자리와 epoch의 본질적 중첩은 문맥 기반 판정 또는 명시적 보수
    정책으로 일관되게 처리

### R2-M5. 독립 leak gate의 workspace 범위가 불완전함

- gate가 고정 allowlist만 재귀 검사한다.
- 현재 Opus WIP에서도 migration, W1A error handler, AuthProvider, 생성
  OpenAPI TypeScript, staff API adapter가 검사 대상에서 빠진다.
- 따라서 `50 files / 0건`은 staged, unstaged, untracked 전체 변경의
  유출 부재 증거가 아니다.
- 필수 보정:
  - tracked 파일, staged/unstaged 변경, untracked 파일을 Git 기준으로 합침
  - dependency, build, cache 디렉터리만 명시적으로 제외
  - 각 surface에 임시 유출 fixture를 넣으면 non-zero로 실패하는 self-test
  - 읽기 실패와 손상된 gzip은 fail-closed

### R2-M2. actor, time, counter rollback 증거가 불충분함

- 부모 actor가 null이 아닌지만 검사한다. 생성자와 교정자가 같은 계정이어서
  actor 갱신이 없어도 통과한다.
- 자식 actor와 `updated_at_utc` 증가를 검사하지 않는다.
- rollback 테스트는 employment 행 수만 비교하며 실제 증가 대상인
  `BusinessNumberCounter.last_sequence` 전후 값을 비교하지 않는다.
- 첫 자식 flush 뒤 두 번째 자식 실패와 행 rollback 자체는 확인됐다.
  기능 결함이 확정된 것은 아니지만 필수 검증 계약을 충족하지 못했다.
- 필수 보정:
  - 계정 A 생성 후 계정 B가 교정
  - 부모와 모든 자식의 정확한 actor와 증가한 timestamp 확인
  - 실패 전후 counter exact 동일성 확인
  - replacement와 audit 행이 전부 원복됐는지 확인

## 중요 권고

1. M1의 runtime, API, OpenAPI, 생성 TypeScript required-nullable 계약은
   해결됐지만 실제 PostgreSQL 통합 테스트에도 omission 422를 추가한다.
2. 비-API catch-all 보존 코드에 실제 non-API 예외 회귀 테스트를 추가한다.
3. 손상된 gzip을 빈 문자열로 취급하지 않고 fail-closed한다.

## M1~M9 판정

| 항목 | 판정 | 근거 |
|---|---|---|
| M1 | 해결 | omission 422, explicit null, required-nullable OpenAPI·TS |
| M2 | 증거불충분 | actor/time/counter assertion 미달 |
| M3 | 미해결 | unmount cache, signal 미전달, 지연 401 위험 |
| M4 | 미해결 | traceback/Uvicorn 연결은 해결, 후보 경계 결함 잔존 |
| M5 | 미해결 | 후보 경계와 workspace scan 누락 |
| M6 | 해결 | schema/table/sequence ACL과 precondition 확인 |
| M7 | 해결 | 서버 projection과 날짜 경계 테스트 |
| M8 | 해결 | enum, normalization, pattern, 생성 TS 일치 |
| M9 | 해결 | format/check/mypy/OpenAPI drift 해소 |

## 마르코 독립 검증

- backend 관련 33 tests: PASS
- frontend 2 files, 9 tests: PASS
- Ruff format/check: PASS
- mypy 29 files: PASS
- frontend lint/build: PASS
- OpenAPI `-Check`: PASS
- staged/unstaged `git diff --check`: PASS
- 기존 leak gate: 50 files, 0건
  - 단, R2-M5 때문에 승인 증거로 인정하지 않음
