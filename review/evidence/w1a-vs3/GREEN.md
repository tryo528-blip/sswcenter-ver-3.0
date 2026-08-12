# W1A-VS3 GREEN 최종 검증 증거

> 상태: `PASS / GREEN_SEALED`
>
> 최종 검증 시각: 2026-07-28 07:07 KST
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 기준 commit: `728958d4357b12bf34996ce10221118238b67c20`
>
> 검증 대상: 위 commit 이후 현재 unstaged/untracked W1A-VS3 작업본
>
> 총괄·최종판정: 김부장(Codex 본진 / SOL Max)
>
> stage·commit·push: 수행하지 않음

## 1. 최종 판정

`W1A-VS3` 직원 신규·정기교육을 실제 PostgreSQL, FastAPI, 생성 OpenAPI 타입,
React UI와 실제 브라우저에서 독립 재현했다.

재직별 신규직원교육, 직원·과목·기간별 정기교육, 같은 기간 재입사 보존,
완료·완료해제 audit, 권한·동시성·rollback과 exact 교육과목 7행을 모두
검증했다. 봉인 RED는 수정하거나 약화하지 않았다.

DB와 UI 교차검증, 누락 behavioral 계약 보강, 김부장 최종 runtime gate가 모두
GREEN이므로 `W1A-VS3 PASS / GREEN_SEALED`로 판정한다.

이 판정은 W1A 전체 완료가 아니다. 건강검진, 직원 분기상담, 초기 직원 이관과
legacy mapping은 후속 W1A micro-slice에서 계속한다.

## 2. 역할별 결과

| 담당 | 범위 | 판정 |
|---|---|---|
| 김루나 | `0005` migration, backend·DB·OpenAPI 구현 | PASS |
| 박루나 | frontend 구현과 누락 behavioral 계약 보강 | PASS |
| 이루나 | migration·DB invariant·ACL·동시성·rollback 교차검증 | PASS |
| 송루나 | 실제 PG UI·문맥·민감정보·artifact·3 viewport 교차검증 | PASS |
| 김부장 | diff·전체 runtime gate 독립 재현·최종판정 | PASS |

## 3. PostgreSQL·backend 증거

| 검증 | Exit | 결과 |
|---|---:|---|
| backend 전체 pytest | 0 | 78 passed, 26 skipped |
| Ruff format check | 0 | 58 files already formatted |
| Ruff check | 0 | All checks passed |
| mypy | 0 | 29 source files, no issues |
| W1A-VS3 실제 PostgreSQL harness | 2 | 내부 18 passed, 0 failed/skipped/errors |
| W1A-VS1 실제 PostgreSQL 회귀 | 0 | `W1A_POSTGRES_HARNESS_OK` |
| W1A-VS2 실제 PostgreSQL 회귀 | 0 | 16/16, `W1A_VS2_POSTGRES_GREEN` |
| OpenAPI 생성 타입 drift | 0 | `OPENAPI_TYPES_UP_TO_DATE` |
| `git diff --check` | 0 | whitespace 오류 없음 |

VS3 harness의 wrapper exit 2와 `W1A_VS3_RED_NOT_REPRODUCED`는 제품 부재
marker가 모두 사라진 GREEN 전환의 설계된 결과다. 내부 증거는 다음과 같다.

- database bootstrap, migration head, `0005` downgrade·upgrade: 모두 0
- offline SQL: 0
- collection: 18 tests
- 실행: 18 passed, 0 failed, 0 skipped, 0 errors
- 제품 부재 marker: 0
- PostgreSQL stop: 0
- 임시 cluster: 0
- postcheck: `W1A_VS3_DB_POSTCHECK_OK`

행동계약은 exact 교육과목 7행, employment/onboarding 동일 transaction과 exact
rollback, 재입사 신규 onboarding, 같은 `2026-H1` periodic ID·완료상태 유지,
중복 race, stale row version 409, 완료·완료해제 audit, ADMIN·`STAFF_VIEW`·
`STAFF_MANAGE`·ungranted USER, CSRF와 field-level 422를 포함한다.

## 4. Frontend·브라우저 증거

| 검증 | Exit | 결과 |
|---|---:|---|
| VS3 focused Vitest | 0 | 봉인 4 + 구현 behavioral 8 = 12/12 |
| frontend 전체 Vitest | 0 | 12 files, 74 passed |
| oxlint | 0 | PASS |
| TypeScript·Vite build | 0 | 147 modules |
| 전체 Playwright discovery | 0 | 18 tests, 4 files, workers 1 |
| 실제 PG VS3 Playwright | 0 | workers 1, 3/3 passed |

실제 PG Playwright viewport:

- `1440x1000`
- `1440x900`
- `1366x768`

fresh isolated PostgreSQL와 migration head 뒤 E2E 자체 bootstrap으로 실행했고,
각 viewport가 exact catalog, 신규·정기교육, 완료·완료해제, 재입사 same-period,
GET 재조회, A↔B·검색·정렬·page·실제 scroll event·교육 tab·browser back,
popup 0, 가로 overflow 0과 금지필드·민감정보 부재를 끝까지 통과했다.

추가 구현 behavioral test 8개는 소스 문자열 검사가 아니라 실제
render·fetch·mutation·`QueryClient` 행동으로 다음을 증명한다.

- loading·error·empty와 API-only catalog source
- `STAFF_VIEW` read-only, `STAFF_MANAGE`·ADMIN write
- 신규·정기교육 `false→true→false`, `expected_row_version`, 성공 재조회
- stable 409·field-level 422·403에서 직원·tab·period·checkbox 상태 보존
- 직원 A→B와 session/logout의 지연응답 abort
- `AbortSignal`, query·mutation cache 격리와 stale success 차단

## 5. 누출·artifact·cleanup 증거

| 검증 | Exit | 결과 |
|---|---:|---|
| leak gate negative self-test | 0 | `W1A_LEAK_GATE_SELF_TEST_OK` |
| normal leak gate | 0 | 196 files, `W1A_LEAK_GATE_GREEN` |
| 실제 PG E2E artifact | 0 | 1 runner metadata file, media 0 |
| `git diff --check` | 0 | whitespace 오류 없음 |

최초 self-test와 normal gate를 동시에 실행한 검증자 orchestration에서 normal
gate가 self-test의 의도적 민감 fixture를 fail-closed로 탐지했다. 두 명령을
직렬화하고 해당 임시 fixture를 정확한 temp 경계에서 cleanup한 뒤 self-test와
normal gate를 각각 exit 0으로 독립 재현했다. 검사 제외나 assertion 약화는
하지 않았다.

최종 cleanup:

- 임시 PostgreSQL·data root: 0
- 임시 leak fixture root: 0
- `frontend/test-results`: 0
- E2E media: 0
- listener `55433`~`55448`, `8000`, `4173`: 0

## 6. 구현·검증 중 발견하고 닫은 결함

1. VS3 E2E helper의 CSRF header, Node/DOM 문맥, page/row readiness와 실제
   overflow·scroll fixture 결함
   - 송루나가 허용된 VS3 E2E 한 파일에서만 보정
   - 중복 workaround 제거 뒤 fresh PG 3/3을 다시 확인
2. 봉인 focused test 이름과 실제 assertion 의미가 달라 loading·error·권한·
   session·cache·abort 행동증거가 비어 있던 검증 공백
   - 봉인 RED는 수정하지 않음
   - 박루나가 새 구현 behavioral test 한 파일로 8개 실제 행동을 보강
   - 제품 추가 변경 없이 focused 12/12, 전체 74/74

## 7. 다음 단계

`W1A-VS3`를 다시 열지 않고 W1A 건강검진을 별도 RED→구현→교차검증
micro-slice로 진행한다. 이후 분기상담과 초기이관/legacy mapping을 계속하며,
디자인·내부 사용성 조정은 사용자 지시에 따라 W2로 넘긴다.
