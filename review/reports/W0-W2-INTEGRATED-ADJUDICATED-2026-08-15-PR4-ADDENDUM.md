# SSWCenter 3.0 W0~W2 통합 재판정 — PR #4 current-main 부록

> 부록일: 2026-08-15 KST
> 적용 대상: [`W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md`](W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md)
> 판정 대상: PR #4로 병합된 FOUNDATION-0025 U-09/U-08 구현
> 평가 기준 HEAD: `main` / `358d4c0153bac5fc26b94428c1cbc9da62b1ec47`
> 지위: 역사 보고서의 current-main 기준을 보정하는 append-only 부록. W0 전체 acceptance·W1F PASS·Wave 승격·release acceptance가 아니다.

## 원문과 현재 기준의 관계

8월 14일 통합보고서는 병합 전 `b1cd055ea92ad5cf9558009e2a270147acf17d6f`를 기준으로 작성됐다. 원문은 당시의 재판정 기록으로 보존하고, 이 부록에서만 PR #4 이후의 current-main 상태를 판정한다. 원문에 적힌 U-08/U-09의 `CURRENT_CONFIRMED` 상태를 현재 main의 미해결 상태로 재사용하지 않는다.

현재 계보는 다음과 같다.

```text
b1cd055 (통합보고서 기준 main)
→ 4bce570 (PR #4 구현 후보의 최종 문서·증거 commit)
→ 358d4c0 (PR #4 merge commit, current main)
```

PR #4는 [FOUNDATION-0025 current-head init·복구 구현](../packets/FOUNDATION-0025-IMPLEMENTATION-PACKET-v1.0.md)의 U-09 → U-08 범위를 병합했다. 패킷의 `PREPARATION_ONLY` 표기는 작성 당시 실행 전 상태이며, 실행 결과는 [`2026-08-14_FOUNDATION_0025.md`](../environment/home/2026-08-14_FOUNDATION_0025.md)에 별도로 기록한다.

## current-main 상태 보정

| ID | 이전 통합보고서 | current-main 부록 판정 | 범위 |
|---|---|---|---|
| U-08 | `CURRENT_CONFIRMED` | `SATISFIED_BY_PR_4` | exact 0025 backup→새 review DB/data root restore와 dispatcher marker를 PR #4로 병합하고, 격리 PostgreSQL 증거를 남겼다. |
| U-09 | `CURRENT_CONFIRMED` | `SATISFIED_BY_PR_4` | exact current-head dispatcher를 개발 init과 연결하고, missing/multiple/unknown revision fail-close 계약을 PR #4로 병합했다. |

`SATISFIED_BY_PR_4`는 해당 구현 범위가 current main에 병합되고 기록된 검증 증거가 있다는 뜻이다. 이는 운영 DB 복구훈련, 전체 W0~W2 acceptance, W1F PASS, Wave 2 승격 또는 release 승인으로 승격하지 않는다.

부록 적용 후 이슈 분포는 다음과 같다.

| 분류 | 수 | 비고 |
|---|---:|---|
| `CURRENT_CONFIRMED` | 14 | U-02~U-07, U-11~U-15, U-17, U-19~U-21 등 잔여 제품·계약 공백 |
| `SATISFIED_BY_PR_4` | 2 | U-08, U-09; 구현·증거의 current-main 병합 |
| `SATISFIED_BY_PR_2` | 1 | U-01 PIN 정본 |
| `SATISFIED_BY_PR_1` | 1 | U-10 catalog 후보 |
| `CONTRACT_DECISION` | 2 | U-07, U-18 |
| `REJECTED_AS_WRITTEN` | 1 | U-16 원문 처방 |
| `BLOCKED_EVIDENCE_GAP` | 1 | U-22 pre-W2 W1F PASS 계보 |
| `OPERATIONAL_UNVERIFIED` | 1 | U-23 운영 증거 |
| `PARTIAL_CONFIRMED` | 1 | U-24 |

## U-08/U-09 증거 요약

- 대상 Alembic head는 `20260813_0025_w1_relationship_lock_contract_correction` 하나다. 현재 migration에 0026~0028은 없다.
- `review/environment/home/2026-08-14_FOUNDATION_0025.md`에 `FOUNDATION_0025_INIT_GREEN`, `FOUNDATION_0025_BACKUP_GREEN`, `FOUNDATION_0025_RESTORE_GREEN`, `FOUNDATION_0025_POSTGRES_GREEN`과 cleanup `listener=0 process=0 temp=0 database=0 artifact=0 git=0`가 기록돼 있다.
- 기록된 계약·인접 테스트는 `7 passed`, combined foundation 계약 테스트는 `18 passed`다. Ruff exit `0`, PowerShell AST 오류 `0`, 변경 파일 mypy(`--follow-imports=skip`) exit `0`이다.
- PR #4의 병합 대상 commit `4bce570f3207a1284d704d44d4433c4ccd8b4064`는 GitHub Codex Security Review에서 보안 이슈 없음으로 검토됐다. 이 결과는 보안 diff 검토이며 운영 수용 서명이 아니다.

## 다음 작업 경계

U-08/U-09는 다음 구현 순서에서 제거한다. 다음 후보는 통합보고서의 기존 순서를 유지해 U-05 readiness/write gate이며, 이후 U-02/U-03/U-04/U-06 인증·로그 안전을 별도 후보로 다룬다. W1E 공백(U-12~U-15), W2 bridge·projection·race(U-17~U-20), U-22 계보, U-23 운영 증거, W2B packet 및 운영정본 7문서는 이 부록으로 해결되지 않는다.

```text
U-05 readiness/write gate
→ U-02/U-03/U-04/U-06 인증·로그 안전
→ U-12~U-15 W1E 제품 공백
→ U-17~U-20 W2 bridge·projection·race
→ 동일 SHA 최종 운영·독립 acceptance
```

이 부록은 current-main 기준과 구현 증거의 연결만 정정하며, 남은 이슈를 자동으로 PASS 또는 release 승인으로 바꾸지 않는다.
