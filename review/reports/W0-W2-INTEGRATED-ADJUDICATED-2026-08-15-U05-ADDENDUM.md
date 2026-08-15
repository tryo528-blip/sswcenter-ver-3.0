# SSWCenter 3.0 W0~W2 통합 재판정 — U-05 readiness/write gate 부록

> 부록일: 2026-08-15 KST
> 적용 대상: [`W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md`](W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md)
> 평가 기준: `main` base `a55d25d64ea571acf94ca2cbfbfd38bf4eb5e4bf` → candidate `6a368e3`
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
  - `os.access`만 믿지 않고 각 runtime directory에 실제 create/delete probe를 수행한다.
  - readiness probe는 database URL별 공유 `pool_size=1`, `max_overflow=0` 엔진을 사용한다.
  - 파일 probe는 프로세스별 고정 marker와 lock으로 cleanup 실패 시 호출마다 orphan을 만들지 않는다.
  - `app.log`, `error.log`, `access.log`, `install-update.log` 각각의 기존 파일에 append open을 수행해 실제 handler 파일 ACL도 확인한다.
  - health endpoint와 write gate가 같은 `application_is_ready` 결과를 사용한다.
- `backend/app/api/health.py`
  - `/health/ready`가 migration/runtime path 실패를 `503 not_ready`로 반환한다.
- `backend/app/api/dependencies.py`
  - 모든 database-backed dependency 경로에서 `get_db_session` 전에 readiness를 확인한다.
  - 인증된 GET도 session `last_seen_at_utc`/idle expiry를 commit할 수 있으므로 stale
    schema에 heartbeat를 쓰지 않도록 fail closed 한다.
  - 실패 시 `503 service_not_ready`와 비밀 없는 reason code를 반환한다.
- `backend/tests/test_u05_readiness_write_gate.py`
  - stale·missing/multiple head, runtime path, write refusal, safe liveness를 mutation-sensitive하게 검증한다.
- `backend/tests/test_u05_readiness_write_gate_postgres.py`
  - 격리 PostgreSQL에서 current head 200, missing root write 503, stale head health/write 503을 검증한다.
- `scripts/test-u05-readiness-write-gate.ps1`
  - loopback 임시 PostgreSQL 17 cluster의 upgrade/probe/cleanup harness다. 운영 DB를 사용하지 않는다.
  - `TEMP` 계열뿐 아니라 기존 `PGCLIENTENCODING`·`SSWCENTER_*` process 환경값도 저장 후 복원한다.
  - 환경변경과 임시 data directory 생성까지 보호된 `try/finally` 안에서 수행해 초기 생성 실패에도 호출자 환경을 복원한다.

## 검증 증거

- 직전 candidate `910233f`의 focused pytest는 `70 passed, 1 skipped`, exit `0`이었다. append-access 보정 후 현재 공유 backend venv에서 U-05 focused pytest는 `12 passed`, exit `0`이었다.
- 직전 candidate의 격리 PostgreSQL 17 probe는 `U05_EPHEMERAL_POSTGRES_GREEN`으로 기록돼 있다. 이번 bounded-pool/probe/harness 수정 후에는 같은 의존성 부재로 PG probe를 재실행하지 못했다.
- 현재 candidate(`6a368e3`) Ruff exit `0`, Python compile exit `0`, PowerShell parse exit `0`, `git diff --check` exit `0`.

## 남은 경계

- 실제 production DB·운영 runtime root·Linux `LINUX_ACTIVE` cutover evidence는 이 candidate에서 다루지 않았다.
- `U-05` ordinary `/review`는 `6a368e3` 이후 다시 요청하며, 결과가 오면 지적사항을 재판정한다. candidate 보안 diff review는 최종 다중 슬라이스 후보에서 한 번만 수행한다.
- 다음 구현 후보는 기존 순서대로 U-02/U-03/U-04/U-06이며, 이 부록은 W1E/W2 제품 공백이나 전체 release 승인으로 범위를 넓히지 않는다.
