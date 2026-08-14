# SSWCenter 3.0 W0~W2 통합 재판정 — U-05 readiness/write gate 부록

> 부록일: 2026-08-15 KST
> 적용 대상: [`W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md`](W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md)
> 평가 기준: `main` base `a55d25d64ea571acf94ca2cbfbfd38bf4eb5e4bf` → candidate `6c9512e`
> 지위: U-05 한 슬라이스의 구현·검증 후보 기록. W0 전체 acceptance·운영 수용·release 승인과 동일하지 않다.

## 판정

| ID | 이전 상태 | candidate 상태 | 범위 |
|---|---|---|---|
| U-05 | `CURRENT_CONFIRMED` | `SATISFIED_BY_CANDIDATE` | DB 접속과 `erp` schema에 더해 정확한 Alembic 0025 head, runtime root/logs 경로를 확인하고, DB-backed mutating request가 readiness 실패 시 503으로 거부되도록 했다. |

`SATISFIED_BY_CANDIDATE`는 구현 커밋과 검증 증거가 있는 PR 후보라는 뜻이다. PR 병합과 최종 Grade 5/security review 전에는 current-main 해결로 재사용하지 않는다.

## 구현 범위

- `backend/app/db/session.py`
  - `erp.alembic_version`의 단일 row와 정확한 current revision `20260813_0025_w1_relationship_lock_contract_correction`을 확인한다.
  - `SSWCENTER_DATA_ROOT`와 `logs` directory의 존재·읽기·쓰기·탐색 가능성을 확인한다.
  - health endpoint와 write gate가 같은 `application_is_ready` 결과를 사용한다.
- `backend/app/api/health.py`
  - `/health/ready`가 migration/runtime path 실패를 `503 not_ready`로 반환한다.
- `backend/app/api/dependencies.py`
  - `POST`, `PUT`, `PATCH`, `DELETE` 요청에서 `get_db_session` 전에 readiness를 확인한다.
  - 실패 시 `503 service_not_ready`와 비밀 없는 reason code를 반환한다.
- `backend/tests/test_u05_readiness_write_gate.py`
  - stale·missing/multiple head, runtime path, write refusal, safe liveness를 mutation-sensitive하게 검증한다.
- `backend/tests/test_u05_readiness_write_gate_postgres.py`
  - 격리 PostgreSQL에서 current head 200, missing root write 503, stale head health/write 503을 검증한다.
- `scripts/test-u05-readiness-write-gate.ps1`
  - loopback 임시 PostgreSQL 17 cluster의 upgrade/probe/cleanup harness다. 운영 DB를 사용하지 않는다.

## 검증 증거

- focused pytest: `70 passed, 1 skipped`, exit `0`.
- 격리 PostgreSQL 17 probe: `U05_EPHEMERAL_POSTGRES_GREEN`, integration `1 passed`; current head `/health/ready=200`, runtime path write `503`, stale 0024 health/write `503`.
- Ruff: changed Python files exit `0`.
- PowerShell AST: `0` errors.
- `git diff --check`: exit `0`.
- 전체 non-PostgreSQL 회귀: `387 passed, 7 skipped`; 기존 `test_r0_w2_read_only_contract_02_file_hashes_are_expected` 1건은 candidate와 무관한 고정 hash 불일치(`expected B37B...`, current `B0CC...`)로 남았다.
- 임시 cluster, port `55433` listener, test residue: 모두 `0`.

## 남은 경계

- 실제 production DB·운영 runtime root·Linux `LINUX_ACTIVE` cutover evidence는 이 candidate에서 다루지 않았다.
- `U-05`의 candidate 보안 diff review는 이 최종 slice가 PR로 올라간 뒤 한 번만 요청한다. 보안리뷰 전의 ordinary docs/test correction은 별도 리뷰 단위로 쪼개지 않는다.
- 다음 구현 후보는 기존 순서대로 U-02/U-03/U-04/U-06이며, 이 부록은 W1E/W2 제품 공백이나 전체 release 승인으로 범위를 넓히지 않는다.
