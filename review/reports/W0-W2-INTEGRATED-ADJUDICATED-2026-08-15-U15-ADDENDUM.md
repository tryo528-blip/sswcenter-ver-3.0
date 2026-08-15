# SSWCenter 3.0 W0~W2 통합 재판정 — U-15 recipient TEST sentinel 부록

> 부록일: 2026-08-15 KST
> 적용 대상: [`W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md`](W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md)
> 평가 기준: `main` base `a55d25d64ea571acf94ca2cbfbfd38bf4eb5e4bf` → candidate `ea3fde1`
> 지위: U-15 한 슬라이스의 구현·검증 후보 기록. W1 전체 acceptance·운영 수용·release 승인과 동일하지 않다.

## 판정

| ID | 이전 상태 | candidate 상태 | 범위 |
|---|---|---|---|
| U-15 | `CURRENT_CONFIRMED` | `SATISFIED_BY_CANDIDATE` | 합성 `TEST` recipient sex sentinel은 응답·목록에서만 허용하고, 생성·수정 입력과 프론트 쓰기 payload에서는 제외했다. |

`SATISFIED_BY_CANDIDATE`는 구현 커밋과 검증 증거가 있는 PR 후보라는 뜻이다. PR 병합과 최종 Grade 5/security review 전에는 current-main 해결로 재사용하지 않는다.

## 구현 범위

- `backend/app/domains/recipient/schemas.py`
  - 생성·수정용 `RecipientInputSexCode`는 `MALE | FEMALE`만 허용한다.
  - 응답·목록용 `RecipientSexCode`는 `MALE | FEMALE | TEST`를 유지한다.
  - `RecipientService._recipient_response`의 enum cast가 DB `TEST` 값을 그대로 반환할 수 있게 한다.
- `frontend/src/generated/sswcenter-api.ts`
  - 입력 요청에는 `RecipientInputSexCode`, 응답에는 `RecipientSexCode`를 참조하도록 동기화했다.
- `frontend/src/services/recipientApi.ts` 및 `frontend/src/pages/RecipientsPage.tsx`
  - 생성·수정 타입과 payload에서 `TEST`를 배제하고, 상세 `TEST`는 읽기 전용 선택값으로 표시한다.
  - 기존 성별을 `미입력`으로 지울 때 `sex_code: null`을 명시적으로 전송한다.
- `backend/tests/test_u15_recipient_sex_sentinel.py`
  - 생성·수정 request가 `TEST`를 거부하고 response projection이 `TEST`를 보존하는지 검증한다.
- `frontend/src/test/RECListFrontend.test.tsx`
  - 상세 `TEST` 응답이 열리고 성별 컨트롤이 읽기 전용인지 검증한다.

## 검증 증거

- U-15 frontend focused Vitest: `53 passed`.
- frontend supported Vitest: `25 files, 230 passed`.
- frontend build (`tsc -b` + Vite): exit `0`.
- 변경 파일 oxlint: exit `0`; 기존 `RecipientsPage.tsx`의 exhaustive-deps 경고 2건만 남았다.
- backend Ruff 및 `py_compile`: exit `0`.
- backend U-15 pytest: `1 passed`, exit `0` (shared backend venv).
- OpenAPI generator `-Check`: 동일한 backend 의존성 부재로 재실행하지 못했으며, checked-in generated contract는 입력/응답 enum 분리를 반영했다.
- `git diff --check`: exit `0`.

## 남은 경계

- 실제 격리 PostgreSQL에서 `TEST` recipient 조회와 production 생성·수정 차단을 실행하는 증거는 이 candidate에서 다루지 않았다.
- U-15 ordinary `/review`는 PR candidate에서 수행하며, 지적사항이 있으면 수정 후 위 검증을 재실행한다.
- U-15 candidate 보안 스캔은 최종 다중 슬라이스 후보에서 한 번만 수행한다.
