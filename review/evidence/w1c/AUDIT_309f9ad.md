# W1C Exact Audit — 309f9ad

## 판정

- 감사 후보 SHA: `309f9ad24fb3bff4da2be8f1c540fc765887f7ad`
- 누적 기준 SHA: `5980602f00f47744e2f3786961c4b7d740cae76c`
- 방식: exact SHA detached worktree 대상 read-only 감사
- Opus 결과: `W1C_FINAL_AUDIT_CONCUR`, blocking finding `0`
- 요셉 결과: `JOSEPH_W1C_REQUIRED_CHANGES`
- 유효 판정: 차단 finding이 하나라도 있으므로 `W1C_REQUIRED_CHANGES`

두 감사 모두 지정 SHA와 clean worktree를 기준으로 수행했다. Opus는 Claude Code
`2.1.215`의 `opus` 모델을 실제 CLI로 호출했다. 요셉은 사용자에게 보이는 별도 Codex
작업방에서 독립 검토했다. 결과적으로 Opus의 blocking finding `0` 판정은 아래 두
HIGH를 놓친 false negative이며 단독 승인 근거로 사용할 수 없다.

## Finding 1 — HIGH: 인정 identity 소유자 키 변경 가능

`erp.recipient_certification_identity`의 불변 trigger가
`certification_number`만 감시하고 `recipient_id`는 감시하지 않았다. `erp_app`에는
테이블 UPDATE 권한이 있으므로, 자식 원장이 없는 identity는 자격번호를 유지한 채 다른
수급자로 직접 재배정할 수 있었다.

요구 보정:

- DB trigger에서 `recipient_id`와 `certification_number`를 모두 불변으로 강제
- 실제 `erp_app` 연결에서 소유자 변경을 시도하고 SQLSTATE `23514`와
  `ck_recipient_certification_identity_immutable` 진단을 검증
- postcheck가 trigger 존재만이 아니라 감시 열과 함수 본문을 검증

## Finding 2 — HIGH: 실제 application-role·인증·CSRF 수용 증거 공백

기존 W1C PostgreSQL 하네스는 owner URL로 W1C 테스트를 실행했다. HTTP 테스트도 DB,
조회 권한, 관리 권한 dependency를 override했고, Playwright는 W1C API를 mock했다.
따라서 실제 `erp_app` DML/ACL과 오버라이드 없는 로그인·세션·권한·CSRF 성공 경로가
W1C HIGH gate에 포함되지 않았다.

요구 보정:

- migration과 catalog postcheck는 `erp_owner`로 유지
- runtime service와 API pytest는 `erp_app` URL로 실행
- 실제 세션 기준 401, 조회 권한 403, CSRF 403, 관리 권한 403, 허용된 201을 검증
- `erp_app`의 SELECT/INSERT/UPDATE 허용과 DELETE/TRUNCATE 거부를 실제 role에서 확인

## Finding 3 — HIGH (후속 재현): 인정 무효화와 등급 생성 write-skew

Opus는 등급 생성·대체 시 부모 인정기간을 명시적으로 잠그지 않는 점을 처음에는
비차단 권고로 분류했다. 그러나 FK가 부모에 취하는 `FOR KEY SHARE`는 인정기간의
비키 UPDATE가 취하는 `FOR NO KEY UPDATE`와 충돌하지 않는다. READ COMMITTED에서
양쪽 trigger가 상대 transaction의 미커밋 변경을 보지 못하면 인정 무효화와 등급
INSERT가 모두 커밋되어 무효 부모 아래 활성 등급이 남을 수 있었다.

`af501acdec474063ce4c884715690d752c521815` 코드에 회귀 테스트만 추가한 RED
실행에서 이 경합이 실제 재현됐다. 무효화 transaction을 연 상태에서 다른
connection의 raw grade INSERT가 차단되지 않고 커밋되어 예상 constraint가 나오지
않았고, 결과는 `1 failed, 5 passed`였다. 따라서 Opus의 비차단 분류는 Regina가
HIGH로 상향했다.

요구 보정:

- 등급 trigger가 부모 인정기간에 `FOR SHARE`를 취해 부모 UPDATE와 직렬화
- 서비스의 등급 생성·대체도 부모 인정기간을 명시적으로 잠금
- postcheck가 배포된 trigger 함수의 잠금 절을 검증
- 무효화 우선·등급 INSERT 우선 두 순서에서 실제 lock 대기, 정확한 constraint,
  최종 orphan 부재를 raw SQL 두 connection으로 검증

## 보정과 재검증

- identity trigger가 `BEFORE UPDATE OF recipient_id, certification_number`로 바뀌고,
  두 값 중 하나라도 바뀌면 SQLSTATE `23514`를 발생시킨다.
- postcheck가 trigger 감시 열과 함수의 두 불변 비교식을 확인한다.
- W1C 하네스가 `W1C_APP_ROLE_OK`를 출력한 뒤 `erp_app` URL로 runtime/API 테스트를
  실행하고, owner URL로 돌아와 catalog/ACL postcheck를 수행한다.
- 오버라이드 없는 실제 로그인·세션·권한·CSRF API 회귀를 추가했다.
- 격리 PostgreSQL 결과: `5 passed`, `W1C_DB_POSTCHECK_OK`,
  `W1C_POSTGRES_GREEN`.
- 정식 비실DB 범위: `134 passed`, `43 skipped`, `4 deselected`.
- 프런트: 전체 `98 passed`, lint/build 통과, W1C Playwright `9 passed`.
- W1B 교차회귀: 정적 `4 passed`, 실DB/브라우저 `3 passed`,
  leak `295` files, 잔여 listener·artifact·temp cluster `0`,
  `W1B_E2E_GREEN`.

## 재실행 과정 기록

- 첫 광범위 `pytest -q`는 격리 DB 환경변수 없이 harness 전용 테스트까지 포함해
  fail-close했다. 제품 assertion 실패가 아니라 실행범위 오류였으며, VS6 PostgreSQL
  파일과 W1B 실DB 4건을 분리한 정식 비실DB 명령은 위 `134/43/4`로 통과했다.
- 프런트 전체 unit을 build·백엔드 회귀와 동시에 실행한 첫 시도는 기존 비동기 테스트
  3건이 제한시간을 넘겼다. 다른 부하 없이 같은 전체 명령을 단독 재실행해
  `16 files / 98 passed`를 확인했다.
- 첫 Playwright 파일 인수는 Windows 경로가 test matcher와 일치하지 않아
  `No tests found`로 종료했다. 파일명을 올바르게 지정한 재실행은 3 viewport
  `9 passed`였다.

Finding 3의 후속 보정은 exact 후보
`b6d49ada90c24266fff1851a54e1f931cdbb83af`에 반영했다. 수정 후 격리
PostgreSQL은 양방향 동시성 회귀를 포함해 `6 passed`,
`W1C_DB_POSTCHECK_OK`, `W1C_POSTGRES_GREEN`이었다. 요셉은 같은 exact SHA를
실DB로 재실행해 `JOSEPH_W1C_B6D49AD_APPROVE`, Opus는 정적 잠금 추적으로 no
findings에 동의했다. 상세 근거는
`review/evidence/w1c/REAUDIT_B6D49AD.md`에 보존한다.

증적-only commit의 exact SHA를 별도 마르코 작업방에서 최종 반대검토한 뒤에만
Regina가 `PASS`를 선언할 수 있다.
