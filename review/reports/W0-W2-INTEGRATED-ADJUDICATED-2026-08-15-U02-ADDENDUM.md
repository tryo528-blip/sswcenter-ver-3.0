# SSWCenter 3.0 W0~W2 통합 재판정 — U-02 인증 422 redaction 부록

> 부록일: 2026-08-15 KST
> 적용 대상: [`W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md`](W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md)
> 평가 기준: `main` base `a55d25d64ea571acf94ca2cbfbfd38bf4eb5e4bf` → candidate `HEAD` (deterministic redaction-test correction)
> 지위: U-02 한 슬라이스의 구현·검증 후보 기록. PR 병합·보안 review·W0 전체 acceptance와 동일하지 않다.

## 판정

| ID | 이전 상태 | candidate 상태 | 범위 |
|---|---|---|---|
| U-02 | `CURRENT_CONFIRMED` | `SATISFIED_BY_CANDIDATE` | `/api/auth/**`와 `/api/bootstrap`의 schema `422`를 공통 `VALIDATION_ERROR` 봉투로 반환하고, PIN·요청 body가 `input` 필드나 원문 문자열로 재노출되지 않도록 했다. |

`SATISFIED_BY_CANDIDATE`는 별도 구현 worktree와 현재 테스트 증거가 있다는 뜻이다. PR·최종 보안 review·release 승인 전에는 current-main 해결로 재사용하지 않는다.

## 구현 범위

- `backend/app/api/w1a_errors.py`
  - `/api/v1/` 기존 구조화 validation 경로를 유지한다.
  - `/api/auth/**`와 `/api/bootstrap`도 같은 `VALIDATION_ERROR`/`field_errors` 봉투를 사용한다.
  - FastAPI 기본 `RequestValidationError`의 `input` 전체를 인증 응답에서 제거한다.
  - 인증·bootstrap의 업무 422 `HTTPException`도 같은 봉투로 정규화하고 원문 `detail.message`를 노출하지 않는다.
- `backend/app/api/auth.py`와 `frontend/src/generated/sswcenter-api.ts`
  - 로그인·bootstrap의 OpenAPI 422 응답을 `ErrorEnvelope`로 명시하고 생성 TypeScript 계약을 재생성했다.
- `backend/tests/test_u02_auth_validation_redaction.py`
  - 로그인 PIN 길이 오류가 422 봉투를 사용하고 `input`·PIN을 포함하지 않는지 검증한다.
  - bootstrap PIN 오류가 제출 PIN·요청 body를 재노출하지 않는지 검증한다.
  - 비인증 경로는 기존 기본 handler 범위를 유지하는지 확인한다.
  - 실제 production app OpenAPI가 두 인증 operation 모두 `ErrorEnvelope`를 선언하는지 검증한다.
  - PIN redaction assertion은 UUID `request_id`를 제외한 response fields만 검사해 우연한 숫자 충돌을 배제한다.

## 검증 증거

- U-02 focused pytest plus security regression: `13 passed`, exit `0`.
- 관련 회귀(`test_u02`, `test_health`, `test_security`, `test_settings`): `70 passed`, exit `0`.
- OpenAPI 생성물 check: `OPENAPI_TYPES_UP_TO_DATE`, exit `0`.
- Ruff: 변경 Python 파일 exit `0`.
- `git diff --check`: exit `0`.

## 남은 경계

- 이 부록은 로컬 Codex Security review 결과가 아니며, 전체 슬라이스 완료 후 최종 후보에서 1회 수행한다.
- 실제 운영 FastAPI deployment와 production browser/client는 이 candidate에서 검증하지 않았다.
- `/api/v1/`의 기존 field mapping은 변경하지 않았으며, U-03 로그인 상태전이는 별도 슬라이스다.
