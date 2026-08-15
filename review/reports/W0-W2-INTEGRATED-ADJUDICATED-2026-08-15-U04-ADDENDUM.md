# SSWCenter 3.0 W0~W2 통합 재판정 — U-04 로그 cap 격리 부록

> 부록일: 2026-08-15 KST  
> 적용 대상: [`W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md`](W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md)  
> 평가 기준: `main` base `a55d25d64ea571acf94ca2cbfbfd38bf4eb5e4bf` → candidate `d8590a5`  
> 지위: U-04 한 슬라이스의 구현·검증 후보 기록. W0 전체 acceptance·운영 수용·release 승인과 동일하지 않다.

## 판정

| ID | 이전 상태 | candidate 상태 | 범위 |
|---|---|---|---|
| U-04 | `CURRENT_CONFIRMED` | `SATISFIED_BY_CANDIDATE` | 로그 total cap을 디렉터리 전체의 `.log` 활성 파일과 모든 log-family archive에 적용하되, 삭제 대상은 archive로만 제한해 다른 활성 로그 family를 교차 삭제하지 않는다. |

`SATISFIED_BY_CANDIDATE`는 구현 커밋과 검증 증거가 있는 PR 후보라는 뜻이다. PR 병합과 최종 Grade 5/security review 전에는 current-main 해결로 재사용하지 않는다.

## 구현 범위

- `backend/app/core/logging.py`
  - `DailySizeCompressedFileHandler._prune_archives`의 total-cap 계산을 로그 디렉터리의 활성 `.log`와 모든 `.log.*.gz` archive로 통합한다.
  - cap 초과 시 archive만 삭제해 `app.log` handler가 `error.log`, `access.log`, `install-update.log` 등 sibling 활성 로그를 삭제하지 않으면서 디렉터리-wide 예산을 유지한다.
- `backend/tests/test_logging.py`
  - sibling 활성 로그 3종과 app/error 양쪽 archive를 함께 둔 cap 시나리오를 추가했다.
  - cap 초과 시 모든 family archive가 삭제되고 sibling 활성 로그는 보존되는지 mutation-sensitive하게 검증한다.

## 검증 증거

- focused pytest: `9 passed`, exit `0`.
- 전체 backend pytest: `391 passed, 139 skipped`; 기존 `test_r0_w2_read_only_contract_02_file_hashes_are_expected` 1건은 candidate와 무관한 고정 hash 불일치(`expected B37B...`, current `B0CC...`)로 남았다.
- Ruff: 변경 Python 파일 exit `0`.
- mypy: 변경 logging source exit `0`.
- `git diff --check`: exit `0`.

## 남은 경계

- 실제 production 로그 디렉터리에서의 운영 cap·권한·디스크 장애 증거는 이 candidate에서 다루지 않았다.
- U-04 ordinary `/review`는 PR candidate에서 수행하며, 지적사항이 있으면 수정 후 위 검증을 재실행한다.
- U-04 candidate 보안 스캔은 최종 다중 슬라이스 후보에서 한 번만 수행한다.
