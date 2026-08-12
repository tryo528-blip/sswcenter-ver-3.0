# W1A-VS4 GREEN 최종 검증 증거

> 상태: `PASS / GREEN_SEALED`
>
> 최종 검증 시각: 2026-07-28 13:05 KST
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 기준 commit: `98534cf9bc0acb3ae9274bf04efd636aabf954d0`
>
> 검증 대상: 위 commit 이후 현재 W1A-VS4 작업본
>
> 총괄·최종판정: 김부장(Codex 본진 / SOL Max)
>
> 검증 중 push: 수행하지 않음

## 1. 최종 판정

`W1A-VS4` 직원 건강검진을 실제 PostgreSQL 17, FastAPI, 생성 OpenAPI 타입,
React UI와 실제 브라우저에서 독립 재현했다.

건강검진 사실과 대상별 상태 원장 분리, same-date 복수 fact, nullable
same-staff employment, exact `COMPLETE` / `INCOMPLETE` / `EXEMPT`, active target
중복 race, stale version, audit·invalidation·replacement와 rollback을 검증했다.
실제 브라우저에서는 두 원장 CRUD, 성공 재조회, A↔B·검색·정렬·page·실제
scroll·tab·browser-back, popup·overflow·금지 surface·민감정보 부재를 세
viewport에서 확인했다.

backend·DB와 frontend 구현, 두 독립 교차검증, 김부장 최종 runtime gate가 모두
GREEN이므로 `W1A-VS4 PASS / GREEN_SEALED`로 판정한다.

이 판정은 W1A 전체 완료가 아니다. 직원 분기상담과 초기 직원 이관·legacy
mapping은 후속 W1A micro-slice에서 계속한다. 공식 기준이 필요한 건강검진
자동 대상판정·D-day·업무카드는 승인 범위대로 W2 전 동결 상태다.

## 2. 역할별 결과

| 담당 | 범위 | 판정 |
|---|---|---|
| 김루나 | `0006` migration, backend·DB·OpenAPI 구현 검증 | PASS |
| 박루나 | 생성 타입 기반 adapter, 검진 tab, 두 원장 UI·상태관리 | PASS |
| 이루나 | DB invariant·권한·동시성·rollback 독립 교차검증 | PASS |
| 송루나 | 실제 PG UI·문맥·민감정보·artifact·3 viewport 검증 | PASS |
| 김부장 | 생성 타입, diff, 전체 runtime gate 독립 재현·최종판정 | PASS |

## 3. PostgreSQL·backend 증거

| 검증 | Exit | 결과 |
|---|---:|---|
| VS4 focused non-PG pytest | 0 | 9 passed, 2 skipped |
| backend 전체 pytest | 0 | 87 passed, 33 skipped |
| Ruff format/check | 0 / 0 | PASS |
| mypy | 0 | 29 source files, issue 0 |
| W1A-VS4 실제 PostgreSQL harness | 2 | 내부 16 passed, 0 failed/skipped/errors |
| OpenAPI 생성 타입 drift | 0 | `OPENAPI_TYPES_UP_TO_DATE` |
| `git diff --check` | 0 | whitespace 오류 없음 |

VS4 harness의 wrapper exit 2와 `W1A_VS4_RED_NOT_REPRODUCED`는 제품 부재
marker가 모두 사라진 GREEN 전환의 설계된 결과다. 내부 증거는 다음과 같다.

- fresh base→`0006`, `0005→0006`, `0006→0005→0006`: 모두 PASS
- offline SQL 생성·적용·검증: PASS
- 실행: 16 passed, 0 failed, 0 skipped, 0 errors
- postcheck: `W1A_VS4_DB_POSTCHECK_OK`
- 실제 dump/restore revision: `20260728_0006_w1a_staff_health_check`
- PostgreSQL stop, database drop, temp cluster, restore artifact cleanup: PASS

행동계약은 두 원장 분리, same-date 복수 fact, same-staff 복합 FK·trigger,
exact 3상태 truth table, active target partial unique와 duplicate race,
stale 409, field-level 422, audit·invalidation·replacement, audit 실패 exact
rollback, ADMIN·`STAFF_VIEW`·`STAFF_MANAGE`·ungranted USER와 CSRF를 포함한다.

## 4. Frontend·브라우저 증거

| 검증 | Exit | 결과 |
|---|---:|---|
| VS4 focused Vitest | 0 | 5/5 |
| frontend 전체 Vitest | 0 | 13 files, 79/79 |
| oxlint | 0 | PASS |
| TypeScript·Vite build | 0 | 147 modules |
| VS4 Playwright discovery | 0 | workers 1, 3 tests |
| 실제 PG VS4 Playwright | 0 | workers 1, 3/3 passed |

실제 PG Playwright viewport:

- `1440x1000`
- `1440x900`
- `1366x768`

fresh isolated PostgreSQL에 `0001`~`0006`을 적용하고 FastAPI·Vite를 기동한 뒤,
E2E 자체 bootstrap과 trusted synthetic requirement fixture로 실행했다. 세
viewport 모두 검진사실 create·update·invalidate/replacement, 대상상태
`COMPLETE→INCOMPLETE→EXEMPT`, payload·row version·GET 재조회, A↔B·검색·
정렬·page 2·실제 scroll event·검진 tab·browser back, popup 0, 가로 overflow
0과 금지필드·민감정보 부재를 끝까지 통과했다.

제품 UI는 generated OpenAPI 타입 adapter를 사용하며 다음을 검증했다.

- 독립 `검진` tab과 `검진사실`·`대상별 상태` 두 영역
- 선택 재직, same-date 복수 fact, 상태별 조건부 fact·면제사유
- `STAFF_VIEW` read-only, `STAFF_MANAGE`·ADMIN write
- loading·empty·error·403·409·422, 실패 시 문맥 보존, 성공 재조회
- 직원·session/logout 전환의 `AbortSignal`, stale 응답 차단
- 직원별 query/mutation cache 격리
- 자동 대상·D-day·task·업무카드·첨부·file/evidence UI 부재

## 5. 누출·artifact·cleanup 증거

| 검증 | Exit | 결과 |
|---|---:|---|
| leak gate negative self-test | 0 | `W1A_LEAK_GATE_SELF_TEST_OK` |
| normal leak gate | 0 | 210 files, `W1A_LEAK_GATE_GREEN` |
| 실제 PG E2E artifact | 0 | runner metadata 1 file, media 0 |
| `git diff --check` | 0 | whitespace 오류 없음 |

최종 cleanup:

- 임시 PostgreSQL·data root: 0
- 임시 leak fixture root: 0
- `frontend/test-results` files: 0
- E2E media: 0
- listener `55455`, `8000`, `4173`: 0
- backend·frontend server: 0

## 6. 검증 중 발견하고 닫은 테스트 하네스 결함

제품 assertion을 삭제하거나 약화하지 않고 원 테스트 소유자가 다음 결함을
최소 보정한 뒤 매번 discovery·TypeScript·lint와 실제 PG를 다시 확인했다.

1. trusted SQL의 `INSERT ... RETURNING` 출력에 psql command tag가 섞이던 문제
   - quiet 옵션을 추가해 tuple-only ID를 읽도록 보정
2. COMPLETE requirement가 참조한 fact를 무효화하려던 fixture 순서 모순
   - 미참조 fact를 update/invalidate 대상으로 사용해 DB reverse guard 유지
3. active-only GET에서 폐기 원본을 찾던 무효화 assertion 모순
   - 응답의 폐기 시각·대체 ID, 활성 목록의 대체행 존재·원본 부재를 검증
4. A→B helper가 검색·page·scroll을 초기화한 뒤 보존을 기대하던 순서 모순
   - 기존 page 2 목록의 B를 직접 선택
5. 8px overflow fixture에서 Playwright 자동 scroll-into-view가 offset을
   변경하던 드라이버 부작용
   - 동일 React click event를 auto-scroll 없이 전달하고 exact offset 검증 유지

## 7. 다음 단계

`W1A-VS4`를 다시 열지 않고 직원 분기상담을 별도 RED→구현→교차검증
micro-slice로 진행한다. 이후 초기 직원 이관·legacy mapping을 계속하며,
건강검진 자동 대상판정·D-day·업무카드는 공식 원문 확정 뒤 W2에서 다룬다.
