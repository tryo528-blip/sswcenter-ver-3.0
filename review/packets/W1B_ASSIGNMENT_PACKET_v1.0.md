# W1B 작업 배정 패킷 v1.0

> 작업: 수급자·보호자·독립 납부자 (W1B)
>
> 상태: `P0_W1B_PASS`
>
> 작성: `D1 계약·설계실` — Grok (본 후보 D1 바인딩)
>
> 작성일: 2026-07-29 KST · 개정: 2026-07-30 KST (G1 exact-SHA 승인·P0 최종 PASS)
>
> P0 승인: 2026-07-29 KST · 제품 보정 확장 승인: 2026-07-30 KST
>
> 현행 운영정본: `docs/AI_업무분담_운영규정_v3.5.md` · 적용: §6에 따라 본 W1B 기존 절차 자동 소급 없음
>
> 후보 branch: `wip/w1a-office-handoff` · basis: `e204023a7277e486018f3057653fe8aebf7b7fcf` · 제품 commit: `958590a84bf0b4bdcaec88a1dac6e1fa3e7312c6` · cross-wave 보정: `26f4d2462e0181297e6318f152f3aab39afee0d5` · G1 승인 후보: `80ed49b3b6fb3ce2f342ca09658d9e3dc8c8b416`
>
> W1A 직접 의존: `6deb1f0336a16829bdd1ef3fef2120ef080af605` (VS6 legacy import gate)
>
> 증거: 구현 전 역사 `review/evidence/w1b/RED.md`, `F2_RED.md` · 현 후보 `GREEN.md`
>
> D1 제품 write: **금지** — 본 산출물은 `review/packets/` 만

## Change log

| 일자 | 변경 |
|---|---|
| 2026-07-29 | P0 REQUIRED_CHANGES: anchor 02§11·03§8·matrix§13 정정; 권한/path/오류코드/migration/sex_code를 P0 전 **제안**; REC-03 full·SIG-01 full → W1D `NOT_RUN/DEFERRED_TO_W1D`; REC-02 합성 import 필수; F1 generator-only TS / F2 temp drift; 승계·leak·R1 필수; 미봉인 path 제거; 상태 `D1_PACKET_REVISED / AWAITING_P0_REVIEW` |
| 2026-07-29 | P0 재검토 승인: RED용 권한·resource path·409 코드·sex_code 경계를 봉인하고, D1 후속 감사 바인딩을 Opus로 복귀. 같은 후보에서 Grok이 D1 설계에 참여했으므로 G1은 요셉, 불가 시 Regina(Sol Max)로 유지 |
| 2026-07-29 | R1 `REQUIRED_CHANGES`: payer type 선택기 역전, substring-only false-green, migration single-lane·기간 경계·권한/PII·REC-02 실동작 부족을 RED 보정 대상으로 봉인. B2/F2 보정 뒤 D1 Opus 감사와 R1 재검토 전에는 B1/F1 제품 write 금지 |
| 2026-07-29 | D1 Opus RED 감사 후 P0 추가 보정: F2 실행 증거를 분리 기록하고 3-viewport browser RED와 focused GREEN real-PG 승계를 구분. 대표 보호자 composite FK, history action route, generated TS exact check, 응답·로그 leak를 RED 필수로 추가 |
| 2026-07-29 | D1 Opus 2차 RED 감사 `APPROVE / RED_VALID_PENDING_PRODUCT`: backend 11건·F2 Vitest 8건·Playwright 21건의 named RED와 ABS 분리, REC-03/SIG-01 W1D 유보를 승인. 다음 필수 단계는 R1 재검토 |
| 2026-07-29 | R1 2차 `REQUIRED_CHANGES`: exclusion 무효화 predicate, payer 전체 기간 경계·독립성, 대표 동시 경쟁, REC-02 attachment/memo·동일 key 승계, 전체 ACL·안정 오류·강제 500 leak, direct-child offline SQL, W1B 소유 recipient_no unique/immutable, 실제 browser back 문맥을 추가 봉인 |
| 2026-07-29 | B2/F2 3차 RED 보정 및 P0 독립 재현 완료: backend 11 collected/8 failed/3 ABS passed, Vitest 8/8 failed, Playwright 21/21 failed·3 viewport, skip/error 0. D1 Opus 5 `medium` 재감사 `APPROVE / RED_VALID_PENDING_PRODUCT`; R1 재검토 대기 |
| 2026-07-29 | R1 3차 `REQUIRED_CHANGES`: 대표 race의 duplicate-UNIQUE 우회, forced-500 PII canary 누락, REC-02 same-key 조회 비결정성, exact-revision catalog 미검증, nested API 및 연락처 submit/readback 실동작 누락을 추가 false-green으로 봉인 |
| 2026-07-29 | B2/F2 4차 보정 및 P0 재현 뒤 D1 Opus 5 `medium` 감사 `APPROVE / RED_VALID_PENDING_PRODUCT`: R1 3차 5건의 봉인을 확인 |
| 2026-07-29 | P0 후속 강화: PostgreSQL 17 실측으로 exclusion predicate를 `pg_index.indpred`에서 읽도록 교정하고, primary/payer replacement·invalidate의 wrong `expected_row_version` 409+PG 무변경, REC-03 W1B partial UI의 `NULL→미부여`·사용자 입력 부재를 추가. backend 11=8 RED/3 ABS PASS, Vitest 8/8 RED, Playwright 21/21 RED·3 viewport를 재현하고 R1 최종 재검토로 전환 |
| 2026-07-29 | P0 승인 사슬 교정: 직전 Opus 승인은 P0 후속 강화 이전 스냅샷에만 유효하므로 현 스냅샷 승인으로 사용할 수 없다. 제품 write를 계속 잠그고 `Opus → Marco → Opus → Marco → Regina` 전 단계를 현 스냅샷 기준으로 재시작 |
| 2026-07-29 | Grok 1차 `REQUIRED_CHANGES` 2건 후속 보정: (1) `/{id}/replacements` POST 전용 schema와 payload 실제 키·값에서 `expected_row_version`을 강제해 collection create schema 누락 경로를 차단, (2) create POST의 `recipient_no` key 완전 부재와 list/detail 편집 control 0을 강제. B2 backend 11 collected = 8 intended RED / 3 ABS PASS / skip·error 0, ruff clean; F2 Vitest 8/8 RED, Playwright 21/21 RED·3 viewports, skip/config/env error 0. 동일 Grok 1차 재감사 직전으로 갱신 |
| 2026-07-29 | Grok ROUND 1 재감사 `REQUIRED_CHANGES`: backend finding 1 `CLOSED` — exact replacements action schema·실제 `expected_row_version` payload·stale 409/PG 무변경·valid lifecycle 폐쇄. frontend finding 2 `OPEN` — `recipient-list-recipient-no`·`recipient-detail-recipient-no` display leaf 하위만 검사하는 false-green을 확인; `recipient-list`·`recipient-detail-workspace` root 전체의 기존 selector 3종 count 0 보정이 필요. F2 최소 보정 대기 |
| 2026-07-29 | F2 최소 보정·검증 완료: 기존 selector 3종 유지, list/detail control 0 검사 루트를 leaf에서 `recipient-list`·`recipient-detail-workspace` 전체 root로 변경, exact `미부여` 및 create POST `recipient_no` key 완전 부재 유지. Vitest 8/8 intended RED·0 pass/skip·첫 marker `W1B_F2_API_RECIPIENT_LIST_MISSING`; Playwright 21/21 intended RED·3 viewports 각 7·0 pass/skip·config/env error 0·첫 marker `W1B_F2_API_RECIPIENT_LIST_MISSING_REAL_BROWSER_REQUEST`; TypeScript exit 0·허용 파일 diff check 0·tracked 제품 diff 0·stage/commit/push 없음. 동일 Grok 1차 재감사 직전으로 갱신 |
| 2026-07-30 | 실 PG 3-viewport 승계에서 stale 409 최신값/차이/재적용 UI, page-2 선택 문맥, 연결별 timezone 설정 지속성 결함을 확인하고 R1 Marco `REQUIRED_CHANGES`. P0는 순차 단일 writer 보정을 승인하며 B1에 `backend/app/db/session.py`를 추가 배정한다. F1은 `RecipientsPage.tsx` 내부 GET 재조회 방식으로 보정하여 공통 `api.ts` 소유 확장을 피하고, URL 갱신은 호출 시점의 최신 browser location을 병합해 초기 자동선택과 검색 입력의 stale-closure 덮어쓰기를 차단한다. F2는 동일 instant 정규화, stale 최신 GET 후 React render 대기, exact page-2 응답 대기를 보정하고, browser가 폐기해 읽을 수 없는 응답 body는 고정 합성 표식으로 보안 표면에 남겨 event-handler unhandled rejection을 차단하며, 승인되지 않은 backend filter/sort 계약은 강제하지 않는다. B2는 wrapper에 app engine rollback/pool-reuse session 설정 지속성 gate를 추가하고 marker를 실제 Playwright `Error:` heading으로만 집계하며, marker 없는 실패는 고정 reason code와 spec line 번호만 출력해 비밀 노출 없이 진단한다. |
| 2026-07-30 | R1 Marco 교정 검토 `REQUIRED_CHANGES`: page-2 응답 header만 기다린 뒤 기존 page-1 row에서 scroll 조작이 먼저 실행될 수 있는 false-green 1건을 확인했다. P0는 기존 F2 소유 파일만 보정하도록 승인한다. `pageTwoResponse.finished()`와 page-2 row 3건 render를 scroll 조작 전에 순서대로 확정하고, stale 재적용 PATCH가 외부 갱신의 최신 `row_version`과 사용자 변경 필드만 전송했는지도 exact payload로 봉인한다. 제품 재작성이나 소유 확장은 없다. |
| 2026-07-30 | F2 교정 후 전체 격리 PostgreSQL gate 재실행 `W1B_E2E_GREEN`: exact migration 1, session settings BEFORE/AFTER/OK, postcheck 전후, Playwright 3/3·skip/error 0, leak 275, listener/artifact/temp 잔여 0. Marco가 현재 바이트와 sealed hash 10/10, stage 0을 확인하고 `R1_MARCO_CORRECTION_APPROVE` 판정했다. 다음은 G1 pre-commit 독립검수이며, 커밋 SHA·clean 검수 worktree·최종 P0 PASS는 `퇴근!` Git closeout까지 보류한다. |
| 2026-07-30 | G1 요셉 pre-commit 독립검수 `REQUIRED_CHANGES`: DB/backend는 포함 종료일 `[start,end+1)` 및 당일 단일 기간을 허용하지만 UI가 `end_date == start_date`를 거절하고 strict `<` 겹침으로 동일 종료일 경계를 놓치는 계약 불일치 1건을 확인했다. P0는 순차 단일 writer로 F1의 `RecipientsPage.tsx`에서 equality 허용·포함 종료일 overlap을 보정한 뒤, F2의 `w1b-recipients-real-pg.spec.ts`에서 대표·납부자 당일 기간과 경계 겹침을 실 UI/PG로 봉인하도록 승인한다. sealed RED 파일·backend·migration·공통 API·다른 파일 write는 금지한다. |
| 2026-07-30 | F1 김루나 `F1_INCLUSIVE_END_CORRECTION_PASS`: `RecipientsPage.tsx` 한 파일에서 대표·납부자 `end_date == start_date`를 허용하고 포함 종료일 overlap을 `<=`로 교정했다. generator drift 0, lint/build, focused Vitest 8/8, full Vitest 93/93, diff check가 모두 exit 0이며 stage 0이다. 다음 단일 writer는 F2 박루나이며 real-PG spec 한 파일만 수정한다. |
| 2026-07-30 | F2 박루나 `F2_INCLUSIVE_END_REGRESSION_PASS`: real-PG spec 한 파일에서 대표·납부자 각각 당일 기간 UI POST 201+readback, 같은 포함 종료일 overlap UI 오류+POST 불변, 다음 날 adjacency UI POST 201을 봉인하고 생성 행을 최신 row_version으로 무효화·재조회했다. TypeScript/build/lint, Playwright exact 3 수집, diff check가 exit 0이며 stage 0이다. 실 PG 실행은 P0 전체 재검증으로 승계한다. |
| 2026-07-30 | P0 변경 후 전체 gate `GREEN`: backend ruff/format/mypy, OpenAPI drift 0, frontend build/lint, focused Vitest 8/8, full Vitest 93/93, Playwright exact 3 수집을 통과했다. 격리 PG는 exact migration 1, session settings BEFORE/AFTER/OK, postcheck 전후, 포함 종료일 UI 회귀 포함 3/3·skip/error 0, artifact path failure 0, leak 275, listener/artifact/temp 잔여 0으로 `W1B_E2E_GREEN`이다. 다음은 G1 요셉 동일 지적 재검토다. |
| 2026-07-30 | 제품 commit `958590a84bf0b4bdcaec88a1dac6e1fa3e7312c6` clean exact-SHA G1에서 제품·정적·frontend·실 PG는 GREEN이었으나 cross-wave 회귀 2건과 현재 GREEN evidence 부재로 `G1_JOSEPH_REQUIRED_CHANGES`: exact metadata 목록이 신규 W1B 테이블 5개를 거부했고, VS6 predecessor 검사가 descendant `0009`를 old migration으로 오인했다. 기존 `0001`~`0008` 실제 변경 0, 신규 제품 결함 0. |
| 2026-07-30 | P0 cross-wave 최소 보정 commit `26f4d2462e0181297e6318f152f3aab39afee0d5`: exact metadata에 승인 W1B 테이블 5개를 추가하고 VS6 불변 검사를 exact predecessor `0001`~`0007`로 고정했다. targeted 6/6, 넓은 비PG 122 passed/7 skipped, Ruff/format/mypy, OpenAPI drift 0, tsc/lint/build, Vitest 8/8·93/93, Playwright 3/1, 격리 PG 3/3·leak 275·cleanup 0이 clean worktree에서 GREEN. `GREEN.md`를 현 후보 증거로 추가하고 G1 exact-SHA 재검토로 전환. |
| 2026-07-30 | G1 요셉은 evidence candidate `80ed49b3b6fb3ce2f342ca09658d9e3dc8c8b416`의 exact 4-commit chain, basis 대비 고유 31 paths·삭제 0, 기존 migration `0001`~`0008` byte 동일, clean/stage/diff 0을 확인했다. Ruff/format/mypy, targeted 6/6, non-PG 122 passed/7 skipped를 독립 재실행했고 runtime·migration·frontend·E2E·PG wrapper delta 0에 따라 기존 독립 PG 3/3·leak 275·cleanup 0 증거를 승인하여 `G1_JOSEPH_CANDIDATE_SHA_APPROVE`를 반환했다. P0는 확정 결함 0으로 `P0_W1B_PASS`를 판정한다. |

## 0. 한 줄 요약

W1A PASS 위 수급자 identity·보호자·대표기간·독립 납부자 snapshot·내부 legacy
mapping(합성 import 포함)을 DB·API·OpenAPI 생성 타입·UI·실 PG·브라우저까지
연다. 인정·계약·배정·first-contract 번호 발급·서명자 본계약은 비범위(W1D 등).

## 1. 목표 / 비범위

### 1.1 목표 (canonical behavior)

1. **수급자** (`W1-REC-01`, `W1-REC-02` 전체; `W1-REC-03` W1B 분): 필수
   name·birth_date·sex_code; 선택 우편·주소·자택/휴대 분리·출처 메모; PK와
   화면 수급자번호 분리; 계약 전 `recipient_no=NULL`·사용자 편집 없음;
   immutable은 `NULL→값`만(발급 runtime=W1D); legacy key 내부 전용·공개 비노출.
2. **보호자** (`W1-GUA-01/02`, `ABS-01~02`): 0+명, 이름만 필수; 전화·주소·관계
   선택; birth/sex 금지; 대표 0 허용·동시 최대 1(exclusion)·**이력 보존**.
3. **납부자 snapshot** (`W1-PAY-01`, `ABS-03`): 유효 0|1, 행 있으면 이름 필수;
   type/guardian FK/SELF/PRIMARY_GUARDIAN/연동 trigger 금지; 보호자·대표 변경 후
   payer **불변**; **payer 기간** non-overlap·이력(`04` 기간사실).
4. **공통**: `/api/v1`, 권한·CSRF·`row_version`, named schema, 목록 유지형 상세
   (`W1-CMN-02` 수급자), 합성자료만.
5. **부재**: ABS-01~03; signer FK/birth/address 토큰 부재 가드 허용 — 단
   **`W1-SIG-01` PASS/SKIP 집계 금지** (§6).

### 1.2 비범위

| 제외 | 소유 |
|---|---|
| 인정·등급·혜택·승인금액 | W1C |
| 계약·signer runtime·overlap·first-contract 발급/경쟁/rollback | W1D (REC-03 full, SIG-01 full) |
| 인정 전환 / 배정 / 통합 / 일정·RFID·청구·파일·OCR | W1D / W1E / W1F / Wave2+ |
| W1A sealed 약화, migration `0001`~`0008` 수정, 생성 TS **수동** 편집 | 금지 |
| 정본 `docs/0*.md` 수정, Git stage/commit/push/이력조작 | P0 명시 전 금지 |

## 2. 필수 정본 anchor

| 영역 | Anchor |
|---|---|
| 업무 | `02#fr-recipient` (§4.1~§4.3) |
| 의미분류 | **`02` §11**: 수급자 `IDENTITY`, 납부자 snapshot `PERIOD_FACT` |
| 폐기구조 | `02` §13: 보호자 전화/관계 필수, 납부자 SELF/PRIMARY_GUARDIAN·guardian FK |
| UI | `03#ui-recipient` (§4.1~§4.4); §1.1 목록 유지형·popup 금지 |
| DOM/OpenAPI | **`03` §8** OpenAPI 소비·DOM/Playwright 이름 선택 |
| DB | `04#db-recipient` (§4.1~§4.2); §5.1 guardian, §5.2 primary period, §5.3 payer |
| DB 공통 | `04` §1 counter 의미(발급≠W1B), §2.1 exclusion, §2.2 무효화·`row_version` |
| 기술 | `05#api-contract`; §1.2 recipient 도메인 분리 |
| 로드맵 | `06` §1 W1A→**W1B**→…, §2 W1B 행 |
| matrix | §5 REC/GUA/PAY, §9 ABS-01~03, **§13 W1B 공식 행**, CMN 해당분 |
| 운영 | 현행 v3.5 §6 적용 규칙; 본 패킷 §4·§9·§11의 기존 W1B 절차 유지 |

`02`§4.4·`03`§5·`04`§8 계약/서명자 = 참조만. W1B 구현 아님.

## 3. 기준선·W1A 의존·위험

```text
branch: wip/w1a-office-handoff
HEAD:   6e43f1e7db1df23f4badf4e1b360c2d5a1141ee9
W1A:    6deb1f0336a16829bdd1ef3fef2120ef080af605 (VS6 gate)
위험:   HIGH · MIGRATION/DB/AUTH/PII/DOMAIN/API_CONTRACT/UI/E2E
계열:   W1B-RECIPIENT-20260729-0009 (revision exact=제안)
```

- **W1A exact 의존**: 전 slice·특히 VS6. 재사용: row_version·audit·CSRF·권한·
  `erp`·counter 테이블(발급≠W1B)·exclusion·목록 유지형 UI. 금지: W1A/`0003`~`0008`
  약화, staff RRN 혼동. staff FK 비필수. 실패는 `recipient*`에 국한; **MIGRATION
  전역 1슬롯** 공유.
- **R1 필수** (HIGH: migration·PII·exclusion·race). 생략 불가.
- PII: 성명·연락처·주소·생년월일. 수급자 RRN encrypt slot 없음. §7 leak.

## 4. 업무석·승계·파일 경계

### 4.1 배정 `CONFIRMED(default)` 제안

```text
평시 승계:  D1 = Opus → Grok → 요셉(Joseph)
            G1 = Grok → 요셉(Joseph) → Regina (Sol Max)
본 후보:    [P0] Codex  [D1 설계·RED 재감사] Grok(완료)
            [B1] 송루나(Luna Max, 완료)  [B2] 나루나(Luna Max, 완료)
            [F1] 김루나(Luna Max, 완료)  [F2] 박루나(Luna Max, 완료)
            [R1] 마르코(Sol Max, `R1_MARCO_CORRECTION_APPROVE`)
            [G1] 요셉(Sol Max, `G1_JOSEPH_CANDIDATE_SHA_APPROVE`) — Grok이 D1에 참여했으므로 G1≠Grok
현재 위치: 제품 958590a + cross-wave 보정 26f4d24 + 증거 후보 80ed49b → `P0_W1B_PASS`
운영 closeout: P0 PASS 증거 commit → push·local/upstream/remote SHA·clean 봉인
```

- Opus 호출은 **한도 거절**로 진행하지 못했고, 새 작업으로 전환하지 않은 동일 검토 사슬의
  1차 재감사를 Grok에게 인계했다.
- 한도 복구로 진행 중인 검토 사슬을 회수하지 않는다. Grok RED 재감사와 B1/B2/F1/F2
  구현·보정, 독립 실 PG GREEN을 마쳤다.
- Marco R1은 제품 보정 뒤 F2 false-green 1건을 추가 확인했고, 동일 F2 소유 보정과
  전체 실 PG 재실행 뒤 `R1_MARCO_CORRECTION_APPROVE`로 폐쇄했다.
- 같은 후보에서 Grok은 이미 D1에 참여했으므로 G1으로 재배정하지 않는다.
- 요셉은 D1·G1 백업요원이며 호출 모델은 Sol Max다.
- F1·F2·B1·B2의 호출 모델은 모두 Luna Max다.
- D1·R1·G1 제품·테스트 write 금지. Grok 하부=RO·독립 검수 주체 아님. 동시 multi-writer 금지.

### 4.2 파일 소유 (경계 — 미봉인 exact path 비고정)

경로 미봉인 항목은 **소유 경계**만. B1 생성 exact path/revision → evidence/패킷 개정.
**후보당 migration 1파일**, `0008` 다음 단일 revision.

| 석 | 소유 경계 |
|---|---|
| B1 | recipient* migration 1; models recipient* 추가; domains/recipient; API mount; 권한 seed(승인 문자열); postcheck/restore W1B 훅(최소·P0 확인); **OpenAPI 안정화**; `backend/app/db/session.py`의 연결별 timezone·timeout·search_path 설정 지속성 보정 |
| B2 | backend RED/GREEN·PG wrapper·ABS/leak/postcheck; `review/evidence/w1b/*` 초안 |
| F1 | 수급자 UI(목록 유지형·popup 0)·client. 선행: OpenAPI 승인 후 **승인 generator로만** `frontend/src/generated/sswcenter-api.ts` 갱신. **수동 edit 금지** |
| F2 | Vitest·Playwright real-PG·DOM ABS; **독립 temp regenerate → drift 0** (손편집 금지) |
| RO | `0001`~`0008`; staff domain/API; docs/00~06; matrix 본문; 생성 TS 수동 편집 |

소유 변경 = write 전 패킷 개정 + P0.

### 4.3 P0 승인 결정 (RED 계약)

아래는 P0가 RED 작성에 필요한 최소 범위로 승인했다. 정본 행동을 넘는 내부
구현방식은 봉인하지 않는다.

| 항목 | P0 승인 | 비고 |
|---|---|---|
| 권한 | `RECIPIENT_VIEW` / `RECIPIENT_MANAGE` | 미부여 403·ADMIN 계승; VIEW는 mutation 금지 |
| resource path | `/api/v1/recipients`, nested `guardians`, `primary-guardian-periods`, `payer-snapshots` | list/create/detail/update. 기간·snapshot 이력은 기존 W1A 관례대로 `/{id}/invalidate`, `/{id}/replacements` POST |
| 409 코드명 | `PRIMARY_GUARDIAN_PERIOD_CONFLICT`, `CURRENT_PAYER_CONFLICT` | 대표기간 겹침·현재 payer 중복의 canonical API 코드 |
| migration | 현재 Alembic single head 확인 뒤 다음 revision 1개 생성 | exact revision·파일명은 B1 생성 직후 evidence에 기록; 사전 문자열 고정 금지 |
| sex_code | DB CHECK `MALE/FEMALE/TEST`; public create/update·일반 UI `MALE/FEMALE` | `TEST`는 합성 DB/harness 전용이며 public OpenAPI enum에서 제외 |

봉인 행동: mutation=권한+CSRF+expected `row_version`; named schema;
`additionalProperties` 금지 관례; `ROW_VERSION_CONFLICT`; 422; 500에
SQL/traceback 비노출; create required=name·birth_date·sex_code only;
`recipient_no` request required 금지·response nullable; public에
`legacy_*`·payer guardian FK·payer_type·SELF·PRIMARY_GUARDIAN 금지.

## 5. DB / API / UI 행동

| 대상 | 불변 행동 |
|---|---|
| recipient | name/birth/sex NOT NULL; 연락처·주소 null; recipient_no NULL→unique·immutable; memo 출처; audit·row_version |
| legacy_mapping | source+key unique 관례; 공개 비노출; 일반 router 금지 |
| guardian | name NOT NULL; phone/address/relationship null; **birth/sex 컬럼 없음** |
| primary_period | 복합 FK; half-open range; 수급자별 유효 대표 exclusion; 0 허용; **무효화·대체 이력** |
| payer_snapshot | 행 시 name NOT NULL; 유효 payer 기간 non-overlap·이력; **FK/type 없음**; 0행 허용 |

미래 FK(file/OCR/schedule) 없음. 무효화행 exclusion 제외.

API: `/api/v1`; 권한·path·도메인 코드명=§4.3 승인. legacy **공개 API 없음** —
테이블+ABS+**합성 import**(§6.2).

UI: 목록(이름·번호 미부여·birth·sex; legacy 0); 기본 필수3·전화 분리·번호 비편집;
보호자 0+·이름 required·대표0·이력·동시2 차단; 납부 0|1·이름만·type 선택기 0·
복사 시 독립 snapshot; 이름→같은 workspace 상세·`window.open` 0·뒤로가기 문맥 복원;
W1C/W1D 전 가짜 인정/계약 요약 금지; “월간 일정 팝업” 제거.

## 6. Matrix · RED/GREEN · 필수 import

### 6.1 ID 소유

| ID | W1B | 규칙 |
|---|---|---|
| REC-01 | 전체 | 필수3·전화 분리 RT |
| REC-02 | 전체 | **ABS only ≠ full.** 테이블+**합성 import** 필수(§6.2) |
| REC-03 | 부분 | NULL·immutable·UI 미부여·create non-required. **full 발급/경쟁/rollback=W1D** → `NOT_RUN`/`DEFERRED_TO_W1D`. 부재 가드 가능·**ID PASS/SKIP 집계 금지** |
| GUA-01/02, PAY-01, ABS-01~03 | 전체 | 경계·동시성·payer 불변 |
| SIG-01 | **전량 W1D** | 부재 가드=별도 ABS만. **`W1-SIG-01` PASS/SKIP 금지** (`NOT_RUN`/`DEFERRED_TO_W1D`) |
| CMN-01~04 | 해당 | 권한/CSRF/version; 목록 문맥; 비밀/SQL; OpenAPI→TS |

### 6.2 REC-02 legacy-import micro-slice (**필수**, optional 아님)

matrix: ABS + **합성 import**. base 테이블+public absence만으로 full REC-02 /
final `W1B_PASS` 금지. 필수: 합성 fixture로 내부 mapping create/조회·
public/OA/UI 비노출·unique/무효화 관례; `legacy_recipient_key`와
`legacy_attachment_key`의 nullable·attachment-only 조합; 질병/기존 비고를
source가 구분된 recipient memo로 보존. replacement는 기존 source+legacy key를
새 active mapping으로 승계하고 원 mapping을 무효화하며, 원 key 기준 invalidate를
검증한다. staff VS6의 `rows`·`active_legacy_*_keys` 호출 관례 참고·staff 약화 금지.
내부 호출 관례는 W1A VS6와 같은 `app.domains.recipient.legacy_import`의
`prepare`·`apply`·`invalidate_mapping`·`replace_mapping`으로 고정한다.
공개 route 없음. 미완 시 **`W1B_PASS` 차단**.

### 6.3 RED (구현 전) B2+F2

제품 부재=named marker; 금지 구조 부재 분리(`RED_VALID_PENDING_PRODUCT`).
제품 diff 0. 기대값 약화 금지. 소스 전체의 문자열·substring 존재만으로 PASS하는
RED는 금지한다. 제품이 없을 때는 named missing marker로 실패하고, 제품이 생긴
뒤에는 실제 migration graph·ORM metadata·operation별 OpenAPI·API 요청·PG
catalog/transaction·생성 TS·DOM 동작을 검사해야 한다.

B2: migration 부재 marker; 기존 0001~0008 불변·single lane·다음 direct child 1개
`down_revision`; W1B direct-child까지의 offline SQL에 W1B 객체 전부를 요구하고,
fresh PG를 exact direct revision까지만 올린 catalog에서 전체 컬럼·FK·CHECK·unique·
exclusion·trigger 계약을 검증한 뒤 같은 DB를 head로 올려 descendant 호환성을
별도로 확인; 실제 metadata/domain/router; 수급자 선택 연락처·주소 컬럼 nullable;
대표기간 `(recipient_id, guardian_id)` composite FK와
다른 수급자 guardian 차단; exclusion predicate는 반드시
`invalidated_at_utc IS NULL`; 대표와 payer 모두 same-day overlap·next-day
adjacency·open-ended·역순·무효화 재사용 전 경계를 검증하고, 대표는
서로 다른 guardian·서로 다르지만 겹치는 기간의 2-connection barrier 동시
지정에서 정확히 1 success이며 실제 PG `contype='x'`·`&&`·active predicate를
catalog에서 확인; 보호자·대표 변경 뒤 payer
필드 hash·row_version 불변 및 autosync trigger 0; recipient_no nullable·unique와
`NULL→value`만 허용하는 immutable DB guard(발급/경쟁/rollback full은 W1D);
REC-01 201·미인증 401·무권한 403·ADMIN 상속·VIEW 조회 성공·VIEW mutation
403·MANAGE+CSRF+row_version·stale 409 `ROW_VERSION_CONFLICT`; guardian/primary/payer
경로의 실제 HTTP lifecycle — guardian name-only, payer name-only,
primary/payer conflict code, nested ACL·CSRF·version, invalidate/replacements action;
`[start,end+1)` same-day overlap·
next-day adjacency·open-ended·역순·무효화 경계의 실제 PG assertion;
history action request의 `expected_row_version` 필수; 강제 DB/constraint 실패의
500 `UNEXPECTED_SERVER_ERROR`; 합성 name/address/phone canary를 `NEW` 값과
강제 DB 예외 detail에 싣고 응답·formatted `exc_info`·captured log에서
SQL/trace/PII canary 비노출;
OpenAPI와
`scripts/generate-openapi-types.ps1 -Check`의 checked-in TS exact 일치;
ABS·legacy public 0; REC-02 합성 importer를 실제
호출하여 mapping create/조회·unique·무효화/대체·public 비노출; same-key
replacement 뒤 old는 original mapping ID, new는 old의 exact replacement ID로
결정적으로 조회; ERROR 0;
leak self-test(§7).
F2: 실 API/필수3 부재; 수급자 `home_phone`/`mobile_phone` 분리와 보호자 phone,
합성 browser/unit 계약에서 home/mobile submit·list/detail readback;
대표 history; payer snapshot name surface는 존재하되 payer type 선택기는 ABS;
public mock/API의 `sex_code`는 `MALE/FEMALE`만; popup 0; 이름 A→B 뒤 실제
`page.goBack()`으로 검색어·필터·정렬·페이지·스크롤·목록 row 문맥 복원;
3 viewport
browser RED. 현 RED는 제품 부재 named marker와 UI 계약을 고정하며, B1/F1 뒤
실 PG create/readback·3 viewport는 별도 focused GREEN에서 필수로 승계하고
`F2_RED.md`에 `NOT_RUN_PENDING_PRODUCT`로 명시한다. browser mock 결과를
real-PG PASS로 주장하지 않는다.

REC-03/SIG-01 full = 미실행 또는 DEFERRED; 부재 가드 ≠ 해당 ID PASS/SKIP.

### 6.4 GREEN / R1 / G1

| 게이트 | 내용 |
|---|---|
| static·API·OA | B1→B2: format/mypy; CRUD·권한·CSRF·row_version·named 오류 |
| PG | exclusion·동시 대표1; payer 불변; recipient_no immutable; **합성 import**; postcheck; restore |
| absence/leak | ABS-01~03·legacy 0·signer-token 가드(SIG ID 비집계); §7 |
| TS | B1 OpenAPI 안정화 → F1 승인 generator로 갱신; **F2 temp regen drift 0** |
| FE | Vitest+Playwright: 필수3·전화·guardian/payer; 생성→목록→상세; 대표; payer; A→B→back; popup0; 3 viewport |

**R1 필수**: half-open 경계; 동시 대표 race; payer 복사 숨은 FK; NULL recipient_no;
postcheck 누락; 문자열-only ABS false-green; migration offline; **REC-02 import 누락**.

**G1**: exact SHA 묶음; clean tree; non-PG+W1B PG; FE+drift; W1A 비파괴; leak;
backup/restore. **`PASS`=P0만.**

## 7. Leak gate (협소)

**Fail-close:** 실개인정보; 지정 비밀/민감 토큰(실 DSN 비밀·암호화 키·세션 비밀·
실 RRN 등 정본 계열); 로그·오류·trace·fixture·screenshot 평문.

**False-fail 금지:** 합성 fixture 값; 기대 API payload 필드·스키마상 합성 응답;
계약상 화면 표시 합성 필드. capture/self-test=W1A 관례. 합성만 사용.

## 8. 금지

```text
0001~0008 수정; W1A 약화; W1C/D/E/Wave2 본구현; 번호 발급·계약·signer runtime
payer_type/guardian_id/SELF/PRIMARY_GUARDIAN; 보호자 phone·관계 required; birth/sex 컬럼
공개 legacy keys; 생성 TS 수동 편집; 실 PII·운영 DB/파일; 정본 무단 수정; Git 이력 조작
D1/R1/G1 제품 write; multi-writer; RED 약화; REC-03/SIG-01 full을 W1B PASS 주장
REC-02 = 테이블+public ABS only 로 full PASS
```

## 9. 완료 · 순서

동일 exact 후보 전부 충족 시 단위 완료 후보. **최종 `W1B_PASS`=P0만.**

1. P0 패킷 승인 완료; B2·F2 RED와 R1 설계 반대검토 착수
2. B2·F2 RED + D1 RED 감사
3. B1 구현(단일 migration)+focused GREEN+**REC-02 import**
4. OpenAPI 안정 → 승인 → **generator만** TS
5. F1 UI GREEN → B2 독립 PG/ABS/복구/leak/import → F2 Vitest/PW/**temp drift**
6. D1 감사 → **R1 필수** → G1 → 증거 SHA 일치 → **P0 `W1B_PASS`**

순서: P0 → (R1 설계 병행 가능) → RED → D1 → B1 → OA/TS → F1 → 독립 GREEN →
후보 고정 → D1·R1 → G1 → P0. **RED before implementation.** MIGRATION 단일 계열.
패킷 단독 commit 허가 없음.

## 10. 반환 형식

```text
담당/업무석/작업방 ID:
패킷: review/packets/W1B_ASSIGNMENT_PACKET_v1.0.md
기준 HEAD: 6e43f1e7db1df23f4badf4e1b360c2d5a1141ee9
결과 식별자: (Git SHA 또는 파일 SHA-256 묶음)
판정: IN_PROGRESS | RED_VALID_PENDING_PRODUCT | FOCUSED_GREEN |
      APPROVE | REQUIRED_CHANGES | BLOCK | PASS | NOT_RUN | DEFERRED_TO_W1D
변경 파일 / 명령·exit / 수치·marker:
matrix ID→결과 (REC-03 full·SIG-01 full = NOT_RUN/DEFERRED_TO_W1D;
  부재 가드는 별도 행, 해당 ID PASS/SKIP 금지)
미실행 / blocker / git status --short / 다음 한 단계
```

증거: `review/evidence/w1b/RED.md`, `GREEN.md` (상태·SHA·파일·명령·수치·marker·
leak·잔여 위험). 자기 commit SHA 순환 기록 금지.

## 11. 다음 역할 · P0 결정

| 우선 | 석 | 이유 |
|---|---|---|
| 완료 | **D1 Grok** | RED 재감사 승인; D1≠G1 유지 |
| 완료 | **B1·B2·F1·F2** | 구현·보정·정적/회귀·실 PG GREEN |
| 완료 | **R1 Marco** | 제품 결함 및 F2 false-green 폐쇄 후 `R1_MARCO_CORRECTION_APPROVE` |
| 완료 | **F1 김루나** | `RecipientsPage.tsx` 당일 기간 허용·포함 종료일 overlap 보정 |
| 완료 | **F2 박루나** | real-PG spec 대표·납부자 UI 경계 회귀 봉인 |
| 완료 | **P0 cross-wave 보정** | exact metadata와 VS6 predecessor 회귀 2건 폐쇄; `26f4d246...` |
| 완료 | **G1 요셉** | `80ed49b3...` exact-SHA read-only 재검토 후 `G1_JOSEPH_CANDIDATE_SHA_APPROVE` |
| 완료 | **P0** | 확정 결함 0, 수용 hold 0으로 `P0_W1B_PASS` 판정 |
| 운영 closeout | **P0** | PASS 증거 commit·push·local/upstream/remote SHA·clean 봉인 |

### 11.1 F2 최소 RED 보정 봉인 작업지시 (완료·역사)

**담당 및 단일 writer:** 박루나 F2

**허용 write 파일:**

- `frontend/src/test/W1BRecipientsRed.test.tsx`
- `frontend/e2e/w1b-recipients-red.spec.ts`

**금지:** 제품 파일, backend, `review/evidence/w1b/*`, docs, 기타 frontend 파일,
Git stage/commit/push/history 조작, 테스트 계약·수량·범위의 확장.

**목표:** frontend finding 2를 최소 범위로 RED에 반영한다. `미부여` display leaf
(`recipient-list-recipient-no`, `recipient-detail-recipient-no`)만 검사해 sibling
control을 놓치는 false-green을 닫는다.

**정확한 최소 수정:**

1. 기존 selector 3종만 사용한다: named control
   (`input/select/textarea[name="recipient_no"]`), canonical input testid
   (`[data-testid="recipient-no-input"]`), contenteditable matcher
   (기존 `name`·`data-field`·`data-testid`·`aria-label`의 `recipient_no`/
   `recipient_no_input` 정규화 검사). E2E의 기존 3개 selector 상수와 Vitest의
   기존 contenteditable matcher를 그대로 확장 적용한다.
2. list root `recipient-list`와 detail workspace root `recipient-detail-workspace`
   각각에서 위 3종의 count가 모두 0인지 검사한다. display leaf 하위 범위로
   축소하지 않는다.
3. 기존 create POST의 `recipient_no` key 완전 부재와 exact `미부여` display 검사를
   유지한다. 새 테스트·selector·계약은 추가하지 않는다.

**필수 검증 및 반환 수치:**

- Vitest 기존 8건: 현 RED 기준 `8/8 RED`, skip 0, config/env error 0.
- Playwright 기존 21건: 3 viewports에서 현 RED 기준 `21/21 RED`, skip 0,
  config/env error 0.
- 허용된 두 파일 대상 diff check 결과와 exit code를 반환한다.
- 제품 diff 0을 확인하고, 변경 파일·명령/exit·수치·marker·BLOCKER를 반환한다.

**완료 결과:** Vitest 8/8 intended RED·0 pass/skip·첫 marker
`W1B_F2_API_RECIPIENT_LIST_MISSING`; Playwright 21/21 intended RED·3 viewports 각
7·0 pass/skip·config/env error 0·첫 marker
`W1B_F2_API_RECIPIENT_LIST_MISSING_REAL_BROWSER_REQUEST`; TypeScript exit 0·허용
파일 diff check 0·tracked 제품 diff 0·stage/commit/push 없음.

**P0 결정**

1. §4.3 계약을 RED 기준으로 승인한다.
2. migration exact revision·파일명은 B1 생성 직후 evidence 기록으로 승인한다.
3. 최초 `P0_PACKET_APPROVED / RED_AUTHORIZED`로 B2·F2와 R1 착수를 허가했다.
   Opus 한도 거절 뒤 동일 검토 사슬은 Grok에게 인계되었고, Grok RED 재감사,
   B1/B2/F1/F2 구현·보정, 독립 실 PG GREEN을 완료했다. Marco R1의 제품 보정
   요구와 후속 F2 false-green 1건도 전체 실 PG 재실행 뒤
   `R1_MARCO_CORRECTION_APPROVE`로 폐쇄했다. 현재 상태는
   `R1_MARCO_CORRECTION_APPROVE` 뒤 제품 exact-SHA G1의 제품·PG GREEN과
   cross-wave 회귀 `REQUIRED_CHANGES`를 거쳤다. 해당 2건을 최소 보정하고
   evidence candidate `80ed49b3...`를 exact-SHA 재검토한 결과
   `G1_JOSEPH_CANDIDATE_SHA_APPROVE`이며, P0 최종 판정은 `P0_W1B_PASS`다.
4. G1 dispatch 시 요셉 가용성을 확인하고, 이미 작업 중이면 Regina를 Sol Max로
   호출한다. 진행 중 임무는 한도 해제만으로 회수하지 않는다.

```text
D1 설계 서명: Grok · D1_PACKET_REVISED / P0_ACCEPTED
D1 RED 재감사: Opus 한도 거절 뒤 Grok 인계 · 승인 완료
B1/B2/F1/F2 상태: 구현·보정·정적/회귀·실 PG GREEN 완료
실 PG 최종 재현: E2E 3/3 · skip/error 0 · leak 275 · listener/artifact/temp 0
R1 상태: Marco `R1_MARCO_CORRECTION_APPROVE` · current/sealed hash 10/10 · staged 0
G1 pre-commit 상태: 요셉 `G1_JOSEPH_REQUIRED_CHANGES` · 포함 종료일 UI 계약 불일치 폐쇄
G1 exact 제품 commit 상태: `G1_JOSEPH_REQUIRED_CHANGES` · cross-wave 테스트 2건·GREEN evidence 부재
G1 최종 상태: 요셉 `G1_JOSEPH_CANDIDATE_SHA_APPROVE` · exact 후보 80ed49b3 · 확정 결함 0
F1 상태: 김루나 `F1_INCLUSIVE_END_CORRECTION_PASS` · 제품 한 파일 보정·비PG 회귀 GREEN
F2 상태: 박루나 `F2_INCLUSIVE_END_REGRESSION_PASS` · real-PG spec 한 파일 경계 회귀 봉인
P0 cross-wave 보정: commit 26f4d246 · targeted 6/6 · non-PG 122/7 · 계약 약화 0
P0 exact 재검증: static/frontend GREEN · real-PG 3/3 · leak 275 · cleanup 0
현 증거: GREEN.md 추가 · RED/F2_RED는 구현 전 역사 증거로 보존
현재 위치: P0 최종 수용 판정 완료
수용 hold: 0
P0 판정: P0_W1B_PASS
다음: PASS 증거 commit → push → local/upstream/remote SHA·primary clean 봉인
```
