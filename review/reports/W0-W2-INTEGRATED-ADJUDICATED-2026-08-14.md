# SSWCenter 3.0 W0~W2 통합 재판정 보고서

> 재판정일: 2026-08-14 KST
> 판정 대상: 형님이 제공한 Grok Build Plan Mode 통합 정적검수 1개와 `review/reports/W0-*`~`W2-*` 단위 보고서 20개
> 저장소: repository root (이 보고서의 저장소 상대 범위)
> 기준 branch/HEAD: `main` / `b1cd055ea92ad5cf9558009e2a270147acf17d6f`
> 판정 지위: current-byte 기술 재판정. 구현 승인·W1F PASS·Wave 승격·release acceptance가 아니다.

## U-10 계보와 현재 상태

현재 main과 Git object를 직접 대조한 U-10 계보는 다음과 같다.

```text
db8b5ca (역사적 unsealed WIP)
→ 65afdaf (독립 후보)
→ 9147ed9 (PR #1 병합)
→ b1cd055 (current main)
```

`65afdaf`의 U-10 후보는 `9147ed9` PR #1 merge commit으로 병합되어 현재 main에
반영되어 있다. 따라서 U-10의 현재 저장소 상태는 `SATISFIED_BY_PR_1`이다. 다만 PR #1
병합은 W0 전체 acceptance, W1F PASS, Wave 승격 또는 release approval을 뜻하지 않는다.
live acceptance와 release approval은 별도 동일-SHA 실행·독립검수·운영 증거가 필요하다.
이 두 문서의 교정은 W2B packet, operations 7문서, W0~W2 단위보고서 20개의 수정·재승인·
재봉인을 포함하지 않으며, W2B 보류 판정은 그대로 유지한다.

U-01은 `c5cecd2` PR #2 commit으로 current main에 병합되어 현재 저장소 상태가
`SATISFIED_BY_PR_2`다. 이 병합도 W0 전체 acceptance, W1F PASS, Wave 승격 또는 release
approval을 뜻하지 않는다.

## 기술 요약 — 전체 FAIL은 유지하되 실행목록은 교정해야 한다

Grok 보고서의 전체 결론인 **`FAIL / NOT_READY_FOR_ACCEPTANCE`는 유지**한다. 다만 원문의
24개 통합 이슈를 그대로 구현 백로그로 쓰면 안 된다. 현재 바이트와 Git 역사를 다시
대조한 결과, 16개는 현재 결함으로 확인됐지만 `U-16`은 주장된 형태로 기각되고,
`U-18`은 계약결정으로 내려가며, `U-22`는 정본 개정 문제가 아니라 저장소 내부
W1F PASS 증거가 없는 상태로 재분류된다.

현재 분포는 다음과 같다.

| 분류 | 수 | 의미 |
|---|---:|---|
| `CURRENT_CONFIRMED` | 16 | 현재 소스·정본의 직접 불일치 또는 제품 공백 |
| `SATISFIED_BY_PR_2` | 1 | U-01 PIN 정본 수정이 PR #2로 current main에 병합됨; live acceptance/release approval은 아님 |
| `SATISFIED_BY_PR_1` | 1 | U-10 후보가 PR #1로 current main에 병합됨; live acceptance/release approval은 아님 |
| `CONTRACT_DECISION` | 2 | U-07, U-18은 구현 전에 형님 결정 필요 |
| `REJECTED_AS_WRITTEN` | 1 | U-16 원문 처방은 근거가 뒤집힘 |
| `BLOCKED_EVIDENCE_GAP` | 1 | U-22의 pre-W2 W1F PASS를 현재 저장소에서 입증하지 못함 |
| `OPERATIONAL_UNVERIFIED` | 1 | U-23은 제품 결함이 아니라 현재 후보의 live 증거 공백 |
| `PARTIAL_CONFIRMED` | 1 | U-24 일부는 확인됐지만 백업 위치 주장은 별도 결정사항 |

따라서 첫 구현은 W2 업무기능이 아니라 다음 순서의 기반 복구여야 한다.

```text
U-10 Wave 0 postcheck 후보 봉인
→ U-09 current-head postcheck dispatcher와 개발 init 연결
→ U-08 exact 0025 공식 backup/restore
```

이 순서를 고정하는 실행 문서는
[`review/packets/FOUNDATION-0025-IMPLEMENTATION-PACKET-v1.0.md`](../packets/FOUNDATION-0025-IMPLEMENTATION-PACKET-v1.0.md)다.

## 판정 기준 — 현재 바이트와 실행 증거를 분리했다

- `CURRENT_CONFIRMED`: 현재 working tree의 코드와 정본만으로 경로가 직접 성립한다.
- `SATISFIED_BY_PR_2`: U-01 정확히 6자리 정본 수정 commit `c5cecd2`가 current main에 병합된 상태다. 이는 W0 전체 acceptance·W1F PASS·release approval이 아니다.
- `WIP_UNSEALED`: 보정 바이트가 있으나 현재 HEAD의 승인 증거로 사용할 수 없는 별도 역사적 상태다. 현재 U-10에는 적용하지 않는다.
- `CONTRACT_DECISION`: 어느 구현이 맞는지 현재 정본만으로 하나로 결정할 수 없다.
- `REJECTED_AS_WRITTEN`: 원문의 원인 또는 최소조치가 현재 코드와 맞지 않는다.
- `BLOCKED_EVIDENCE_GAP`: 사실 여부를 판정할 저장소 내부 exact-SHA 증거가 없다.
- `OPERATIONAL_UNVERIFIED`: 제품 소스 결함이 아니라 현재 후보의 실행 증거가 없다.

이 보고서는 dirty working tree를 읽었다. 시작 확인 당시 `main`은 77개 변경을 가지고
있었으며, 이 중 PIN 정본 1개는 이번 재판정 과정에서 수정됐다. 따라서 HEAD만을 기준으로
한 봉인 보고서가 아니며, 아래 `RESOLVED`는 acceptance가 아니다.

## 원문에서 반드시 고쳐야 하는 판정

| 항목 | Grok 원문 | 재판정 |
|---|---|---|
| U-01 | 6자리 이상 구현으로 갈 수 있는 계약결정 | 접두어 자동제출 충돌을 피하기 위해 **정확히 6자리**로 정본을 수정했고, `c5cecd2` PR #2로 current main에 병합됐다. `SATISFIED_BY_PR_2`; 이는 W0 전체 acceptance/release approval이 아니다. |
| U-10 | 기술적으로 고쳐진 항목 | `db8b5ca`의 역사적 unsealed WIP에서 `65afdaf` 독립 후보를 거쳐 PR #1 (`9147ed9`)로 current main (`b1cd055`)에 병합됐다. `SATISFIED_BY_PR_1`; 이는 W0 전체 acceptance/release approval이 아니다. |
| U-12/U-13 | 구현 또는 정본 후퇴를 동등 선택지로 취급 | 현 정본은 두 배정 화면을 W1E 필수로 확정했다. 범위를 후퇴시킬 때만 형님 결정이 필요하다. |
| U-16 | 현재 통보일 대신 그 이전 통보일을 써야 함 | 최신 유효 통보가 곧 지난 유효 통보다. 계산식 결함 주장은 기각하고, bridge가 최신 행만 받는지 U-17 안에서 재현한다. |
| U-18 | same-contract trigger가 확정 최소조치 | 승인계획은 부모 계약과 계획서의 동시 정정을 허용한다. same-recipient와 same-contract를 분리한 계약결정이 먼저다. |
| U-22 | W1F 역사봉인 또는 0025 재봉인 중 즉시 결정 | 먼저 pre-W2 W1F PASS가 있었는지 증명해야 한다. 현재 저장소에서는 찾지 못했으므로 `BLOCKED_EVIDENCE_GAP`이다. |
| U-24 | OpenAPI·lock·백업 위치 모두 현재 결함 | OpenAPI gate와 dependency lock은 확인됐다. 실제 백업 위치·세대수·책임자는 정본상 아직 결정사항이다. |

추가로 W1 보고서에 남은 `0026`/`0027`/`0028` head 주장은 **역사적 원문의
`KNOWN_FALSE_CLAIM`**으로 격리한다. 현재 main의 실제 Alembic head는
`20260813_0025_w1_relationship_lock_contract_correction`이며 current migration
디렉터리에는 0026~0028 Python migration이 없다. 이 claim은 역사적 원문 provenance로만
남기고 현재 사실로 취급하지 않으며 retarget 근거로 사용하지 않는다. W2-02~W2-05는 파일명과 달리 provider 본문이 없는
Codex-only 결과이므로, 현 바이트로 다시 확인된 항목만 채택했다.

## 24개 이슈 최종 재판정

| ID | Wave / 심각도 | 최종 상태 | 현재 근거와 정확한 조치 |
|---|---|---|---|
| U-01 | W0 / P1 | `SATISFIED_BY_PR_2` | `docs/05_기술_보안_파일처리_아키텍처_v1.5.md:231`을 숫자 정확히 6자리로 수정한 바이트가 `c5cecd2` PR #2로 current main에 병합됐다. `security.py:11-16`, `api.ts:44-54`, `LoginForm.tsx:14,143-148,241`와 일치한다. 이는 W0 전체 acceptance/release approval이 아니며 live acceptance는 별도 검증 대상이다. |
| U-02 | W0 / P1 | `CURRENT_CONFIRMED` | `/api/auth/**` validation이 기본 handler로 흘러 PIN 입력을 422에 재노출할 수 있다. `backend/app/api/w1a_errors.py:104-110`. 인증 전용 422에서 `input`을 제거하고 mutation test를 둔다. |
| U-03 | W0 / P1 | `CURRENT_CONFIRMED` | 로그인 오류가 화면에 소비되지 않고 bootstrap 401 뒤 loading 종료가 generation guard에 막힐 수 있다. `LoginForm.tsx:117-140`, `AuthProvider.tsx:75-105`, `api.ts:180-224`. 401/423/429와 bootstrap 401 상태전이를 시험한다. |
| U-04 | W0 / P1 | `CURRENT_CONFIRMED` | 로그 cap 정리가 같은 디렉터리의 다른 종류 활성 로그까지 대상으로 삼는다. `backend/app/core/logging.py:122-145,161-178`. handler 종류별 prefix 경계와 교차삭제 거부시험이 필요하다. |
| U-05 | W0 / P1 | `CURRENT_CONFIRMED` | readiness는 DB 접속과 `erp` schema만 확인한다. `backend/app/api/health.py:19-33`, `backend/app/db/session.py:38-53`. migration·필수경로 실패 시 503과 write 거부를 같이 봉인한다. |
| U-06 | W0 / P2 | `CURRENT_CONFIRMED` | `PIN 123456` 같은 공백 구분 표현이 redaction 정규식 밖에 남는다. `backend/app/core/logging.py:43-57`. 공백·화살표·구분자 mutation probe가 필요하다. |
| U-07 | W0 / P1 후보 | `CONTRACT_DECISION` | 정본은 감사 보존을 요구하지만 DB trigger를 직접 강제하지 않고, `infra/postgres/grant-application-access.sql:5-13`은 UPDATE/DELETE를 회수한다. trigger 의무화 여부를 먼저 결정하고 실 role 권한을 별도로 검증한다. |
| U-08 | W0/W1/W2 / P1 | `CURRENT_CONFIRMED` | `scripts/restore-drill.ps1:56-77`은 0019까지만 허용해 0025 manifest를 거부한다. exact 0025만 current postcheck와 연결하고, 0020~0024를 verifier 없이 일괄 허용하지 않는다. |
| U-09 | W1 / P1 | `CURRENT_CONFIRMED` | `init_development.py:12,99-102`는 `upgrade head` 뒤 0025를 받지 않는 역사 postcheck를 호출한다. exact revision dispatcher를 먼저 만들고 init이 이를 사용해야 한다. |
| U-10 | W0 / P1 | `SATISFIED_BY_PR_1` | catalog shape 보정 후보는 `65afdaf` 독립 후보로 확인되고 PR #1 (`9147ed9`)을 통해 current main (`b1cd055`)에 병합됐다. 이는 W0 전체 acceptance/release approval이 아니며 live acceptance는 별도 검증 대상이다. |
| U-11 | W1 / P1 | `CURRENT_CONFIRMED` | 두 개발·합성 seed가 제거된 `GradePeriodCreateRequest`, `home_phone`, 날짜형 benefit, 금지 signer 필드를 사용한다. 영향은 개발·합성 seed entrypoint 파손이며, restore가 이 seed를 호출한다는 원문 주장은 채택하지 않는다. |
| U-12 | W1 / P1 | `CURRENT_CONFIRMED` | `care_assignment` DB 원장은 있지만 API/domain/UI가 없다. 정본 `docs/03_UI_API_상호작용_계약_v1.2.md:350-356`과 로드맵 W1E에 대한 구현 공백이다. 정본대로 제품 입출력을 만들거나 형님 승인으로 범위를 개정해야 한다. |
| U-13 | W1 / P1 | `CURRENT_CONFIRMED` | 월 전문직 담당 backend API는 `backend/app/api/w2.py:74-132`에 있으나 generated 파일 밖 frontend client/UI 검색 결과가 없다. `docs/03:358-367`, `docs/06:57`의 **W1E 선행 blocker**다. |
| U-14 | W1 / P2 | `CURRENT_CONFIRMED` | FAMILY인데 `family_relationship_text=NULL`이 가능하고 기존 test도 nullable을 기대한다. `0012:62-103`, `models.py:1795-1822`, `test_w1e_contract.py:876-883`. forward migration·ORM·mutation PG test가 필요하다. |
| U-15 | W1 / P1 | `CURRENT_CONFIRMED` | DB/ORM은 recipient sex `TEST`를 허용하지만 API enum은 MALE/FEMALE뿐이고 응답 조립이 직접 cast한다. `recipient/schemas.py:15-17`, `recipient/service.py:211-220`. 직원과 같은 read sentinel 계약으로 맞춘다. |
| U-16 | W2 / P1 후보 | `REJECTED_AS_WRITTEN` | `notice.notification_date+6개월`은 그 notice가 최신 유효 통보라면 정본과 일치한다. Dashboard도 날짜·ID 내림차순 첫 행을 쓴다. 실제 미확인은 `record_service_plan_notice_card_source()`가 임의의 active `notice_id`를 받을 수 있다는 점이며 U-17 다이력 시험에 통합한다. |
| U-17 | W2 / P1 | `CURRENT_CONFIRMED` | 인정·계약 만료는 constructor만 있고 계획서통보 bridge도 production 호출처가 없다. `w2/policies.py:62-108`, `w2/service.py:835-891`. U-13 뒤 담당자 선택을 확정하고 세 원천·우선순위를 같은 transaction으로 연결한다. |
| U-18 | W2 / P2 후보 | `CONTRACT_DECISION` | replacement는 단순 self-FK지만 승인계획은 부모 계약과 계획서의 동시 정정을 허용한다. `0024:68-74`, `W2_SERVICE_PLAN_NOTICE_PLAN.md:39-42`. same-recipient DB 방어와 same-contract 강제를 분리해 결정한다. |
| U-19 | W2 / P2 | `CURRENT_CONFIRMED` | generated OpenAPI에는 `finalized_at_utc`가 있지만 `w2Api.ts:82-87,299-306`이 버린다. 즉시 데이터 손실이 아니라 frontend projection·생성타입 소비 결함이다. |
| U-20 | W2 / P2 | `CURRENT_CONFIRMED` | 월 전환 fetch 중 이전 snapshot이 남고 mutation 버튼은 `loading`을 보지 않는다. `ScheduleLedger.tsx:145-164,346-349`. loading 중 mutation 차단과 month/request-generation 결속 시험이 필요하다. |
| U-21 | W0/W1 / P2 | `CURRENT_CONFIRMED` | W0 smoke는 현재 없는 selector를 기다리고 W1B 역사 red test는 제거된 `home_phone` 계약을 쓴다. 현재 smoke와 역사 drift를 한 결함처럼 고치지 말고 분리한다. |
| U-22 | W1→W2 / P1 governance | `BLOCKED_EVIDENCE_GAP` | 저장소 최초 commit부터 0018이 존재하고, W1F 원장은 runtime GREEN 뒤 independent REJECT와 후속 미완료를 기록한다. pre-W2 W1F PASS commit은 현재 refs/object DB에서 찾지 못했다. 정본을 고치지 말고 외부 옛 계보 증거를 회수하거나 현재 후보에서 다시 봉인한다. |
| U-23 | W0/W2 / P1 운영 | `OPERATIONAL_UNVERIFIED` | W0의 CONFIG_DRIFT와 후속 W2-F READY는 다른 시점이다. W2-F도 `LINUX_ACTIVE` 미등록으로 Ubuntu PostgreSQL 16을 실행하지 않았다. 최종 동일 SHA에서만 다시 측정한다. |
| U-24 | W0 / P2 | `PARTIAL_CONFIRMED` | 일반 test/build에 OpenAPI drift가 연결되지 않았고 backend transitive dependency lock이 없다. 다만 실제 백업 경로·세대수·책임자는 `docs/05:437`이 06 결정으로 남겼으므로 별도 계약결정이다. |

## U-22는 정본 개정이 아니라 증거 회수 문제다

현재 저장소에서 확인되는 W1F 계보는 다음과 같다.

1. 최초 commit `48f6727615d51a2289f7739e4bbf3cbb0834ed03`부터 W1F 0017 도구와 W2 0018이 함께 존재한다.
2. `review/environment/office/2026-08-01_W1F.md:613-632`는 exact SHA
   `5e8b5bf...`의 전체 runtime GREEN 뒤 독립검수 `REJECT`를 기록한다.
3. 같은 원장 `634-656`은 보정 후 새 clean commit·전체 재실행·독립 재검수가 남았다고 명시한다.
4. 마지막 `W1F-030`도 non-live repair이며 full W1F PASS를 선언하지 않는다.
5. W2 0023/0024는 `db8b5ca...`에서 도입됐지만, 현재 object DB에는 위 역사 후보 commit이나 별도 pre-W2 W1F PASS commit이 없다.

따라서 `W1F PASS가 실제로 없었다`고 역사 전체를 단정하지는 않는다. 정확한 판정은
**현재 저장소 내부에서 승인 계보를 입증할 수 없으므로 W2 승격 근거가 BLOCKED**라는 것이다.
옛 저장소에서 exact commit, 원격 ref, runtime transcript와 독립 PASS 원문을 회수하면
다시 판정한다.

## 교정된 처리 순서

```text
0. U-01 PR #2 병합 바이트의 current-main 반영을 확인하고 U-07/U-18/U-17 담당자 계약을 결정
1. U-10 PR #1 병합 후보의 current-main 반영 확인
2. U-09 current-head dispatcher와 development init
3. U-08 exact 0025 backup→restore
4. U-05 readiness/write gate
5. U-02/U-03/U-04/U-06 인증·로그 안전
6. U-12/U-14/U-15/U-13 W1E 제품 공백
7. U-11 seed를 최종 W1 schema에 맞춤
8. U-17과 교정된 U-16 최신행 검증, U-19/U-20 병렬, U-18 결정 반영
9. U-21/U-24 release gate 정비
10. 한 후보 SHA 고정 뒤 U-23 Ubuntu·PostgreSQL·복구·브라우저와 최종 독립검수
```

W1E의 U-12/U-13이 열려 있으므로 FOUNDATION-0025 PASS를 W1F PASS로 부르면 안 된다.
FOUNDATION-0025는 이후 제품 수정을 검증할 수 있도록 current-head init/restore 기반만
정상화한다.

## 재검증 등급과 종료 증거

| 묶음 | 테스트 등급 | 검수 등급 | 필수 종료 증거 |
|---|---:|---:|---|
| U-10 | 3 | 4 | catalog mutation이 실패하고 격리 PG current invariant가 통과 |
| U-09 | 3 | 4 | fresh base→0025, dispatcher exact marker, unknown future fail-close |
| U-08 | 5 | 5 | exact 0025 dump→새 DB/data root restore, full-row·파일 hash 일치, cleanup 0 |
| U-02~U-06 | 2~4 | 4 | 422 비밀 부재, 상태전이, 교차로그 보존, 503+write 거부 |
| U-12~U-15 | 3~5 | 5 | W1E API·UI·PG·E2E와 sentinel/FAMILY mutation |
| U-17~U-20 | 3~4 | 4 | 세 원천 발생·우선순위·최신행·adapter parity·월전환 race |
| 최종 후보 | 5 | 5 | 동일 SHA, clean worktree, Ubuntu/PG/복구/브라우저, 독립 read-only acceptance |

## 방법과 한계

이번 재판정은 다음 근거를 사용했다.

- 정본 00~06과 운영 등급 정의
- 20개 W0~W2 단위 보고서와 Grok 통합 원문 1개
- 현재 migration/ORM/API/domain/frontend/test/harness 바이트
- `git log`, `git show`, refs와 object 존재 여부를 이용한 W1F/W2 계보 확인
- 세 범위의 독립 current-byte 재판정 후 본 문서에서 중복 제거

제품 test, 실제 PostgreSQL, browser, Ubuntu foundation, backup/restore는 이번 문서 작성
중 실행하지 않았다. 따라서 정적 경로가 확인된 항목도 runtime 재현 전에는 release
acceptance가 아니다. 현재 working tree는 dirty이므로 파일 수와 상태는 다음 후보에서
다시 측정해야 한다.

## 아직 형님 결정이 필요한 질문

1. U-07: 감사 불변성을 application-role grant로 충분히 볼지, DB trigger까지 강제할지.
2. U-17: 공식 업무카드의 담당자를 어느 날짜의 월 전문직 담당으로 정할지.
3. U-18: replacement를 같은 수급자까지만 허용할지, 같은 계약까지 강제할지.
4. U-24: 실제 백업 매체 경로·세대수·암호키 및 복원훈련 책임자를 어떻게 정할지.
5. U-22: 옛 2.1/2.2 exact W1F PASS 증거를 회수할 수 있는지. 회수하지 못하면 현재
   완성된 W1 범위를 기준으로 새 W1F를 수행해야 한다.

이 보고서가 승인하는 다음 작업은 FOUNDATION-0025 패킷 작성과 그 패킷에 따른 별도
worktree 구현 준비까지다. 제품 구현, Git 통합, Wave 승격은 별도 승인 대상이다.
