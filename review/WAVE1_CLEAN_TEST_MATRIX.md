# Wave 1 Clean Rebuild 테스트 매트릭스

> 상태: SSWCenter 3.0 현재 정본의 Wave 1 실행 명세
> 기준일: 2026-08-13 KST
> 지위: 정본 계약을 테스트 ID와 기대결과에 연결한다. 실행 SHA·수치·과거 결과는 별도 증거가 소유한다.

## 🚨 형님 승인 절대 게이트

> **형님 승인 없이 어떠한 계약도 추가하거나 삭제하지 않는다.**
> 구 테스트를 통과시키기 위해 폐기 필드·상태·경로를 되살리지 않는다.

## 1. 기준과 테스트 층

| 영역 | 단일 원문 |
|---|---|
| 업무 의미 | `docs/02_업무규칙_계약_v1.1.md` |
| UI·API 상호작용 | `docs/03_UI_API_상호작용_계약_v1.2.md` |
| PostgreSQL 불변조건 | `docs/04_데이터_DB_불변조건_v4.8_PostgreSQL.md` |
| 공통 기술·보안 | `docs/05_기술_보안_파일처리_아키텍처_v1.5.md` |
| 실행순서·미결 | `docs/06_개발로드맵_결정현황_v1.2.md` |

| 표기 | 의미 |
|---|---|
| `SEM` | 순수 업무 의미·경계값 |
| `PG` | 실제 격리 PostgreSQL 제약·transaction·동시성 |
| `API` | 세션·CSRF·권한·오류봉투 |
| `OA` | OpenAPI·생성 TypeScript |
| `DOM` | 사용자에게 관찰되는 UI |
| `E2E` | 실제 API·PostgreSQL·브라우저 흐름 |
| `ABS` | 폐기·미래 구조 부재 |
| `BR` | backup/restore와 migration lifecycle |

공통 원칙:

- 기간 경계는 양 끝 날짜를 포함한다.
- DB 불변조건은 SQLite·mock·단위 테스트로 대체하지 않는다.
- 같은 version의 동시 쓰기는 실제 두 connection과 barrier로 검증한다.
- OpenAPI는 임시 위치에 독립 재생성해 checked-in 생성 타입과 비교한다.
- 실제 개인정보·운영 DB·운영 파일을 테스트에 사용하지 않는다.

## 2. 공통 계약

| ID | 요구사항 | PASS 기준 |
|---|---|---|
| `W1-CMN-01` | 변경 권한·CSRF·version | 동일 version 동시 요청 중 하나만 성공, 패자 409, 부분 write·성공 audit 0건 |
| `W1-CMN-02` | 결정적 목록 | 정렬 동률에도 안정 PK가 마지막 키이고 pagination 누락·중복 없음 |
| `W1-CMN-03` | 오류·비밀 비노출 | raw SQL·constraint·stack·DSN·주민번호·PIN·session token이 응답·로그·감사에 없음 |
| `W1-CMN-04` | OpenAPI 기술 원본 | backend OpenAPI와 독립 재생성 TypeScript가 일치하고 생성파일 수동수정 없음 |
| `W1-CMN-05` | 기존 Wave 0 보존 | auth/session/CSRF/audit와 `staff.display_name`·`staff.memo` 값이 upgrade/restore 뒤 보존 |
| `W1-CMN-06` | migration 전진성 | 적용된 revision 수정 없이 fresh upgrade와 이전 head upgrade가 단일 head로 성공 |
| `W1-CMN-07` | 실패 원자성 | validation·constraint·fault 어느 실패에서도 업무행·counter·감사가 일부만 남지 않음 |

## 3. W1A 직원

| ID | 요구사항 | DB·API·UI 기대 | 핵심 검증 |
|---|---|---|---|
| `W1-STF-01` | 직원 identity·재직·재입사 | 직원 ID 유지, 재입사마다 새 재직 ID·번호, 기간중복 거부 | 번호 경쟁·기간경계·rollback `PG/E2E` |
| `W1-STF-02` | 직종·업무역할 분리 | 별도 기간원장과 화면, 재직범위 양방향 보호 | 부모 단축과 같은 transaction 정정 |
| `W1-STF-03` | 주민번호 보안 | 신규 일반직원 필수, 암호화·HMAC·마스크, 관리자 POST+PIN reveal | 평문 0건·성공당 access event 1건 |
| `W1-STF-04` | 자격증·서비스 제공자격 분리 | 자격증 3종 seed, 일반 CRUD 3개 이상, 제공자격은 재직·서비스 기간원장 | wrong-staff source·containment·reverse guard |
| `W1-STF-05` | 교육 정확히 8종 | 신규직원교육 1 + 정기교육 7, 보수교육 포함, 완료 boolean만 | seed exact 8·재입사 유지·감사 |
| `W1-STF-06` | 건강검진일만 저장 | 검진일 외 상태·면제·사유·유형·결과·파일 없음 | 신규 1년 경계(2026-08-15이면 2025-08-16 포함), 기존 연 1회, 12월 30일 퇴사 제외, 재입사 신규 취급 |
| `W1-STF-07` | 분기상담 완료 토글 | 직원·연도·분기 unique, completed boolean만 | 상담일·내용·사유·면제·파일 부재, 완료/해제 감사 |
| `W1-STF-08` | legacy mapping 내부전용 | 공개 API·검색·DOM·출력에 legacy key 없음 | 합성 이관과 공개 schema `ABS` |

## 4. W1B 수급자·보호자·납부자 선택

| ID | 요구사항 | DB·API·UI 기대 | 핵심 검증 |
|---|---|---|---|
| `W1-REC-01` | 수급자 필수값은 휴대전화만 | 이름·생년월일·성별·우편번호·주소·메모 nullable, mobile nonblank, 자택전화 없음 | 최소 생성·빈 이름 round trip·필수/선택 OA/DOM |
| `W1-REC-02` | 빈 이름 표시 | 저장값은 바꾸지 않고 목록·카드에서 `미입력` | API projection·DOM exact text |
| `W1-REC-03` | 수급자번호 | 최초 계약 transaction에서 한 번 발급 후 immutable | 동시 최초계약·rollback·재계약 불변 |
| `W1-GUA-01` | 보호자 최대 2명 | slot 1·2만, 이름·관계·전화·주소·이메일 모두 선택 | 0/1/2명 성공, 3명·필수 강제 실패 |
| `W1-GUA-02` | 대표보호자 없음 | 대표여부·대표기간·대표변경 API/UI/DB 없음 | catalog/OA/DOM `ABS` |
| `W1-PAY-01` | 보호자 납부 선택 | 보호자1/2 선택 또는 NULL=수급자 본인, 같은 수급자 FK | 타 수급자 보호자 거부·삭제 시 본인 복귀 |
| `W1-PAY-02` | 별도 납부자·서명자 없음 | payer 원장/입력필드/type/snapshot과 계약 signer 필드 없음 | DB/OA/TS/DOM `ABS` |

## 5. W1C 인정기간·등급·혜택·승인금액

| ID | 요구사항 | DB·API·UI 기대 | 핵심 검증 |
|---|---|---|---|
| `W1-CERT-01` | 인정 본번호 | `L+10자리`, suffix 제거, 수급자 1:1·전역 unique | 소문자/suffix·타 수급자·동시소유 충돌 |
| `W1-CERT-02` | 인정기간과 등급 단일 원장 | 인정기간마다 grade 1~5 하나, 기간중복 거부 | 별도 등급기간/등급변경일 부재, 정정 이력 |
| `W1-CERT-03` | 별도 등급행 교정 | 기존 등급행이 인정기간과 정확히 1:1·동일 날짜일 때만 합침 | 불일치 migration fail-closed |
| `W1-BEN-01` | 혜택 6종·초기 GENERAL | 수급자 생성 transaction에서 GENERAL 1건, 현재 혜택 최대 1건 | 생성 rollback 원자성·중복 current 경쟁 |
| `W1-BEN-02` | 시작값은 표시 텍스트 | 최초 `''`, date parse·기간검증·마감계산 없음 | 날짜처럼 보이는 문자열도 원문 round trip |
| `W1-AMT-01` | 승인금액 기간원장 | 원 단위 bigint, 수급자별 기간중복 거부, 이력 보존 | 경계·동시중복·결정적 목록 |
| `W1-ABS-CERT-01` | 인정 전환 삭제 | preview/apply route·service·function·UI 없음 | DB/API/OA/TS/DOM 부재 |

## 6. W1D 서비스계약

| ID | 요구사항 | DB·API·UI 기대 | 핵심 검증 |
|---|---|---|---|
| `W1-CON-01` | 최소 계약 | 서비스·시작일만 필수, 종료일·급여개시일·종료사유 선택 | 최소 201·round trip |
| `W1-CON-02` | 기간 충돌 | 같은 서비스와 상호배타 그룹 충돌, 허용된 같은 그룹 서비스 공존 | same-day·open-ended·동시삽입 `PG` |
| `W1-CON-03` | 종료계약 재활성화 금지 | 재이용은 새 계약, 과거 계약 보존 | reactivate route/button 부재 |
| `W1-CON-04` | 계약서명자 삭제 | signer 컬럼·request property·입력·표시 없음 | DB/OA/TS/DOM `ABS` |

## 7. W1E 배정

| ID | 요구사항 | DB·API·UI 기대 | 핵심 검증 |
|---|---|---|---|
| `W1-ASG-01` | 요양보호사 계약별 기간배정 | 계약·재직·제공자격 containment, 가족관계 snapshot, 여러 일반 제공자 허용 | forward/reverse guard·동시중복 |
| `W1-ASG-02` | 배정변경은 교체상담 아님 | Wave 3 실제근무 전 카드 side effect 없음 | trigger/service/API/DOM `ABS` |
| `W1-MON-01` | 월 전문직 담당 1명 | 방문요양+방문목욕을 합친 수급자·월 슬롯 하나, 사회복지사/간호사는 같은 역할 | 두 직종 동시담당 거부·월중 변경 history·공백 허용 |

## 8. Wave 2 경계 수용점

Wave 1에서는 아래 제품 구조가 없어야 하지만, Wave 2 구현은 다음 의미를 지킨다.

| ID | 승인 의미 | Wave 1 ABS | Wave 2 핵심 테스트 |
|---|---|---|---|
| `SEM-W2-01` | 공식카드 5종·카드정보 5개 | 카드 table/API/UI 없음 | enum 범위·DOM exact field·추가 금지 |
| `SEM-W2-02` | 공식카드 권한·닫기 | 카드 권한 side effect 없음 | 본인만 닫기, 관리자 직원별 read-only, 재개방 없음 |
| `SEM-W2-03` | 카드 날짜·우선순위 | D-day worker 없음 | 인정 D-100, 계약 D-45, 작성마감 D-45, 인정>계약>계획서 원자 교체 |
| `SEM-W2-04` | 개인 할 일 | todo table/API/localStorage 없음 | 본인만·토글·회색·완전삭제·드래그·단일 편집창 409 |
| `SEM-W2-05` | 원장·화면 분리 | Dashboard 개인 할 일 없음 | 공식=Dashboard, 개인=사회복지사 달력, 합침 API/union 없음 |
| `SEM-W2-06` | 공용 일정 원장 | schedule/month-control 없음 | 수급자/직원 동일 PK, 재직·자격 밖 draft 허용, 확정 거부 |
| `SEM-W2-07` | 일정 동시성 | schedule lock 없음 | 월 제어행 잠금, PK 순서, 먼저 저장 1건, 패자 최신 snapshot 409, 자동병합 없음 |
| `SEM-W2-08` | Dashboard 마감일 | 서버 카드목록 없음 | 페이지당 최소 15건, overflow 때만 페이지 이동 |

## 9. 폐기구조 부재 gate

| ABS ID | 남아 있으면 FAIL |
|---|---|
| `W1-ABS-01` | 수급자 이름·생년월일·성별 필수 또는 자택전화 필드 |
| `W1-ABS-02` | 보호자 3명 이상·보호자 필수필드·대표보호자/대표기간 |
| `W1-ABS-03` | 독립 납부자 원장·payer type·계약서명자 필드 |
| `W1-ABS-04` | 별도 등급기간 원장·인지지원등급·인정 전환 |
| `W1-ABS-05` | GENERAL 미생성 또는 혜택 시작텍스트 날짜 사용 |
| `W1-ABS-06` | 건강검진 대상상태·면제·사유·유형·결과·파일 |
| `W1-ABS-07` | 분기상담 날짜·내용·사유·면제·파일 |
| `W1-ABS-08` | 전문직 역할별/서비스별 중복 담당 슬롯 |
| `W1-ABS-09` | 공식카드 진행률·상태단계·공개 생성/삭제/재개방 |
| `W1-ABS-10` | 공식카드·개인 할 일 합침 API·Dashboard 개인 할 일·todo localStorage |
| `W1-ABS-11` | Wave 3 실제근무·RFID·공단 source 또는 미래 nullable FK 선구현 |
| `W1-ABS-12` | `contract_no`·고정 종료사유·급여개시일 필수화·구 deprecated 호환필드 |

## 10. 통합 종료 gate

1. 정본문서와 matrix 금지토큰·링크 일치.
2. fresh DB와 이전 head에서 전체 migration upgrade, 단일 head, application role grant.
3. 실제 PostgreSQL 제약·reverse guard·두 connection 동시성·fault rollback.
4. backend unit/API/OA/lint/type과 OpenAPI 독립 재생성 일치.
5. frontend unit/DOM/lint/build와 실제 PostgreSQL·API Playwright.
6. 합성자료만 사용한 backup/restore와 핵심 count/hash·read smoke.
7. 동일 후보의 독립 read-only 검수와 미검증 항목 0건.
