# W1A-VS3 작업 배정 패킷 v2.2

> 상태: `PASS / GREEN_SEALED / COMPLETE`
>
> 작성일: 2026-07-28 KST
>
> 운영정본: `docs/AI_업무분담_운영규정_v2.2.md`
>
> 상세계획: `review/plans/W1A_VS3_STAFF_TRAINING_PLAN.md`
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 기준 commit: `728958d4357b12bf34996ce10221118238b67c20`
>
> 총괄·최종판정: 김부장(Codex 본진 / SOL Max)
>
> RED backend·PostgreSQL 작업방: 이루나
> `019fa2dc-2c9a-7a51-83f8-1704c1b2320b`
>
> RED DOM·E2E·ABS 작업방: 송루나
> `019fa2dc-58b2-7e72-8073-be5d78ac3bee`

## 1. 시작 조건

- `W1A-VS2 PASS / GREEN_SEALED`
- branch와 base commit 확인
- 현재 dirty 통합본 보존
- README, 정본목록, AI 운영정본, VS3 계획 UTF-8 선행 확인
- 새 작업방·하부·보조·대체 에이전트 생성 금지
- stage/commit/push/pull/reset/rebase 금지

## 2. 공통 목표

exact 교육과목 7행, 재직별 신규직원교육, 직원·과목·기간별 정기교육의
구현 전에 실패하는 정밀 RED 계약을 만든다.

## 3. 공통 금지

- 제품 GREEN 구현
- 기존 migration `0001`~`0004` 수정
- VS1/VS2 테스트 또는 evidence 약화
- 교육시간·이수일자·이수센터·file/task 구조 추가
- 건강검진·분기상담·초기이관 범위 선점
- 같은 파일 동시 수정
- 환경 실패를 제품 RED로 보고

## 4. 단계 A — RED 배정

### 이루나

허용 파일:

- `backend/tests/test_w1a_vs3_semantics.py`
- `backend/tests/test_w1a_vs3_api.py`
- `backend/tests/test_w1a_vs3_postgres.py`
- `backend/tests/test_w1a_vs3_openapi_contract.py`
- `backend/tests/test_w1a_vs3_absence_contract.py`
- `scripts/test-w1a-vs3-postgres.ps1`

완료조건:

- exact 7행 seed·cycle·결정적 순서 RED
- onboarding 재직 transaction 원자성·rollback RED
- 재입사 새 onboarding과 periodic same-period 유지 RED
- cycle/period truth table와 duplicate race RED
- completed true/false audit RED
- ADMIN/VIEW/MANAGE/ungranted USER, CSRF, 409/422 RED
- migration lifecycle·offline·postcheck·restore RED
- 금지 DB/API/OpenAPI 구조 부재검사
- named `W1A_VS3_*` marker와 명령별 exit/test 수 보고

### 송루나

허용 파일:

- `frontend/src/test/W1AStaffTraining.test.tsx`
- `frontend/e2e/w1a-staff-training-real-pg.spec.ts`
- VS3 전용 leak/absence vector가 꼭 필요할 때만 새 전용 파일

완료조건:

- exact label/cycle, 신규/정기교육 분리 RED
- 생성 타입 기반 adapter·UI·상태전환 RED
- 재입사와 periodic same-period 보존 RED
- loading/empty/error/403/409/422/session/cache RED
- A↔B, 검색·정렬·page·scroll·tab·browser back RED
- 실제 PostgreSQL 자체 bootstrap, workers 1, 3 viewport 계약
- DOM/cache/log/artifact leak와 forbidden field ABS
- named `W1A_VS3_*` marker와 명령별 exit/test 수 보고

## 5. 단계 A 반환 형식

각 작업방은 다음 형식으로 반환한다.

1. `RED_VALID` 또는 `REQUIRED_CHANGES`
2. 수정 파일 목록
3. 실행 명령과 exit code
4. collected/passed/failed/skipped 수
5. 첫 named marker와 제품 부재 의미
6. 환경 blocker 유무
7. stage/commit/push 미실행 확인

## 6. 후속 단계

- 두 RED 결과를 김부장이 실제 파일·명령·marker 의미로 독립검증한다.
- 유효 RED만 `review/evidence/w1a-vs3/RED.md`에 봉인한다.
- RED 봉인 뒤 기존 김루나 방에 backend·DB 구현을 배정한다.
- backend·OpenAPI 계약 고정 뒤 기존 박루나 방에 frontend 구현을 배정한다.
- 구현자는 자신의 결과를 최종 승인하지 않는다.
- REQUIRED_CHANGES는 본진이 제품결함을 대신 고치지 않고 원 소유자에게 반환한다.

두 RED는 `review/evidence/w1a-vs3/RED.md`에 봉인됐다. 단계 B backend·DB,
단계 C frontend, 단계 D 이루나·송루나 교차검증과 김부장 전체 runtime gate가
모두 PASS했다. 최종 증거는 `review/evidence/w1a-vs3/GREEN.md`에
`PASS / GREEN_SEALED`로 봉인했고 이 패킷은 완료 상태다.
