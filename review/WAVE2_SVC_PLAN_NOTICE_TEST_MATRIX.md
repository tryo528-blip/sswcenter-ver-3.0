# Wave 2 급여계획서(Service Plan Notice) 테스트 매트릭스

> 상태: Wave 2 슬라이스 중 **급여계획서 DB 계약 하나만** 등록. `WAVE1_CLEAN_TEST_MATRIX.md`와
> 같은 형식을 따르되, 범위는 이 슬라이스로 한정한다 — 일정·업무카드, 직원교체,
> 공단·RFID·실제근무, 수가·청구, OCR 등 다른 Wave 2 영역은 각자 설계가 나올 때
> 별도 매트릭스 항목으로 등록한다. 이 문서가 Wave 2 전체를 대표하지 않는다.
>
> 작성일: 2026-08-10 KST, 갱신: 2026-08-11 KST
>
> 기준 문서: [`review/plans/W2_SERVICE_PLAN_NOTICE_PLAN.md`](plans/W2_SERVICE_PLAN_NOTICE_PLAN.md)
> (§6 RED 테스트 범위 제안, 19개 항목 — CONTRACT 2개 + PG 17개)
>
> 기준 commit: `fe132f5` (RED 테스트 추가), 설계 기준 HEAD `d4d2ab2`/`b0dc1ee`
>
> 독립검수: 설계 문서는 Codex 정적 읽기전용 검수 PASS(findings 0, 2026-08-10).
> RED 테스트 코드(`test_w2_service_plan_notice_postgres.py`) 자체의 Codex Sol
> 독립검수는 최초 시도에서 12개 findings(HIGH 8 / MEDIUM 3 / LOW 1)로 FAIL했다.
> DeepSeek Writer 재작업 4라운드 + 오퍼레이터 직접 수정 3건을 거쳐 2026-08-11
> Codex Sol(ultra reasoning) 최종 재검수 **PASS(findings 0)**로 완료됐다. 별도로,
> 재검수 도중 `C:\sswcenter\warpper` AI wrapper의 mutation watcher가 git 자체가
> 만드는 `.git/index.lock` 일시 파일과 그로 인한 `.git` 디렉토리 메타데이터
> 변경 이벤트를 실제 mutation으로 오판하던 결함을 발견해 wrapper 자체를
> 수정했다(`GIT_OPTIONAL_LOCKS=0` + 좁은 이벤트 예외처리 + 진단 로깅, 오프라인
> 회귀 92/92 PASS). 라이브 PostgreSQL 게이트를 켠 실행으로 §3에 기록된 대로
> RED 형태도 실측 확인했다.

## 1. 정본 anchor

| 영역 | 참조 |
|---|---|
| 업무 | `docs/02_업무규칙_계약_v1.1.md` §9.1 (line 390–403) |
| UI 오류 표시 | `docs/03_UI_API_상호작용_계약_v1.2.md` §7 (line 381–409) |
| DB 경계선언 | `docs/04_데이터_DB_불변조건_v4.8_PostgreSQL.md` §12 Wave 2·3 경계 (line 755–785) |
| 계약 FK 대상 | `04` §8.2 `recipient_contract` (line 592–605) |
| 인정기간 스키마 | `04` §6.2 `recipient_certification_period` (line 499–508) |
| orphan 금지·역방향 guard | `04` §3.5 (line 241–243, W1E `care_assignment` 사례) |
| 로드맵 | `docs/06_개발로드맵_결정현황_v1.2.md` §1 Wave 2 행 (line 27), §5 Wave 2 성숙도 (line 129) |
| 설계 초안 | `review/plans/W2_SERVICE_PLAN_NOTICE_PLAN.md` |

## 2. 테스트 층 표기

| 표기 | 의미 |
|---|---|
| `CONTRACT` | DB-free, offline alembic/ORM absence·shape 검사 (`test_w2_service_plan_notice_contract.py`) |
| `PG` | 실제 격리 PostgreSQL 제약·동시성 테스트, `SSWCENTER_W2_SVC_PLAN_NOTICE_REAL_PG` 게이트 (`test_w2_service_plan_notice_postgres.py`) |

## 3. 매트릭스

Phase 1(RED-only) 최종 완료 상태 — 2026-08-11 `scripts/test-w2-service-plan-notice-red-gate.ps1`
(ephemeral PostgreSQL, `SSWCENTER_W2_SVC_PLAN_NOTICE_REAL_PG=1`, 현재 head
`20260808_0017_recipient_guardian_email`까지만 upgrade)로 실측: **`54 failed`
+ `1 skipped`**(전체 55개 테스트). 실패 54개 전부 정확한 사유로 RED —
순수함수 8개는 `W2_PRODUCT_ABSENT` 계열 마커(모듈 import 실패), 나머지 46개는
`W2_MIGRATION_REVISION_NOT_APPLIED`(기대 `20260809_0018_w2_service_plan_notice`,
실제 `20260808_0017`). skip 1개는 `test_downgrade_upgrade_downgrade_reupgrade_lifecycle`
— 별도 opt-in 게이트(`SSWCENTER_W2_SVC_PLAN_NOTICE_MIG_PG`)라 이번 실행에서는
켜지 않았다(의도된 스킵). 게이트를 끈 오프라인 실행(`SSWCENTER_W2_SVC_PLAN_NOTICE_REAL_PG`
미설정)에서는 `8 failed`(위와 동일 순수함수 RED) + `47 skipped`(live 게이트
꺼짐)이다.

1차 산출물에서 날짜 계산 5개 항목이 아직 없어야 할 제품 로직을 테스트 파일
안에서 직접 구현해 자기 자신을 테스트하는 결함이 있었고(§6 pg-1/pg-16 위반),
DeepSeek Writer에게 재작업을 지시해 실제 부재 모듈
(`app.domains.recipient.service_plan_notice`) import 실패로 정정했다(RunId
`W2-01-SVC-PLAN-NOTICE-RED` → `W2-01B-SVC-PLAN-NOTICE-RED-FIX`). 이후 Codex Sol
독립검수에서 나온 12개 findings를 DeepSeek 재작업 4라운드 + 오퍼레이터 직접
수정 3건으로 전부 해소했다(최종 PASS, findings 0, 2026-08-11). 이 과정에서
함수가 다수 추가·교체됐다 — 아래 표는 최종 상태 기준이다.

| ID | 요구사항(§6 항목) | 테스트 층 | 테스트 함수 | 상태 |
|---|---|---|---|---|
| W2-SPN-C1 | migration/ORM 부재 시 안정적 RED (DB-free 1) | `CONTRACT` | `test_w2_svc_plan_notice_01_direct_child_revision_is_fixed`, `test_w2_svc_plan_notice_02_offline_sql_contract` | RED |
| W2-SPN-C2 | 정확한 컬럼 집합·타입·nullability, `recipient_certification_period_id` 부재 (DB-free 2, §2-4) | `CONTRACT` | `test_w2_svc_plan_notice_03_orm_contract_is_exact` | RED |
| W2-SPN-01 | 기본 종료일 계산(1~6월/7~12월) | `PG` | `test_default_end_date_jan_jun`, `test_default_end_date_jul_dec` | RED (모듈 부재) |
| W2-SPN-02 | 고정된 `applied_end_date`, 명시값 우선 | `PG` | `test_fixed_end_date_not_recalculated`, `test_explicit_end_date_overrides_default` | RED (migration 부재, 실측 확인) |
| W2-SPN-03 | `recipient_contract_id` 필수 RESTRICT FK | `PG` | `test_missing_contract_rejected` | RED (실측 확인) |
| W2-SPN-04 | 계약 무효화 시 INSERT/UPDATE 거부, 자기무효화는 제외 | `PG` | `test_contract_invalidated_rejects_insert`, `test_contract_invalidated_rejects_update`, `test_contract_invalidated_plan_notice_self_invalidated_skips_check` | RED (실측 확인) |
| W2-SPN-05 | 같은 트랜잭션 무효화+대체 원자적 정정(계약·인정기간 동시 단축 포함) | `PG` | `test_atomic_correction_invalidate_and_replace` | RED (실측 확인) |
| W2-SPN-06 | `applied_start_date` < 계약 `start_date` 거부(INSERT·UPDATE) | `PG` | `test_start_date_before_contract_start_rejected`, `test_start_date_before_contract_start_rejected_on_update` | RED (실측 확인) |
| W2-SPN-07 | 계약 `start_date` 지연 역방향 guard | `PG` | `test_reverse_guard_contract_start_delayed_rejected` | RED (실측 확인) |
| W2-SPN-08 | cap 3가지 조합(계약/인정/무기한) — 경계값·UPDATE-past-cap 포함 | `PG` | `test_cap_contract_shorter_than_certification`, `test_cap_certification_shorter_than_contract`, `test_cap_endless_contract_cert_only_cap`, `test_cap_boundary_accepted_at_exact_contract_end_date`, `test_cap_boundary_rejected_one_day_past_contract_end`, `test_cap_update_past_cap_rejected`, `test_cap_boundary_accepted_at_exact_cert_end_date`, `test_cap_boundary_rejected_one_day_past_cert_end`, `test_cap_update_past_cert_cap_rejected`, `test_cap_boundary_accepted_at_exact_cert_end_date_endless`, `test_cap_boundary_rejected_one_day_past_cert_end_endless`, `test_cap_update_past_cert_cap_rejected_endless` | RED (실측 확인) |
| W2-SPN-09 | 인정기간 부재/부분 커버 거부 | `PG` | `test_no_certification_period_rejected`, `test_partial_certification_coverage_rejected` | RED (실측 확인) |
| W2-SPN-10 | 다른 수급자 인정기간 미사용 | `PG` | `test_other_recipient_certification_not_used` | RED (실측 확인) |
| W2-SPN-11 | `applied_end_date >= applied_start_date` CHECK | `PG` | `test_end_date_before_start_date_rejected` | RED (실측 확인) |
| W2-SPN-12 | 역방향 guard: 계약·인정기간 각각 단축·무효화·대체·DELETE | `PG` | `test_reverse_guard_contract_shorten_end_date_rejected`, `test_reverse_guard_contract_invalidate_rejected`, `test_reverse_guard_contract_replace_rejected`, `test_reverse_guard_cert_period_delete_rejected`, `test_reverse_guard_cert_period_shorten_rejected`, `test_reverse_guard_cert_period_invalidate_rejected`, `test_reverse_guard_cert_period_replace_rejected`, `test_reverse_guard_contract_delete_blocked_by_fk`, `test_reverse_guard_invalidated_plan_excluded` | RED (실측 확인) |
| W2-SPN-13 | DEFERRABLE 동일 트랜잭션 원자적 정정 | `PG` | `test_deferrable_atomic_contract_shorten_with_plan_correction` | RED (실측 확인) |
| W2-SPN-14 | SERIALIZABLE write-skew 감지(실제 2-connection) | `PG` | `test_serializable_isolation_accepted`, `test_serializable_write_skew_two_transactions` | RED (실측 확인) |
| W2-SPN-15 | `recipient_id` immutability + OLD-key orphan 감지(계약·인정기간 양쪽) | `PG` | `test_recipient_contract_recipient_id_immutable`, `test_certification_period_recipient_id_immutable`, `test_reverse_guard_old_recipient_orphan_detection`, `test_reverse_guard_old_recipient_orphan_detection_cert_period` | RED (실측 확인) |
| W2-SPN-16 | 작성마감일 기준 D-100/D-45 순수함수(계약·인정기간 cap 포함) | `PG` | `test_d100_calculation`, `test_d45_calculation`, `test_d100_d45_edge_month_boundary`, `test_d100_calculation_capped_by_contract_end`, `test_d45_calculation_capped_by_contract_end`, `test_deadline_capped_by_earlier_of_two` | RED (모듈 부재) |
| W2-SPN-17 | PERIOD_FACT 정정(무효화+신규+과거 ID 지속, actor/timestamp/row_version) | `PG` | `test_period_fact_correction_invalidate_new_persist_id` | RED (실측 확인) |
| W2-SPN-18 | migration 단일 head | `PG` | `test_single_head_migration_chain` | RED (실측 확인) |
| W2-SPN-19 | downgrade 완전 복원(실제 upgrade→downgrade→re-upgrade lifecycle 포함) | `PG` | `test_downgrade_restores_clean_state`, `test_downgrade_sequence_cleanup`, `test_downgrade_upgrade_downgrade_reupgrade_lifecycle` | RED (전부 실측 확인) |

모든 `PG` 항목이 2026-08-11 라이브 게이트 실행으로 RED 실측 확인됐다.
`test_downgrade_upgrade_downgrade_reupgrade_lifecycle`은 별도 opt-in 게이트
(`SSWCENTER_W2_SVC_PLAN_NOTICE_MIG_PG` + `SSWCENTER_W2_SVC_PLAN_NOTICE_MIG_DATABASE_URL`)를
`scripts/test-w2-service-plan-notice-migration-lifecycle-gate.ps1`(빈 디스포저블
DB, alembic이 `None → W2_PREV_HEAD`까지 전체 체인을 실제로 실행)로 켜서 확인
—  `W2_MIGRATION_MISSING_FOR_LIFECYCLE_TEST: Can't locate revision identified by
'20260809_0018_w2_service_plan_notice'`로 정확히 설계된 RED가 나왔다.

## 4. Wave 2 이상으로 남겨둔 것 (이 슬라이스에서 명시 제외)

- 공식 업무카드 엔진(`COMPLETE`/`INCOMPLETE`/`EXEMPT`/`WAITING`, 단계별 완료) — `02` §9.3
- 월간 일정·확정월 — `02` §9.4
- 실제 급여제공 기반 직원교체 — `W2-07`, `DESIGN_REQUIRED`로 차단
- API·UI·service 구현, 실 PostgreSQL GREEN, migration 적용 — 별도 승인 후 Phase 2
- ERP 업무카드/WorkCadence 연동 계약(`review/plans/W2_WORK_CARD_WORKCADENCE_CONTRACT_PLAN.md`,
  commit `cc434ec`) — 별도 슬라이스, 이 문서가 다루지 않음

## 5. 다음 단계

1. ~~라이브 PostgreSQL 하네스 준비 후 게이트 켜서 RED 전환 확인~~ — **완료**
   (2026-08-11, `scripts/test-w2-service-plan-notice-red-gate.ps1`, §3 참조).
2. ~~RED 테스트 코드 자체의 Codex 독립검수~~ — **완료**(2026-08-11, Codex Sol
   ultra reasoning, 7회 검수 끝에 PASS/findings 0). 검수 도중 발견된 AI wrapper
   mutation-watcher 결함(`C:\sswcenter\warpper`)도 별도로 수정·오프라인
   회귀 92/92 PASS로 검증했다.
3. ~~`test_downgrade_upgrade_downgrade_reupgrade_lifecycle`의 별도 opt-in
   게이트 실행 증거~~ — **완료**(2026-08-11,
   `scripts/test-w2-service-plan-notice-migration-lifecycle-gate.ps1`, §3 참조).
4. 남은 건 migration + ORM 모델(`app.domains.recipient.service_plan_notice`
   포함) 구현 — 별도 승인 후 Phase 2로 진행.
