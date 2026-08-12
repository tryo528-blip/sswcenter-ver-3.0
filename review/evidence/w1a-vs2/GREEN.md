# W1A-VS2 GREEN 최종 검증 증거

> 상태: `GREEN_SEALED`
>
> 최종 검증 시각: 2026-07-28 03:23 KST
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 기준 commit: `728958d4357b12bf34996ce10221118238b67c20`
>
> 검증 대상: 위 commit 이후 현재 unstaged/untracked W1A-VS2 작업본
>
> 총괄·최종판정: 김부장(Codex 본진 / SOL Max)
>
> stage·commit·push: 수행하지 않음

## 1. 최종 판정

`W1A-VS2`의 공통 서비스 catalog, 일반 자격증 사실, 서비스 제공자격 기간을
실제 PostgreSQL, API, 생성 OpenAPI 타입, React UI, 실제 브라우저까지
교차검증했다.

RED 계약을 약화하거나 skip으로 우회하지 않았고, 구현 중 발견된 catalog 순서,
E2E 로딩·locator·실제 scroll fixture, browser-back 선택 복원 결함을 원 소유자가
보정한 뒤 동일 gate를 다시 실행했다.

DB 교차검증과 UI·누출 교차검증, 김부장 독립검증이 모두 GREEN이므로
`W1A-VS2 PASS / GREEN_SEALED`로 판정한다.

이 판정은 W1A 전체 완료가 아니다. 교육·건강검진·분기상담·초기 이관과 legacy
mapping은 후속 W1A micro-slice에서 계속한다.

## 2. 역할별 결과

| 담당 | 범위 | 판정 |
|---|---|---|
| 김루나 | backend·DB 구현, catalog 결정적 업무순서 보정 | PASS |
| 박루나 | frontend 구현, URL `staff_id` browser-back 복원 보정 | PASS |
| 이루나 | migration·DB invariant·ACL·동시성·rollback 교차검증 | PASS |
| 송루나 | 실제 PG UI·목록문맥·민감정보·artifact·3 viewport 교차검증 | PASS |
| 김부장 | diff·전체 gate·독립 재현·최종판정 | PASS |

## 3. PostgreSQL·backend 증거

| 검증 | Exit | 결과 |
|---|---:|---|
| W1A-VS2 실제 PostgreSQL harness | 0 | 16/16, `W1A_VS2_POSTGRES_GREEN` |
| backend 전체 pytest | 0 | 69 passed, 17 skipped |
| Ruff check | 0 | All checks passed |
| Ruff format check | 0 | 52 files already formatted |
| mypy | 0 | 29 source files, no issues |
| Alembic fresh base→head | 0 | `0001→0002→0003→0004` |
| OpenAPI 생성 타입 drift | 0 | `OPENAPI_TYPES_UP_TO_DATE` |

DB 교차검증에는 exact catalog manifest, application role ACL, active unique,
overlap·same-staff FK·employment containment·reverse guard, 동시성,
row-version conflict, audit·replacement·counter·rollback과 restore drill이
포함됐다.

## 4. Frontend·브라우저 증거

| 검증 | Exit | 결과 |
|---|---:|---|
| frontend 전체 Vitest | 0 | 10 files, 62 passed |
| W1A-VS2 focused Vitest | 0 | 1 file, 8 passed |
| oxlint | 0 | PASS |
| TypeScript·Vite build | 0 | 147 modules |
| VS2 Playwright discovery | 0 | 3 tests, 1 file |
| 전체 Playwright discovery | 0 | 15 tests, 3 files |
| 실제 PG Playwright | 0 | workers 1, 3/3 passed, 1.4m |

실제 PG Playwright viewport:

- `1440x1000`
- `1440x900`
- `1366x768`

strict assertion으로 확인한 범위:

- 공통 서비스 3그룹·5종 exact code·표시명·업무순서
- 직원 A/B 자격증·제공자격 격리
- 일반 자격증 3건
- 자격증 없는 제공자격과 optional source
- 재입사 뒤 같은 source 자격증 재사용
- 저장 뒤 GET 재조회
- 실제 overflow와 `scroll` event, 동일한 양수 `scrollTop`
- 검색·정렬·page 2·선택 탭 문맥
- A→B 뒤 실제 browser back으로 A 상세 복원
- popup 0, 가로 overflow 0
- 내부 오류·금지필드·민감정보 노출 0

## 5. 누출·artifact·cleanup 증거

| 검증 | Exit | 결과 |
|---|---:|---|
| leak gate negative self-test | 0 | `W1A_LEAK_GATE_SELF_TEST_OK` |
| normal leak gate | 0 | 185 files, `W1A_LEAK_GATE_GREEN` |
| E2E artifact | 0 | 2 files, 3527 bytes, media 0 |
| 임시 debug marker | 0 | 0건 |
| `git diff --check` | 0 | whitespace 오류 없음 |

normal gate의 최초 fail-closed 읽기 실패는 실행 중 backend가
`access.log`를 공유 잠금한 상태에서 발생했다. E2E 종료 후 backend를 정상
종료하고 같은 data/artifact root를 다시 scan해 185 files GREEN을 확인했다.
검사 우회나 파일 제외는 하지 않았다.

최종 cleanup을 김부장이 다시 확인했다.

- 임시 PostgreSQL/data root: 없음
- 임시 artifact root: 없음
- `frontend/test-results`: 없음
- listener `8000`: 0
- listener `4173`: 0
- listener `55446`: 0

## 6. 구현 중 발견·보정된 결함

1. 서비스 catalog가 PK 순서에 의존해 업무순서가 비결정적이던 결함
   - `backend/app/domains/staff/repository.py`에서 exact 5종 업무순서와 미래
     code 결정적 fallback으로 보정
2. E2E의 인증 live-page 재이동, catalog option 로딩, nested-label locator,
   project 간 검색 격리, 실제 scroll fixture 부족
   - `frontend/e2e/w1a-staff-qualifications-real-pg.spec.ts` 소유범위에서 보정
3. browser history가 A의 URL을 복원해도 page 2의 B가 A를 다시 덮어쓰던 제품
   결함
   - RED: 기존 7 pass, 신규 browser-back 회귀 1 fail
   - 첫 marker: `W1A_VS2_BACK_TARGET_A_DETAIL_NOT_RESTORED`
   - `frontend/src/pages/StaffPage.tsx`가 URL `staff_id`를 목록 자동선택보다
     우선하도록 박루나가 보정
   - GREEN: focused 8/8, 전체 62/62

## 7. 다음 단계

`W1A-VS2`를 다시 수정하지 않고 W1A 잔여 micro-slice를 별도 RED→구현→
교차검증 흐름으로 진행한다. 디자인·page size·내부 사용성 조정은 사용자
지시에 따라 W2로 넘긴다.
