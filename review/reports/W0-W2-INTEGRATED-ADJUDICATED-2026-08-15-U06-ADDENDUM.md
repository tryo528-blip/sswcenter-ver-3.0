# SSWCenter 3.0 W0~W2 통합 재판정 — U-06 PIN redaction 부록

> 부록일: 2026-08-15 KST  
> 적용 대상: [`W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md`](W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md)  
> 평가 기준: `main` base `a55d25d64ea571acf94ca2cbfbfd38bf4eb5e4bf` → candidate `0ec115d`  
> 지위: U-06 한 슬라이스의 구현·검증 후보 기록. W0 전체 acceptance·운영 수용·release 승인과 동일하지 않다.

## 판정

| ID | 이전 상태 | candidate 상태 | 범위 |
|---|---|---|---|
| U-06 | `CURRENT_CONFIRMED` | `SATISFIED_BY_CANDIDATE` | 비구조화 로그의 PIN 값이 공백·화살표·구분자로 분리되어도 마스킹되도록 보강하고, 자연어 문장을 과잉 마스킹하지 않는 회귀를 추가했다. |

`SATISFIED_BY_CANDIDATE`는 구현 커밋과 검증 증거가 있는 PR 후보라는 뜻이다. PR 병합과 최종 Grade 5/security review 전에는 current-main 해결로 재사용하지 않는다.

## 구현 범위

- `backend/app/core/logging.py`
  - `pin`과 `current_pin` 뒤의 공백, `->`, `=>`, `:`, `=`, `|`, `/`, 하이픈 계열 구분자를 인식한다.
  - 숫자로 시작하는 PIN 후보 토큰을 `[REDACTED]`로 바꿔 exact-six 값뿐 아니라 잘못된 길이의 입력도 평문으로 남기지 않는다.
- `backend/tests/test_logging.py`
  - 공백·화살표·구분자와 5/7자리 numeric PIN 후보를 mutation-sensitive하게 검증한다.
  - `PIN rejected by policy`처럼 numeric value가 없는 자연어는 그대로 보존하는 과잉 마스킹 방지 테스트를 둔다.

## 검증 증거

- focused pytest: `17 passed`, exit `0`.
- 전체 backend pytest: `399 passed, 139 skipped`; 기존 `test_r0_w2_read_only_contract_02_file_hashes_are_expected` 1건은 candidate와 무관한 고정 hash 불일치(`expected B37B...`, current `B0CC...`)로 남았다.
- Ruff: 변경 Python 파일 exit `0`.
- mypy: 변경 logging source exit `0`.
- `git diff --check`: exit `0`.

## 남은 경계

- 실제 production 로그 수집기·운영 권한·외부 sink에서의 redaction 증거는 이 candidate에서 다루지 않았다.
- U-06 ordinary `/review`는 PR candidate에서 수행하며, 지적사항이 있으면 수정 후 위 검증을 재실행한다.
- U-06 candidate 보안 스캔은 최종 다중 슬라이스 후보에서 한 번만 수행한다.
