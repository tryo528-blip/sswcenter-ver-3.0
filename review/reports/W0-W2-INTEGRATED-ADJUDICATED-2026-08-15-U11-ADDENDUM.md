# SSWCenter 3.0 W0~W2 통합 재판정 — U-11 seed contract 부록

> 부록일: 2026-08-15 KST  
> 적용 대상: [`W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md`](W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md)  
> 평가 기준: `main` base `a55d25d64ea571acf94ca2cbfbfd38bf4eb5e4bf` → candidate `55a1c4a`  
> 지위: U-11 한 슬라이스의 구현·검증 후보 기록. W1 전체 acceptance·운영 수용·release 승인과 동일하지 않다.

## 판정

| ID | 이전 상태 | candidate 상태 | 범위 |
|---|---|---|---|
| U-11 | `CURRENT_CONFIRMED` | `SATISFIED_BY_CANDIDATE` | 개발·극한 합성 seed를 현재 W1C/W1B schema와 ORM에 맞춰 import·실행 가능한 shape로 정렬했다. |

`SATISFIED_BY_CANDIDATE`는 구현 커밋과 검증 증거가 있는 PR 후보라는 뜻이다. PR 병합과 최종 Grade 5/security review 전에는 current-main 해결로 재사용하지 않는다.

## 구현 범위

- `backend/app/db/seed_dev_recipients.py`
  - 제거된 `GradePeriodCreateRequest`와 별도 grade 호출을 없애고, grade를 `CertificationPeriodCreateRequest`에 포함한다.
  - `RecipientBasicCreateBatchRequest`에는 basic recipient/guardian만 전달하고 benefit은 현재 W1C service 호출로 별도 생성한다.
  - `BenefitPeriodCreateRequest.start_text`에 opaque display text를 전달하며 제거된 `home_phone`·날짜형 benefit 필드는 사용하지 않는다.
- `backend/app/db/seed_extreme_test_data.py`
  - 현재 recipient schema에 없는 `home_phone`과 recipient contract의 퇴역 signer 필드를 제거한다.
  - 현재 certification period의 non-null `grade_code`를 유효한 1~5 값으로 채운다.
- `backend/tests/test_u11_seed_contract.py`
  - 두 seed의 현재 model shape와 grade 이동을 DB 없이 직접 검증하고 extreme seed의 grade도 확인한다.

## 검증 증거

- review 전 focused pytest: `3 passed`, exit `0`.
- review 후 수정은 `ruff` exit `0`, `py_compile` exit `0`, `git diff --check` exit `0`으로 확인했다. 현재 시스템 Python 환경에는 FastAPI/SQLAlchemy가 없어 수정 후 pytest는 재실행하지 못했다.
- 전체 backend pytest의 기존 baseline은 `393 passed, 139 skipped`; `test_r0_w2_read_only_contract_02_file_hashes_are_expected` 1건은 candidate와 무관한 고정 hash 불일치(`expected B37B...`, current `B0CC...`)로 남았다.
- scoped mypy (`--follow-imports=skip`)는 의존성 환경 부재로 이번 재검증에서 수행하지 않았다.
- 일반 strict mypy는 기존 `app/domains/recipient/service.py` 오류 3건 때문에 저장소 baseline에서 실패하며, 이번 candidate 변경과 무관하다.
- `git diff --check`: exit `0`.

## 남은 경계

- 실제 격리 PostgreSQL에서 200건 개발 seed·극한 seed 전체를 실행하는 증거는 이 candidate에서 다루지 않았다.
- U-11 ordinary `/review`는 PR candidate에서 수행하며, 지적사항이 있으면 수정 후 위 검증을 재실행한다.
- U-11 candidate 보안 스캔은 최종 다중 슬라이스 후보에서 한 번만 수행한다.
