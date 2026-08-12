# Wave 1 Clean 최종 조율 crosswalk

> 작성일: 2026-07-26 KST
> 지위: **비정본 review 추적 증거**
> 제품 구현 권한: 없음
> 이전 정본 SHA: `80194c55bd781afb5b9a639d74171d87b060ee8b`
> 이전 검수결과 SHA: `a9363ac01ba7b9852b2418fe71c2b862f59d0098`
> Clean rebuild 기준 SHA: `6938573189fc7aede8a95f09934c3228e3745ebe`

이 파일은 사용자의 최신 14개 방향 결정과 7개 기술보정이 어느 정본 절과
테스트 gate에 반영됐는지 추적한다. 결정 본문은 각 정본이 소유하며 이 파일은
정본 9개에 포함되지 않는다. 별도 SHA manifest도 아니다.

사용자의 가장 최신 실행경계에 따라 실제 Wave 시작과 branch/base 확정은 새
**2.1 프로젝트**에서 한다. 현재 저장소는 정본 봉인, exact-SHA 독립검수,
review-only 결과 commit, 원격 readback과 인계까지만 수행한다.

## 1. 14개 방향 결정

| ID | 최신 결정 요약 | 정본 소유 위치 | 테스트·통제 ID |
|---|---|---|---|
| FC-01 | 06은 세 문서로 나누지 않고 `06_파일처리_영역_경계와_확정사항.md` 하나로 유지 | `00` §2~3, `06` 제목·§0 | `PREP-DOC-01`, `PREP-SCOPE-01` |
| FC-02 | 파일함·입출력 `PARTIAL_DESIGN`, OCR `CONCEPT_ONLY`, 상세 DDL `DEFERRED`; 구현 상세정본 아님 | `00` §3, `06` 머리말·성숙도표 | `PREP-DOC-01`, `PREP-REG-01` |
| FC-03 | 04 실행 권위는 W0 적용 schema, W1 상세 DDL, W2 업무계약·인터페이스·금지, W3~5 원칙으로 제한 | `04` §0 | `PREP-DB-01` |
| FC-04 | W2+ 실제 테이블·컬럼·FK·revision 구조를 현재 봉인하지 않음 | `04` §0·§11~12 | `PREP-DB-01` |
| FC-05 | 안정 ID를 이름목록으로 고정하지 않고 업무개념 분류·정정 지속·후속 참조를 기록 | `01` §5, `02` §10, `04` §11 | `PREP-SEM-01` |
| FC-06 | W1 핵심 원장에 document/import/OCR 미래 역참조 FK를 추가하지 않음 | `01` §5, `02` §10, `04` §11, `06` §1 | `PREP-ABS-01`, `W1-ABS-12` |
| FC-07 | 불변 물리 content와 source receipt를 분리하고 같은 bytes와 같은 접수를 동일시하지 않음 | `06` §2.1 | `PREP-FP-01` |
| FC-08 | import는 filebox document/version을 필수 요구하지 않고 filebox 정책과 import 감사정책을 분리 | `05` §8.4, `06` §2.1 | `PREP-FP-02` |
| FC-09 | filebox 삭제가 import 근거를 cascade 삭제하지 않고 import 원본을 일반 사용자에게 자동 공개하지 않음 | `05` §8.4, `06` §2.1 | `PREP-FP-02` |
| FC-10 | 문서 연결은 대상별 typed FK를 우선하며 대형 nullable link와 FK 없는 type/id는 미승인 | `06` §2.1~2.2 | `PREP-FP-03` |
| FC-11 | OCR은 typed application/domain command만 사용하고 직접 SQL·HTTP 자기호출을 금지 | `05` §5.3·§10.1, `06` §6 | `PREP-OCR-01` |
| FC-12 | OCR 원자성은 run 전체가 아니라 사용자 승인 적용묶음이며 짧은 transaction과 감사로 통제 | `05` §5.3·§6.5·§10.1, `06` §6 | `PREP-OCR-02` |
| FC-13 | W1에는 미래 file/import/OCR 의존 부재 테스트를 유지 | `04` §11·§13, `06` §9 | `PREP-ABS-01`, `W1-ABS-12` |
| FC-14 | exact SHA·clean tree·원격 일치·독립 PASS 전 제품 구현 금지 | `00` §1·§6, `01` §2, `05` §20, `07` §0·P2·P3·§15 | `PREP-GIT-01` |

## 2. 7개 기술보정

| ID | 기술보정 | 반영 위치 | 테스트·통제 ID |
|---|---|---|---|
| TC-01 | 06 정확한 파일명과 Git rename 이력 | `00` §2~3, `01` §3, `05` §9, `06`, `07` §11~14 | `PREP-DOC-01`, `PREP-SCOPE-01` |
| TC-02 | 성숙도와 07 결정상태를 분리 | `00` §3, `06` 머리말, `07` §8·§11·§13 | `PREP-DOC-01`, `PREP-REG-01` |
| TC-03 | 안정 인터페이스를 의미분류로 정의하되 W1 실제 DDL 매핑은 04에 기록 | `01` §5, `02` §10, `04` §11, matrix §9 | `PREP-SEM-01` |
| TC-04 | 물리 content identity와 source receipt identity 분리 | `06` §2.1 | `PREP-FP-01` |
| TC-05 | OCR 적용묶음의 권한·row version·독립 멱등키·typed command·동일 transaction·실패 0건 | `05` §5.3·§6.5·§10.1, `06` §6 | `PREP-OCR-01`, `PREP-OCR-02` |
| TC-06 | 부재 테스트를 문자열이 아닌 catalog/FK·ORM/migration·service/worker·API/TS/UI 의미로 수행 | `04` §11·§13, `06` §9, matrix §1.1·§9 | `PREP-ABS-01`, `W1-ABS-12` |
| TC-07 | 검수대상 정본 SHA와 review 결과 SHA를 분리 | `00` §1·§6, `01` §2, `07` P2·P3·§15 | `PREP-GIT-01` |

## 3. 최종 조율 보완사항

| ID | 보완사항 | 처리 |
|---|---|---|
| LC-01 | content/receipt·import/filebox 경계는 `W3-C06 CONFIRMED`, 실제 schema·저장·GC·typed 연결은 `W3-07 DESIGN_REQUIRED` | `07` §11 |
| LC-02 | 실제 보존기간과 세부 역할별 열람권한 분리 | `W5-06`, `W5-09` |
| LC-03 | OCR 실제 문서·추출필드는 샘플 전 미확정 | `W5-01 SAMPLE_REQUIRED`, `W5-02 DESIGN_REQUIRED/SAMPLE_REQUIRED` |
| LC-04 | 폐기 06 경로 검색은 active 권위범위만 실패시키고 역사 review/Git 이력은 허용 | matrix `PREP-SCOPE-01` |
| LC-05 | Wave 0 기존 nullable non-FK `access_event.generated_document_id`는 이름만으로 부재검사를 실패시키지 않음 | `04` §11, `06` §1, matrix `PREP-ABS-01`·`W1-ABS-12` |
| LC-06 | 현재 저장소에서 W1A branch를 만들지 않고 새 2.1 프로젝트에 인계 | `01` §2, `05` §20, `07` §0·P3·§15, matrix `PREP-GIT-01` |

## 4. 인계 증거 형식

최종 인계에는 다음 값을 Git에서 읽어 기록한다.

```text
CLEAN_REBUILD_BASE_SHA=6938573189fc7aede8a95f09934c3228e3745ebe
NEW_CANONICAL_DOC_SHA=<정본·검수통제 commit의 40자리 SHA>
NEW_REVIEW_RESULT_SHA=<review-only 결과 commit의 40자리 SHA>
```

추가 필수 증거:

- `NEW_CANONICAL_DOC_SHA`가 rebuild 기준의 descendant
- 정본 commit과 review 결과 commit의 local/remote SHA 일치
- 최종 clean tree
- `NEW_CANONICAL_DOC_SHA..NEW_REVIEW_RESULT_SHA` 변경경로가 `review/**`뿐
- backend·frontend·migration·infra·제품 script 변경 0건
- 새 2.1 프로젝트가 실제 Wave branch/base를 별도로 확정
