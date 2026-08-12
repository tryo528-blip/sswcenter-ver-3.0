# W1A-VS1 요셉 설계 1차 검토

> 판정일: 2026-07-26 KST
>
> 검토자: 요셉
>
> 검토 대상: `review/plans/W1A_STAFF_VERTICAL_SLICE_PLAN.md`
>
> 검토 범위: 정본 07 §3, test matrix §12~§14 및 연결 정본과 기존 Wave 0 코드
>
> 전체 판정: `REQUIRED_CHANGES`

## 발견사항

### W1A-VS1-F01 — BLOCKER

계획이 정본에서 확정하지 않은 권한정책을 `STAFF_MANAGE`와 “모든 활성 사용자의
masked 조회”로 미리 결정했다.

- 실제 영향: 직원정보 열람·변경 범위가 사용자의 센터 운영정책과 다르게 고정될 수
  있다.
- 권고: 읽기·생성·수정·종료 action별 역할표를 제품 코드 전에 owner decision으로
  봉인한다. 확정 전에는 이를 고정 계약으로 쓰지 않는다.

### W1A-VS1-F02 — BLOCKER

재직·직종·역할 종료와 정정 command가 완결되지 않았다. 현재 model에는
`row_version`과 actor 정보가 없고, 계획의 API에는 재직 PATCH만 있으며 직종·역할
정정 API가 없다. 재직 종료일을 단축할 때 열린 자식기간을 함께 어떻게 처리할지도
정해지지 않았다.

- 실제 영향: 원장 이력 손실, 부분 commit, 기간 제약 충돌, UI와 API의 동작 불일치가
  생길 수 있다.
- 권고: 각 command별 expected version, actor/time audit, 무효화·대체 규칙,
  conflict, transaction 경계를 적는다. 재직 종료 시 자식기간을 같은 transaction에서
  닫을지 전체 command를 거부할지 명시한다.

### W1A-VS1-F03 — BLOCKER

주민번호 reveal의 current-PIN step-up 보안계약이 불완전하다.

- 실제 영향: 잘못된 계정 검증, 잠금 우회, audit 없이 평문 반환, 복호화 실패 시
  민감정보 노출 가능성이 있다.
- 권고: 현재 계정 검증, 실패횟수·잠금 영향, 재시도와 안정 오류, 복호화 실패,
  `access_event`와 응답의 transaction 순서를 명시한다. 성공 audit commit 전에는
  평문을 반환하지 않는다.

### W1A-VS1-F04 — HIGH

현재 로그 redaction은 주민번호를 다루지 않고 Playwright는 실패 trace를 보존한다.

- 실제 영향: 실패 로그·trace·video·screenshot에 주민번호 또는 PIN이 남을 수 있다.
- 권고: 전 계층의 주민번호 redaction과 민감 E2E artifact 비활성화·sanitize를
  테스트 계약으로 추가한다.

### W1A-VS1-F05 — HIGH

새 직원 API의 `/api/v1`과 기존 인증 API의 `/api` 공존 방식, 기존 `detail` 오류
envelope와 새 envelope, 수동 TypeScript 타입과 생성 타입의 소유권이 봉인되지
않았다.

- 실제 영향: Wave 0 인증 회귀, 두 오류 계약의 혼용, 타입 중복이 생길 수 있다.
- 권고: 경로·version·envelope·type ownership 표를 추가하고 request ID/예외 매핑
  적용범위, 기존 인증 계약 보존, 생성·수동 타입 공존 및 제거 경계를 명시한다.

### W1A-VS1-F06 — HIGH

현재 `/auth/me`는 permission을 반환하지 않아 계획의 권한별 UI 제어를 구현할 수
없다.

- 실제 영향: UI가 권한을 추측하거나 모든 control을 노출할 수 있다.
- 권고: F01 결정 뒤 capability/permission 계약 또는 대안을 정하고 refresh/cache,
  백엔드 최종검사, UI와 직접 API 검증을 명시한다.

### W1A-VS1-F07 — BLOCKER

application role과 W1 PostgreSQL 검증계획이 현재 harness에서 실행 가능하지 않다.
임시 PG는 대부분 superuser로 실행되고 grant를 실제 검사하지 않는다. Wave 0
postcheck는 table 수·permission 수·revision을 `20260724_0002`에 고정했으며
restore도 Wave 0 postcheck만 호출한다.

- 실제 영향: app role 권한 오류를 놓치거나 W1 migration 자체가 기존 검증기를
  깨뜨릴 수 있다.
- 권고: Wave 0 불변검사와 W1 head 검사를 분리·합성하고, exact script와 app role의
  허용·거부 경로, W1 postcheck, revision-aware restore를 계획한다.

### W1A-VS1-F08 — HIGH

직종·역할·성별 code의 DB/OpenAPI 경계가 확정되지 않았다. 직종은 기존 다섯 값이
있지만 `role_code`에는 catalog/check가 없고 UI는 `MALE/FEMALE`, 합성 seed는
`TEST`를 쓴다.

- 실제 영향: migration, OpenAPI, seed, UI 사이에서 서로 다른 code가 저장될 수
  있다.
- 권고: DB와 OpenAPI의 허용경계를 봉인하고 `TEST`가 합성 전용이라면 그 경계를
  명시하며 bootstrap 회귀를 검증한다.

### W1A-VS1-F09 — MEDIUM

민감행이 없는 기존 0-row 직원에게 주민번호를 나중에 추가하는 API/UI 범위가
모호하다.

- 실제 영향: 계획과 실제 제품에서 기존 직원의 민감정보 보강 가능 여부가 달라질 수
  있다.
- 권고: 신규 직원만 다루는 VS1에서는 해당 API/UI를 명시적으로 제외하고 후속
  항목으로 추적한다.

### W1A-VS1-F10 — HIGH

RED 기준과 증거가 추상적이라 구현 전 실패를 재현할 수 없다.

- 실제 영향: 테스트가 실제로 먼저 작성됐는지, 올바른 미구현 사유로 실패했는지
  입증하기 어렵다.
- 권고: 파일, 명령, 최초 기대실패, 증거 경로, RED-only commit 경계를 명시하고
  Codex 승인 전 구현을 시작하지 않는다.

## 1차 결론

- 중요한 미해결사항: 권한정책, 종료·정정 transaction, PIN·audit·decrypt,
  API 공존·capability, app-role·revision postcheck, code 경계, 재현 가능한 RED
- 요셉 2차 검토: 필요
- 마르코 인계: 현재 불가
- 다음 조건: F01·F02·F03·F07 BLOCKER를 해결하고 HIGH 항목을 실행 가능한 계약으로
  바꾼 뒤 요셉 2차 검토를 진행한다.
