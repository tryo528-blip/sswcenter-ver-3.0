# W2 급여계획서(Service Plan Notice) 상세 작업계획 (small-slice, DB/contract only)

> 문서 상태: `DRAFT_PROPOSED` — 아직 구현·RED·GREEN 없음. 이 문서는 설계 제안이며
> 정본 문서(02·03·04·06)를 수정하지 않는다.
>
> 작성일: 2026-08-09 KST
>
> 기준 branch: `main` (v3.8, W1F PASS 이후 최초 Wave 2 후보)
>
> 설계 기준 HEAD: `ffd7a6991de3d56403801262a95b796b98da8907`
>
> 개정 이력: 2026-08-09 Codex 독립검수 1라운드(FAIL, findings 4건) 반영 개정 —
> 인정기간 FK 컬럼 미저장 결정(형님 확정: 인정 근거의 authoritative source는
> 공단 전산이며 이 ERP는 유효 종료일 계산만 하면 됨) + 역방향 guard 신설,
> cap 계산의 NULL 가정 오류 수정, RED 범위 확장, 06 anchor 인용 수정. 2라운드
> (FAIL, findings 5건) 반영 재개정 — (a) D-100/D-45를 "미정"으로 지운 게
> 과했음을 확인: `02` §9.1(line 399)·`03` §7(line 391)이 이미 적용종료일
> 기준 D-100/D-45를 봉인했고 이 문서는 정본을 수정하지 않는다고 스스로
> 선언했으므로 되돌림. (b) 역방향 guard를 W1E 수준(생존 필터·DEFERRABLE·
> 동일 트랜잭션 대체 허용·계약 대체 포함)으로 구체화. (c) 정방향
> guard에 "연결 계약이 무효화 상태가 아닐 것" 조건 추가. (d) migration
> 안전성 절 신설. (e) 04 §11/§6.2 anchor의 과잉 서술 제거, orphan guard
> 근거를 실제 위치(04:241–243)로 교정, W2-07 line 번호 교정(142).
> 4라운드(FAIL, findings 4건) 반영 재개정 —
> (a) D-100/D-45 기준이 2라운드 당시 '적용종료일'에서 이후 '작성마감일'로
> 정본 봉인되었음을 확인, 상기 2라운드 이력의 '적용종료일 기준'은 당시
> 사실이나 현재는 작성마감일 기준이므로 주의. (b) 동시성/잠금을 per-recipient advisory lock으로 전환
> (이후 5라운드에서 DEFERRABLE trigger와의 양립 불가로 SERIALIZABLE로
> 대체됨). (c) recipient_contract·recipient_
> certification_period의 recipient_id immutability CHECK 및 OLD+NEW
> 역방향 guard 신설(W1E 선례). (d) D-45/D-100 목적 매핑의 02/03 봉인
> 과잉 주장 제거. (e) anchor line 범위를 작성마감일 전체로 교정.
>
> 단일 writer: 미배정 (이 문서 다음 단계에서 Task Packet으로 전환)
>
> matrix: 신규 — Wave 1 매트릭스에는 없음. Wave 2 착수 시
> `review/WAVE1_CLEAN_TEST_MATRIX.md`와 동급 Wave 2 매트릭스 항목을 새로 등록해야
> 한다(이 문서는 그 등록을 대신하지 않는다).

## 0. 이 문서가 정하는 것과 정하지 않는 것

- 정함: `recipient_service_plan_notice`(급여계획서) 테이블의 DB 불변조건,
  기본 종료일 계산과 cap 규칙(위반 시 저장 거부), migration 안전성, 제안
  실패코드, RED 테스트 범위 제안.
- 정하지 않음: API·UI·업무카드(D-100/D-45) 표시 엔진, 일정·직원교체·확정월.
  이들은 아래 §3에서 명시적으로 제외한다. 정본 문서 anchor는 인용만 하며
  수정하지 않는다.
- 여기 적힌 object 이름·컬럼·실패코드는 **제안값**이며 Task Packet 작성과
  독립검수 단계에서 확정된다.

## 1. 정본 anchor

| 영역 | 참조(비수정) |
|---|---|
| 업무 | `02_업무규칙_계약_v1.1.md` §9.1 급여계획서 (line 390–403, 2026-08-09 수정: 기간 불일치·연결자료 부족은 저장 거부, 작성마감일 산식 포함) |
| UI 오류 표시 | `03_UI_API_상호작용_계약_v1.2.md` §7 (line 381–409, 2026-08-09 수정: 작성마감일 산식·D-100/D-45·저장 거부 오류 포함) |
| DB 경계선언 | `04_데이터_DB_불변조건_v4.8_PostgreSQL.md` §12 Wave 2·3 경계 (line 755–785) |
| 계약 FK 대상 | `04` §8.2 `recipient_contract` (line 592–605) |
| 인정기간 스키마 참조 | `04` §6.2 `recipient_certification_period` (line 499–508) |
| PERIOD_FACT 정정 의미(참고) | `04` §11 (line 707–730) |
| orphan 금지·역방향 guard 의무 근거 | `04` §3.5 (line 241–243, W1E `care_assignment` 사례) |
| 로드맵 | `06_개발로드맵_결정현황_v1.2.md` §1 Wave 2 행 (line 27), §5 Wave 2 성숙도 (line 129) |
| (참고) legacy 통보일 테이블 | `backend/alembic/versions/20260803_0014_recipient_plan_notification.py` — 기존 `erp.recipient_plan_notification` 테이블 + `backend/app/domains/recipient/service.py`의 `_plan_renewal_due_date()` 함수. 본 슬라이스와 **공존**하며, 개편·폐기는 API/service/work-card 슬라이스로 분리됨(§5b) |

## 2. 봉인 범위 제안 (SEALED 후보 — 급여계획서 DB 계약만)

1. **계약 연결** — `recipient_service_plan_notice.recipient_contract_id`는
   `recipient_contract(id)`로의 필수 RESTRICT FK다. 계약이 없으면 계획서를
   만들 수 없다. FK 존재만으로는 부족하다 — 연결된 계약이 **이미 무효화된
   행**(`invalidated_at_utc IS NOT NULL`)이면 INSERT/UPDATE를 거부한다.
   `recipient_contract`는 정정을 무효화+대체로 처리하므로(`04` 공통 규칙,
   line 82) 무효화된 계약 행도 테이블에 남아있어 FK만으로는 걸러지지 않는다.
   단, 이 검사는 계획서 자신이 최종 커밋 시점에서 유효(`invalidated_at_utc
   IS NULL`)일 때만 적용한다 — 같은 트랜잭션에서 기존 계획서를 무효화하고
   대체 계획서를 삽입하는 정당한 원자적 정정은, 무효화된 옛 행을 검사하지
   않고 살아있는 대체 행만 검사한다(§2-7 DEFERRABLE 지연평가와 동일 구조).
2. **기본 종료일 계산** — 통보월 1~6월은 같은 해 12월 31일, 7~12월은 다음 해
   6월 30일이 기본 `applied_end_date`다. 이 계산은 계획서 생성 시 한 번
   고정되는 값이며(추후 통보월 변경 시 재계산하지 않음), 사용자가 다른 값을
   명시적으로 지정하면 그 값을 우선한다.
3. **cap 규칙** — `applied_end_date`는 연결된 계약의 `end_date`와, 그 시점에
   유효한 **같은 수급자의** `recipient_certification_period.end_date` 중 더
   빠른 날짜를 초과할 수 없다. 인정기간은 반드시 계약 소유 수급자와 동일한
   `recipient_id`를 가져야 한다(`04` §6.2, line 504 — `recipient_id` FK;
   `04` §8.2, line 592–605 — `recipient_contract`도 `recipient_id` 보유).
   다른 수급자의 인정기간은 cap 검사에 사용하지 않는다.
   `recipient_contract.end_date`만 NULL(무기한)일 수 있다(`04` §8.2,
   line 600); `recipient_certification_period.end_date`는 NOT NULL이다(`04`
   §6.2, line 505). 계약이 무기한이면 인정기간 `end_date`가 유일한 cap
   기준이며, 둘 다 유효한 날짜를 가지면 더 빠른 쪽이 cap이다.
4. **기간 불일치·연결자료 부족은 저장 거부** — cap 초과 시도나 해당 시점에
   유효한 **같은 수급자의** 인정기간이 없는 경우, 그 INSERT/UPDATE는
   거부된다(경고 후 저장 허용 없음). W1E `care_assignment`의 정방향 guard와
   동일한 hard-reject 패턴을 그대로 재사용한다.
   **`recipient_certification_period_id`는 컬럼으로 저장하지 않는다
   (2026-08-09 형님 확정)** — 인정 자격의 authoritative source는 공단
   전산이며, 이 ERP는 계획서가 몇 번 인정서에 귀속되는지 감사추적할 필요
   없이 유효 종료일 계산만 하면 된다. 검증은 저장 시점의 동적 조회로만
   수행한다(FK 없음, W1E와 동일 — 정방향 guard만으로는 부족한 나머지 절반은
   §2-7 역방향 guard가 담당한다).
   모든 정방향 검사는 계획서 자신이 최종 커밋 시점에서 유효(`invalidated_at_utc
   IS NULL`)일 때만 적용된다 — 같은 트랜잭션에서 무효화되는 옛 행은 검사하지
   않는다.
5. **작성마감일(비테이블 불변조건, 정본 인용)** — `02` §9.1(line 399–402)과
   `03` §7(line 391–392)이 2026-08-09 봉인한 대로, **작성마감일**(다음
   계획서를 새로 작성해야 하는 기한)은 지난 통보일로부터 6개월 뒤이며,
   연결 계약 종료일과 그 시점 유효 인정 종료일 중 가장 빠른 날짜로
   cap한다. 갱신 내부 업무는 작성마감일 D-100, 메인 카드 노출은
   작성마감일 D-45다. 이 슬라이스는 그 *날짜 계산*(지난 통보일+6개월 후
   cap 적용)만 순수 함수로 제공하고, 실제 업무카드 생성·표시·상태 전이는
   §3에서 제외한다. (참고 배경: D-45는 계약 종료에 임박한 인원배치 알림,
   D-100은 보호자 책임 인정갱신 알림이라는 실무 목적 구분이 있으며, 이
   문서의 설명적 맥락일 뿐 `02`/`03` 정본에 봉인된 것은 작성마감일 산식과
   'D-100 내부 업무, D-45 메인 카드' 레이블뿐이다. 업무카드 엔진 자체는
   여전히 §3에서 제외된다.)
6. **PERIOD_FACT 정정** — 계획서 정정은 기존 행을 무효화하고 새 행을 만든다
   (W1D/W1E와 동일한 공통 무효화·대체·감사·`row_version` 규칙, `04` 공통 규칙
   재사용— 이 슬라이스가 새로 발명하지 않는다).
7. **역방향 guard(신규, W1E `care_assignment` §5.4와 동일 수준)** —
   `recipient_contract_id`는 저장된 FK지만 계약의 `end_date`·`start_date`
   변경이나 계약 무효화를 FK만으로 막을 수 없고, 인정기간 쪽은 아예 저장된
   참조가 없다. 양쪽 모두에 W1E와 동일한 형태의 부모 테이블 역방향
   constraint trigger를 추가한다(`04` §3.5 orphan 금지 의무, line 241–243;
   W1E 참조 `W1E_CARE_ASSIGNMENT_PLAN.md` §5.4, line 170–187):
   - **대상 사건**: 계약 단축(시작 늦춤/종료 당김)·무효화·**대체**(W1E와
     동일하게 세 가지 모두 — 단축뿐 아니라 대체도 포함), 인정기간 단축·
     무효화·대체·**DELETE**. `recipient_contract`는 `care_assignment`와
     본 테이블의 RESTRICT FK로 인해 참조 행이 존재하면 DELETE 자체가
     거부되므로 역방향 guard에서 DELETE를 별도 감시할 실익이 없으나,
     `recipient_certification_period`는 계획서 쪽에 저장된 FK가 없으므로
     인정기간 행의 DELETE가 살아있는 계획서를 조용히 orphan시킬 수 있어
     DELETE도 반드시 감시한다.
   - **생존 필터**: 이미 무효화된(`invalidated_at_utc IS NOT NULL`) 계획서는
     역방향 guard 검사 대상에서 제외한다(W1E line 197과 동일 — "유효" 집합만
     보호).
   - **수급자 범위**: 인정기간 역방향 guard는 계획서가 연결된 계약의
     `recipient_id`와 동일한 `recipient_id`를 가진
     `recipient_certification_period` 행만 검사 대상으로 삼는다.
   - **DEFERRABLE INITIALLY DEFERRED**: 정방향·역방향 guard 모두 트랜잭션
     종료 시점까지 지연 평가한다(`04` line 172–174). 이 덕분에 "계약을
     단축하면서 동시에 영향받는 계획서를 같은 트랜잭션에서 정정"하는 정당한
     원자적 수정은 최종 상태만 일관되면 통과하고, 정정 없이 방치된 경우만
     거부된다.
   - **REQUIRED CALLER CONTRACT — SERIALIZABLE 격리수준(2026-08-09
     Codex 5라운드 수정)**: 이전 4라운드에서 시도한 per-recipient advisory
     lock 설계는 DEFERRABLE INITIALLY DEFERRED constraint trigger와
     구조적으로 양립할 수 없어 폐기되었다. 대신 PostgreSQL의 표준 해법인
     **Serializable Snapshot Isolation (SSI)**에 위임한다:
     - **REQUIRED CALLER CONTRACT** — `recipient_service_plan_notice`,
       `recipient_contract`, `recipient_certification_period`에 대해 이
       적용범위(cap/coverage) 판단에 영향을 줄 수 있는 INSERT/UPDATE/DELETE를
       수행하는 모든 트랜잭션은 **SERIALIZABLE 격리수준**으로 실행해야 한다
       (`SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`).
     - PostgreSQL의 SSI는 이 설계가 우려했던 write-skew race를 자동으로
       탐지한다: 부모 계약·인정기간을 단축·무효화·재귀속하는 트랜잭션과,
       동일한 부모 행의 pre-change 스냅샷에 의존하여 새 recipient_service_
       plan_notice를 INSERT하는 동시 트랜잭션이 경합할 때, PostgreSQL SSI가
       read-write anti-dependency cycle을 감지하여 둘 중 하나를 `40001
       serialization_failure`로 중단시킨다.
     - 호출자는 `40001`을 catch하여 트랜잭션을 재시도해야 한다(재시도 시
       guard가 정합성을 다시 평가하여, 조건을 만족하면 통과하고 아니면 거부).
     - 격리수준 강제와 retry loop 구현은 **API/service 계층의 책임**이며,
       본 DB-contract-only 슬라이스(§3)의 범위가 아니다. 이 슬라이스의
       migration은 DEFERRABLE INITIALLY DEFERRED constraint trigger 자체만
       제공하고(최종 커밋 상태 정합성 검증 + 동일 트랜잭션 원자적 다단계
       정정 허용, 이는 동시성 직렬화와 별개의 여전히 유효한 속성), 트랜잭션
       격리수준을 설정하거나 강제하지 않는다.

8. **부모 recipient_id 재귀속(re-keying) 방어(신규)** —
   `backend/alembic/versions/20260730_0010_w1c_certification_ledgers.py`와
   `20260730_0011_w1d_recipient_contract.py`에서 `recipient_contract`와
   `recipient_certification_period`의 `recipient_id`는 현재 일반 updatable
   컬럼이며 immutability guard가 없다. 누군가 기존 계약이나 인정기간의
   `recipient_id`를 다른 수급자로 UPDATE하면, 살아있는 계획서의 적용범위가
   조용히 잘못된 수급자에게 재귀속되어 orphan이 발생할 수 있고, 현행
   역방향 guard(단축·무효화·대체만 감지)는 이 사건을 감지하지 못한다.
   - **문서 검토 결과**: `docs/02`와 `docs/06` 어디에도 이 두 테이블의
     `recipient_id`를 의도적으로 재귀속(reparent)하는 업무 시나리오는
     존재하지 않는다(`06`의 `W1-01`은 직원 주민번호 이전/합치기이며 수급자
     자식원장의 `recipient_id` 변경과 무관).
   - **선택한 접근법 — immutability CHECK + 역방향 guard 이중 방어**:
     (i) 본 슬라이스의 migration에서 `recipient_contract`와
     `recipient_certification_period` 각각에 `recipient_id` 변경을 거부하는
     `BEFORE UPDATE` trigger를 추가한다. `OLD.recipient_id IS DISTINCT FROM
     NEW.recipient_id`이면 `23514`(`check_violation`)로 거부 — 이는 `04`
     §11 (line 718)의 인정 본번호 immutability 패턴(`fn_recipient_
     certification_number_immutable`) 및 `W1C`
     `20260730_0010_w1c_certification_ledgers.py`의 `bu_recipient_
     certification_number_immutable` trigger와 동일한 관행이다.
     (ii) 이중 안전장치로, 계약·인정기간 역방향 guard도 `recipient_id`
     변경 시 OLD 수급자의 계획서를 검사한다(OLD+NEW 양쪽 평가). 이는
     `W1E_CARE_ASSIGNMENT_PLAN.md` 및 `backend/tests/test_w1e_contract.py`
     (line ~2405–2471 근방)의 OLD-key 검증 선례를 따른다.
   - immutability CHECK가 1차 방어선이며, 역방향 guard의 OLD+NEW 검사는
     만약의 CHECK 우회(예: `ALTER TABLE ... DISABLE TRIGGER <name>`으로
     immutability trigger가 명시적으로 비활성화된 후 재활성화되지 않은
     경우)에 대한 벨트-and-braces 보호다. 단, `session_replication_role =
     replica` 등 광범위한 트리거 우회 수단은 역방향 guard 자체도 함께
     비활성화하므로 이 방어선으로 막을 수 없음에 유의한다.

## 3. 명시적 제외 (다음 슬라이스로 분리)

- **공식 업무카드 엔진**(`02` §9.3): `COMPLETE`/`INCOMPLETE`/`EXEMPT`/`WAITING`
  상태, 발생이유, 단계별 완료, 역할별 범위 제한. 이 슬라이스는 D-100/D-45
  *날짜만* 계산하고(§2-5, 작성마감일 기준 — 산식은 `02`/`03`에 봉인 완료)
  카드 테이블·상태 전이·표시·트리거 메커니즘은 만들지 않는다.
- **월간 일정·확정월**(`02` §9.4): 별도 슬라이스.
- **실제 급여제공 기반 직원교체**(`02` §9.2): `W2-07`
  (`06` line 142, `DESIGN_REQUIRED`)로 이미 차단됨 — 실제근무 정정·재판정
  계약이 확정되기 전까지 착수하지 않는다.
- API·UI·service 구현.
- 실 PostgreSQL GREEN·live DB 실행, migration 적용.
- branch 변경·staging·commit·push.

## 4. 위협 모델

| 위협 | 결과 | 방어 |
|---|---|---|
| 계약 없는 계획서 | orphan 계획서, 무의미한 급여 판정 근거 | `recipient_contract_id` 필수 RESTRICT FK |
| 이미 무효화된 계약에 계획서 연결 | FK는 통과하지만 근거가 죽은 계약 | 정방향 guard가 `invalidated_at_utc IS NULL`도 함께 검사(§2-1) |
| cap 초과를 저장 | 계약·인정 종료 후에도 급여계획이 유효한 것처럼 보임 | cap 초과 INSERT/UPDATE를 hard-reject |
| 인정기간 미연결 상태로 저장 | 근거 없는 급여계획이 살아있음 | 해당 시점 유효 인정기간 부재 시 hard-reject |
| 통보월 계산 규칙 우회(다른 기본값) | 반기 cap 규칙 무력화 | 기본값은 애플리케이션이 아니라 이 패킷의 RED가 정확한 계산식을 계약으로 고정(회귀 시 즉시 실패) |
| 계약/인정기간을 저장 이후에 단축·무효화·대체 | `recipient_contract_id` FK는 저장되었으나 계약의 `end_date`·`start_date` 변경·무효화를 FK만으로 막을 수 없고, 인정기간은 저장된 참조 자체가 없어 이미 저장된 계획서가 cap을 초과한 채로 조용히 남을 수 있음 | `recipient_contract`·`recipient_certification_period`에 역방향 constraint trigger 추가, 세 사건(단축/무효화/대체) 모두 포함(§2-7) |
| 정당한 동시 정정을 오탐 차단 | 계약·계획서를 같은 트랜잭션에서 함께 고치는 정상 작업이 막힘 | 모든 guard `DEFERRABLE INITIALLY DEFERRED`로 트랜잭션 종료 시점 평가(§2-7) |

## 5. 테이블 계약 제안

`recipient_service_plan_notice`:

| 컬럼 | 규칙 |
|---|---|
| `id` | bigint `GENERATED BY DEFAULT AS IDENTITY` PK |
| `recipient_contract_id` | 필수 RESTRICT FK → `recipient_contract(id)` |
| `notification_date` | NOT NULL |
| `applied_start_date` | NOT NULL |
| `applied_end_date` | NOT NULL; `applied_start_date` 이후 CHECK |
| 무효화·대체·감사·`row_version` | 공통 규칙(W1D/W1E와 동일 패턴) |

`recipient_certification_period_id`는 의도적으로 컬럼에 넣지 않는다(§2-4
결정, 2026-08-09 형님 확정). 인정 근거는 저장 시점 동적 검사로만 확인하고,
저장 이후의 보호는 역방향 guard(§2-7)가 맡는다.

CHECK/trigger 불변조건(제안, W1E `care_assignment` 정방향 guard와 동일한
hard-reject 패턴. 모든 검사는 계획서 자신이 최종 커밋 시점에서 유효
(`invalidated_at_utc IS NULL`)일 때만 적용 — 같은 트랜잭션에서 무효화되는
옛 행은 검사하지 않는다. **REQUIRED CALLER CONTRACT**: 이 테이블에 대한
INSERT/UPDATE와, `recipient_contract`·`recipient_certification_period`에
대한 cap/coverage-affecting DML을 수행하는 모든 트랜잭션은 SERIALIZABLE
격리수준으로 실행해야 한다(§2-7 REQUIRED CALLER CONTRACT 참조). 격리수준
강제와 40001 재시도는 API/service 계층 책임이며 본 슬라이스 범위가 아니다):

- `applied_end_date >= applied_start_date`.
- `applied_start_date`가 연결된 `recipient_contract.start_date`보다 앞서면
  거부. 실패코드 제안: `SERVICE_PLAN_BEFORE_CONTRACT_START`.
- 연결된 `recipient_contract`가 무효화 상태(`invalidated_at_utc IS NOT NULL`)면
  거부. 실패코드 제안: `SERVICE_PLAN_CONTRACT_INVALIDATED`.
- `applied_end_date`가 연결된 `recipient_contract.end_date`를 초과하면 거부
  (`end_date`가 NULL(무기한)이면 이 검사는 건너뛴다). 실패코드 제안:
  `SERVICE_PLAN_OUTSIDE_CONTRACT_PERIOD`.
- `applied_start_date`~`applied_end_date` 전 구간을 커버하는 유효한 **같은
  수급자의** `recipient_certification_period`가 없으면(부분 미보장 포함)
  거부. 인정기간의 `recipient_id`는 계획서가 연결된 계약의 `recipient_id`와
  일치해야 한다. 실패코드 제안:
  `SERVICE_PLAN_OUTSIDE_CERTIFICATION_PERIOD`.

역방향 guard trigger(제안, `04` line 172–174와 동일하게 모두 `DEFERRABLE
INITIALLY DEFERRED`):

| 부모 | guard(제안) | 방식 |
|---|---|---|
| `recipient_contract` | `fn_recipient_contract_service_plan_reverse_guard` / `ct_...` (신규) | 계약 단축(시작 늦춤/종료 당김)·무효화·대체·**수급자 재귀속(re-keying)**으로 유효 계획서가 `applied_start_date < contract.start_date`이거나 `applied_end_date > contract.end_date`가 되어 cap을 위반하게 되면 거부. 이미 무효화된 계획서는 검사 제외. `recipient_id` 변경 시에도 OLD·NEW 양쪽 수급자 모두 검사(OLD 수급자의 계획서가 orphan 되지 않도록, §2-8 W1E OLD-key 선례). `recipient_id` 자체는 아래 §2-8 immutability CHECK로 별도 보호. trigger는 UPDATE에 부착; DELETE는 `care_assignment`와 본 테이블의 RESTRICT FK에 의해 참조 행 존재 시 거부되므로 역방향 guard에서 별도 감시하지 않는다 |
| `recipient_certification_period` | `fn_recipient_certification_period_service_plan_reverse_guard` / `ct_...` (신규) | 인정기간 단축·무효화·대체·**DELETE**·**수급자 재귀속(re-keying)**으로 유효 계획서가 미보장(uncovered)이 되면 거부. **같은 수급자**의 인정기간만 검사. 이미 무효화된 계획서는 검사 제외. `recipient_id` 변경 시에도 OLD·NEW 양쪽 수급자 모두 검사(OLD 수급자의 계획서가 orphan 되지 않도록, §2-8 W1E OLD-key 선례). `recipient_id` 자체는 아래 §2-8 immutability CHECK로 별도 보호. trigger는 INSERT·UPDATE·DELETE에 부착; DELETE는 계획서 쪽에 저장된 FK가 없어 살아있는 계획서를 조용히 orphan시킬 수 있으므로 반드시 감시한다 |

## 5b. Migration 안전성 (제안)

| 항목 | 규칙(제안) |
|---|---|
| upgrade | `recipient_service_plan_notice` 테이블 + 위 CHECK·정방향 guard 신규 생성; `recipient_contract`·`recipient_certification_period`에 신규 역방향 constraint trigger 추가(기존 트리거는 미수정 — 같은 이름 재사용 없이 신규 함수만 추가); `recipient_contract`·`recipient_certification_period`에 `recipient_id` immutability `BEFORE UPDATE` trigger 추가(§2-8). `erp_app`에는 `SELECT, INSERT, UPDATE`(DELETE·TRUNCATE 제외) + 시퀀스 `USAGE, SELECT`, `erp_backup`에는 `SELECT`만 grant(`20260803_0014` 패턴과 동일) |
| downgrade | **순서:** (1) `recipient_service_plan_notice`에 부착된 정방향 trigger·function drop; (2) `recipient_contract`·`recipient_certification_period`에 추가한 역방향 trigger·function drop; (3) `recipient_contract`·`recipient_certification_period`의 `recipient_id` immutability trigger·function drop; (4) `erp_app`·`erp_backup` grant revoke; (5) `recipient_service_plan_notice` 테이블 drop. trigger/function을 테이블보다 먼저 제거해야 dangling 참조가 생기지 않는다 |
| revision 순서 | Wave 1 PASS SHA 직속 chain의 새 단일 revision. 기존 revision id 재사용·수정 금지(`04` §0 규칙). branching 금지 — 단일 head 직속 child 1개만 |
| Phase 1 | migration 파일 생성 금지(RED만 요구). 정확한 revision id·grant 목록은 Task Packet 단계에서 확정 |
| legacy 공존 | 본 슬라이스의 migration은 기존 `erp.recipient_plan_notification` 테이블과 그 데이터를 **건드리지 않는다**(rename·drop·truncate·ALTER 금지). 두 테이블은 공존한다. legacy `PLAN_RENEWAL` deadline-kind와 `backend/app/domains/recipient/service.py`의 `_plan_renewal_due_date()` 함수 소비 코드의 폐기·절환은 API/service/work-card 슬라이스로 명시적 분리 — 이 DB-contract-only 슬라이스의 범위가 아니다 |

## 6. RED 테스트 범위 제안 (구현 전 실패해야 함)

`backend/tests/test_w2_service_plan_notice_contract.py`(DB-free):

1. migration/ORM 부재 시 안정적인 `W2_PRODUCT_ABSENT` RED.
2. 정확한 컬럼 집합·타입·nullability 계약 검사(존재 시) — `recipient_certification_period_id`
   컬럼이 **없어야** 함을 포함(§2-4 결정 회귀 방지).

`backend/tests/test_w2_service_plan_notice_postgres.py`(live, 기존 W1E/W1F
패턴과 동일하게 `SSWCENTER_*_REAL_PG` 게이트):

1. 기본 종료일 계산: 통보월 1~6월/7~12월 각각의 정확한 기본값.
2. 통보월이 바뀌어도 이미 고정된 `applied_end_date`는 재계산되지 않음; 사용자가
   명시한 값이 기본 계산값보다 우선함.
3. `recipient_contract_id` 필수 RESTRICT FK: 계약 부재/삭제 시 거부.
4. 연결된 계약이 이미 무효화 상태면 INSERT/UPDATE 거부(§2-1,
   `SERVICE_PLAN_CONTRACT_INVALIDATED`). 단, 계획서 자신이 무효화 상태인
   행은 검사하지 않음(§2-1 live-filter, §2-7 DEFERRABLE).
5. 같은 트랜잭션에서 기존 계획서 무효화 + 대체 계획서 INSERT의 원자적 정정
   성공: 계약·인정기간을 동시에 단축해도 대체 행이 새 조건을 만족하면 커밋
   성공(§2-1 live-filter, §2-7).
6. `applied_start_date`가 `recipient_contract.start_date`보다 앞서면 거부
   (`SERVICE_PLAN_BEFORE_CONTRACT_START`, §5).
7. 계약 `start_date`를 저장 이후 늦추는 역방향 guard: 계약 `start_date`를
   계획서의 `applied_start_date`보다 나중으로 이동시키는 UPDATE가 거부됨
   (`SERVICE_PLAN_BEFORE_CONTRACT_START` 계열, §5 reverse guard).
8. cap 규칙: 계약이 더 짧음/인정이 더 짧음/계약이 NULL(무기한)이라 인정
   종료일이 유일한 cap인 경우 3가지 조합에서 각각 정확한 cap과, cap 초과
   INSERT/UPDATE의 거부. (`recipient_certification_period.end_date`는 NOT
   NULL이므로 '둘 다 NULL' 조합은 성립하지 않는다.)
9. 해당 시점 유효 인정기간이 전혀 없는 경우와 부분적으로만 커버하는 경우 각각
   거부.
10. **수급자 범위 검증**: 다른 수급자의 유효한 인정기간이 날짜를 커버하더라도
    `recipient_id`가 다르면 cap/coverage 검사에 사용되지 않고 거부됨(§2-3,
    §5 CHECK).
11. `applied_end_date >= applied_start_date` CHECK 위반 거부.
12. 역방향 guard(§2-7): 저장된 계획서가 있는 상태에서 연결된 계약을 단축·
    무효화·**대체**하거나 인정기간을 단축·무효화·**대체**하는 UPDATE는 거부.
    `recipient_certification_period`의 **DELETE**도 살아있는 계획서를
    orphan시키면 거부됨을 확인(계획서 쪽에 저장된 FK가 없으므로 DELETE 감시
    필수). `recipient_contract`의 DELETE는 `care_assignment`와 본 테이블의
    RESTRICT FK에 의해 참조 행 존재 시 거부되므로 역방향 guard가 별도 감시
    하지 않으나 DELETE 시도 자체가 FK에 의해 차단됨을 확인. 이미 무효화된
    계획서는 검사에서 제외됨을 별도로 확인.
13. 동일 트랜잭션 내 정당한 원자적 정정: 계약을 단축하면서 같은 트랜잭션에서
    영향받는 계획서도 함께 정정(무효화+대체)하면 커밋이 성공함(DEFERRABLE
    지연평가 확인, §2-7).
14. **동시성 write-skew 방지(SERIALIZABLE 격리) — RED**: (a) 살아있는
    `recipient_service_plan_notice`의 적용범위가 현재 의존하고 있는 부모
    `recipient_certification_period`(또는 `recipient_contract`) 행을 준비한다.
    (b) 트랜잭션 T1(SERIALIZABLE)에서 해당 부모 행을 단축·무효화·재귀속하여,
    T1의 지연된 역방향 guard가 만약 특정 새 계획서가 존재한다면 거부해야 하는
    상태로 만든다 — 단, T1은 아직 커밋하지 않는다. (c) 동시에 트랜잭션
    T2(SERIALIZABLE)에서 T1이 변경하기 전 부모 행의 pre-change 스냅샷을
    읽고 유효하다고 판단한 채, 새 `recipient_service_plan_notice`를 INSERT한다
    (T2의 정방향 guard는 pre-change 상태를 기준으로 통과). (d) T1과 T2가
    모두 커밋을 시도할 때, PostgreSQL SSI는 read-write anti-dependency
    cycle(T2의 정방향 guard가 T1이 수정 중인 부모 행을 읽었고, T1의 지연된
    역방향 guard는 T2의 새 계획서 행을 올바르게 평가하려면 읽어야 함)을
    감지하여 두 트랜잭션 중 하나를 `40001 serialization_failure`로 중단시킴을
    확인. (e) 중단된 트랜잭션은 caller의 retry loop에 의해 재시도되고, 재시도
    시 guard가 최종 커밋 상태를 기준으로 재평가하여 — 조건을 만족하면 통과,
    불만족이면 올바르게 거부 — 어느 순서로 직렬화되든 정합성이 유지됨을 확인
    (한 트랜잭션은 커밋 성공, 다른 트랜잭션은 40001 후 재시도하여 올바른
    최종 결정을 내림, §2-7).
15. **부모 recipient_id 재귀속 방어**: (i) `recipient_contract.recipient_id`
    또는 `recipient_certification_period.recipient_id`를 다른 수급자로
    UPDATE 시도 → immutability CHECK trigger가 거부(`23514`). (ii) 방어적 RED:
    immutability trigger를 명시적으로 비활성화(`ALTER TABLE ... DISABLE
    TRIGGER <trigger_name>`)한 후 `recipient_id`를 UPDATE하고 trigger를 다시
    활성화한 뒤, 역방향 guard가 OLD 수급자의 유효 계획서를 검사하여 orphan을
    감지·거부함을 확인(§2-8).
16. D-100/D-45 날짜 계산 순수 함수 단위 검증(작성마감일 기준, 업무카드
    생성 없이 날짜값만; §2-5).
17. PERIOD_FACT 정정: 무효화 + 신규 행 + 과거 ID 지속, 무효화·대체·감사·
    `row_version` 공통 규칙 준수.
18. **migration 단일 head**: revision chain이 직속 단일 child이며 branching이
    없음을 확인(W1E §8·§9.1 패턴).
19. **downgrade 완전 복원**: downgrade 후 `recipient_service_plan_notice`
    테이블이 존재하지 않고, `recipient_contract`·`recipient_certification_period`에
    추가된 역방향 trigger·function 및 `recipient_id` immutability trigger와
    그 기저 function도 모두 잔류하지 않음을 확인(§5b).

## 7. 다음 단계

1. 이 설계에 대한 독립검수(Codex 정적 읽기전용)로 anchor 인용의 정확성과
   Wave 2·3 경계 위반 여부를 먼저 확인.
2. 통과하면 Task Packet으로 전환해 DeepSeek Writer에게 RED 테스트 작성을
   지시(Phase 1은 RED-only — migration 파일 생성 금지, §5b; 실제 제품 구현은
   별도 승인 후).
3. Wave 2 매트릭스 항목(`review/WAVE1_CLEAN_TEST_MATRIX.md`에 준하는 신규
   문서)을 별도로 등록.
