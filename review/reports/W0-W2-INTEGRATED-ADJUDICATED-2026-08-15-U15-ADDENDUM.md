# SSWCenter 3.0 W0~W2 통합 재판정 — U-15 recipient TEST sentinel 부록

> 부록일: 2026-08-15 KST
> 적용 대상: [`W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md`](W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md)
> 평가 기준: `main` base `a55d25d64ea571acf94ca2cbfbfd38bf4eb5e4bf` → candidate `fadc74d`
> 지위: U-15 한 슬라이스의 구현·검증 후보 기록. W1 전체 acceptance·운영 수용·release 승인과 동일하지 않다.

## 판정

| ID | 이전 상태 | candidate 상태 | 범위 |
|---|---|---|---|
| U-15 | `CURRENT_CONFIRMED` | `SATISFIED_BY_CANDIDATE` | DB/ORM이 허용하는 합성 `TEST` recipient sex sentinel을 API enum·응답 조립·생성 TypeScript 계약에 맞췄다. |

`SATISFIED_BY_CANDIDATE`는 구현 커밋과 검증 증거가 있는 PR 후보라는 뜻이다. PR 병합과 최종 Grade 5/security review 전에는 current-main 해결로 재사용하지 않는다.

## 구현 범위

- `backend/app/domains/recipient/schemas.py`
  - `RecipientSexCode.TEST`를 생성·수정·응답 enum에 포함한다.
  - `RecipientService._recipient_response`의 enum cast가 DB `TEST` 값을 그대로 반환할 수 있게 한다.
- `frontend/src/generated/sswcenter-api.ts`
  - OpenAPI 재생성으로 `RecipientSexCode`를 `MALE | FEMALE | TEST`로 동기화한다.
- `backend/tests/test_u15_recipient_sex_sentinel.py`
  - 생성 request와 response projection이 `TEST`를 round-trip하는지 직접 검증한다.

## 검증 증거

- focused backend contract pytest: `26 passed, 1 skipped`.
- 전체 backend pytest: `391 passed, 139 skipped`; 기존 `test_r0_w2_read_only_contract_02_file_hashes_are_expected` 1건은 candidate와 무관한 고정 hash 불일치(`expected B37B...`, current `B0CC...`)로 남았다.
- frontend supported Vitest: `25 files, 229 passed`.
- frontend build (`tsc -b` + Vite): exit `0`.
- generated OpenAPI check: `OPENAPI_TYPES_UP_TO_DATE`, exit `0`.
- 변경 frontend generated file oxlint: exit `0`.
- 전체 frontend oxlint에는 기존 경고 5건이 있어 `--deny-warnings` exit `1`; 변경 파일 이외의 Fast Refresh/exhaustive-deps 경고다.
- `git diff --check`: exit `0`.

## 남은 경계

- 실제 격리 PostgreSQL에서 `TEST` recipient 생성·조회·수정 전체와 production 환경 차단을 함께 실행하는 증거는 이 candidate에서 다루지 않았다.
- U-15 ordinary `/review`는 PR candidate에서 수행하며, 지적사항이 있으면 수정 후 위 검증을 재실행한다.
- U-15 candidate 보안 스캔은 최종 다중 슬라이스 후보에서 한 번만 수행한다.
