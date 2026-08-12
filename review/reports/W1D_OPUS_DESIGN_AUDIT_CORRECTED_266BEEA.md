# W1D Opus 재감사 — corrected 266beea

## 실행 식별

- 완료 시각: 2026-07-30 20:55 KST
- 대상 branch: `codex/w1d-contract-transition`
- committed base SHA: `266beeaa2d150371ccd1a0f26f69249eca86ba16`
- corrected snapshot plan SHA-256:
  `febcc5d53630a419837001379df535a6b1eb521af12aa787bcf66cf98a2d6ad0`
- corrected snapshot PostgreSQL RED SHA-256:
  `91a9580ec5b697a681e17eaf03985a7749861e7192dd68a83ab12b5a44fff24e`
- 감사자: Claude CLI Opus alias
- CLI: `C:\Users\USER\.local\bin\claude.exe` `2.1.217`
- 요청: `--model opus --effort medium`
- effective model metadata: `claude-opus-4-8`
- session: `54686ae8-304a-4ec5-ae18-d6b8c69131ed`
- duration: `544404 ms`
- exit: `0`
- 도구: `Read,Glob,Grep` only, permission denial `0`, repository write `0`
- 정본 04 §4.1·§5·§8·§10 직접 통독: 완료

## 판정

```text
OPUS_W1D_REAUDIT_RESULT=REQUIRED_CHANGES
```

이전 B1·B2·H1·H3·M1·M2·M3은 실질 폐쇄됐다. H2 보정으로 새 HIGH 2건이
생겼고 W1-TRN-03 실행 커버리지 MEDIUM 1건이 남아 구현경계 재봉인은 불가하다.

## 폐쇄 확인

| ID | 결과 | 핵심 근거 |
|---|---|---|
| B1 | CLOSED | grade → certification 종료 순서, 정확 종료일과 fault rollback RED |
| B2 | CLOSED | DB stale hash와 signed replacement intent 분리, 오류 선행순위 봉인 |
| H1 | CLOSED | tamper·expiry·cross-recipient·preview-required·write 0 |
| H3 | CLOSED | W1C-head self-check live 1 pass |
| M1 | CLOSED | 실제 handler의 `CSRF_REQUIRED`, exact 403와 write 0 |
| M2 | CLOSED | aggregate audit 1, step audit 0, PII canary 부재 |
| M3 | CLOSED | empty/partial/full snapshot, 기존 guardian·payer update 뒤 불변 |

## 신규 HIGH

### W1D-N1 — counter DELETE가 전역 unique recipient_no를 재발급해 GREEN 불가

- 위치:
  - `backend/tests/test_w1d_postgres.py:560`
  - `backend/tests/test_w1d_postgres.py:640`
  - `backend/tests/test_w1d_postgres.py:674`
- 결함:
  - `RECIPIENT_NO/0` counter를 삭제하고 다시 `1`부터 발급하면 이미 남아 있는
    전역 unique `recipient_no="000001"`과 충돌한다.
  - 같은 테스트 안에서도 첫 race가 번호를 발급한 뒤 counter를 다시 삭제하고
    두 번째 recipient에게 같은 번호를 재발급하려 한다.
  - `after_counter == 1` 하드코딩과 `seq >= 1`은 전역 monotonic counter 계약과
    맞지 않는다.
- 영향: 정확한 제품 구현도 unique violation 또는 worker 실패로 RED가 GREEN에
  도달하지 못한다.
- 필수 보정:
  - counter를 DELETE/reset하지 않는다.
  - 현재 baseline에 대한 정확한 `after == before + 1`을 단정한다.
  - 신선한 isolated cluster의 최초 발급 자체를 absent-row race로 사용하거나,
    전역 번호 재사용 없이 absent-row 경로를 분리한다.
  - 두 compatible service 계약 성공, 계약 2건, 번호 1회 발급은 유지한다.

### W1D-N2 — 재계약 단계가 앞선 open-ended 계약과 반드시 overlap

- 위치:
  - `backend/tests/test_w1d_postgres.py:586`
  - `backend/tests/test_w1d_postgres.py:644`
- 결함:
  - race가 HOME_CARE와 HOME_BATH를 `2026-11-01`부터 open-ended로 만든다.
  - 직후 HOME_CARE `2027-01-01..2027-01-31`을 생성해 same-service exclusion에
    반드시 걸린다.
  - 예외가 처리되지 않아 stable product marker가 아니라 pytest error가 된다.
- 필수 보정:
  - race 계약에 종료일을 주거나 재계약 기간을 비충돌로 배치한다.
  - 재계약 성공 후 recipient_no 불변과 counter 미증가를 단정한다.

## 신규 MEDIUM

### W1D-N3 — W1-TRN-03 동시 apply와 다차원 stale 실행 RED 부재

- 위치:
  - `backend/tests/test_w1d_postgres.py:1130`
  - plan의 W1-TRN-03 mapping
- 결함:
  - stale 실행은 grade_code 한 차원뿐이다.
  - 두 valid preview를 동시에 apply해 정확히 하나 성공하고 다른 하나가
    `CERTIFICATION_TRANSITION_STALE`이 되는 실행 RED가 없다.
- 필수 RED:
  1. 두 thread 동시 apply, 정확히 `1 success / 1 STALE`, 최종 DB 일관성
  2. 인정 날짜와 계약 기간 또는 서비스 multiset을 각각 바꾼 stale 케이스

## 사양 공백과 LOW

- apply schema의 `preview_token`은 key required이면서 `None`을 service-level
  `PREVIEW_REQUIRED`로 처리할지, non-nullable schema에서 validation error로
  차단할지 plan과 RED가 일치하도록 봉인한다.
- contract-create fault seam `after_contract_insert`를 plan의 허용 label 목록에
  명시한다.
- 정본 04 §10.2가 benefit/approval을 apply 단계에 포함하지 않음을 직접 확인해
  W1D 제외 결정은 정본과 일치한다.

## 다음 조건

N1·N2·N3을 plan과 future-GREEN executable RED에서 보정하고 같은 snapshot 계열로
재감사하기 전 제품 구현을 시작하지 않는다.
