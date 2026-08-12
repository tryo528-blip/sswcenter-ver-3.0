# Wave 1 Clean 최종 조율 exact-SHA 독립검수

> 검수일: 2026-07-26 KST
> 검수자: Marco independent review
> 판정: **PASS**
> 검수대상 SHA: `e52db047a2324171b4d3e8c5d57b69e67a48206b`
> 직접 부모 SHA: `a9363ac01ba7b9852b2418fe71c2b862f59d0098`
> Clean rebuild 기준 SHA: `6938573189fc7aede8a95f09934c3228e3745ebe`
> 검수 branch: `rebuild/wave1-clean`
> 검수 방식: 별도 detached worktree의 exact commit read-only 검수

## 1. 검수 범위와 판정 한계

이번 검수는 사용자의 최신 실행경계에 따라 현재 저장소의 **정본·검수통제
봉인**만 판정한다. 실제 Wave 시작, W1A branch/base 확정, 제품 테스트와 제품
구현은 새 2.1 프로젝트에서 수행한다.

다음을 exact SHA에서 전체 재독했다.

- `docs/AI_작업_운영_원칙_v1.3.md`
- `.agents/skills/ssw-independent-review/SKILL.md`
- `docs/00_정본_문서_목록.md`와 나머지 정본 8개
- 루트 `README.md`
- `review/REVIEW_SCOPE.md`
- `review/WAVE1_CLEAN_TEST_MATRIX.md`
- `review/WAVE1_CLEAN_FINAL_COORDINATION_CROSSWALK.md`
- 변경구간 `a9363ac01ba7b9852b2418fe71c2b862f59d0098..e52db047a2324171b4d3e8c5d57b69e67a48206b` 전체 diff

제품 runtime, PostgreSQL, API/OpenAPI 생성, frontend DOM/E2E, backup/restore는
실행하지 않았다. 운영 DB·운영 파일·실 개인정보에 접근하지 않았고 외부 AI
CLI도 실행하지 않았다. 따라서 이 PASS는 제품 구현 PASS나 Wave 1 완료 판정이
아니다.

## 2. 최종 판정

**PASS**

검수대상 exact commit에서 사용자 최신 14개 방향 결정과 7개 기술보정이 정본,
crosswalk와 현재 문서봉인 gate에 완결되게 반영돼 있다. 정본 간 직접 충돌,
미반영 결정, 깨진 활성 참조, 미래 file/import/OCR 의존의 신규 제품 반영,
제품변경 혼입 또는 재현 가능한 문서 결함을 발견하지 못했다.

- FAIL finding: 0건
- BLOCKED 항목: 0건
- 별도 `review/findings/` 파일: 생성하지 않음

## 3. Git exact-SHA·원격·변경범위 증거

검수용 detached worktree:

```text
C:\Users\USER\Documents\sswcenter-wave1-marco-final-e52db04
```

주요 재현 명령과 결과:

| 검사 | 명령 | 결과 |
|---|---|---|
| exact HEAD | `git rev-parse HEAD` | `e52db047a2324171b4d3e8c5d57b69e67a48206b` |
| 직접 부모 | `git rev-parse HEAD^` | `a9363ac01ba7b9852b2418fe71c2b862f59d0098` |
| rebuild ancestry | `git merge-base --is-ancestor 6938573189fc7aede8a95f09934c3228e3745ebe e52db047...` | exit 0 |
| prior review ancestry | `git merge-base --is-ancestor a9363ac... e52db047...` | exit 0 |
| local branch ref | `git rev-parse refs/heads/rebuild/wave1-clean` | `e52db047...` |
| remote-tracking ref | `git rev-parse refs/remotes/origin/rebuild/wave1-clean` | `e52db047...` |
| live remote readback | `git ls-remote --exit-code origin refs/heads/rebuild/wave1-clean` | `e52db047...`, exit 0 |
| primary 시작상태 | `git status --porcelain=v2 --branch` | clean, upstream `+0 -0` |
| detached 상태 | `git status --porcelain=v2 --branch` | detached exact SHA, clean |
| diff whitespace | `git diff --check a9363ac..e52db047` | exit 0 |

`a9363ac..e52db047` 변경은 9개 파일, 455 insertions, 175 deletions이다.
변경경로는 `docs/**` 7개와 `review/**` 2개뿐이며 `docs/06`은 Git이
`R059` rename으로 인식했다.

```text
docs/00_정본_문서_목록.md
docs/01_새_프로젝트_목적_및_추진_방향_v1.4.md
docs/02_새프로젝트_기능요구사항_정리본_v1.0.md
docs/04_DB_업무구조_최종설계_v4.7_PostgreSQL.md
docs/05_기술아키텍처_및_개발기준_v1.4.md
docs/06_파일처리_영역_경계와_확정사항.md
docs/07_개발로드맵_및_결정현황_v1.0.md
review/WAVE1_CLEAN_FINAL_COORDINATION_CROSSWALK.md
review/WAVE1_CLEAN_TEST_MATRIX.md
```

`6938573189fc7aede8a95f09934c3228e3745ebe..e52db047...`에서
`backend`, `frontend`, `infra`, `scripts`와 루트 실행설정 파일의 diff는 각각
0건이다. 즉 이번 정본·검수통제 계보에 제품 code, migration, frontend,
infra 또는 제품 script 변경이 없다.

## 4. 최신 결정 반영 검증

### 4.1 14개 방향과 7개 기술보정

crosswalk 기계검사 결과:

| 집합 | 기대 | 결과 |
|---|---:|---:|
| `FC-01..FC-14` | 14개, 중복 없음, 연속 | 14개 PASS |
| `TC-01..TC-07` | 7개, 중복 없음, 연속 | 7개 PASS |
| `LC-01..LC-06` | 6개, 중복 없음, 연속 | 6개 PASS |
| crosswalk가 참조한 gate ID | 모두 matrix에 존재 | 13개 모두 존재 |

crosswalk는 스스로 비정본 review 추적증거이며 별도 SHA manifest가 아니라고
명시한다. 각 결정 본문은 영역별 정본이 소유한다.

### 4.2 `06` rename·성숙도·소유경계

- old path
  `docs/06_파일함_OCR_입출력_상세설계_v1.1.md`에서
  `docs/06_파일처리_영역_경계와_확정사항.md`로 실제 rename됐다.
- `06`은 구현 상세정본이나 상세 DDL/API 명세가 아니라고 명시한다.
- 파일함과 입출력은 `PARTIAL_DESIGN`, OCR은 `CONCEPT_ONLY`, 파일처리 상세
  DDL은 `DEFERRED`다.
- 위 성숙도는 `07`의 `CONFIRMED`, `DESIGN_REQUIRED`,
  `SAMPLE_REQUIRED`, `USER_DECISION_REQUIRED`와 분리돼 있다.

### 4.3 `04` 실행 권위와 교차웨이브 의미

`04` §0은 실행 권위를 다음처럼 분리한다.

- Wave 0: 적용 migration과 실제 PostgreSQL catalog
- Wave 1: 실행 가능한 상세 DDL
- Wave 2: 확정 업무계약·교차웨이브 인터페이스·금지사항
- Wave 3~5: 책임·의존방향·보존원칙·금지사항

Wave 2 이후의 실제 테이블·컬럼·FK·revision 구조는 현재 봉인하지 않는다.

`02` §10, `04` §11과 matrix §9에서 추출한 13개 업무개념의
`IDENTITY`·`PERIOD_FACT`·`CURRENT_PROJECTION` 분류는 13개 모두 일치했다.
`01` §5는 네 분류의 공통 의미를 정의하고, `REVISION`은 실제 승인된 영역에서만
사용한다고 제한한다. 정정 뒤 지속·무효화·대체와 후속 참조대상도 각 표에
기록돼 있다.

### 4.4 content·receipt·import·filebox·OCR

`05`와 `06`은 다음 경계를 일관되게 고정한다.

- 불변 물리 content와 source receipt는 다른 identity다.
- 같은 bytes를 재사용할 수 있지만 재접수는 별도 접수 사실일 수 있고,
  hash만으로 접수 동일성을 판정하지 않는다.
- import는 일반 filebox document/version을 필수 요구하지 않는다.
- filebox 삭제·휴지통은 import 감사근거를 cascade 삭제하지 않는다.
- import 감사원본과 OCR 근거는 일반 공유파일 ACL을 자동 상속하거나 일반
  사용자에게 자동 공개되지 않는다.
- 실제 보존기간은 `W5-06`, 역할별 열람권한은 `W5-09`의
  `USER_DECISION_REQUIRED`로 분리돼 있다.
- 업무대상 연결은 대상별 typed FK를 우선하고, 대형 nullable link와 FK 없는
  `target_type + target_id`는 승인하지 않는다.

OCR 적용은 typed application/domain command만 사용한다. 직접 SQL,
service/repository 우회 commit과 애플리케이션 HTTP 자기호출은 금지된다.
원자성 단위는 OCR run 전체가 아니라 사용자가 승인한 적용묶음이며, 실행
멱등성과 적용 멱등성을 분리한다. 권한·CSRF 경계·후보 version·대상
`row_version`·적용 멱등키를 재검증하고 업무변경과 감사를 같은 짧은
transaction에 기록하며 실패·stale·중복 불일치 때 변경은 0건이다. 실제
route, run/apply table, `batch_id` 모양은 현재 봉인하지 않는다.

### 4.5 미래 의존 부재와 Wave 0 예외

`04`, `06`과 matrix는 문자열 존재만이 아니라 catalog/FK graph,
nullability, ORM/migration, service/repository/worker, OpenAPI, 생성
TypeScript와 UI의 **새 dependency 의미**를 검사하도록 일치한다.

기존 Wave 0의 `access_event.generated_document_id`는 migration과
SQLAlchemy model에서 nullable `BigInteger` scalar이고 해당 document FK가 없다.
정본은 이 기존 non-FK 감사 placeholder를 이름만으로 FAIL 처리하지 않으며,
새 file/import/OCR 테이블·FK·필수 업무의존을 추가했는지 판정하도록 명시한다.
rebuild 기준부터 검수 SHA까지 제품 경로 diff가 0건이므로 이번 조율에서 새
미래 의존이 추가되지 않았다.

### 4.6 결정 register와 2.1 인계

`07` register는 다음 상태를 정확히 분리한다.

| ID | 상태 |
|---|---|
| `W3-C06` | `CONFIRMED` |
| `W3-07` | `DESIGN_REQUIRED` |
| `W5-06` | `USER_DECISION_REQUIRED` |
| `W5-09` | `USER_DECISION_REQUIRED` |
| `W5-01` | `SAMPLE_REQUIRED` |
| `W5-02` | `DESIGN_REQUIRED/SAMPLE_REQUIRED` |

`00`, `01`, `05`, `07`, crosswalk와 matrix는 현재 저장소가 정본 봉인,
review-only 결과 commit, 원격 readback과 2.1 인계에서 끝난다고 일치한다.
현재 저장소에서 W1A branch나 제품변경을 만들지 않는다.

## 5. topology·참조·문서 무결성

정적 검사 결과:

| 검사 | 결과 |
|---|---|
| `git ls-tree -r --name-only HEAD -- docs` | 정확히 9개 |
| `06` 활성 파일 | 새 이름 1개, old 이름 0개 |
| standalone SHA manifest·개정내역 정본 | 0개 |
| active 범위의 old `06` 경로 참조 | 0건 |
| 전체 worktree old `06` 경로 참조 | 과거 독립검수 보고서 2건만 존재 |
| strict UTF-8 검사 | 14개 대상 모두 PASS |
| UTF-8 BOM | 0건 |
| merge conflict marker | 0건 |
| 불균형 fenced code block | 0건 |
| 검사한 로컬 Markdown 링크 | 151개 |
| 깨진 로컬 링크 | 0건 |

old `06` 경로의 역사 보고서 2건은 당시 검수대상 blob을 재현하는 증거다.
matrix `PREP-SCOPE-01`이 `review/reports/**`, findings/evidence, Git history와
삭제경로를 active 참조 실패에서 명시적으로 제외하므로 결함이 아니다.

`05`의 backup/release/content용 manifest는 제품·복구 계약이며, 금지된 별도
정본 SHA manifest와 의미가 다르다.

## 6. 현재 실행하지 않은 2.1 runtime gate

다음은 새 2.1 프로젝트의 exact **implementation SHA**에서 실행해야 하며 이번
정본문서 PASS의 근거로 사용하지 않았다.

- 실제 격리 PostgreSQL의 base→head, downgrade/re-upgrade, offline SQL,
  catalog/FK/constraint/trigger, reverse invariant, 동시성 및 fault rollback
- backend SEM/API와 인증·권한·CSRF·`row_version` 계약
- OpenAPI named schema와 OpenAPI→TypeScript 독립 재생성 일치
- frontend unit/DOM, lint, TypeScript build
- 실제 API+실제 격리 PostgreSQL의 Playwright E2E
- 화면 크기별 overflow, 개인정보·legacy key·폐기필드 비노출
- backup 생성·manifest/hash·격리 review DB restore drill과 W1 postcheck

위 runtime gate를 실행하지 않은 것은 검수불능 누락이 아니라 최신 사용자
결정에 따른 저장소 경계다. 제품변경이 0건인 현재 commit에 제품 runtime PASS를
부여하지 않았고, 해당 gate는 matrix §14에 명시적으로 남아 있다.

## 7. 2.1 인계 값과 남은 통제절차

```text
CLEAN_REBUILD_BASE_SHA=6938573189fc7aede8a95f09934c3228e3745ebe
NEW_CANONICAL_DOC_SHA=e52db047a2324171b4d3e8c5d57b69e67a48206b
NEW_REVIEW_RESULT_SHA=<이 보고서의 review-only commit 뒤 Git에서 기록>
```

이 검수에서는 사용자의 지시대로 commit·push를 수행하지 않았다. 따라서
Codex 통합자가 이후 수행할 현재 저장소의 남은 통제절차는 다음과 같다.

1. 이 보고서만 `review/**` 변경으로 review-only commit한다.
2. 그 commit을 push하고 local/remote exact SHA를 readback한다.
3. `e52db047...NEW_REVIEW_RESULT_SHA`의 변경경로가 `review/**`뿐인지 확인한다.
4. clean tree를 확인한 뒤 위 세 SHA와 남은 결정 register를 새 2.1 프로젝트에
   인계한다.

이후 실제 Wave branch/base 선택과 W1A 제품 구현은 새 2.1 프로젝트의 별도
결정·증거다.
