# W1D Opus 사전 설계감사 — 266beea

## 실행 식별

- 완료 시각: 2026-07-30 20:33 KST
- 대상 branch: `codex/w1d-contract-transition`
- committed base SHA: `266beeaa2d150371ccd1a0f26f69249eca86ba16`
- 감사 snapshot: Grok Phase 1 판정
  `RED_VALID_PENDING_DESIGN_AUDIT`
- 감사자: Claude CLI Opus alias
- CLI: `C:\Users\USER\.local\bin\claude.exe` `2.1.217`
- 요청 설정: `--model opus --effort medium`
- 결과가 보고한 effective model: `claude-opus-4-8`
- session: `54686ae8-304a-4ec5-ae18-d6b8c69131ed`
- duration: `509291 ms`
- exit: `0`
- 도구: `Read,Glob,Grep` only, safe mode, permission denial `0`
- repository write: `0`

이 보고서는 Opus stdout의 finding·판정·한계를 Regina가 구조화해 보존한 것이다.
제품 부재 때문에 발생한 정상 RED는 설계결함으로 세지 않는다.

## 판정

```text
OPUS_W1D_DESIGN_AUDIT_RESULT=REQUIRED_CHANGES
```

| 등급 | 수 |
|---|---:|
| BLOCKER | 2 |
| HIGH | 3 |
| MEDIUM | 3 |
| LOW | 2 |

제품 구현은 계속 금지한다. 아래 BLOCKER/HIGH/MEDIUM을 plan과 executable RED에서
봉인하고 동일 snapshot 계열로 재감사하기 전 Regina 구현경계를 재봉인하지 않는다.

## BLOCKER

### W1D-B1 — apply 변경 순서가 W1C 즉시 등급-인정 포함 트리거를 위반

- 근거:
  - `review/plans/W1D_CONTRACT_TRANSITION_PLAN.md:344` 이후는 인정기간을 먼저
    종료하고 등급기간을 다음 statement에서 종료한다.
  - `backend/alembic/versions/20260730_0010_w1c_certification_ledgers.py:281`
    이후의 `ct_recipient_certification_grade_containment`는
    `DEFERRABLE INITIALLY IMMEDIATE`다.
- 결함: 인정기간을 먼저 줄이는 statement가 끝나는 순간, 아직 긴 활성 등급기간이
  축소된 인정기간 밖에 남아 trigger 위반이 발생한다.
- 영향: 계획대로 구현하면 apply 성공 경로가 GREEN에 도달할 수 없다.
- 필수 보정:
  - 안전한 statement 순서를 명시한다. 기본안은 기존 등급기간 종료일 축소 후 기존
    인정기간 종료일 축소다.
  - 다른 순서를 택한다면 transaction 안의 constraint deferral과 최종 검증을
    설계·RED에 명시한다.
  - 새 인정과 새 등급 생성 순서도 기존 exclusion·containment를 함께 만족하도록
    고정한다.
- RED 보강:
  - `backend/tests/test_w1d_postgres.py`의 전환 성공 경로에 기존 등급기간의
    정확한 종료일 단정을 추가한다.
  - 활성 등급이 존재하는 실제 상태에서 apply 전체가 성공함을 강제한다.

### W1D-B2 — replacement를 stale hash에 포함해 409 STALE과 422 MISMATCH가 충돌

- 근거:
  - plan canonical projection은 사용자 요청값 `replacements`를 hash 입력에
    포함한다.
  - apply는 projection을 다시 계산해 hash를 비교한다고 적는다.
  - `backend/tests/test_w1d_postgres.py:807` 이후는 DB가 변하지 않은 상태에서 빈
    replacement 배열을 보내 422
    `CERTIFICATION_TRANSITION_REPLACEMENT_MISMATCH`를 기대한다.
- 결함: 요청 replacement가 hash에 들어가면 빈 배열은 먼저 hash 불일치가 되어
  409 `CERTIFICATION_TRANSITION_STALE`로 끝난다. stable error contract가 서로
  양립하지 않는다.
- 필수 보정:
  1. stale hash는 DB 파생 상태와 전환 기준만 대표하도록 replacement 요청값을
     분리한다.
  2. preview에서 승인한 원본 replacement 전체는 서명 token payload에 별도로
     바인딩한다.
  3. 검사 순서를 `confirmed → token 진위/만료/recipient → DB stale hash →
     replacement multiset·내용 완전성`으로 고정한다.
  4. service/start/end뿐 아니라 모든 사용자 제어 replacement 필드의 binding
     범위를 명시한다.
- RED 보강:
  - DB 무변경 상태의 누락·추가·중복·서비스 변경이 STALE이 아니라 정확한
    MISMATCH/TOKEN 계약으로 분류되는지 고정한다.

## HIGH

### W1D-H1 — token 진위·만료·수신자·preview-required 행동 검증 부재

- 근거:
  - `backend/tests/test_w1d_contract.py`는
    `CERTIFICATION_TRANSITION_TOKEN_INVALID`와
    `CERTIFICATION_TRANSITION_PREVIEW_REQUIRED` 상수 존재만 확인한다.
  - `backend/tests/test_w1d_postgres.py:1147` 이후의 invalid token 요청은
    `confirmed=False`라 confirmation gate에서 먼저 끝난다.
  - frontend mock token은 고정 합성 문자열이라 HMAC·TTL을 검증하지 않는다.
- 영향: 상수 token 또는 recipient 미바인딩 구현도 현재 RED를 통과할 수 있다.
- 필수 RED:
  - token 변조
  - 주입 가능한 clock/seam을 사용한 TTL 만료
  - recipient A token을 recipient B에 재사용
  - preview 없는 apply
  - 각 경우의 정확한 status와 stable error code, DB write `0`

### W1D-H2 — first-contract 경쟁이 counter가 아니라 exclusion으로 끝나 비구속

- 근거:
  - `backend/tests/test_w1d_postgres.py:412` 이후 두 worker가 같은
    `SERVICE_HOME_CARE`를 사용한다.
  - same-service exclusion이 한쪽 계약을 먼저 탈락시키므로 번호발급 counter
    경쟁을 증명하지 못한다.
  - `expected_delta = 1 if before_counter is None else 1`은 항상 `1`이고, counter
    최초행 부재 때 `after >= 1`은 이중 증가도 허용한다.
- 필수 보정:
  - 같은 허용 group의 서로 다른 서비스로 경쟁시켜 두 계약 모두 성공 가능하게
    한다.
  - 활성 계약 정확히 2, recipient number 정확히 하나, counter delta 정확히
    `+1`을 단정한다.
  - counter 최초행이 없는 상태의 동시 insert·unique 충돌·retry 의미를 별도
    케이스로 검증한다.

### W1D-H3 — 실PG 본문이 revision gate 뒤에서 한 번도 실행되지 않음

- 근거:
  - wrapper는 W1D revision mismatch에서 pytest 전에 정상 product RED로 끝난다.
  - env 없는 직접 실행은 7개 전부 skip이다.
- 영향: seed, W1C 의존, login, audit column, fault seam 등 약 1,100줄짜리 실PG
  본문의 harness 가정이 아직 실행되지 않았다. 구현 후 harness 결함과 제품 결함이
  섞일 수 있다.
- 필수 보정:
  - W1C head DB에서 가능한 harness self-check/dry-run을 분리해 seed·기존 service
    signature·login·audit schema를 지금 검증한다.
  - revision 부재라는 제품 RED는 유지하되, 도달 가능한 harness 전제는 별도
    증거로 기록한다.

## MEDIUM

### W1D-M1 — CSRF RED가 정확한 거부를 강제하지 않음

- 근거: `backend/tests/test_w1d_postgres.py:1109` 이후는 token 없는 POST가
  정확히 `201`일 때만 실패한다. `200/422/500`도 통과한다.
- 필수 보정:
  - no-CSRF mutation의 정확한 `403` error envelope를 단정한다.
  - DB 행 미생성 `0`을 확인한다.
  - no-CSRF와 정상 요청 payload를 분리해 순서 의존을 없앤다.

### W1D-M2 — 단일 aggregate audit와 PII 비노출이 강제되지 않음

- 근거:
  - 전환 테스트는 `CERTIFICATION_TRANSITION_APPLY == 1`만 센다.
  - 단계별 contract/certification/grade audit가 추가로 생기지 않았는지
    확인하지 않는다.
  - plan의 before/after contract snapshot에서 signer PII projection이 명확하지
    않다.
- 필수 보정:
  - apply transaction 창의 aggregate event 정확히 1, 단계별 추가 event 0을
    단정한다.
  - audit JSON에서 signer name/phone/address 등 PII canary 부재를 단정한다.
  - plan에 audit용 비식별 projection을 고정한다.

### W1D-M3 — 부분 signer snapshot과 원본 변경 독립성 검증 부족

- 근거: 현재 signer 테스트는 빈/완전 snapshot과 무관한 신규 guardian insert만
  확인한다.
- 필수 보정:
  - 이름만 있는 부분 snapshot을 추가한다.
  - 기존 guardian와 payer row를 실제 update한 뒤 contract snapshot이 바뀌지
    않음을 단정한다.

## LOW와 잔여질문

### W1D-L1 — 현재 ABS 조기 PASS

W1D 스키마 부재 시 ABS-08/09/10이 `assert True`로 조기 통과한다. 패킷이
`ABS PASS != 제품 GREEN`으로 분리했으므로 현재 차단은 아니지만, 구현 후 expected
schema name이 어긋나도 침묵하지 않도록 후속 검토한다.

### W1D-L2 — no-reactivation guard 범위

종료 상태로 생성된 계약의 오타 정정까지 non-null→null을 전역 차단하는 것이
정본 의도인지 재확인한다.

### 추가 잔여

- transition token 전용 key가 CSRF/app secret와 실제로 분리되는지 구현감사에서
  확인한다.
- 모든 service group 조합, 특히 BARO_CARE 교차는 generic trigger 설계지만
  대표 RED가 부족하다.
- `certification_number=null` recipient의 전환 허용 의미를 확정한다.
- benefit/approval period를 전환 범위에서 제외하는 결정은 정본 04 §10과 다음
  감사에서 다시 대조한다.

## 감사 한계와 다음 조건

- Opus 출력은 8개 W1D 산출물과 기존 migration/pattern을 읽었다고 보고했다.
- 동시에 정본
  `docs/04_데이터_DB_불변조건_v4.8_PostgreSQL.md` 원문은 직접 읽지 못했고
  matrix·packet 근거로만 판단했다고 명시했다.
- 따라서 이 감사의 `REQUIRED_CHANGES`는 유효하지만 향후 `APPROVE` 근거로는
  불충분하다. 보정 후 재감사는 정본 04 §4.1·§5·§8·§10 직접 대조를 완료해야 한다.
- 요청 alias는 `opus`였으나 결과 metadata의 effective model 문자열은
  `claude-opus-4-8`이다. 이후 보고에서도 이를 `Opus 5`로 바꾸어 적지 않는다.
