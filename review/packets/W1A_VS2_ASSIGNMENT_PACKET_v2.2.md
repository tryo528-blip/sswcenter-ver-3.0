# W1A-VS2 작업 배정 패킷 v2.2

> 상태: `COMPLETED_GREEN_SEALED`
>
> 작성일: 2026-07-27 KST
>
> 운영정본: `docs/AI_업무분담_운영규정_v2.2.md`
>
> 상세계획: `review/plans/W1A_VS2_LICENSE_QUALIFICATION_PLAN.md`
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 기준 commit: `728958d4357b12bf34996ce10221118238b67c20`
>
> 총괄·최종판정: 김부장(Codex 본진 / SOL Max)
>
> RED 검증 증거: `review/evidence/w1a-vs2/RED.md`
>
> GREEN 검증 증거: `review/evidence/w1a-vs2/GREEN.md`

> RED backend·PostgreSQL 작업방: 이루나
> `019fa2dc-2c9a-7a51-83f8-1704c1b2320b`
>
> RED DOM·E2E·ABS 작업방: 송루나
> `019fa2dc-58b2-7e72-8073-be5d78ac3bee`

## 1. 시작 조건

다음을 모두 확인하기 전에는 제품 구현을 시작하지 않는다.

1. `OD-W1A-VS2-01` 최초 자격종류 catalog 사용자 승인 — 완료:
   `CARE_WORKER`/요양보호사, `SOCIAL_WORKER`/사회복지사, `NURSE`/간호사
2. current branch/upstream과 clean tree 확인
3. 기준 SHA가 현재 작업선의 ancestor인지 확인
4. 역할별 파일 소유권과 작업방 ID 기록
5. RED 담당과 구현 담당이 같은 제품 파일을 동시에 수정하지 않음

## 2. 공통 목표

W1A 소유의 exact 3그룹·5서비스 catalog, 일반 자격증 사실, 재직기반 서비스
제공자격 기간을 DB·API·OpenAPI 생성 타입·직원 UI·실제 PostgreSQL·브라우저로
완성한다.

## 3. 공통 금지

- 적용된 migration `0001`~`0003` 수정
- W1A-VS1 주민번호·재직·직종·역할 계약 약화
- 교육·검진·분기상담·legacy mapping·W1B 이상 구현
- 자격증 expiry/start/end 또는 일반 2개 제한 추가
- qualification에 자격번호·발급일 중복 저장
- 미래 schedule·assignment·file FK 추가
- 생성 TypeScript 직접수정
- 실제 개인정보·운영 DB·운영 파일 사용
- 같은 파일을 둘 이상의 구현자가 동시에 수정
- Git stage·commit·push·reset·rebase·force push
- 다른 작업자나 하부 에이전트 생성

## 4. 단계 A — RED 배정

### 이루나

목표:

- `W1-STF-05`~`06`의 backend·PostgreSQL 계약을 구현 전에 실패시킨다.

수정 가능 후보:

- `backend/tests/test_w1a_vs2_semantics.py`
- `backend/tests/test_w1a_vs2_openapi_contract.py`
- `backend/tests/test_w1a_vs2_api.py`
- `backend/tests/test_w1a_vs2_postgres.py`
- `scripts/test-w1a-vs2-postgres.ps1`

완료조건:

- 3/5 seed, 3개 이상 자격증, active duplicate race, correction history
- same-staff source FK, 재직 containment/reverse guard, overlap, 재입사 source 재사용
- ADMIN·STAFF_VIEW·STAFF_MANAGE·미부여 USER 권한
- named missing marker와 명령별 exit code

### 송루나

목표:

- 서로 다른 자격증·제공자격 DOM/OpenAPI 부재계약과 실제 UI RED를 고정한다.

수정 가능 후보:

- `backend/tests/test_w1a_vs2_absence_contract.py`
- `frontend/src/test/W1AStaffQualifications.test.tsx`
- `frontend/e2e/w1a-staff-qualifications-real-pg.spec.ts`

완료조건:

- 별도 두 탭·폼·named model
- forbidden expiry·2개 제한·중복 자격정보·future FK 부재
- 목록 문맥 유지·popup 0·권한 없는 제어 부재
- 3 viewport 실제 PG E2E가 정확한 missing assertion에서 RED

RED 담당자는 제품 파일을 수정하지 않는다.
두 담당자는 같은 evidence 파일을 수정하지 않고 최종보고로 결과를 반환한다.
김부장이 독립 재현 뒤 `review/evidence/w1a-vs2/RED.md`를 단독 작성한다.

## 5. 단계 B — backend·DB 구현 배정

### 김루나

수정 가능 후보:

- `backend/alembic/versions/20260727_0004_w1a_staff_qualifications.py`
- `backend/app/db/models.py`
- `backend/app/db/postcheck_w1a_vs1.py` 또는 승인된 새 W1A postcheck
- `backend/app/domains/staff/schemas.py`
- `backend/app/domains/staff/repository.py`
- `backend/app/domains/staff/service.py`
- `backend/app/domains/staff/errors.py`
- `backend/app/api/staff.py`
- 승인된 새 catalog router와 `backend/app/main.py`
- `backend/app/api/dependencies.py`
- backend 구현에 직접 필요한 기존 테스트 fixture

수정 금지:

- frontend 제품 파일
- RED의 업무기대값 약화
- 적용된 migration
- 정본·상세계획·이 배정 패킷

완료조건:

- migration fresh/upgrade/downgrade/offline
- exact catalog와 DB manifest
- 별도 license/qualification API·named model·stable error
- 권한·CSRF·version·audit·rollback
- 전체 backend Ruff·mypy·pytest

## 6. 단계 C — frontend 구현 배정

### 박루나

선행조건:

- backend OpenAPI가 김부장에게 승인되고 생성 TypeScript가 재생성되어야 한다.

수정 가능 후보:

- `frontend/src/pages/StaffPage.tsx`
- `frontend/src/services/staffApi.ts`
- `frontend/src/styles/staff.css`
- `frontend/src/test/W1AStaffQualifications.test.tsx`
- 필요시 승인된 새 staff qualification component 파일

수정 금지:

- `frontend/src/generated/sswcenter-api.ts` 직접수정
- backend·migration·정본
- 기존 목록 문맥·민감정보 reveal 계약 약화

완료조건:

- 별도 자격증·제공자격 탭과 폼
- 3개 이상 자격증
- 자격증 없는 제공자격·선택 source
- 권한·409·422·loading·empty 상태
- 직원 전환과 뒤로가기 문맥 유지
- 전체 frontend test·lint·build

## 7. 단계 D — 교차검증

### 이루나

- migration exact manifest
- application role ACL
- active unique·overlap·same-staff FK·containment·reverse guard
- concurrent duplicate와 row-version conflict
- audit·replacement·counter·rollback
- backup/restore postcheck

### 송루나

- 실제 PG 3 viewport Playwright, workers 1
- 목록 문맥·popup 0·가로 overflow
- forbidden field·legacy key·평문 주민번호·내부 오류 누출 0
- screenshot·trace·artifact 합성자료 확인

## 8. 김부장 통합·최종판정

- 기준 SHA와 모든 실제 diff 확인
- OpenAPI를 temp 재생성하고 checked-in TypeScript drift 0 확인
- 역할 간 파일 충돌 해결
- REQUIRED_CHANGES를 원 소유자에게 반환
- 전체 backend/frontend/PostgreSQL/Playwright/backup·leak gate 실행
- exact implementation SHA에서 최종 PASS 또는 재작업 판정

## 9. 반환 형식

```text
담당:
작업방 ID:
기준 SHA:
판정:
변경 파일:
명령별 테스트와 exit code:
업무계약별 증거:
남은 blocker:
git status --short:
다음 의존성:
```

사용자 결정, RED, backend·DB와 frontend 구현, 이루나·송루나 교차검증,
김부장 독립 runtime 검증을 모두 완료했다. 최종 결과는
`review/evidence/w1a-vs2/GREEN.md`에 봉인했으며 `W1A-VS2`는
`PASS / GREEN_SEALED`다. 후속 작업은 W1A 잔여 micro-slice로 이어간다.
