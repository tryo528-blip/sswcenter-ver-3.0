# W1C Technical GREEN Evidence

## 상태와 작업 식별

- 상태: `W1C_PASS / GREEN_SEALED`
- 판정 범위: 구현자 기술 검증, 요셉·Opus 재감사, 마르코 1차 finding 보정,
  새 exact SHA 마르코 재검토와 레지나 최종 `PASS`까지 완료.
- 누적 diff 기준 SHA: `5980602f00f47744e2f3786961c4b7d740cae76c`
- 기술 재감사 코드 SHA: `b6d49ada90c24266fff1851a54e1f931cdbb83af`
- 마르코 1차 반대검토 SHA: `e1f5e39fb94ba73a81638fbf118aa2746daaed5c`
- 최종 후보 SHA: `a86567fe5c3b88bc9148c04b97f3626e0972ed75`
- 마르코 최종 재검토: `MARCO_W1C_REVIEW_RESULT=APPROVE`
- 레지나 최종 판정: `W1C_PASS` (2026-07-30 19:45 KST)
- 브랜치: `codex/w1c-certification-ledgers`
- 작업 경로: `C:\sswcenter\2.1`
- 검증일: 2026-07-30
- 실제 개인정보·운영 DB·운영 자격증명은 사용하지 않았으며 실DB 테스트 값은 합성값이다.

최종 후보 `a86567f...`는 이 PASS 기록 이전의 제품·테스트·마이그레이션·계약과
보정 증거를 포함한 exact SHA다. 마르코는 당시 `git rev-parse HEAD`, staged,
unstaged, untracked 상태와 cleanup을 직접 확인했다. 이 PASS 기록을 담는 후속
evidence-only commit SHA는 commit이 자신을 포함할 수 없으므로 본문에 적지 않으며
Git 이력으로 식별한다.

## 구현된 계약

- 인정 본번호: `l`/`L` + 숫자 10자리와 선택 suffix `-NNN`을
  `L##########`으로 정규화하고, 수급자별 1개·전역 단일 소유·저장 후 불변을 DB와
  API에서 보장한다.
- 인정기간·등급기간: 양 끝 날짜 포함, 활성 기간 중복 금지, 등급 `1`~`5`만 허용,
  등급기간의 인정기간 포함과 부모 인정기간 변경 시 역방향 orphan 방지를
  deferrable DB trigger로 보장한다.
- 혜택기간: 정본의 정확한 6개 코드만 허용하고 코드와 무관하게 수급자 전체에서 활성
  기간 중복을 금지한다. `GENERAL`은 명시 선택 전 생성하지 않는다.
- 지자체 승인금액: PostgreSQL `bigint` 범위의 0 이상 정수 원 단위로 저장하며,
  혜택기간과 독립된 기간원장으로 관리한다.
- 네 원장 모두 현재·과거 조회, 무효화, row-version 기반 정정·대체 이력을 제공한다.
- `issued_date`, 인지지원등급, 부담률, 월중 최고액 자동계산 구조는 추가하지 않았다.

## 검증 결과

| Gate | 결과 |
|---|---|
| Ruff | `ruff check --no-cache app tests`, 통과 |
| Ruff format | `84 files already formatted` |
| mypy | `44` source files, 통과 |
| W1C 계약·ORM schema pytest | `7 passed` |
| W1C 격리 PostgreSQL/API pytest | `6 passed`; 실제 `erp_app` runtime/API, 양방향 동시성 회귀 포함 |
| W1C migration round trip | `0009 → 0010 → 0009 → 0010`, 통과 |
| W1C DB catalog/ACL postcheck | `W1C_DB_POSTCHECK_OK` |
| W1C 실DB 최종 gate | `W1C_APP_ROLE_OK`, `W1C_POSTGRES_GREEN` |
| OpenAPI TypeScript 생성 재현성 | `OPENAPI_TYPES_UP_TO_DATE` |
| W1C 프런트 단위 테스트 | `5 passed` |
| W1C Playwright | 3개 viewport, `9 passed` |
| 전체 프런트 단위 테스트 | 공식 `npm test`, 1 worker, `16 files / 98 passed` |
| 프런트 lint / production build | 통과 / `151` modules transformed |
| 비실DB 백엔드 회귀 | `134 passed`, `44 skipped`, `4 deselected` |
| W1B 정적 회귀 | `7 passed`, `4 deselected` |
| W1B 격리 PostgreSQL/API/브라우저 회귀 | 비기본 포트 `55491/18091/14191`, `3 passed`, `W1B_E2E_GREEN` |
| Git whitespace 검사 | 오류 `0` |

관찰된 경고는 FastAPI TestClient의 `httpx2` 전환 안내 1건이며 테스트 실패는 아니다.
프런트 전체 첫 실행의 기존 비동기 테스트 2건은 감사·실DB·브라우저 부하와 겹쳐
기본 대기시간을 넘겼다. 사무실 공식 `npm test`를 1 worker로 고정한 뒤 같은 전체
명령이 16 files / 98 tests를 통과했다. W1C 집중 5개와 Playwright 9개도 별도로
통과했다.

## 독립 감사 보정

첫 exact 후보 `6d9ace1aa48672feace09f981de0b33980f7c7dd`는 독립 감사에서
`W1C_AUDIT_REQUIRED_CHANGES` 판정을 받았다.

- 브라우저 `Number`/일반 JSON 파싱의 PostgreSQL bigint 정밀도 손실을
  `BigInt` 범위검증, lossless 응답 파싱, 숫자 token 직렬화로 보정했다.
- 네 replacement 흐름 모두 원본 REPLACE와 새 사실 REPLACEMENT_CREATE 감사를 같은
  transaction·시각·request ID로 각각 남기도록 보정했다.
- bigint 최대값의 실제 API raw JSON과 Chromium 3개 viewport GET→POST→UI 왕복,
  네 replacement 감사쌍을 실제 PostgreSQL에서 회귀검증했다.

상세 finding은 `review/evidence/w1c/AUDIT_6d9ace1.md`에 보존한다. 이 보정을 포함한
새 exact 후보 `7c760955e97672c7443a21924d5d040bd3436f46`는 독립 재감사에서
`W1C_REAUDIT_APPROVE` 판정을 받았다. 폐쇄 근거는
`review/evidence/w1c/REAUDIT_7c76095.md`에 보존한다.

두 번째 evidence 후보 `309f9ad24fb3bff4da2be8f1c540fc765887f7ad`에서 실제 CLI
Opus는 blocking finding `0`으로 동의했으나, 별도 작업방 요셉은 다음 두 HIGH 차단을
재현했다.

- identity의 `recipient_id`가 DB 불변 trigger 범위 밖이어서 자식 원장이 없는 경우
  소유자 재배정이 가능함
- W1C 실DB/API 테스트가 owner와 dependency override를 사용해 실제 `erp_app`
  로그인·권한·CSRF 수용 증거가 없음

두 finding은 identity 소유자·번호 동시 불변 trigger, trigger/function postcheck,
owner migration과 app runtime 분리, 오버라이드 없는 실제 401/403/201 API 회귀로
보정했다. 상세 감사와 폐쇄 근거는
`review/evidence/w1c/AUDIT_309f9ad.md`에 보존한다.

그 보정을 포함한 `af501acdec474063ce4c884715690d752c521815` 재감사에서 Opus는
인정기간 무효화와 등급 INSERT가 동시에 수행될 때 FK의 `FOR KEY SHARE`와 부모
UPDATE의 `FOR NO KEY UPDATE`가 충돌하지 않는 write-skew 가능성을 추가로 지적했다.
다만 이를 비차단 권고로 분류했기 때문에 Regina가 HIGH로 상향해 직접 RED를
재현했다. 실제로 무효화 transaction이 미커밋인 동안 등급 INSERT가 커밋되어
활성 등급이 무효 인정기간 아래 남았다.

최종 코드 후보 `b6d49ada90c24266fff1851a54e1f931cdbb83af`는 DB trigger의 부모
조회에 `FOR SHARE`, 서비스 등급 생성·대체의 부모 조회에 `FOR UPDATE`, postcheck의
잠금 본문 검증을 추가했다. 양쪽 transaction 순서를 모두 고정한 raw SQL 회귀는 실제
lock 대기를 확인하고, 패배 transaction의 정확한 constraint와 최종 orphan 0건을
검증한다. exact SHA 재감사 결과는 다음과 같다.

- 요셉: `JOSEPH_W1C_B6D49AD_APPROVE`, 실DB·migration·app-role·인증/권한/CSRF
  재실행, HIGH/MEDIUM `0`
- Opus: no findings로 동의. 단, 해당 CLI 환경에는 venv/PostgreSQL이 없어 정적
  잠금 추적만 수행했으며 실DB 실행 근거로 사용하지 않는다.

상세 RED·보정·재감사 근거는
`review/evidence/w1c/REAUDIT_B6D49AD.md`에 보존한다.

그 증적을 포함한 `e1f5e39fb94ba73a81638fbf118aa2746daaed5c`를 마르코가
최종 반대검토해 `MARCO_W1C_FINAL_BLOCK`을 판정했다.

- HIGH: W1B 하네스의 `BackendPort`·`FrontendPort`가 Playwright/Vite에 전달되지
  않아 비기본 격리 포트 실행에서 bootstrap status 3건 실패
- MEDIUM: W1C scoped Ruff는 통과했지만 `app tests` 전체 format gate에서 기존
  W1B/schema 테스트 2파일 미정렬
- MEDIUM: GREEN의 누적 기준 SHA와 최종 후보 SHA 역할이 구분되지 않았고
  `REAUDIT_B6D49AD.md`가 이미 생성된 evidence commit을 미래 절차로 표현

하네스는 두 포트를 검증된 숫자 환경변수로 Playwright와 Vite proxy까지 전달하도록
보정했다. 같은 실하네스를 비기본 포트에서 실행해 W1B `3 passed`,
`W1B_E2E_GREEN`, 전후 postcheck·leak·listener·artifact·cluster 잔여 0을 확인했다.
Ruff formatter로 두 파일을 정리해 broad check/format을 통과시켰고, SHA 필드는
역할별로 분리해 self-reference가 없는 exact HEAD 검증 절차를 명시했다. 상세
finding과 폐쇄 근거는 `review/evidence/w1c/MARCO_E1F5E39.md`에 보존한다.

## 사무실 환경 기록

사무실에서 발생한 항목은 집 환경 기록과 분리해
`review/environment/office/2026-07-30_W1C.md`에 `OFFICE-ENV-*` 번호로 기록했다.

## 최종 판정

W1C는 DB schema·기간 이력·row version을 포함하므로 운영규정 v3.5상 `HIGH`다.
최종 후보 `a86567fe5c3b88bc9148c04b97f3626e0972ed75`를 마르코가 별도 read-only
작업방에서 exact SHA로 재검토해 `MARCO_W1C_REVIEW_RESULT=APPROVE`를 반환했다.

- 검수 당시 HEAD 일치: `true`
- staged / unstaged / untracked: 모두 `0`
- 누적 W1C 경로: `38`, 삭제 `0`
- 기존 migration blob 변경: `0`; 신규 `0010`은 `0009`의 direct child
- 직전 HIGH `1`, MEDIUM `2`: 모두 폐쇄
- 확정 제품 결함: `0`
- 남은 HIGH/MEDIUM blocker: `0`
- listener·임시 cluster·테스트 artifact 잔여: `0`

따라서 레지나는 코드를 수정하지 않고 이 후보를 `W1C_PASS / GREEN_SEALED`로
최종 판정한다. 상세 exact-SHA 재검토는
`review/evidence/w1c/MARCO_A86567F.md`에 보존한다.

운영 closeout으로 이 PASS evidence-only delta를 commit·push한 뒤
local/upstream/remote SHA 일치와 clean tree를 확인하는 절차가 남아 있다.
