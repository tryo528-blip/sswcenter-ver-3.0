# Wave 1 Clean Rebuild 테스트 매트릭스

> 상태: 현재 v2.1 제품 저장소의 Wave 1 테스트 계약·실행 gate
>
> 작성일: 2026-07-27 KST
>
> 적용 저장소: SSWCenter v2.1 제품 저장소(실제 branch/base는 작업계획에서 확정)
> 목적: 구 Wave 1·2 구현을 복사하지 않고, 최신 수용계약의 의미를 테스트부터 다시 고정한다.

## 1. 기준 문서와 판정 원칙

이 매트릭스의 요구사항 추출 기준 입력은 Google Drive의
[`WAVE1_CLEAN_REBUILD_ACCEPTANCE_CONTRACT_v1.0.md`](https://drive.google.com/file/d/1YuHgEyRCWC3_nl2zzsU0dqxwwMllCMNM)
이다. 확인한 Drive 파일 ID는 `1YuHgEyRCWC3_nl2zzsU0dqxwwMllCMNM`, 수정시각은
`2026-07-26T01:50:13.650Z`이다.

이 인용은 입력문서의 내용·버전 provenance를 고정한다. 동일 문서가 repository의
`docs/context/` 또는 `docs/decisions/`에 standalone 파일로 존재해야 한다는 뜻이 아니다.
repository 안의 구현 권위는 그 내용이 흡수된 영역별 정본이다. 각 테스트는 해당 영역별
정본의 절을 근거로 연결하고, 중복 standalone 입력문서의 존재를 gate로 검사하지 않는다.
직원 업무계약은 02, 공개 UI는 03, DB 불변조건은 04, 기술·보안·migration은
05, 파일처리 경계는 06, 실행·미결상태는 07을 직접 기준으로 사용한다.

검토 기준 SHA:

- clean rebuild 기준 commit: `6938573189fc7aede8a95f09934c3228e3745ebe`
- 위 기준의 parent: `b40cbc23f76c1ae1bedebb1fdb61b7b9ba680f78`
- 구 evidence 추출 commit: `4212d12bb1e0c8bbbb2e417ed1a3b18ae1ad7e59`

이 문서는 다음 원칙으로 작성했다.

- 최신 수용계약과 충돌하면 구 테스트·구 finding·구 스키마의 단정은 폐기한다.
- 구 자산에서는 업무 의미, 경계값, 실패의 원자성, 동시성, 개인정보 비노출 같은
  관찰 가능한 기대만 재사용한다.
- 구 migration 번호, 테이블/컬럼/constraint 이름, DTO 모양, 화면 컴포넌트와
  `data-testid`는 새 설계를 구속하지 않는다.
- 모든 기간은 별도 결정이 없는 한 양 끝 날짜를 포함한다. 따라서 `end_date`와 다음
  `start_date`가 같은 날이면 중복이고, `end_date + 1일`부터 인접 기간이다. 인정 전환의
  `new start - 1일` 제안도 이 규칙을 뒷받침한다.
- 아래 오류코드 중 코드블록 없이 적은 기존 코드는 구 증거에서 의미가 확인된 계승
  대상이다. `제안:`으로 적은 코드는 첫 API 구현 전에 오류 카탈로그에서 이름을 확정한
  뒤 테스트 문자열을 고정해야 한다.
- 단위 테스트만으로 DB 불변조건 통과를 선언하지 않는다. 중복, 역방향 부모 변경,
  동시성, rollback은 실제 격리 PostgreSQL에서 검증한다.
- mock fetch Playwright는 UI smoke일 뿐 업무 E2E가 아니다. 최소 한 개의 W1A 직원
  시나리오는 실제 API와 실제 격리 PostgreSQL을 사용한다.
- 현재 v2.1 제품 저장소는 작업단위별 PG/API/OA/DOM/E2E/BR runtime gate를
  실제 구현과 함께 실행한다. 아직 실행하지 않은 후속 작업단위의 gate를 현재
  PASS로 오인하지 않는다.

테스트 층 표기는 다음과 같다.

| 표기 | 의미 |
|---|---|
| `SEM` | DB·프레임워크에 독립적인 순수 업무 의미 테스트 |
| `PG` | 실제 격리 PostgreSQL의 제약·동시성·transaction 테스트 |
| `API` | 인증된 HTTP 계약과 안정 오류 envelope 테스트 |
| `OA` | OpenAPI 스키마·경로·required/nullable/enum/오류 응답 테스트 |
| `DOM` | Testing Library 기반 사용자 관찰 가능 UI 테스트 |
| `E2E` | 브라우저 사용자 흐름 테스트 |
| `ABS` | 폐기 또는 미래 구조가 없음을 확인하는 음성 검사 |
| `BR` | backup/restore drill |

### 1.1 현재 문서봉인 정적 gate

| ID | 검사 | PASS 기준 |
|---|---|---|
| `PREP-DOC-01` | 정본 topology·06 지위 | `docs/` 9개, `06_파일처리_영역_경계와_확정사항.md` 단일 파일, 파일함/입출력 `PARTIAL_DESIGN`, OCR `CONCEPT_ONLY`, 상세 DDL `DEFERRED` |
| `PREP-SCOPE-01` | 폐기 06 경로 active 참조 | 현재 9개 정본, README, 현재 independent-review skill, `review/REVIEW_SCOPE.md`, 이 matrix, 현재 code/config/scripts에서 0건. 과거 `review/reports/**`·findings/evidence·Git history·삭제경로는 역사증거로 예외 |
| `PREP-DB-01` | 04 실행 권위 | Wave 0 적용 schema, Wave 1 상세 DDL, Wave 2 업무계약·인터페이스·금지, Wave 3~5 책임·의존·보존·금지만 권위이며 W2+ object 이름을 봉인하지 않음 |
| `PREP-SEM-01` | 교차웨이브 업무개념 | `IDENTITY`·`PERIOD_FACT`·`REVISION`·`CURRENT_PROJECTION`, 정정 뒤 지속/대체, 후속 참조대상이 01·02·04와 §9에서 일치 |
| `PREP-ABS-01` | Wave 1 미래 역참조 부재 | catalog/FK graph, ORM/migration, service/repository/worker, OpenAPI/TS/UI에 새 file/import/OCR 역참조·필수의존 없음. 기존 Wave 0 nullable non-FK `access_event.generated_document_id`는 이름만으로 실패시키지 않음 |
| `PREP-FP-01` | 물리 content와 접수 사실 | 같은 bytes 재사용 가능, 별도 접수는 별도 identity, hash만으로 접수 동일성 판단 금지가 06에 존재 |
| `PREP-FP-02` | 파일함과 import 감사경계 | import가 filebox document/version을 필수 요구하지 않고, filebox 삭제 cascade·일반 사용자 자동공개·ACL/보존 자동공유를 금지 |
| `PREP-FP-03` | 문서 연결방식 | 대상별 typed FK 우선, 대형 nullable link와 FK 없는 `target_type + target_id` 미승인 |
| `PREP-OCR-01` | OCR 호출경계 | typed application/domain command만 허용하고 직접 SQL·service 우회·HTTP 자기호출 금지 |
| `PREP-OCR-02` | OCR 적용 원자성 | run 전체가 아닌 사용자 승인 적용묶음, 실행/적용 멱등성 분리, 권한·CSRF 경계·`row_version`·업무+감사 동일 transaction·실패 0건 |
| `PREP-REG-01` | 상태분리 | W3-C06 `CONFIRMED`, W3-07 `DESIGN_REQUIRED`, W5-06·W5-09 `USER_DECISION_REQUIRED`, OCR profile은 `SAMPLE_REQUIRED`; 06 성숙도와 07 결정상태를 혼합하지 않음 |
| `PREP-GIT-01` | SHA·2.1 인계 | rebuild 기준, 최신 정본 SHA, review 결과 SHA를 분리하고 canonical→review diff `review/**` only·local/remote 일치·clean tree를 기록; 현재 저장소는 W1A branch/제품변경 없음 |

## 2. Wave 경계

### Wave 1에 포함

- 직원, 재직, 직종, 시스템 역할, 자격증, 서비스 제공자격 기간
- 직원 신규교육·정기교육 6종·건강검진·분기상담의 업무 원장
- 수급자, 보호자, 독립 납부자 snapshot
- 인정 본번호·인정기간·등급기간과 인정 전환
- 혜택기간, 지자체 승인 월급여액 기간
- 서비스별 계약과 계약서명자 snapshot
- 요양보호사 기간배정
- 사회복지사·간호사 월 배정과 변경 history
- 후속 Wave가 참조할 `IDENTITY`·`PERIOD_FACT` 의미, 정규화
  `CURRENT_PROJECTION`, `row_version`, audit

### Wave 2 이상으로 격리

- 공단 일정, RFID, 실제근무·실제 급여제공 evidence
- 급여계획서 갱신과 D-100/D-45 task
- 실제 제공 순서 기반 직원교체 상담 case와 Day 14 판정
- 대시보드 업무카드 생성·노출
- 공식 기준을 근거로 한 건강검진 자동 대상생성·D-day·업무카드
- 수가, 급여·청구·수납 계산, 은행자료, OCR 적용
- Wave 3 방문 실행모델, Wave 4 월중 최고 등급·혜택·승인액 계산

Wave 2+ 테스트는 W1 gate에 import하거나 skip 상태로 두지 않는다. 별도 보관 목록으로
격리하고 W1 코드·DB·OpenAPI·UI에 그 구조가 나타나지 않는지 `ABS`로 검사한다.

### 비충돌 Wave 2 의미 인벤토리

다음 인벤토리는 W1 제품구조를 선생성하기 위한 테스트가 아니다. immutable base
문서의 비충돌 의미가 Git 이력에만 남지 않도록 미래 DB/API/OA/DOM/PG/E2E
수용점을 고정하고, W1에서는 `ABS`로 구조 부재만 검사한다.

재현:

```powershell
git show 6938573:docs/02_새프로젝트_기능요구사항_정리본_v0.8.md |
  rg -n '공식 업무카드와 개인 할 일|완료·미완료·면제·대기|업무 발생이유|D-day|단계별 완료|해당 월 담당 수급자|정확히 2명|대상 일정·건수 미리보기|실제근무가 확인된 일정 제외|경고확인자와 확인시각|확정해제 사유'
```

| ID | 보존 의미 | 미래 DB/PG | 미래 API/OpenAPI | 미래 DOM/E2E | W1 gate |
|---|---|---|---|---|---|
| `SEM-W2-01` | 공식 업무카드와 개인 할 일 분리 | source 종류와 서로 다른 생성권한, 같은 화면용 결정적 union 조회 | named discriminator와 공식/개인 mutation 분리 | source label을 보존해 같은 목록에 표시 | 카드/todo table·route·model 부재 |
| `SEM-W2-02` | 공식 상태 `COMPLETE`/`INCOMPLETE`/`EXEMPT`/`WAITING`, 발생이유·기한/D-day | exact CHECK, 발생근거와 기준일 보존 | exact enum·reason·due fields | 4상태·발생이유·D-day 표시 | status/task 구조 부재 |
| `SEM-W2-03` | 단계별 완료 뒤 최종완료 | 단계 순서·필수여부·완료 history, 필수 전체완료 전 최종완료 차단 | step mutation과 final-state response | 단계별 체크→최종완료 E2E | step/task 구조 부재 |
| `SEM-W2-04` | 전문직 공식 카드는 해당 월 담당 수급자 범위 | W1 월 담당 ID/기간을 scope 원천으로 사용 | 타 담당범위 카드 mutation 거부 | 사회복지사·간호사별 카드 범위 E2E | W1 월 담당만 구현, 카드 없음 |
| `SEM-W2-05` | 방문목욕 서로 다른 요양보호사 정확히 2명 | 최종 transaction 상태에서 distinct staff count=2 | 2명 미만/초과/동일인 422·409 named error | 2명 입력·오류 DOM과 real PG E2E | schedule table/route 없음 |
| `SEM-W2-06` | 일괄취소 preview·최종확인·실제근무 일정 제외 | preview hash·lock·제외집합 재검산·원자 취소 | preview/apply 분리와 stale 응답 | 건수·제외사유 확인 뒤 apply | bulk-cancel/actual evidence 없음 |
| `SEM-W2-07` | 저장 허용 WARNING 확인자·확인시각 | acknowledgement actor/time append | warning token과 명시 확인 | 확인 전 저장상태와 확인 후 이력 | schedule warning 구조 없음 |
| `SEM-W2-08` | 확정월 해제 사유·해제/정정/재확정 이력 | 잠금, nonblank 사유, actor/time append-only | unlock POST·CSRF·reason·version | 사유 modal과 잠금/재확정 E2E | month-control 구조 없음 |
| `SEM-W2-09` | 이름과 분리된 명시적 일정 popup | 해당 없음 | 일정이 존재할 때만 action capability | 이름 클릭 popup 0, 별도 action popup 1 | W1 일정 action/route 없음 |

최신 결정이 prior를 대체한 부분도 같이 봉인한다. 급여계획서는 반기 종료일과
계약·인정 종료일 cap을 사용하고, 직원교체는 배정변경이 아니라 실제 급여제공
순서를 사용한다. 실제근무 evidence는 Wave 3 소유이므로 Wave 2/W1이 미래
nullable FK나 가짜 evidence를 만들지 않는다.

## 3. 공통 계약 매트릭스

| ID | 요구사항 | DB 불변조건 | API·오류코드 | OpenAPI | UI/DOM | PostgreSQL/E2E |
|---|---|---|---|---|---|---|
| W1-CMN-01 | 모든 변경은 권한·CSRF·`row_version` 검사 | 변경 가능한 원장에 증가하는 version과 actor/time audit. 같은 version의 동시 쓰기 중 하나만 commit | 무권한/CSRF 403은 Wave 0 envelope 계승. stale은 409 `ROW_VERSION_CONFLICT`; 내부 constraint명·SQL 미노출 | 모든 mutation에 version 입력과 403/409 표준 오류모델 명시 | 저장 충돌 시 현재값 재조회와 재적용 안내. 권한 없는 제어 미노출 | `PG`: 두 connection/barrier 동시 갱신 결과 1 success + 1 conflict. `E2E`: stale 화면이 조용히 overwrite하지 않음 |
| W1-CMN-02 | 결정적 목록과 이름 선택의 목록 유지형 상세 | 업무 정렬키가 같아도 PK tie-breaker가 존재 | 반복 GET/pagination에 누락·중복 없음; 이름 선택은 detail 조회일 뿐 일정 route를 호출하지 않음 | list/detail named schema; W1에는 schedule action/capability 없음 | 직원·수급자 이름 활성화 뒤 row·검색·필터·정렬·페이지·스크롤이 남고 같은 workspace detail만 교체; `window.open` 0회 | 동일 정렬키 연속조회. 직원·수급자 각각 real E2E로 이름 A→B→뒤로가기 문맥 유지와 popup 0 검증 |
| W1-CMN-03 | 표준 오류와 비밀 비노출 | DB/driver 오류와 평문 주민번호를 영속·반환하지 않음 | 예상 입력은 4xx, 예상 밖 오류는 500 `UNEXPECTED_SERVER_ERROR`; request ID 유지, 내부 예외·constraint·DSN·평문 주민번호 비노출 | 모든 JSON 성공/오류는 named schema; 임의 `additionalProperties`와 일반 평문 주민번호 property 금지 | 기술 예외 대신 행동 가능한 한국어 안내; 평문을 error boundary에 표시하지 않음 | DB/constraint 실패 redaction; 로그·오류·traceback·audit/access detail·fixture/snapshot/trace에서 주민번호·PIN·DSN 평문 0건 |
| W1-CMN-04 | OpenAPI가 TypeScript의 기술 원본 | 해당 없음 | 모든 경로는 versioned `/api/v1` | backend OpenAPI를 독립 재생성한 TS와 UTF-8/LF 정규화 hash 일치; 생성파일 수동수정 금지 | UI request/response 타입은 생성 타입에서 파생 | CI에서 regenerate-to-temp 후 diff/hash. stale generated file이면 FAIL |
| W1-CMN-05 | 운영 DB·실 개인정보를 테스트에 사용하지 않음 | 임시 cluster, 합성 seed, 전용 role만 사용 | fixture에 실제 주민번호·전화·이름 금지 | 예제값도 합성 표식 사용 | screenshot/trace에도 합성값만 존재 | cluster와 data root가 OS temp 아래인지 확인하고 종료 후 안전 삭제 |
| W1-CMN-06 | Wave 0 회귀와 직원 표시/메모 보존 | Wave 0 schema/auth/audit 및 `staff.display_name`·`staff.memo` 컬럼·기존 값 보존 | bootstrap/auth/session/CSRF 기존 계약 유지; 표시/메모를 침묵 삭제하는 mutation 없음 | Wave 0 경로·모델 삭제 금지; 기존 공개필드 disposition을 임의 변경하지 않음 | 로그인·권한 shell 회귀; 기존 표시/메모가 있는 합성 직원 round trip | base→W1A upgrade와 backup/restore 전후 두 컬럼의 nullability·값 hash 동일; Wave 0 unit/API/PG/Playwright 전체 통과 |
| W1-CMN-07 | exact DB naming policy | model/migration/catalog에서 Base `pk_`·`fk_`·`uq_`·`ck_`·`ix_`, 명시적 `ex_`·`fn_`; DEFERRABLE constraint trigger `ct_`, ordinary trigger `trg_` | API는 raw constraint명을 반환하거나 분기하지 않고 안정 업무오류로 매핑 | error schema에 DB object name 없음 | 기술 object name을 DOM에 표시하지 않음 | fresh/upgrade DB의 `pg_constraint`·`pg_trigger`·`pg_proc`·`pg_indexes`를 exact manifest와 비교; `ct_`는 constraint+deferrable, `trg_`는 ordinary인지 검사 |

## 4. 직원 원장 매트릭스

| ID | 요구사항 | DB 불변조건 | API·오류코드 | OpenAPI | UI/DOM | PostgreSQL/E2E |
|---|---|---|---|---|---|---|
| W1-STF-00 | 초기 직원 이관은 승인된 필드만 수용하되 Wave 0 값을 삭제하지 않음 | legacy 직원키 mapping, 이름, 암호화 주민번호, 주소, 전화, 입·퇴사일, 직종, 자격종류·번호·발급일 최대 2개만 staging→원장 반영. 새 legacy 별칭·고용형태·계좌·급여·보험·퇴직금·서비스단가·미사용 컬럼·과거 검진은 반입하지 않음. 기존 `display_name`·`memo`는 그대로 보존 | 공개 import API는 W1 계약사항이 아님. one-off 이관기는 포함/제외 건수와 사유만 안전하게 기록하고 전체 apply를 원자 처리 | 이관 전용 2개 입력범위를 일반 CRUD `maxItems=2`로 전파하지 않음; `display_name`·`memo` 삭제 migration을 정당화하지 않음 | 공개 import UI는 요구하지 않음. 초기등록만 2개이고 일반 자격증 원장에는 제한 없음 | 합성 legacy 허용/제외 필드, 일반 CRUD 자격증 3건, base의 non-null `display_name`·`memo` upgrade/restore hash 불변 |
| W1-STF-01 | 내부 직원 PK와 재직번호 분리, 재입사는 같은 직원에 새 재직 생성 | `staff.id`는 유지. 재직기간은 직원별 중복 금지. 재입사마다 새 `staff_employment.id`와 새 재직번호, 번호 unique | 재입사 성공. 겹침은 409 `제안: STAFF_EMPLOYMENT_PERIOD_CONFLICT` | 직원과 재직을 별도 named model로 표현; 재직번호를 직원 PK로 오인시키지 않음 | 퇴사 여부는 종료일로 표시하고 별도 근무상태 입력을 만들지 않음 | 최초 재직 종료→재입사 후 staff ID 동일, employment ID/번호 상이. 경계일 중복과 동시 재입사 차단 |
| W1-STF-02 | legacy 직원키는 내부 mapping만 | mapping은 직원 FK와 source/key uniqueness를 가지며 업무 테이블의 식별자로 사용하지 않음 | 일반 list/detail/search/export 응답·query에 legacy key 없음 | public schema 전체에서 legacy key property 없음 | 화면·검색·출력·접근성 이름에 legacy key 없음 | `ABS`: OpenAPI 직렬화와 DOM text 검색. import 매칭만 합성 legacy key로 검증 |
| W1-STF-03 | 주민번호 cardinality·입력·암호화·마스크·reveal·rotation | `staff_sensitive_identity.staff_id` PK/FK로 0..1; 기존/bootstrap 0행 허용. ciphertext nonempty, nonce 정확히 12-byte, key version 양수, HMAC 정확히 32-byte UNIQUE, 평문/mask 컬럼 없음. 신규 일반직원은 service transaction에서 직원+민감행 원자 생성 | 숫자 13자리 또는 `YYMMDD-XXXXXXX`; 달력·세기·성별 일치, checksum-only 비거부. 일반응답은 `birth_date` 기반 `YYMMDD-*******`. reveal은 관리자 POST+CSRF+현재 PIN step-up+no-store, 성공당 `access_event` 정확히 1건; 비관리자 403·invalid 422 | ordinary staff create에는 resident input required, bootstrap/legacy response는 민감행 nullable; 일반 model에 평문/ciphertext/nonce/HMAC 없음. reveal은 별도 POST operation과 no-store/403/422 기술 | 신규 일반직원 필수 라벨, 기존 0행 상세 허용, mask만 표시. reveal dialog는 현재 PIN·경고를 요구하고 닫은 뒤 평문 DOM/cache/URL 0건 | 32-byte versioned AES keyring과 별도 안정 32-byte HMAC key 설정 gate. 같은 입력 2회는 서로 다른 nonce/ciphertext·같은 HMAC, staff/key-version AAD swap 복호화 실패, 중복 HMAC race 1 success, 신규 원자 rollback, successful reveal 1회=event 1건. offline exclusive HMAC rebuild 전후 unique/row count. 로그·오류·audit/access detail·fixture/snapshot/trace 평문 0건 |
| W1-STF-04 | 직종과 시스템 업무역할 분리, 기간은 재직 안에 존재 | 직종기간·역할기간이 유효 재직기간 밖으로 나갈 수 없음. 역방향으로 재직을 줄여 orphan을 만들 수도 없음 | 범위 위반은 409 `제안: STAFF_PERIOD_OUTSIDE_EMPLOYMENT` | position과 role을 별도 필드/모델로 표현 | 직종과 권한/업무역할을 같은 선택값으로 합치지 않음 | insert/update 양방향 실패와 같은 transaction에서 자식·부모 함께 축소 성공을 각각 검증 |
| W1-STF-05 | 일반 자격증 사실 원장 | `license_type` exact seed는 `CARE_WORKER`/요양보호사, `SOCIAL_WORKER`/사회복지사, `NURSE`/간호사 3개. `staff_license(id,staff,type,number,issued_date)` 분리, 유효행 type+number unique, 안정 ID·무효화/대체; expiry/start/end 없음, 일반 3건 이상 | `/staff/{id}/licenses` CRUD는 3건 이상 성공; 무효화가 제공자격을 자동종료하지 않음; 초기등록만 2건 한도 | exact 3종 catalog와 일반 license named model에 `maxItems=2`·expiry 없음; qualification model과 별도 | `자격증` 탭에 exact 3종·번호·발급일만, 3건 이상·자격증만 보유 가능 | exact seed, 3건 round trip, active duplicate race, correction history; `ABS` DB/OA/DOM에서 등급 구분·간호조무사·관리책임자 seed, expiry와 영구 2개 제한 없음 |
| W1-STF-06 | employment-scoped 서비스 제공자격과 W1A 공통 service catalog | W1A가 3 group/5 service catalog를 seed. qualification은 안정 ID·staff/employment·service·기간·nullable same-staff source license; 재직 containment/reverse guard, 동일 staff/service overlap 차단. license number/date 중복컬럼 없음 | license CRUD와 별도 qualification CRUD/error. 자격증 없이 생성·재입사 후 같은 source 재사용 성공; 범위 위반 409. W1E 배정 orphan 단축 거부 | service exact enum/catalog와 qualification ID/기간/source nullable named model; 미래 schedule FK 없음 | `서비스 제공자격` 별도 탭, 선택 근거 자격증, 재직범위 오류; 기간을 자격증 만료로 표시하지 않음 | Wave 0→W1A standalone upgrade에서 catalog/FK 완결. 자격증만·자격기간만·재입사 재사용, wrong-staff source 실패, 부모/자식 같은 transaction 정정 성공, 배정 역방향 guard |
| W1-STF-07 | 신규직원교육과 periodic exact seed | catalog exact 7행: `NEW_HIRE_ORIENTATION`/신규직원교육/`ON_HIRE`; `ELDER_RIGHTS`/노인인권/`HALF_YEAR`; `DISABLED_ABUSE`/장애인학대 신고의무자교육, `ELDER_ABUSE`/노인학대 신고의무자교육, `SEXUAL_HARASSMENT`/직장 내 성희롱 예방교육, `WORKPLACE_BULLYING`/직장 내 괴롭힘 예방교육, `PRIVACY`/개인정보보호교육은 `ANNUAL`. onboarding은 employment별 active 1행, periodic은 staff+subject+period active unique·employment 없음, 모두 completed boolean | onboarding/periodic 분리 CRUD; 완료·해제마다 audit. 같은 기간 재입사해도 periodic 유지; 새 employment는 새 미완료 onboarding | exact code/name/cycle enum/catalog, boolean only; hours/completion-date/center/file property 없음 | exact 한국어 labels·주기·checkbox; same-period rehire 뒤 periodic 유지·새 onboarding 표시 | exact seed/catalog test, 신규 employment 원자 생성, periodic unique/race, rehire 유지, completed true/false audit 각 1건; 금지필드와 task side effect `ABS` |
| W1-STF-08 | 건강검진 사실과 대상상태 분리 | `staff_health_check`는 stable ID·staff·nullable same-staff employment·check date·nullable type/note·history를 갖고 같은 날짜 복수 사실을 허용. `staff_health_check_requirement`는 staff+target key active unique, rule version, exact 3상태, optional same-staff fact FK와 조건부 exempt reason·history를 가짐 | 사실 CRUD와 대상상태 조회·변경은 분리. COMPLETE는 같은 직원 fact 필수, INCOMPLETE는 fact 없음, EXEMPT는 fact 없음+면제사유. 미승인 자동 대상생성·D-day/task API 없음 | fact와 requirement named model 분리; exact enum·조건부 nullable. task/evidence/file property 없음 | `검진사실`과 `대상별 상태` 분리. 완료 fact, 미완료, 면제사유와 이력 표시; 자동대상/D-day/업무카드/첨부 없음 | 같은 날짜 복수 fact, wrong-staff employment/fact 실패, target duplicate race, 상태 truth table, invalidation/audit. `ABS` 미승인 target generator·task side effect·file FK; 공식 기준은 Wave 2 전 동결 |
| W1-STF-09 | 직원 분기상담은 care-change와 분리 | staff+calendar year+quarter active unique; status exact `COMPLETE`/`INCOMPLETE`/`EXEMPT`; COMPLETE=date+nonblank content, INCOMPLETE=nonblank incomplete reason, EXEMPT=nonblank exempt reason, 나머지 조건부 null; invalidation/replacement/audit, file/care-change FK 없음 | 직원 quarterly CRUD와 status별 422 field detail; Wave 2 care-change route/status 공유 금지 | 상담일·내용·두 reason의 conditional schema 설명과 exact enum; evidence/care-change property 없음 | 상태에 따라 정확한 필드만 required/visible; 분기상담과 교체상담 제목·메뉴 분리 | active duplicate/race, 모든 valid/invalid truth table, correction audit; `ABS` file FK·care-change coupling 없음 |

## 5. 수급자·보호자·납부자·서명자 매트릭스

| ID | 요구사항 | DB 불변조건 | API·오류코드 | OpenAPI | UI/DOM | PostgreSQL/E2E |
|---|---|---|---|---|---|---|
| W1-REC-01 | 수급자는 이름·생년월일·성별만 필수 | 세 필드만 NOT NULL. 우편번호·주소·자택전화·휴대전화 nullable | 최소 payload 201. 선택값 빈 문자열은 정규화 정책에 따라 null/빈 값 중 하나로 일관 | required 정확히 세 필드. `home_phone`/`mobile_phone` 분리 | 필수표시는 세 항목뿐이고 전화 두 종류를 별도 입력·표시 | 최소 생성→목록→상세 E2E. 두 전화가 서로 덮어쓰지 않는 round trip |
| W1-REC-02 | legacy recipient/attachment key는 내부 mapping, 구 등록번호로 재해석 금지 | source/key mapping unique. recipient number/RRN 칼럼에 legacy 값을 복사하지 않음 | 일반 조회·검색·출력에 두 legacy key 없음 | public schemas/parameters에 legacy key 없음 | 일반 화면과 검색에 legacy key 없음 | `ABS`와 합성 import 검증. 질병/기존 비고는 source가 구분된 메모로 보존 |
| W1-REC-03 | 수급자번호는 첫 계약 확정 때 한 번만 transaction-safe 자동부여 | 계약 전 null 허용. counter 잠금/원자 증가. recipient별 한 번호, 전체 unique. 재계약·서비스 추가로 불변 | 계약 전 생성 성공; 첫 계약과 번호부여가 한 transaction. 경쟁 first-contract 요청에서 중복번호 없음 | 번호는 create required 아님, response nullable until first contract | 계약 전 “미부여” 표시; 사용자 입력·수정 제어 없음 | 두 connection의 최초 계약 경쟁, rollback 시 counter/번호/계약 원자성, 재계약 후 번호 동일 |
| W1-GUA-01 | 보호자는 0명 이상, 이름만 필수 | 이름만 NOT NULL. 전화·주소·관계 nullable. 생년월일·성별 compatibility 컬럼 불필요 | 보호자 없이 수급자 저장 성공. 이름만 보호자 201. 필수화 위반 없음 | guardian required는 `name`만; birth/sex는 신규 public schema에 없음 | 전화·주소·관계는 선택으로 표시; 대표 없음이 저장을 막지 않음 | no-guardian, name-only round trip. `ABS`: DB/OA/DOM의 birth/sex 강제 없음 |
| W1-GUA-02 | 같은 시점 대표 보호자 최대 1명, 변경이력 보존 | 수급자별 유효 대표기간 exclusion; 비대표 여러 명 허용; supersession/history 보존 | 겹치는 대표는 409 `제안: PRIMARY_GUARDIAN_PERIOD_CONFLICT` | 대표 여부·유효기간/history 응답 명시 | 대표 변경 전에 영향기간을 보여주고 과거 대표도 이력에서 확인 | 같은 날 경계 중복 실패, 인접기간 성공, 동시 대표 지정 중 하나만 성공 |
| W1-PAY-01 | 현재 납부자는 0명 또는 1명이며 독립 snapshot | payer row가 있으면 이름 필수, 나머지 선택. guardian FK와 payer type 없음. 현재 unique | 납부자 없이 저장 성공, 이름만 저장 성공. 중복 current는 409 `제안: CURRENT_PAYER_CONFLICT` | `guardian_id`, `payer_type`, `SELF`, `PRIMARY_GUARDIAN` 없음 | 보호자 복사/연결을 필수화하지 않는 독립 입력 | 보호자 수정·대표 변경 뒤 payer 값 불변. DB FK catalog와 OA/DOM 금지 토큰 검사 |
| W1-SIG-01 | 계약서명자는 계약 당시 독립 snapshot이며 모두 선택 | 이름·관계·전화 nullable. guardian/payer FK, 생년월일, 주소 없음 | 전부 빈 값인 계약 저장 성공. 보호자/납부자 변경은 기존 서명자 불변 | signer의 세 선택 필드만 허용; 금지 FK/생년월일/주소 없음 | “계약 당시 정보”로 입력하며 보호자 선택을 강제하지 않음 | 빈 snapshot, 부분 snapshot, 원본 인적정보 변경 후 불변성 검증 |

## 6. 인정·등급·혜택·승인금액 매트릭스

| ID | 요구사항 | DB 불변조건 | API·오류코드 | OpenAPI | UI/DOM | PostgreSQL/E2E |
|---|---|---|---|---|---|---|
| W1-CERT-01 | 인정번호는 `L`+숫자 10자리 본번호로 정규화 | canonical base만 저장. 전체 unique, recipient당 base 하나 | `l1234567890-100/-101/-102` 등 3자리 suffix는 `L1234567890`으로 저장. 잘못된 모양 422 | pattern/설명은 suffix 입력 허용과 canonical 응답을 구분. `issued_date`는 required 아님 | suffix 제거 안내와 canonical 결과 표시. legacy key와 혼동 금지 | `SEM`의 대소문자·공백·suffix·오염표. `PG/API`의 canonical 저장과 migration이 아닌 import 정규화 |
| W1-CERT-02 | 같은 본번호의 타 수급자 연결 및 한 수급자의 다른 본번호 금지 | global unique + recipient unique | 타 수급자 충돌 409 `제안: CERTIFICATION_NUMBER_IN_USE`; 동일 수급자 다른 번호 409 `제안: RECIPIENT_CERTIFICATION_NUMBER_FIXED` | 두 conflict 응답 문서화 | 번호 교체를 일반 추가 UI로 제공하지 않음 | 두 수급자/한 수급자 양쪽 충돌과 동시 요청 race 검증 |
| W1-CERT-03 | 인정기간은 이력을 보존하고 중복하지 않음 | recipient의 유효 인정기간 exclusion, start≤end, invalidation/supersession 보존 | 중복은 409 `제안: CERTIFICATION_PERIOD_CONFLICT` | 기간 list/create/update 모델과 409 | 현재·과거 기간 목록, 시작/종료 경계 표시 | 같은 종료일/시작일 중복 실패, 다음날 인접 성공, 무효화 후 이력 유지 |
| W1-GRD-01 | 등급은 1~5만, 기간은 인정기간 안에서 서로 비중복 | grade check 1..5, closed period, certification FK 범위 안, 같은 인정의 유효기간 exclusion | 잘못된 등급/인지지원 422. 범위 밖 409 `제안: GRADE_PERIOD_OUTSIDE_CERTIFICATION`; 중복 409 | enum은 문자열 `1`~`5`만. 별도 grade-change-date 없음 | 선택지는 1~5만, 인지지원 항목 없음 | `SEM` enum/범위, `PG` insert와 인정기간 단축 역방향 guard |
| W1-BEN-01 | 혜택은 확인된 6종만 사용 | enum/check은 `GENERAL`, `BASIC_LIVELIHOOD`, `REDUCTION_6`, `REDUCTION_9`, `MEDICAL_6`, `MEDICAL_9` | 그 외 422. create/list 안정 응답 | 정확한 enum, GET+POST named schemas | 정확한 6개 선택값과 기간 목록 | 모든 허용/거부 코드 round trip |
| W1-BEN-02 | 혜택 유효기간은 코드와 무관하게 수급자 전체에서 비중복 | recipient-wide exclusion, 무효화·대체 이력. 시작일 월초 강제 없음 | 다른 코드라도 중복 409 `제안: BENEFIT_PERIOD_CONFLICT` | 월초 pattern/검증 없음. 실제 부담률 필드 없음 | 과거·현재 기간을 결정적 정렬로 표시 | 같은 날 경계 실패, 다음날 인접 성공, 월중 시작 성공 |
| W1-BEN-03 | 자료 없음은 GENERAL이 아님 | recipient 생성·계약 생성으로 benefit row가 자동생성되지 않음 | 빈 GET은 200 `items=[]`; implicit default 없음 | default `GENERAL` 없음 | 빈 상태를 일반으로 오표시하지 않음 | recipient/contract 생성 뒤 benefit count 0. `ABS`: 부담률 숫자 하드코딩 없음 |
| W1-BEN-04 | 서비스 제공일 기준 적용 혜택을 판정할 수 있음 | 비중복 원장에서 기준일에 유효한 행은 0개 또는 1개 | 기준일 조회는 해당 행 또는 명시적 none을 반환하며 GENERAL fallback 금지 | 기준일 date parameter와 nullable/not-found 정책을 명시 | W1 필수 UI는 기간목록이며 계산결과·부담률을 표시하지 않음 | 시작일·종료일 양끝, 인접일, 무자료일 조회를 검증 |
| W1-AMT-01 | 지자체 승인금액은 혜택과 독립된 원 단위 bigint 기간원장 | 금액 bigint, recipient-wide 기간 exclusion, 무효화·대체 이력 | GET/POST. 중복 409 `제안: APPROVED_AMOUNT_PERIOD_CONFLICT`; 음수/비정수는 422 | JSON integer/int64, decimal string·rate 모델 아님 | 정수 원 단위 입력과 과거·현재 목록 | bigint 최대 정책 경계, 다른 benefit 변화와 독립, 기간 중복/인접 검증 |

## 7. 인정 전환 매트릭스

| ID | 요구사항 | DB 불변조건 | API·오류코드 | OpenAPI | UI/DOM | PostgreSQL/E2E |
|---|---|---|---|---|---|---|
| W1-TRN-01 | preview는 영향 인정·등급·계약·서비스와 `new start - 1일` 종료 제안을 보여주며 DB를 바꾸지 않음 | preview 자체 write 0. token/hash는 변경 대상의 canonical projection을 대표 | preview 200. apply payload에는 token과 명시 확인값 필수; 미확인은 422 `제안: CERTIFICATION_TRANSITION_CONFIRMATION_REQUIRED` | preview/apply를 별도 operation/model로 기술, 영향 ID·서비스 multiset·제안 종료일 포함 | preview 전 apply 없음. 영향목록·대체계약을 표시하고 checkbox 등 명시 확인 전 disabled | preview 전후 row hash/count 동일. DOM과 real E2E에서 취소 시 변화 없음 |
| W1-TRN-02 | 영향 서비스 multiset과 대체계약 multiset이 정확히 일치 | 서비스별 종료와 대체생성이 한 transaction. 누락·추가·중복을 모두 거부 | 422 `CERTIFICATION_TRANSITION_REPLACEMENT_MISMATCH`, 변경 없음 | 422 표준 오류와 replacement item required fields | 누락 서비스가 보이고 완전해질 때까지 apply 차단 | 0건/부분/중복/잘못된 서비스 모두 기존 인정·등급·계약 불변 |
| W1-TRN-03 | preview 뒤 관련 인정·등급·계약이 변하면 stale | apply에서 관련 행 lock 후 인정+등급+계약 projection/hash 재계산 | 409 `CERTIFICATION_TRANSITION_STALE`; 새 preview 요구 | 409 모델과 stale code 명시 | stale 시 이전 preview·확인을 폐기하고 “다시 미리보기” 안내 | 인정 날짜, 등급 코드/기간, 계약 기간/서비스 각각 변경한 stale test. 동시 apply 하나만 성공 |
| W1-TRN-04 | apply는 순서 전체를 단일 transaction으로 처리하고 감사 | 기존 인정 종료→기존 LTC 계약 종료→새 인정/등급→서비스별 새 계약이 원자적. before/after, confirmer, time, target list audit | 중간 실패는 4xx/500 표준 envelope이고 부분변경 0. 성공만 결과 ID 반환 | 성공 response와 감사 상관 ID를 named schema로 고정 | 성공 후 새 기간/계약을 재조회하여 표시 | 각 단계 뒤 fault injection으로 rollback. 성공 시 네 단계와 감사가 모두 존재 |

## 8. 서비스 계약·배정 매트릭스

| ID | 요구사항 | DB 불변조건 | API·오류코드 | OpenAPI | UI/DOM | PostgreSQL/E2E |
|---|---|---|---|---|---|---|
| W1-CON-01 | 서비스별 독립 계약, 시작일만 필수 | service type/start NOT NULL. end, service commencement, signer snapshot, end reason nullable | 최소 계약 201. 급여개시일·서명자·종료사유 누락으로 차단하지 않음 | `contract_no` required 금지이며 별도 승인 전 property 자체를 만들지 않음. `end_reason_text` 자유문자열 | 계약번호 필수표시/입력 없음. 급여개시일·종료사유는 선택, 종료사유 기본값 없음 | 최소 계약, 빈 signer, 빈 end reason, 빈 commencement round trip |
| W1-CON-02 | 종료사유는 빈 값·자유입력, `사망`은 제안일 뿐 | enum/check/default/backfill 없음 | 임의 Unicode 문구와 null 성공 | fixed enum 및 default 없음 | placeholder/datalist로 `사망` 제안 가능하나 초기 value는 빈 값 | 새 계약과 과거 누락행이 자동으로 `사망`이 되지 않음 |
| W1-CON-03 | 종료 계약 재활성화 금지, 재이용은 새 계약 | ended→active 상태역전 금지, 과거 revision/history 보존 | 409 `제안: CONTRACT_REACTIVATION_FORBIDDEN` | reactivate operation 없음; 새 계약 operation 사용 | 종료행에 재활성화 버튼 없음, “새 계약” 흐름 제공 | 직접 DB/API 역전 실패, 새 비중복 계약 성공 |
| W1-CON-04 | 같은 서비스 유효계약 및 다른 서비스그룹 기간중복 차단 | recipient+same service exclusion. 상호 배타적 다른 service group도 recipient-wide exclusion. 같은 허용 group의 다른 service는 정본 규칙대로 | 기존 계승 코드: 409 `CONTRACT_SERVICE_PERIOD_CONFLICT`, 409 `CONTRACT_SERVICE_GROUP_PERIOD_CONFLICT` | 두 409 code 문서화 | 충돌기간과 서비스를 표시 | same-day 경계, open-ended, 같은 서비스, 다른 그룹, 허용된 같은 그룹 조합 matrix |
| W1-ASG-01 | 요양보호사 배정은 계약별 기간, 일반·가족 구분 | assignment가 계약·재직·직종/자격 유효기간 안. 같은 contract+staff 유효기간 중복 금지. 여러 일반 직원 동시배정 허용 | 중복 409 `제안: CARE_ASSIGNMENT_PERIOD_CONFLICT`; 자격 위반 409 `제안: CARE_ASSIGNMENT_STAFF_INELIGIBLE` | assignment type/기간/staff ID와 409 models | 일정일 기준 유효 배정 조회, 여러 일반 제공자 표시 | insert뿐 아니라 계약·재직·직종·자격 단축의 reverse orphan guard. 다중 일반배정 성공 |
| W1-ASG-02 | 가족요양은 관계 snapshot 필수 | FAMILY일 때 관계 nonblank, GENERAL일 때 관계 선택/정규화 | 누락 422 `제안: FAMILY_CARE_RELATIONSHIP_REQUIRED` | conditional validation을 설명하고 응답 snapshot 포함 | FAMILY 선택 시 관계 입력 required로 전환 | FAMILY 누락 실패/관계 포함 성공, 이후 보호자 관계 변경과 snapshot 독립 |
| W1-ASG-03 | 배정변경만으로 직원교체 상담 case를 만들지 않음 | assignment mutation trigger/FK가 care-change case를 만들지 않음 | 배정 성공 응답에 case side effect 없음 | care-change/execution 모델·경로 없음 | 배정 화면에 직원교체 case 생성/완료 UI 없음 | 배정 추가·종료·교체 뒤 미래 case/task 테이블 또는 event 0건; `ABS` 병행 |
| W1-MON-01 | 수급자·서비스월·전문직 역할당 현재 담당 1명, 역할별 공백과 월중 변경 허용 | `(recipient, service type, service month, professional role)`별 current period overlap 차단. 변경 전후/actor/time/note history append-only. 허용 업무역할이 변경시점에 유효하며 월 전체 coverage 강제 없음 | PUT/PATCH는 `row_version`; stale 409. 역할 위반 409 `제안: MONTHLY_ASSIGNEE_ROLE_INVALID` | role별 current와 history를 별도 named models로 제공 | 사회복지사·간호사 역할별 탭에서 현재 담당·공백·변경이력을 표시 | 같은 달 두 역할 동시 성공, 같은 역할 중복 실패, 역할별 공백 성공, 월중 A→B history, 동시변경 하나만 성공, 역할기간 역방향 invalidation 차단 |
| W1-MON-02 | 월 담당과 실제 방문자의 일치판정은 하지 않음 | actual visit/execution FK/check/trigger 없음 | 실제 방문자 검증 API 없음 | visit/execution fields 없음 | 일치/불일치 경고 없음 | `ABS`: 배정 저장으로 방문 event/task 생성 없음 |

## 9. 교차 Wave 업무의미·Wave 1 매핑과 미래구조 부재

후속 Wave가 의존하는 것은 테이블명 목록이 아니라 업무개념의 의미다. 실제
Wave 1 DDL 매핑은 04를 따르며, 정정 뒤 지속·대체와 참조대상을 함께 검사한다.

| 업무개념 | 분류 | Wave 1 실제 매핑 | W1 테스트 |
|---|---|---|---|
| 직원 생애 | `IDENTITY` | `staff.id` | 재입사·직종·역할·자격 변경 뒤 동일 |
| 재직 | `PERIOD_FACT` | `staff_employment.id`·재직번호 | 재입사마다 새 사실, 정정 전 사실과 무효화·대체 history 유지 |
| 직원 전화 정규화값 | `CURRENT_PROJECTION` | `staff.phone_normalized` | 표시 원문이 달라도 같은 후보값, 재계산 가능, FK 대상이 아님 |
| 일반 자격증 사실 | `IDENTITY` | `staff_license.id` | 선택 사실 ID 보존, 정정의 무효화·대체 명시, 제공자격 자동종료 없음 |
| 서비스 제공자격 | `PERIOD_FACT` | `staff_service_qualification_period.id` | 일정일 유효 사실 ID와 정정 전·후 history, license ID와 의미 분리 |
| 수급자 생애 | `IDENTITY` | `recipient.id`·`recipient_no` | 계약 전 ID 사용 가능, 최초 계약 번호 1회 부여 뒤 불변 |
| 인정 본번호 소유권 | `IDENTITY` | `recipient_certification_identity` | suffix 없는 canonical 값과 단일 owner 유지 |
| 인정·등급·혜택·승인금액 | `PERIOD_FACT` | 각 `*_period.id` | 기준일 단일 유효 사실, 정정 전 사실과 대체 ID 보존 |
| 서비스계약 | `IDENTITY` | `recipient_contract.id` | 종료 뒤 과거 계약 ID 유지, 재이용은 새 계약 ID |
| 서비스 종류 | `IDENTITY` | `service_type.id/code` | seed 재실행·조회 순서와 무관하게 의미 안정 |
| 요양보호사 배정 | `PERIOD_FACT` | `care_assignment.id` | 기간 정정·종료 전후 사실과 참조 이력 보존 |
| 월 전문직 담당 | `PERIOD_FACT` | `monthly_professional_assignment.id` | 월중 변경 전후 기간사실과 현재 projection 모두 조회 |
| 독립 납부자 snapshot | `PERIOD_FACT` | `recipient_payer_snapshot.id` | 보호자 변경과 무관하고 기준일 snapshot 재현 |

Wave 1에는 별도 `REVISION` 업무구조를 추가 승인하지 않는다. `row_version`은
동시성 토큰, audit는 변경근거이며 identity가 아니다. 이후 실제 revision이
필요한 영역은 해당 Wave에서 별도 승인한다.

다음 검사는 DB catalog, API route/schema, 생성 TypeScript, UI source/DOM 네 층에서 수행한다.

| ABS ID | 남아 있으면 FAIL인 구조 | 검사 기준 |
|---|---|---|
| W1-ABS-01 | 보호자 전화·관계 필수 | NOT NULL/required/HTML required/저장 차단이 모두 없어야 함 |
| W1-ABS-02 | 보호자 생년월일·성별 compatibility 구조 | 신규 DB column·public property·UI 입력 없음 |
| W1-ABS-03 | payer `SELF`/`PRIMARY_GUARDIAN`, payer type, guardian FK, 대표보호자 유효성 trigger | catalog FK/check/enum, OA token, TS union, UI 선택지 모두 없음 |
| W1-ABS-04 | 인정 `issued_date` 필수 | NOT NULL, OA required, UI required 없음 |
| W1-ABS-05 | 인지지원등급·1~5 외 등급 | DB enum/check, OA enum, UI option에 없음 |
| W1-ABS-06 | 수급자별 복수 인정 본번호 | DB/API race를 포함해 불가능 |
| W1-ABS-07 | 혜택 코드별로만 중복을 막는 제약 | 서로 다른 코드의 같은 수급자 기간도 충돌해야 함 |
| W1-ABS-08 | `contract_no` 필수·자동채번·호환 필드 | 별도 승인 전 DB/API/OA/UI property 없음. 최소한 NOT NULL/default/required는 무조건 없음 |
| W1-ABS-09 | 종료사유 고정코드·`사망` default/backfill·별도 퇴소일 | enum/check/default/초기 UI value와 discharge-date 계열 필드 없음 |
| W1-ABS-10 | 급여개시일 누락 차단 | NOT NULL/required/business gate 없음 |
| W1-ABS-11 | 배정변경 기반 직원교체 case | trigger, side-effect API, UI 흐름 없음 |
| W1-ABS-12 | RFID·공단·visit/execution·billing과 document/filebox/import/OCR의 미래 역참조·필수의존 | `pg_catalog` FK graph·nullability, ORM/migration, service/repository/worker, OpenAPI/생성 TS/UI에서 새 미래 table/route/model/FK/property/control을 선구현하지 않음. Wave 0의 기존 nullable non-FK `access_event.generated_document_id`는 이름만으로 FAIL하지 않고 새 dependency 의미를 검사 |
| W1-ABS-13 | 교육시간·이수일자·이수센터, 자격증 유효기간, 신규 legacy alias·별도 직원 근무상태·고용형태·계좌·급여·보험·퇴직금·서비스별 단가 호환구조 | 신규 DB/API/OA/UI 구조와 public 노출이 없음. 기존 Wave 0 `staff.display_name`·`staff.memo`는 forbidden alias/unused column이 아니며 컬럼·값을 보존. 과거 건강검진은 초기 import로 유입되지 않음 |
| W1-ABS-14 | 실제 부담률·월중 최고값 계산 | 숫자 상수, 계산 endpoint, 계산 결과 column 없음 |
| W1-ABS-15 | 자격증 사실을 제공자격기간에 합친 `license_number`/`issued_date`, 자격증만 보유 불가, 제공자격의 필수 source license | qualification catalog/table/OA/DOM에 license 사실 중복필드 없음; source nullable, license/qualification CRUD 분리 |
| W1-ABS-16 | 미승인 건강검진 자동 대상생성·D-day/task와 교육·검진·분기상담 file FK | 승인된 rule version 없는 target generator·업무카드·파일 DB FK/API/OA route/property/DOM 제어 없음. 건강검진 3상태 원장은 금지대상이 아님 |
| W1-ABS-17 | 직원 분기상담과 Wave 2 care-change 상담의 table/FK/status/API/UI 공유 | 독립 table·route·named model·화면이며 future care-change 구조 없음 |

## 10. 구 증거 F-016~F-025의 처리

| Finding | W1 clean 처리 | 재사용하는 의미 | 폐기·격리할 단정 |
|---|---|---|---|
| `F-016-wave12-lowercase-certification-migration-block.md` | 부분 재사용 | 소문자 `l`과 3자리 suffix를 canonical 본번호로 정규화하고 오염 입력은 거부 | `0004→0005` upgrade, 구 migration/constraint/table 이름. clean W1에서는 API와 초기 import 테스트로 다시 작성 |
| `F-017-care-plan-warning-save-blocked.md` | Wave 2+ 격리 | 향후 “경고가 저장을 차단하지 않는다”는 의미만 Wave 2 자산으로 보관 | care-plan notice/table/API/warning code를 W1에 만들지 않음 |
| `F-018-certification-transition-allows-missing-replacements.md` | 재사용 | 영향 서비스 multiset과 대체계약 완전성, 422 `CERTIFICATION_TRANSITION_REPLACEMENT_MISMATCH`, 변경 0 | 구 request 기본값·구 endpoint 구현·테이블명 |
| `F-019-certification-transition-grade-stale-gap.md` | 재사용 | preview hash에 관련 등급 포함, lock 후 재검산, 409 `CERTIFICATION_TRANSITION_STALE` | 구 projection 직렬화와 구 SQL |
| `F-020-day15-counseling-completes-case.md` | Wave 2+ 격리 | Day 14/15 경계는 향후 실제 제공 순서 기반 상담 테스트 자산 | 상담 case/API/status를 W1에 선구현하지 않음 |
| `F-021-retroactive-evidence-stale-transition.md` | Wave 2+ 격리 | 소급 실제근거가 순서를 재판정한다는 향후 의미 | actual-service evidence/case 구조를 W1에 만들지 않음 |
| `F-022-certification-transition-ui-missing.md` | 재사용 | preview→영향표시→명시확인→apply, stale이면 preview·확인 폐기 후 재실행 | 구 `AlignmentPanel`, wrapper, `data-testid` 이름 |
| `F-023-care-plan-completion-period-ui-missing.md` | Wave 2+ 격리 | 향후 계획서 실제 통보일·적용기간·warning UI 자산 | W1 OpenAPI/TS/DOM에 포함 금지 |
| `F-024-benefit-approved-ledger-list-missing.md` | 재사용 | 혜택·승인금액 GET+POST, 과거/현재 목록, 결정적 정렬, 생성 후 refetch | 구 component/path 모양과 승인금액 decimal-string 단정 |
| `F-025-care-change-history-read-missing.md` | Wave 2+ 격리 | 향후 append-only 상담·예외·상태 history 조회 의미 | W1 history endpoint/UI를 만들지 않음 |

## 11. 구 테스트 자산의 재사용·폐기 지도

기준 경로는 `C:\Users\USER\Documents\sswcenter-wave12-alignment`이다.

| 구 자산 | 가져올 수 있는 기대 | 그대로 복사하면 안 되는 것 |
|---|---|---|
| `backend/tests/test_wave12_semantics.py` | 인정번호 정규화, 등급 1~5, 혜택 6종, inclusive 기간중복, 등급기간이 인정기간 안 | care-plan·D-100/D-45·Day 14 상담 계산은 Wave 2+ |
| `backend/tests/test_wave1_postgres.py` | 최초 계약 번호부여, 계약/그룹 중복, 배정 자격, 월담당 history, CSRF/권한, row-version, 민감조회 감사, reverse orphan 방지 | 직원 birth/sex 등 구 DTO, 필수/nullable `contract_no`, `issued_date`, 보호자 기본 관계코드, 구 revision/current 테이블과 constraint명 |
| `backend/tests/test_wave12_postgres.py` | 보호자 이름만, 대표기간 충돌, payer 독립, 혜택 recipient-wide 중복, 승인금액 중복/list, 인정번호 canonical/global owner | 승인금액 `"1520300.00"` 문자열, `payer-periods` 등 구 route 이름, actual-service/care-change 항목 |
| `backend/tests/test_wave1_api_contract.py` | `/api/v1`, named success/error schemas, 표준 409/500, future file 필드 부재 | 구 path 전체 집합과 구 request/response 필드 |
| `backend/tests/test_wave12_api_contract.py` | guardian name-only, payer forbidden FK/type, contract 선택필드, ledger GET/POST, transition routes | `contract_no` property를 nullable로 유지하는 단정, care-plan/care-change schemas |
| `review/tests/test_wave1_high_risk.py` | 실제 PG 동시 version 경쟁, 4xx/409 매핑, no-store+audit, constraint명 비노출, 계약/배정 matrix | account 중심 exact response key set, 구 payload와 구 constraint 이름 |
| `review/tests/test_wave1_reverse_invariants.py` | 부모 기간 단축/무효화로 기존 배정을 orphan할 수 없음, 같은 transaction의 일관된 공동변경은 가능 | 구 revision/current projection 구조와 exact SQL/constraint명 |
| `review/tests/test_wave12_latest_alignment_regressions.py` | F-018/F-019의 replacement/stale 회귀 | 0004→0005 legacy migration과 W2 care-plan/care-change 테스트 |
| `review/tests/test_wave1_openapi_contract.py` | 독립 OpenAPI 검증, named models, 표준 error envelope, request ID redaction | 구 path allowlist와 response 구조 |
| `review/tests/verify_wave1_openapi_generation.ps1` 및 `scripts/generate-openapi-types.ps1` | temp 재생성, UTF-8/LF hash 비교, 생성파일 stale 실패 | 고정 디렉터리/실행파일 경로는 새 repo 환경에 맞춰 재작성 |
| `frontend/src/test/Wave1Pages.test.tsx` | 권한별 mutation 제어, API 기반 목록/상세, row-version 제출 | 직원 birth/sex, `contract_no`, `GRADE_3`, 구 화면 fixture |
| `frontend/src/test/RecipientsAlignment.test.tsx` | 선택 필드 표기, guardian/payer 독립, 6종 혜택, ledger list, transition confirm/stale UX | guardian 기본 `CHILD`/emergency/start date, recipient-create에 묶인 구 certification DTO, nullable `contract_no`, W2 care history |
| `frontend/e2e/wave0-shell.spec.ts` | 주요 해상도 overflow, 실제 navigation, role별 shell smoke | 모든 API를 route mock한 테스트를 업무 E2E로 계산하는 것, Wave 2 dashboard/schedule 시나리오 |
| `scripts/test-ephemeral-postgres.ps1` | temp cluster, fresh upgrade, downgrade/re-upgrade, offline SQL apply, 합성 seed, 안전 cleanup | 구 Wave 1·2 migration chain과 Wave 0 이름에 결합된 DB/postcheck |
| `scripts/backup-postgres.ps1`, `scripts/restore-drill.ps1`, `infra/backup/README.md` | maintenance DB 거부, live data root 밖 destination, overwrite 거부, manifest/hash, `_review` target, restore hash 검증 | 복원 뒤 Wave 0 postcheck만 실행하는 것과 존재하지 않는 미래 파일 디렉터리를 W1 성공조건으로 삼는 것 |

## 12. 가장 작은 W1A 직원 test-first vertical slice

준비·착수 지시서 P5에 따라 W1A는 **직원 기반**이다. 가장 작은 첫 수직 slice는
**직원 identity + 최초 재직/재입사 + 직종/업무역할 분리 + 전화 정규화 + 주민번호
암호화·기본 마스킹**이다. 수급자·보호자·납부자는 W1B이며 W1A에 넣지 않는다.

첫 구현 전 RED 순서는 다음과 같다.

1. `SEM/ABS/OA` — 직원 내부 PK와 재직 ID·재직번호가 분리되고, 직종과 operational
   role이 별도이며, public schema에 legacy 직원키·별도 근무상태·구 별칭·평문 주민번호가
   없는지 먼저 고정한다. 여기서 “구 별칭 부재”는 새 legacy 호환필드·공개노출 금지이며
   Wave 0 `staff.display_name`·`memo` 삭제를 뜻하지 않는다. 전화 정규화는 한국
   국내번호와 `+82`/`0082` 입력의 동치표,
   허용 구분자, 빈 값, 비한국 국제번호·내선·오염문자 거부표로 원문과
   `+82` projection을 분리한다. 주민번호는 13자리/`6-7`, 달력·세기·성별,
   checksum-only 비거부와 `birth_date` 기반 mask를 먼저 고정한다.
2. `PG` — 직원과 최초 재직의 원자 생성, 재직기간 중복 차단, 종료 후 같은 직원의
   재입사, 새 재직 ID·번호 발급, 직종·역할기간의 재직범위, 동시 재입사 번호 경쟁,
   전화 정규화값, 민감행 0..1/신규 원자생성, nonce/HMAC 길이·unique,
   AAD 이동실패와 주민번호 평문 0건을 실제 PostgreSQL에서 검증한다.
3. `API` — 권한·CSRF·row-version, 직원 create/list/detail과 새 재직 생성, 201/200/409
   표준 envelope, 결정적 정렬, legacy key 비노출을 검증한다. 일반 응답은 masked
   주민번호만 반환하고 관리자 reveal은 POST+CSRF+현재 PIN+no-store와 성공당
   `access_event` 정확히 1건을 남긴다.
4. `OA generation` — backend OpenAPI가 직원·재직·직종·업무역할을 named model로
   분리하고 일반 응답에 평문 주민번호가 없는지 확인한 뒤, TypeScript를 temp 재생성하여
   checked-in 결과와 일치시키고 생성 타입 직접수정을 막는다.
5. `DOM` — 직원 목록과 목록 유지형 상세, 이름 클릭 popup 0건, 최초·과거 재직, 계산된 재직/퇴사 상태,
   직종과 업무역할의 분리, 전화 표시, masked 주민번호, legacy key 미노출을 사용자
   관찰 기준으로 검증한다.
6. `real PG E2E` — 실제 격리 PostgreSQL+API+브라우저로 “직원 등록과 최초 재직→masked
   주민번호 확인→재직 종료→같은 직원 재입사→staff ID 유지와 새 재직 ID·번호 확인→
   목록 복귀 문맥 유지”를 수행한다. 관리자 reveal E2E는 current PIN과 성공당
   access event 1건, 닫은 뒤 평문 부재를 함께 검증한다. 종료 후 PG postcheck로
   정규화 전화와 평문 주민번호 부재를 확인한다.

W1A의 나머지 직원 범위인 초기 이관, 공통 service catalog, 분리된 자격증·서비스
제공자격, exact 신규·정기교육, 사실·대상상태를 분리한 건강검진,
조건부 분기상담은 같은 W1A 안의
후속 micro-slice로 완성한다. W1A의 완료 증거는 테스트 이름이나
화면 screenshot만이 아니라, 정확한 commit SHA에서 생성한 PG/API/OA/DOM/실제 E2E 로그와
clean tree여야 한다.

## 13. P5 공식 W1A–W1F test-first 작업단위

아래 작업단위는 현재 SSWCenter v2.1 제품 저장소에서 승인된 작업계획과 정확한
branch/base를 기준으로 실행한다.

| 작업단위 | 고정 범위 | 먼저 실패해야 하는 핵심 테스트 |
|---|---|---|
| W1A | 직원 기반 | 최소 vertical slice의 identity·최초 재직·재입사·직종/역할·전화 정규화·민감정보 exact 계약; 이어서 Wave 0 표시/메모 보존, W1A-owned service catalog, 분리 자격증 3개 이상·서비스자격 source/containment/reverse guard, exact 신규/정기교육, 사실·대상상태 분리 검진, 조건부 분기상담, W1-ABS-13/15/16/17 |
| W1B | 수급자·보호자·납부자 | 수급자 필수 3항목, 자택/휴대전화 분리, guardian 0명·이름만, 동시 대표 최대 1명/history, payer 0명·이름만·current 최대 1명, guardian 변경 후 payer snapshot 불변, 금지 FK/type/legacy key 부재 |
| W1C | 인정·등급·혜택·승인금액 | lowercase/suffix canonical, global/recipient 인정번호 owner 충돌, 등급 1~5와 기간경계, 정확한 혜택 6종과 코드 무관 recipient-wide overlap, GENERAL 미생성, 승인금액 bigint와 안정 GET/POST |
| W1D | 계약·인정전환 | 최소 계약과 독립 signer snapshot, `contract_no` 부재, first-contract 수급자번호 원자 채번, 계약 overlap/재활성화 금지, read-only preview, replacement multiset, 인정·등급·계약 stale, 단일 transaction rollback/audit, confirm/stale UI |
| W1E | 배정 | 요양보호사 기간·자격·reverse guard, 다중 일반배정, 가족관계 snapshot, 배정변경 care-change side effect 부재, 월 사회복지사·간호사 current/history와 역할 유효성 |
| W1F | 통합 봉인 | Wave 0 회귀, 전체 `ABS`, fresh/downgrade/offline PostgreSQL, OpenAPI 생성 일치, frontend unit·DOM·lint·build, 실제 PG Playwright, backup/restore W1 postcheck, 합성자료만 사용, exact SHA clean tree와 독립검수 |

각 작업단위는 해당 DB migration보다 의미 테스트와 `ABS/OA` 테스트를 먼저 추가한다. 후속
단위가 앞 단위의 DTO나 테이블명을 테스트에서 직접 import해 구조를 고착시키지 않도록,
공개 API와 DB catalog/transaction 관찰을 우선한다. P5에 없는 추가 작업단위는 만들지
않는다.

## 14. Wave 1 종료 gate

다음 gate는 현재 v2.1 제품 저장소의 같은 정확한 implementation commit SHA에서
재현되어야 한다. 각 micro-slice는 자기 범위를 실행하고 W1F에서 전체를 봉인한다.

1. **정적·빠른 gate**
   - backend `SEM/API/OA` tests
   - frontend unit/DOM, lint, TypeScript build
   - OpenAPI→TypeScript 독립 재생성 일치
   - 전체 `ABS` token/catalog/schema 검사
   - model·migration·catalog exact name manifest와 `ct_`/`trg_` 종류 검사

2. **PostgreSQL gate**
   - 새 임시 cluster에서 `base→head`
   - Wave 0 head와 W1 head 경계의 downgrade/re-upgrade round trip
   - offline SQL 생성 후 빈 DB 적용
   - application role/grant로 API·제약 테스트
   - forward insert와 reverse parent mutation, 동시성, fault rollback
   - W1A standalone의 공통 service seed·자격증/제공자격 분리·exact 교육 seed
   - 민감 nonce/HMAC 길이·unique·AAD, 건강 사실원장, 분기상담 조건부 CHECK
   - 합성 seed만 사용하고 운영 DSN/실 개인정보 거부

3. **브라우저 gate**
   - mock API로 로딩·빈 상태·409·422·stale 같은 UI 상태를 빠르게 검증
   - 실제 API+실제 임시 PostgreSQL의 W1A 직원 및 W1D 인정전환 핵심 E2E
   - 1440×1000, 1440×900, 1366×768에서 주요 목록/상세/modal의 가로 overflow 없음
   - legacy key, 전체 주민번호, 폐기 필드가 DOM/trace/screenshot에 없음
   - 직원·수급자 이름 클릭 popup 0건과 같은-workspace 목록 문맥 유지
   - 관리자 reveal의 current-PIN step-up·no-store·성공당 access event 1건

4. **backup/restore gate**
   - live data root 내부 destination, maintenance DB, overwrite target 거부
   - dump·manifest·bundle SHA256 검증
   - 새 `*_review` DB와 `sswcenter-restore-review-*` data root에만 복원
   - Wave 0 postcheck뿐 아니라 W1 schema 부재검사와 합성 의미자료 count/hash 검증
   - 복원 DB에서 최소 read API와 W1A 직원 identity·재직·정규화·마스킹,
     `display_name`·`memo`, license/qualification, training seed 불변성 smoke

5. **출구 gate**
   - Wave 0 회귀 포함 전 테스트 PASS
   - 정확한 SHA와 clean tree
   - 독립검수 승인 증거
   - Wave 2 착수 전 기준 tag와 evidence/report 고정

## 15. 명시적으로 하지 않을 일

- 구 Wave 1·2 product code, migration, DTO, generated TS 또는 component를 복사하지 않는다.
- F-016의 구 migration upgrade를 clean rebuild의 migration 목표로 되살리지 않는다.
- 구 test가 통과하도록 `contract_no`, payer type, guardian FK, issued-date required,
  care-change/care-plan 구조를 호환용으로 추가하지 않는다.
- mock-only Playwright, SQLite, in-memory repository로 PostgreSQL 불변조건을 대체하지 않는다.
- 업무오류를 단순 500으로 두거나 raw constraint 이름으로 클라이언트가 분기하게 하지 않는다.
- backup 생성 성공만으로 복원 가능성을 선언하지 않는다.
