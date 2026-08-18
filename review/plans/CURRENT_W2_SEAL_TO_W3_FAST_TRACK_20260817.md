# W2 현재 봉인 → W3 fast-track 실행계획 — 2026-08-17

> 상태: `CURRENT_EXECUTION_PLAN / W2_CONTRACT_IMPLEMENTED_NOT_SEALED`
> 기준 저장소: `/home/codexctl/workspace/sswcenter-3-0`
> 기준 branch / HEAD: `main` / `059ecf3dbfb54ac0a896303702d74ef190f8d984`
> 현재 단계: `W2_TECHNICAL_CANDIDATE_READY / USER_SEAL_APPROVAL_PENDING`
> Git 경계: `NO_MERGE`, stage·commit·push는 실행 시점의 형님 명시 지시에 따름

## 0. 이 계획의 지위

이 파일은 현재 실행만 소유한다. 역사 로드맵·옛 W1F packet·Windows 실행자료를
현재 명령으로 복원하지 않는다. 제품 업무계약을 변경하지 않으며, 계약결정이 필요한
항목은 구현하지 않고 형님께 올린다.

현재 상태·중간 문제·검증 결과는 이 파일에만 누적한다. 과거 전체 로드맵과 보고서는
provenance와 finding 출처로만 남긴다.

보고서는 형님 지시에 따라 Wave 완료 시점에만 발행한다. 현재 W2 작업 중에는 중간
보고서나 HTML을 만들지 않고, 다음 보고서는 W2 봉인 완료 뒤에만 만든다. W3도 같은
방식으로 W3 완료 뒤에만 보고서를 만든다.

## 1. 형님 확정 방향

1. W2 핵심 backend·migration·현재 UI 바이트는 이미 존재하므로 전면 재구현하지
   않는다. current review에서 확인된 gap과 형님이 승인한 seal 범위만 보완한다.
2. 현재 W0~W2를 다시 검수하고 확정 기술결함만 고친다.
3. W2를 현재 exact candidate에서 봉인한다.
4. 실제 입출력 parser/run은 W3에 둔다.
5. W2 봉인 직후 W3 공단 일정·RFID·실제근무·입출력으로 진입한다.
6. W3 기준선 도달 뒤 형님 주도의 대규모 수정을 시작한다.
7. W4 계산·청구·수납은 대규모 수정 뒤 재설계한다.
8. W5 파일함·OCR·공식출력·제품 복구 기능은 이번 계획 범위 밖이다.
9. merge는 하지 않는다.

## 2. 완료 정의

### W2 seal 완료

- current candidate inventory·manifest가 실제 Git status와 일치
- W0~W1E dirty 영향 경로의 회귀가 current bytes에서 PASS
- 형님이 승인한 W2 scoped backend·frontend·migration·PostgreSQL·browser와
  candidate DB/data-root restore validation이 current bytes에서 PASS
- OpenAPI generated drift 0
- static·type·lint·build PASS
- cleanup listener/process/temp/artifact delta 0
- Grok/Terra/Sol의 분리된 독립 review 결과가 current bytes와 일치하며,
  DeepSeek는 provider 비상상황이 아니면 사용하지 않음
- final independent Grade 5에서 P0~P3 current finding 0
- 형님이 W2 scoped seal을 명시 승인

### W3 fast-track 진입 완료

- W2 seal candidate를 변경하지 않는 별도 W3 착수범위 확정
- 공단 일정·RFID·실제근무·입출력의 업무원문·샘플·결정사항을 한 decision packet에 정리
- 형님 결정이 필요한 항목만 짧은 선택지로 제시
- W4 계산·청구·수납과 W5 파일함·OCR을 W3 schema에 선구현하지 않음

## 3. 실행 라운드

### Round A — current-byte 재판정

ACTOR 조합:

- Luna max: 초안
- Grok: 테스트·read-only 검수 뒤 별도 FIX
- Terra max: 테스트·read-only 검수 뒤 별도 FIX
- Grok: 재테스트·read-only 재검수 뒤 별도 FIX
- Sol ultra: final read-only 독립검수
- Codex: 각 결과를 현재 파일·diff·실행 증거와 대조하고 provider 실패를 복구
- DeepSeek: 위 기본 경로를 실행할 수 없는 비상상황에만 사용

종료조건:

- W0, W1A, W1B, W1C, W1D, W1E, W2 상태표
- 닫힌 과거 finding과 열린 current finding 분리
- 기술결함과 사용자 계약결정 분리
- W2 seal gate inventory 확정

### Round B — 비계약 기술결함 수정

원칙:

- REVIEW와 FIX를 서로 다른 실행 단위로 분리하고, 한 실행에는 Writer 한 명만 둔다.
- 수정범위·완료조건·금지경계를 sealed packet으로 제한한다.
- 반대 actor가 fresh read-only review를 수행한다.
- 사용자 정책·필드·상태·API·schema를 추측해 추가하지 않는다.

우선 검토대상:

1. W2 frontend OpenAPI projection 보존
2. 월·필터 fetch generation과 loading 중 mutation 차단
3. active 0027 head에서 W2 migration/postcheck/restore 연결
4. W1E 변경이 W0~W1D와 W2에 만든 cross-layer 회귀
5. 오래된 테스트·wrapper의 current Linux/head drift

### Round C — current candidate gate

#### C0 Runtime

```bash
pwsh -NoProfile -File scripts/ensure-runtime.ps1
pwsh -NoProfile -File scripts/verify-runtime.ps1
```

필수 marker: `SSWCENTER_RUNTIME_GREEN`.

#### C1 Static·API·backend

- `git diff --check`
- Ruff check·format-check
- full-repository mypy
- `scripts/generate-openapi-types.ps1 -Check`
- `backend` cwd에서 current-profile full pytest. 역사 W1F/R0 Windows profile은
  별도 non-acceptance 결과로 기록하며 profile 분리 전에는 current PASS를 선언하지 않음
- capture 문제가 재발하면 `pytest -s`로 실행하고 원인과 우회를 함께 기록
- W0~W2 targeted contract·behavior·API tests

#### C2 PostgreSQL·migration

순차 실행하며 임시 cluster를 병렬로 겹치지 않는다.

1. `scripts/test-w0-postgres-linux.ps1`
2. `scripts/test-w1e-0026-postgres-linux.ps1`
3. active 0027 Linux 통합 cluster에서 W1A~W1D 영향 회귀
4. active 0027 Linux W2 core·계획서 real-PostgreSQL·동시성·ACL gate
5. active 0027 exact backup→new review DB/data-root restore

각 gate는 listener·process·temp·database·artifact·git delta를 0으로 정리한다.

과거 Windows/0025 고정 `test-w2-core-postgres.ps1`, W2 제품 부재를 기대하는
service-plan RED/lifecycle gate, obsolete R0/W2 Windows wrapper는 current seal 명령으로
실행하지 않는다. 필요한 검증 의미는 0027 Linux gate로 옮기되 assertion을 약화하지
않는다.

C2의 restore는 W2 후보를 검증하기 위한 일회성 격리 복원시험이다. W5가 소유하는
사용자용 파일함·OCR·제품 복구 기능을 앞당겨 구현하는 것이 아니다.

#### C3 Frontend·browser

- frontend lint
- full Vitest
- TypeScript production build
- W0 shell browser E2E
- W1A~W1D 실제 브라우저 회귀
- W2 일정·개인 할 일·업무카드·계획서통보 browser flow
- loading·409·423·row-version·session/CSRF·권한·입력보존 확인

W2 browser flow가 현재 unit만 있고 real PostgreSQL E2E가 없다면 테스트를 약화하지
않고 별도 current RED→GREEN 범위로 닫는다.
현재 candidate는 별도 browser DB에서 실제 FastAPI·Vite·Playwright와 2-page stale 409,
최종 DB row/audit를 검증해 이 RED를 GREEN으로 닫았다.

### Round D — W2 독립 봉인

1. candidate SHA와 전체 status inventory 고정
2. candidate manifest 생성
3. Grok/Terra 분리 실행의 fresh read-only 상호검증과 필요한 별도 FIX
4. Sol ultra final clean exact-SHA Grade 5 독립검수
5. responsive HTML 최종보고서와 사용자 승인 seal 기록

worktree 생성·삭제, stage·commit·push는 각각 실행 시점에 형님 명시 승인을 확인한다.
merge는 하지 않는다.

## 4. 계약결정 경계

다음 항목은 current code로 기술 사실을 검증하되, 계약을 임의로 선택하지 않는다.

| ID | 결정 | 현재 경계 |
|---|---|---|
| W2-D01 | 계획서통보 공식카드를 어느 날짜의 월 전문직 담당에게 배정할지 | `CONFIRMED`: 카드의 정확한 `due_date` 업무기준일에 유효한 월 전문직 담당. 호출자 지정·request time 기준 거부 |
| W2-D02 | 계획서 replacement를 same-recipient까지만 허용할지 same-contract까지 강제할지 | `CONFIRMED 3A`: 같은 수급자의 다른 계약 허용. 0027 선언형 복합 FK가 타 수급자 연결을 direct SQL·동시 최종 상태에서도 거부 |
| W2-D03 | 신규직원업무 카드의 발생시점·담당자·마감일 | 자동생성 전 결정 필요 |
| W2-D04 | 직원교체상담 재판정 | W3 실제근무 원장·정정 event 이후에만 구현 |
| W2-D05 | 현재 구현 코어를 scoped 봉인할지, 옛 전체 계약의 배정 UI·확정해제·일괄취소까지 W2에서 채울지 | `CONFIRMED 1A`: scoped 봉인. 옛 일괄취소·확정해제·배정 UI는 복원하지 않음. ADMIN 담당자 변경만 추가 |

W2 seal이 위 항목의 명시적 제외 상태를 수용할 수 있는지 먼저 검수한다. 봉인 필수계약으로
판정되면 그 지점에서 형님께 선택지를 올리고 중단한다.

## 5. W3 fast-track

W2 seal 직후 다음 한 묶음으로 W3 decision packet을 만든다.

1. 공단 일정 원본 import
2. RFID 원본 수집·중복·재수신
3. 직원·수급자·서비스·일정 deterministic matching
4. 실제근무·실제 급여제공 증거 원장
5. 일정정정·무효화·대체와 event
6. 입출력 parser/run·quarantine·검토·적용 경계

현재 확정:

- 실제 입출력 parser/run은 W3 소유다.
- W3까지 진행한 뒤 대규모 수정을 시작한다.
- W4 계산·청구·수납은 그 수정 뒤 재설계한다.
- W5 파일함·OCR·공식출력·제품 복구 기능은 선구현하지 않는다.

W3 착수 직전 형님께 올릴 결정은 RFID 초기활성, 계획/확정 UX, 자동매칭 허용범위,
다건 tie, 대체키, 공단 수가행 grouping, content/receipt 연결, 수기보완, 정정 tie다.

## 6. 현재 상태와 W0~W2 수정 요약

현재 전체 상태는 `W2_CONFIRMED_CONTRACT_IMPLEMENTED / SEAL_NOT_CLAIMED`다.
W2-D01·D02·D05는 형님이 확정했다. 이번 라운드의 backend·migration·UI 결함은 현재
바이트에서 수정·실검증을 완료했고 Sol ultra final review는 current finding 0으로
형님 승인 단계 진입 가능을 판정했다. 다만 형님의 명시 승인 전이므로 W2
acceptance·봉인·승격 상태는 아니다.

| 범위 | 현재 판정 | 현재 바이트에서 확인한 내용 |
|---|---|---|
| W0 | `CURRENT_LINUX_PG_GREEN` | hostile `TEMP/TMP/TMPDIR`에서도 live·cleanup·seal GREEN, OpenAPI drift 0 |
| W1A | `CURRENT_SUPPORTED_REGRESSION_GREEN` | 직원 reverse-orphan·conflict mapping을 포함한 supported backend 회귀에 신규 실패 없음 |
| W1B | `CURRENT_SUPPORTED_REGRESSION_GREEN` | recipient `TEST` sentinel·detail/batch/service와 현실형 seed graph 통과 |
| W1C | `CURRENT_SUPPORTED_REGRESSION_GREEN` | certification·grade·benefit graph와 현재 OpenAPI projection 통과 |
| W1D | `CURRENT_SUPPORTED_REGRESSION_GREEN` | 계약·배정 관계와 current backend 회귀에 신규 실패 없음 |
| W1E | `W1E_SCOPED_GREEN_SEALED / CURRENT_RECHECK_GREEN` | current 0026 Linux PostgreSQL 23 passed, live·cleanup·seal GREEN |
| W2 | `TECHNICAL_CANDIDATE_READY / USER_SEAL_PENDING` | 1A scoped 범위, `due_date` 월 전문직 자동배정, ADMIN 담당자 변경, 3A same-recipient 선언형 composite FK 0027 구현. PG/API/UI/browser/restore GREEN, final Sol P0~P3 0; 형님 명시 승인만 남음 |

W1E scoped 후보의 핵심 수정은 care-assignment CRUD·replacement·audit, FAMILY snapshot,
GENERAL 자격 containment, 422 precheck와 DB race 409 분리, fine-grained advisory lock,
parent reverse guard, 0026 lifecycle/postcheck/ACL, OpenAPI·generated TypeScript다.

현재 독립 review와 Codex 실행으로 확정한 기술 항목은 다음과 같다.

| ID | 결함·보강 | 현재 처리 |
|---|---|---|
| T01 | 개발·합성 seed가 제거된 W1 schema를 사용 | `FIXED`; current schema 보정, 3 seed 모듈 mypy·실 PG 통과 |
| T04 | W2 `finalized_at_utc` frontend projection 누락 | `FIXED`; generated/current adapter와 테스트에서 보존 확인 |
| T05 | 월·대상 전환 중 stale GET/mutation ABA race와 loading mutation | `FIXED`; exact query key+visit ownership, revisited key post-commit refetch, 409 fallback/abort/lock 테스트 추가 |
| T06 | W2 실 PG test·wrapper가 0025/Windows에 고정 | `OPEN_GATE`; 형님 승인 scope로 current-0026 Linux W2 gate를 확정해 실행 |
| T07 | W2 real FastAPI+PostgreSQL browser flow 부재 | `FIXED`; 별도 browser DB·실 로그인·FastAPI·Vite·Playwright로 ADMIN 재배정 200와 stale 409/latest, 최종 row/audit, cleanup 0 검증 |
| T08 | active 0027 backup/restore에 W2 semantic evidence 부재 | `FIXED`; disposable W2 harness 안에서 official backup→격리 restore→postcheck→artifact 검증과 cleanup GREEN |
| T09 | full Ruff에서 0018 migration SQL 한 줄 E501 | `FIXED`; 의미 불변 서식 보정, full Ruff check PASS |
| T10 | backend full run에 역사 W1F/R0 Windows 계약이 섞여 12 FAIL | `PROFILE_DEBT_RECORDED`; current 제품 gate와 historical non-acceptance를 분리 기록 |
| T11 | W0 Linux PG wrapper가 유입된 Windows `TEMP/TMP`를 복원하지 못함 | `FIXED`; Linux temp pin·원값 복원, hostile-env W0 seal GREEN |
| T12 | 테스트 데이터가 단순 이름·주소 반복이고 분포가 빈약함 | `FIXED`; 현실형 한국식 합성 이름·주소·전화·가족·등급·급여 분포 추가 |
| T13 | seed complete 판정이 count만 보고 하위 graph 손상을 놓침 | `FIXED`; exact marker/full graph 검증, 201번째 행·보호자/민감정보 삭제 시 fail-closed |

T02/T03으로 조사했던 W1E 배정 handwritten UI와 월 전문직 담당 UI 부재는
`docs/03_UI_API_상호작용_계약_v1.2.md` §6.1·§6.2에는 존재하지만, current W1E 0026은
backend scoped seal이었다. 옛 전체 로드맵을 현재 명령으로 자동 복원하지 말라는 형님
지시에 따라 이를 기술결함으로 단정하지 않고 W2-D05 범위결정에 포함한다. 같은 이유로
옛 전체 계약의 일정 WARNING·일괄취소·확정해제도 W2-D05 전에는 구현하지 않는다.

과거 로드맵의 `pre-W2 W1F`와 `Wave 2 선구현 부재`를 현재 실행에 다시 적용하지 않는다.
형님의 최신 지시는 이미 존재하는 W2를 전제로 W0~W2를 같은 current candidate에서
통합 재검수·봉인하는 것이다. Wave 1 기능·회귀는 생략하지 않고 이 통합 gate 안에서
검증한다.

### 6.1 현재 검증 스냅샷

- Runtime: provider dispatch 직전 두 번 모두 `SSWCENTER_RUNTIME_GREEN`.
- W0 hostile environment: `W0_POSTGRES_LIVE_GREEN`,
  `W0_POSTGRES_CLEANUP listener=0 process=0 temp=0 git_delta=0`,
  `W0_POSTGRES_SEAL_GREEN`; 외부 `TEMP/TMP/TMPDIR` 원값도 복원.
- OpenAPI: `OPENAPI_TYPES_UP_TO_DATE`.
- Backend current full run: `512 passed, 169 skipped, 12 failed, 2 warnings`.
  12개는 이전과 동일한 stale R0 hash, Linux에 없는 `powershell`/`powershell.exe`,
  역사 W1F restore/current-head drift, 옛 test-profile marker다. 새 제품 회귀로
  재분류하지 않으며 전체 PASS로 낮추지도 않는다.
- Backend static: full Ruff check PASS. full Ruff format-check는 기존 28개 파일,
  full mypy는 기존 test/migration 중심 41개 파일 306 errors로 baseline FAIL이다.
  제품 `mypy app`은 77 source files PASS이고, 최종 3 seed 모듈도 PASS다.
- W1E current Linux PostgreSQL: migration 0026 downgrade→upgrade, ACL, current postcheck,
  `23 passed, 1 warning`, live·cleanup·seal GREEN, `git_delta=0`, `manifest_delta=0`.
- W2 frontend: 25 files / 257 Vitest PASS, lint 0 errors·기존 warning 5,
  production build PASS, diff-check PASS.
- 과거 DeepSeek 재검수는 provider transport `DEEPSEEK_RESULT_INVALID`·`IncompleteRead`로
  실패했다. 현재 round는 형님 정책대로 DeepSeek를 비상용으로 두었고,
  current exact candidate는 Sol ultra final review로 대체 검증했다.
- Browser: 번들된 Ubuntu 24.04 Playwright shared-library runtime을 명시해 W0 E2E
  `15 passed`를 확인했다. W2는 별도 browser DB에서 실제 로그인·FastAPI·Vite·두 page를
  사용해 first reassign 200, stale reassign 409/latest, 관리자 close control 부재,
  최종 assignee/row_version/audit를 `1 passed`로 확인했다. repo-local artifact delta는 0이다.
- exact W2 PostgreSQL은 `30 passed`, active 0027 official backup→격리 restore는
  `W2_0027_POSTGRES_RESTORE_GREEN`, `W2_0027_BROWSER_REAL_PG_GREEN`, OpenAPI는
  zero-drift다. browser 이후 current candidate는 98-path manifest로 다시 동결했고,
  Sol ultra 재검수는 P0~P3 0·형님 승인 단계 진입 가능으로 통과했다.

### 6.2 현실형 합성 테스트 데이터

실재 개인정보나 실거주 세대를 복사하지 않는다. 도로명 형태는 공공장소형 문자열을
참조하되, 모든 상세주소에 `시드센터 합성`을 넣어 실제 개인정보와 구분한다.

- 개발 수급자 200명: 이름 200개·주소 200개 모두 고유, 생월 12개월 분산
  `(1~8월 각 17, 9~12월 각 16)`.
- 장기요양등급: `1=14, 2=28, 3=67, 4=65, 5=26`.
- 급여구분: `일반 104, 기초 24, 감경6 24, 감경9 24, 의료6 12, 의료9 12`.
- 보호자: `없음 67, 1명 67, 2명 66`; 납부자는 `보호자 66,
  보호자 있음+본인납부 67, 보호자 없음+본인납부 67`.
- W0~W2 업무 시나리오: 직원 10명(재직 6·퇴사 4), 수급자 6명
  (이용 4·대기 1·종료 1), 보호자 4·보호자납부 3, 등급/급여 6,
  계약 6, W1E 배정 7, 월 전문직 2, 일정 4·배정직원 5, 2인 방문목욕 1.
  W2-D01/D02 경계인 공식카드·계획서통보·replacement는 의도적으로 0이다.
- 극한 데이터: 수급자 350명(이용 150·종료 200), 직원 364명, active 급여 350,
  정규화 `+82` 직원전화 364개, 직원주소 364개·수급자주소 350개 모두 고유,
  36개 도로명 형태 분산.
- 최종 static: 6 files Ruff check/format PASS, 3 modules mypy PASS,
  `37 passed, 3 skipped`.
- 독립 live PostgreSQL: workflow complete→already-complete→보호자 삭제 partial 거부,
  dev 200→already-complete→201번째 marker·보호자 삭제 거부, extreme 상태·급여·전화·주소와
  두 번째 실행 거부 모두 PASS. 각 cluster cleanup은 `listener=0 process=0 temp=0`.

## 7. 진행상태 ledger

| 단계 | 상태 | 증거·다음 행동 |
|---|---|---|
| Runtime preflight | `PASS` | 2026-08-17 `SSWCENTER_RUNTIME_GREEN` |
| W0~W1E 현황 재구성 | `PASS` | current bytes·seal·51-path manifest 대조 완료 |
| DeepSeek current review | `COMPLETE_FAIL` | 기술결함·계약결정·미검증 gate 분리 |
| Grok current review | `COMPLETE_FAIL` | xhigh 독립 반대심사 완료 |
| 비계약 기술결함 수정 | `COMPLETE` | T01·T04·T05·T09·T11·T12·T13 current-byte 검증 완료 |
| 현실형 테스트 데이터 | `COMPLETE` | static 37 PASS, live PG 3종과 corruption fail-closed PASS |
| W0 current gate | `PASS` | hostile TEMP/TMP 포함 live·cleanup·seal GREEN |
| W1E current gate | `PASS` | PostgreSQL 23 PASS, cleanup/manifest delta 0 |
| Backend current profile | `PRODUCT_GREEN_WITH_HISTORICAL_FAILS` | 512 PASS; 역사 R0/W1F/Windows profile 12 FAIL 별도 유지 |
| W2 계약결정 | `CONFIRMED_1A_DUE_DATE_3A` | 형님 확정: 1A scoped 봉인, 정확한 `due_date` 자동배정, 3A same-recipient replacement |
| W2 확정계약 구현 | `IMPLEMENTED` | 2026-08-17 Grok IMPLEMENT. 0027 head, ADMIN reassign API/UI, 자동배정 fail-closed, 수동 override 상속 |
| W2 PG·restore·browser gate | `GREEN` | 0026→0027→0026→0027 live PG 30 PASS, exact current-head, active-0027 backup→restore, real W2 browser first-200/stale-409/DB audit, cleanup delta 0, OpenAPI PASS |
| W2 independent seal | `SOL_FINAL_PASS / USER_SEAL_APPROVAL_PENDING` | Grok·Terra timeout은 PASS로 산정하지 않음. Sol ultra P2를 host 수정·실검증한 뒤 후속 Sol review는 P0~P3 0·승인 단계 진입 가능으로 PASS; 형님 승인만 남음 |
| W2 완료 보고서 | `NOT_CREATED_BY_USER_RULE` | 봉인 완료 뒤 responsive HTML 1회 생성 |
| W3 decision packet | `PENDING` | W2 seal 뒤 즉시 |
| W4 redesign | `DEFERRED_BY_USER` | W3 기준선·대규모 수정 뒤 |
| W5 | `OUT_OF_SCOPE` | 파일함·OCR·출력·제품 복구 기능; W2 검증 restore와 별개 |

## 8. 형님 확정 계약

형님 확정은 `1A / due_date / 3A`다. 2026-08-17 Grok IMPLEMENT가 현재 dirty candidate에 반영했다.

1. W2-D05 — `A` 현재 구현된 W2 core를 scoped 봉인. 옛 배정 UI·확정해제·일괄취소는
   복원하지 않았다. ADMIN 담당자 변경만 추가했다.
2. W2-D01 — `A` 공식카드 담당자는 카드의 정확한 `due_date` 업무기준일에 유효한 월
   전문직 담당자로 서버가 결정한다. 호출자 지정 담당은 받지 않는다.
3. W2-D02 — `A` 계획서 replacement는 같은 수급자까지 DB에서 강제한다. 다른
   계약 ID는 허용하고, 타 수급자 연결은 0027 가드가 거부한다.

## 9. 중간 문제 ledger

1. W1E manifest는 표준 `sha256sum -c` 형식이 아니라
   `status|sha256|bytes|path` 형식이어서 최초 표준 검사가 실패했다. 전용 exact verifier로
   51/51 PASS를 확인했다.
2. 최초 DeepSeek/Grok read-only 실행은 사용자 turn 중단 뒤 회수 채널 없이 프로세스가
   남았다. exact PID tree를 확인해 종료했고 파일 변경은 0이었다. 회수 가능한 fresh
   session으로 다시 시작했다.
3. 중간 모바일 HTML 렌더 검증에서 지정 device가 WebKit을 요구해 실패했고, Chromium
   재시도는 shared library 경로 미지정으로 `libnspr4.so`를 찾지 못했다. 형님이 보고서를
   Wave 완료 때만 만들도록 정정해 중간 HTML과 렌더 작업을 중단·제거했다.
4. 오래된 보고서의 `CURRENT_CONFIRMED`·`PASS`를 현재 상태로 복사하지 않는다.
5. full Ruff 최초 실행은 `0018` migration SQL 한 줄 E501로 실패했고 T09로 수정했다.
6. full mypy 최초 실행은 `seed_dev_recipients.py`의 제거 schema 사용 8 errors였다.
   수정 뒤 seed 모듈은 PASS이나 full-repository baseline은 41 files / 306 errors다.
7. backend full pytest의 최신 결과는 `12 failed, 512 passed, 169 skipped`다. 실패는
   stale R0 hash/Windows PowerShell, 옛 profile marker, 역사 W1F drift로 유지한다.
8. W0 Linux PostgreSQL 첫 실행은 migration 전 Settings의 temp-root 검증으로 실패했다.
   관련 port·process·temp 잔존은 0이었고 T11 수정 뒤 hostile-env seal까지 PASS했다.
9. pytest 기본 capture는 Windows에서 유입된 `TEMP/TMP` 때문에 임시파일을 만들지 못했다.
   Linux temp selector를 `/tmp`로 고정하고 `pytest -s`로 현재 결과를 얻었다.
10. Codex의 첫 custom PostgreSQL 검증안은 안전장치가 `rm -rf`를 거부해 실행 전 중단됐다.
    이후 `mktemp`+검증된 `/tmp` prefix+`find -depth -delete` cleanup으로 바꿨다.
11. custom PostgreSQL 초기 시도는 기본 socket 권한, 다음 시도는 누락된
    `SSWCENTER_DATA_ROOT`로 migration 전 실패했다. 각 시도 listener·process·temp 0을
    확인하고 loopback socket과 격리 data root를 명시해 재실행했다.
12. 첫 현실형 seed PG 통합 재검증은 data-root leaf가 `sswcenter-`로 시작해야 한다는
    Settings 규칙에 걸렸다. migration 전 종료, cleanup 0 확인 뒤 접두사를 고쳐 3종 PASS했다.
13. 최초 workflow seed는 보호자 삭제 후에도 count만 보고 `ALREADY_COMPLETE`를 반환했다.
    live corruption으로 재현한 뒤 full graph validator를 추가했고 현재는 partial로 거부한다.
14. W0 browser E2E 15개는 앱 시작 전 Linux shared library 4종 부재로 실패했다.
    시스템 package 설치 권한을 확대하지 않았고 생성 artifact는 모두 제거했다.
15. full Ruff format-check의 28개 파일과 full mypy 306 errors는 이번 scoped 변경 전부터의
    baseline이다. 관련 없는 파일을 일괄 포맷하거나 역사 테스트를 수정하지 않았다.
16. W2 frontend 첫 수정 뒤 DeepSeek review가 같은 key를 A→B→A로 재방문하는 ABA race를
    발견했다. query-key+visit ownership과 post-mutation refetch로 재수정해 257 PASS했다.
17. W2 최종 DeepSeek 재검수는 한 번은 final text 없음, 한 번은 `IncompleteRead` transport
    오류로 끝났다. finding 0으로 간주하지 않고 seal round 재검수로 이월했다.
18. Grok xhigh 현실성 보강 실행은 24턴 한도에 도달해 `max turns reached`로 실패했다.
    다만 허용된 extreme seed/test 두 파일에 완결된 부분 변경만 남았고, Codex가 diff·static·
    단위·새 live PostgreSQL을 모두 독립 통과시킨 뒤 현재 후보로 채택했다.
19. 최종 backend full pytest와 분포 집계의 첫 명령은 `backend` cwd에서 실행하면서
    `backend/.venv/bin/python`을 다시 붙인 경로 오타로 테스트/집계 시작 전에 종료됐다.
    `.venv/bin/python`으로 즉시 재실행해 각각 최신 결과를 기록했다.
20. 2026-08-17 Grok IMPLEMENT 실행환경에는 `pwsh`와 `/opt/node` 실행 권한이 없었다.
    runtime PASS(`SSWCENTER_RUNTIME_GREEN`)와 official OpenAPI generate/check,
    frontend Vitest/lint/build는 이 실행에서 선언하지 않았다. backend unit과
    live PostgreSQL은 venv python과 `/tmp/sswcenter-w2-0027-pg-*` 임시 cluster로
    검증했다.
21. 생성된 TypeScript는 `openapi-typescript`를 실행하지 못해 현재 OpenAPI
    스키마를 읽고 기존 생성물 형식에 맞춰 수동 갱신했다. official generate
    check는 아직 미검증이다.
22. W1E Linux gate의 `alembic upgrade head`는 0027을 먹으면 0026 봉인 기대와
    충돌한다. W1E 스크립트를 `$CurrentRevision`(0026)으로 고정하고 계약
    테스트를 그에 맞게 고쳤다. 0026은 previous-head branch로 남긴다.
23. 재배정 뒤 원래 담당자의 닫기는 `CARD_ACCESS_FORBIDDEN`(403)이다. 담당자가
    바뀌었으므로 맞다. 재배정 대 닫기 경합 테스트는 409와 이 403을 모두
    허용하도록 고쳤다. 이미 닫힌 카드 재배정 검증은 담당자를 다시 본인에게
    돌린 뒤 닫고 확인했다.
24. 관리자 계정 `pin_lookup_hmac`은 기존 suffix 역순 hex를 써서 unique 충돌을
    피했다. live PG seed는 PASS했다.
25. 두 번째 Grok `FIX` xhigh/256 실행은 63분을 넘긴 뒤 중단(`INTERRUPTED`)되어
    핵심 0027 선언형 FK·postcheck·adversarial 보강을 완료하지 못했다. 기존 P0/P1은
    해결된 것으로 간주하지 않았다.
26. Terra 독립 `REVIEW`는 변경 없이 FAIL을 기록했다. 핵심 finding은 trigger 기반
    0027이 3A direct SQL/concurrent 최종상태를 충분히 강제하지 못함, manual override
    사후 재검증, current-head marker와 historical/restore 혼동, UI 후보·409·keyboard
    modal 경계 미검증이었다.
27. host 사전 결과는 backend targeted 44 PASS, frontend targeted 40/74 PASS,
    기존 live PG 23 PASS, Ruff/Mypy/lint/build PASS(기존 lint warning 5·chunk warning)였다.
    그러나 `git diff --check`는 두 W2 PostgreSQL test의 EOF blank line으로 FAIL했고,
    official OpenAPI `-Check`도 drift FAIL이었다. 이 green은 3A adversarial/lifecycle
    case가 빠진 false-green이므로 seal 증거가 아니다.
28. Terra FIX 최초 focused backend 명령은 `backend` cwd에서 `backend/.venv/bin/python`
    을 다시 붙여 interpreter 경로가 없어서 시작 전 실패했다. `.venv/bin/python`으로
    즉시 고쳐 37 PASS를 확인했다. 같은 시기 프런트 최초 npm 인자도 전체 test 방향으로
    흘러 `Window.alert` jsdom 경고가 섞였으므로 결과를 gate로 사용하지 않았다.
29. Terra FIX가 추가한 Ruff finding은 postcheck 줄길이와 test import/줄길이 4건이었고
    apply_patch로 정리했다. `mypy app`의 새 postcheck mapping iterable type error 2건도
    `cast(Iterable[object], ...)`로 수정해 78 source files PASS가 되었다. formatter
    check는 기존 Grok 변경의 넓은 재정렬 요구 6 files 때문에 FAIL로 남겼으며,
    무관한 bulk format은 하지 않았다.
30. 첫 실제 0027 PostgreSQL lifecycle은 PowerShell multi-line catalog 값을 문자열로
    합치는 harness bug로 downgrade catalog mismatch가 났다. 출력 행 trim/array 비교로
    고쳤다. 이어 0026의 deferred self-FK trigger event가 backfill UPDATE 뒤 남아
    re-upgrade DDL을 막았고, migration에서 `SET CONSTRAINTS ALL IMMEDIATE`로 drain했다.
31. 0027 postcheck는 `regclass::text` search_path 축약 때문에 exact schema table을
    오판했고, schema joins/group-by로 수정했다. direct SQL tests의 `SET CONSTRAINTS`
    는 `erp.` qualification이 필요했고, catalog mutation test는 verifier SELECT가 만든
    autobegin transaction을 rollback한 뒤 savepoint를 열도록 고쳤다.
32. 현재 Terra FIX real gate는 `scripts/test-w2-0027-postgres-linux.ps1`로
    0026→0027→0026→0027 backfill/lifecycle, ACL, exact 0027/current-head postcheck,
    same-recipient cross-contract direct SQL, cross-recipient fail-at-SET-CONSTRAINTS,
    final correction, two-connection link-vs-move, mutation postcheck, real HTTP role/CSRF,
    due_date boundary, manual override after later ADMIN link, reassign-vs-priority race까지
    `30 passed, 1 warning`으로 PASS했다. warning은 Starlette TestClient deprecation이다.
33. restore-drill은 active 0027 backup만 dispatcher/current-head marker를 요구하도록
    바꿨고, 0025/0026은 각 direct postcheck marker를 요구하며 head marker가 나오면
    fail-closed한다. 아직 안전한 실제 0027 backup bundle을 제공받지 않아 destructive
    restore invocation은 실행하지 않았다.
34. historical 0018 migration의 승인된 단일 REVOKE SQL line만 원래 한 줄로 복원했고
    다른 0001~0019 migration byte는 수정하지 않았다. official
    `scripts/generate-openapi-types.ps1` 실행 뒤 `-Check`는
    `OPENAPI_TYPES_UP_TO_DATE` PASS다.
35. W1E 0026 pinned Linux gate의 첫 재실행은 active 0027 readiness가 의도대로
    historical 0026 HTTP write를 `NOT_READY/alembic_revision_mismatch`로 거부해
    22 PASS/1 FAIL이 났다. production readiness를 낮추지 않고, harness가 이미 direct
    0026 postcheck를 통과한 뒤에만 real `erp_app` session factory를 주입하도록 test를
    좁게 고쳤다. 재실행은 direct 0026 marker만 출력하며 `23 passed, 1 warning`, cleanup
    `git_delta=0 manifest_delta=0` PASS다.
36. Terra FIX의 첫 full Vitest 직접 호출은 package script가 넣는 `--environment jsdom`을
    누락해 browser globals가 없는 환경에서 30 files/212 tests FAIL(55 PASS)로 끝났다.
    코드 결과로 사용하지 않았고, runtime 재확인 뒤 공식 `npm run test:supported`로
    `25 files, 265 passed`를 확인했다. lint는 기존 warning 5건만 남고, build는 PASS이며
    기존 500 kB chunk warning만 출력했다.
37. 최종 Terra FIX recheck는 runtime `SSWCENTER_RUNTIME_GREEN`, focused backend
    `45 passed, 30 skipped`, selected Ruff PASS, `mypy app` 78 source files PASS,
    official OpenAPI generate/check PASS, `git diff --check` PASS였다. W2 disposable
    PostgreSQL lifecycle/adversarial gate는 다시 `30 passed, 1 warning`과 cleanup
    `listener=0 process=0 temp=0 git_delta=0` PASS, W1E pinned historical gate는
    current-head marker 없이 `23 passed, 1 warning`과 manifest delta 0 PASS였다.
    repository 안에는 active 0027 restore에 필요한 `manifest.json`/`bundle.sha256`/dump
    bundle이 없어 destructive restore는 실행하지 않았고, `restore-drill.ps1` parse만
    `RESTORE_DRILL_PARSE_OK`로 확인했다. 이 결과는 Sol 독립 review·browser E2E·안전한
    restore bundle·형님 승인 전의 구현 증거일 뿐 W2 seal 선언이 아니다.
38. Codex host 독립 재검증은 backend targeted `47 passed`, Ruff PASS,
    `mypy app` 78 source files PASS, frontend supported `25 files / 265 passed`,
    lint·build PASS(기존 warning 5건·500 kB chunk warning), official OpenAPI
    `OPENAPI_TYPES_UP_TO_DATE`, `git diff --check` PASS였다. W2 disposable PostgreSQL은
    0026→0027→0026→0027 lifecycle과 adversarial/direct SQL/concurrency/HTTP를 다시
    `30 passed, 1 warning`, cleanup delta 0으로 통과했다.
39. 같은 host의 첫 W1E 0026 pinned 재실행은
    `test_w1e_0026_pg_multi_edge_employment_parent_no_deadlock`에서 assignment가
    `55P03/CARE_ASSIGNMENT_CONCURRENT_CONFLICT`, parent가
    `23514/STAFF_PERIOD_OUTSIDE_EMPLOYMENT`로 모두 거부되어 `22 passed / 1 failed`였다.
    즉시 전체 재실행은 `23 passed`였다. source trace 결과 parent update는 seed된
    1월·2월 assignment가 이미 있는데 employment를 1월 15일로 줄이므로 원래도 invalid이고,
    assignment가 nowait lock을 잃으면 양쪽 rollback이 허용되는 안전한 직렬화였다.
    제품 orphan이나 deadlock이 아니라 테스트가 정확히 한쪽 성공만 허용한 flake였다.
40. Grok read-only 재검수와 그 뒤 좁은 Grok FIX는 각각 xhigh/256으로 실행했지만
    둘 다 63분을 넘겨 `INTERRUPTED`, output 없음으로 끝났다. review는 read-only라
    변경 0건이었고 FIX도 허용된 test/plan byte를 바꾸지 못했다. 이를 PASS나 finding 0으로
    간주하지 않고 Codex가 current byte와 실제 오류쌍을 직접 대조해 복구했다.
41. Codex는 공용 race assertion을 약화하지 않고 multi-edge regression 전용 assertion만
    추가했다. 허용 결과는 기존 strict 한쪽-success 경로 또는 정확한 assignment
    `OperationalError 55P03/CARE_ASSIGNMENT_CONCURRENT_CONFLICT` + parent
    `IntegrityError 23514/STAFF_PERIOD_OUTSIDE_EMPLOYMENT` 양쪽-error 경로뿐이다.
    40P01·반대 index·다른 타입/code/message·orphan은 계속 실패한다. W1E pinned live gate는
    새 disposable cluster로 5회 연속 각각 `23 passed, 1 warning`, 매회
    listener/process/temp/git/manifest delta 0을 통과했다. 이어 W2 gate도 다시
    `30 passed, 1 warning`, cleanup delta 0, OpenAPI `-Check`와 `git diff --check` PASS였다.
42. Codex가 integration test 파일까지 포함한 비표준 `mypy app tests/test_w1e_0026_postgres.py`
    를 실행해 기존 test typing 오류를 포함한 20건으로 FAIL했다. 이 명령은 current gate가
    아니며 결과를 숨기지 않았다. 새 helper에는 명시적 exception type narrowing을 넣었고,
    정본 gate인 `mypy app`과 changed-test Ruff는 별도로 PASS를 재확인한다.
43. Playwright browser runtime은 저장소 밖 번들 경로의 Ubuntu 24.04 shared libraries를
    `LD_LIBRARY_PATH`에 명시해 재검증했다. 공식 W0 shell browser E2E는 `15 passed`였고,
    생성된 `frontend/test-results`는 exact path에서 제거했다. 이는 browser runtime blocker를
    닫지만 W2 real FastAPI+PostgreSQL 재배정 browser spec 부재까지 닫지는 않는다.
44. 안전한 active-0027 bundle 부재는 W2 disposable PostgreSQL harness가 자기 격리 data root에
    합성 blob/공식문서를 만들고 official `backup-postgres.ps1`로 bundle을 생성하도록 보완해
    해소했다. 이어 `restore-drill.ps1`로 별도 review DB/data root에 복구하고 postcheck·artifact를
    검증한 뒤 review target과 bundle을 모두 정리했다. 결과는 `30 passed, 1 warning`,
    `W2_0027_POSTGRES_RESTORE_GREEN`, `W2_0027_POSTGRES_LIVE_GREEN`, cleanup
    `listener=0 process=0 temp=0 git_delta=0`, `W2_0027_POSTGRES_SEAL_GREEN`이다.
45. W1E multi-edge flake assertion 보강 뒤 pinned live gate의 최종 1회를 추가 실행해
    누적 6회 연속 각각 `23 passed, 1 warning`과 cleanup/manifest delta 0을 확인했다.
46. browser gate 구현 전 current mixed dirty tree의 tracked-modified/untracked 94개 파일을
    `review/evidence/W2_20260817_CURRENT_CANDIDATE_MANIFEST.sha256`에
    `status|sha256|bytes|path`로 동결했다. manifest 자신과 untracked `.codex/` 설정만
    제외했으며, 각 status·hash·size와 누락/초과 0을 exact verifier로 확인했다. 뒤이어 승인된
    browser RED→GREEN 파일을 추가했으므로 이 94-entry snapshot은 역사 증거로 남기고 final
    Sol 실행 전에 현재 status 전체로 재생성한다.
47. Luna max draft는 정한 짧은 checkpoint를 넘겨 한 번 interrupt했고, tool-call 없는 즉시
    요약으로 재요청했다. 늦게 도착한 read-only 초안은 별도 browser DB, 실제 login/FastAPI/
    Vite/Playwright, two-page stale 409, bounded process cleanup을 제안했다. 구현은 별도 wrapper를
    늘리지 않고 기존 W2 disposable harness가 새 browser DB까지 소유하도록 좁혔다.
48. 새 E2E 정적검사에서 저장소 linter를 ESLint로 잘못 가정한 `npm exec eslint`는 config
    부재로 검사 전 실패했다. 뒤의 `git diff --check`가 0이라 묶음 shell exit가 0이 된 값은
    PASS로 쓰지 않았다. 정본 `npm run lint`(oxlint)와 production build를 다시 실행해 PASS했다.
49. 병렬 backend contract pytest는 수집 전 capture tmpfile이 사라져 `no tests ran`과
    `FileNotFoundError`로 끝났다. Ruff와 `mypy app` 79 files 결과만 분리해 보존하고, 저장소
    Linux 지침대로 `-s`를 붙여 직렬 재실행해 `27 passed`를 확인했다.
50. 보강된 `scripts/test-w2-0027-postgres-linux.ps1`은 main DB의 기존 lifecycle/adversarial
    `30 passed, 1 warning`, 별도 browser DB fresh head/workflow seed/card seed, 실제 로그인과
    ADMIN 두 page에서 first reassign 200·stale reassign 409/latest, UI five-field/current-candidate/
    no-close, DB assignee·row_version=2·정확히 1개 actor/before/after audit를 통과했다. marker는
    `W2_0027_BROWSER_REAL_PG_GREEN`, restore/live/seal GREEN이고 cleanup은
    `listener=0 process=0 temp=0 git_delta=0`이다.
51. 같은 final regression에서 W1E pinned PostgreSQL은 다시 `23 passed, 1 warning`, cleanup/
    manifest delta 0, frontend는 lint 기존 warning 5·supported `265 passed`·build PASS,
    OpenAPI `OPENAPI_TYPES_UP_TO_DATE`, diff-check PASS였다.
52. 별도 Grok xhigh `REVIEW`는 약 13분 44초 뒤 변경 없이 `FAIL`을 반환했다.
    finding은 stale 409 E2E가 후보 재조회 완료 전의 순간 상태에서도 통과할 수 있는
    oracle 문제와, Playwright timeout 경로의 무한 `WaitForExit()`·child log task의
    무한 `GetResult()`였다. `CHANGED_PATHS=NONE`이고 P0/P1은 발견하지 않았다.
53. 이 두 finding만 허용한 Grok xhigh `FIX`는 5분 36초 체크포인트까지 output과
    허용 3개 파일의 mtime 변경이 모두 0이었다. 약속한 timeout 운영대로 `INTERRUPTED`
    처리했고 provider 성공으로 계산하지 않았다. Grok 수정 byte는 없다.
54. Codex가 확정된 두 finding만 인수했다. stale page는 409 뒤 exact
    eligible-assignee GET 응답과 loading 종료를 기다린 다음 `현재 담당자`의
    `dd=정소연`, select enabled/empty, 정소연 option 0, 강태현 option 1, confirm disabled,
    alert를 정확히 검증한다. harness는 Playwright 180초, kill/exit/log drain과
    backend/frontend cleanup을 모두 10초 bounded wait로 바꾸고 timeout 진단을 throw 전에
    출력하며 후속 PostgreSQL/temp/git/listener cleanup을 계속하도록 했다. parse,
    oxlint, Ruff, contract `11 passed`에 이어 full W2가 PG `30 passed, 1 warning`, real
    Chromium `1 passed`, active-0027 backup/restore, cleanup `listener=0 process=0 temp=0
    git_delta=0`, `W2_0027_POSTGRES_SEAL_GREEN`을 다시 통과했다.
55. Terra max `REVIEW`는 필수 문서·current byte 대조 후 P0/P1은 없다고
    checkpoint했지만, `finally`의 `pg_ctl stop` 오류가 즉시 throw되면 temp/git/listener/
    process 후속 관측을 건너뛸는 P2를 발견했다. 추가 2분 최종 요약
    checkpoint를 넘겨 `INTERRUPTED`로 회수했다. 직접 native migration/test 명령의
    전체 deadline은 이번 child/browser cleanup 수정 범위 밖 운영 residual risk로 분리했다.
56. 확정 P2 하나만 허용한 별도 Terra max `FIX`는 5분 체크포인트까지
    output·mtime 변경이 0이어서 `INTERRUPTED`했다. Terra 수정 byte는 없고, Codex가
    해당 finding만 인수했다.
57. cleanup은 child 단계별 예외를 누적하고, `pg_ctl --timeout=15`로 종료를
    유한 대기하며, cluster가 종료됐다는 확증 없이 temp root를 삭제하지 않는다.
    중간 오류가 나도 process/temp/git/listener를 각각 관측·출력한 뒤 failure를
    반환한다. parse, Ruff, contract `11 passed`, full W2 PG `30 passed, 1 warning`,
    real Chromium `1 passed`, restore GREEN, cleanup 0, seal marker가 현재 byte에서 PASS했다.
58. 최종 회귀는 backend Ruff·mypy 79 files·targeted `27 passed`, frontend lint
    기존 warning 5·supported `265 passed`·build PASS, OpenAPI zero-drift, diff-check PASS,
    W1E pinned `23 passed, 1 warning`·cleanup/manifest delta 0을 재확인했다.
59. Grok xhigh 재검수는 5분 checkpoint까지 output 0으로 `INTERRUPTED`했다.
    이어 수정 2개 파일만 보는 8-turn/180초 초협소 재시도를 했지만 provider가
    `PROVIDER_TIMEOUT` 정확오류를 반환했다. 둘 다 read-only로 변경 0건이며,
    이 시도를 finding 0나 PASS로 산정하지 않고 Sol final review에 그대로 이월한다.
60. 첫 Sol ultra final `REVIEW`는 manifest `98/98`·SHA·status·bytes exact와 W2
    backend/DB/browser 기능 finding 0을 확인했지만, `pg_ctl start` 성공 exit 후에만
    cluster-running flag를 세우는 P2를 발견했다. postmaster spawn 후 start wait가
    nonzero일 때 stop·PID 관측을 건너뛰고 살아 있을 수 있는 data root를 지울 수
    있어 `STATUS=FAIL / READY=NO / CHANGED_PATHS=NONE`으로 정확히 판정했다.
61. Codex는 start 호출 전 `$ClusterMayBeRunning = $true`를 세우고 start에도
    `--timeout=15`를 적용했다. cleanup은 bounded stop이 성공해야만 flag를 false로
    낮추며, process count를 readiness 후 snapshot이 아니라 harness 시작 전 baseline 대비
    현재 모든 신규 PostgreSQL PID로 측정한다. parse, Ruff, contract `11 passed`,
    full W2 PG `30 passed, 1 warning`, real Chromium `1 passed`, restore GREEN, cleanup
    `listener=0 process=0 temp=0 git_delta=0`, seal marker를 재확인했다. 첫 manifest는
    이 수정으로 무효화되었으며 Sol 재검수 전 다시 생성한다.
62. Sol ultra 후속 `REVIEW`는 자신이 찾은 start-failure P2의 현재 byte를
    다시 대조했다. manifest 98/98 exact, runtime·parse·Ruff·contract `11 passed`·
    diff-check PASS였고, potentially-live flag·bounded start/stop·stop 증명 전 삭제 금지·
    baseline PID delta·후속 cleanup 관측을 확인했다. 남은 P0~P3는 `NONE`,
    `STATUS=PASS / READY_FOR_USER_SEAL_APPROVAL=YES / CHANGED_PATHS=NONE`이다.

## 10. 중지조건

- 현재 정본만으로 하나를 선택할 수 없는 사용자 계약결정
- credential·운영자료·프로젝트 밖 자료가 필요한 경우
- current candidate manifest drift
- 반복 실행 뒤에도 재현되는 환경 blocker
- 필수 gate FAIL

W2-D05·D01·D02는 형님 확정 `1A / due_date / 3A`로 닫혔다. 현재 중지는 형님의
W2 scoped 봉인 명시 승인이다. provider timeout과 중간 실패를 PASS로 낮추지 않는다.
