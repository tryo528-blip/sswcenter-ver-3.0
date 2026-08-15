# SSWCenter 3.0 W0~W2 통합 재판정 — U-03 인증 상태전이 부록

> 부록일: 2026-08-15 KST
> 적용 대상: [`W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md`](W0-W2-INTEGRATED-ADJUDICATED-2026-08-14.md)
> 평가 기준: `main` base `a55d25d64ea571acf94ca2cbfbfd38bf4eb5e4bf` → candidate `7a962ba`
> 지위: U-03 한 슬라이스의 구현·검증 후보 기록. PR 병합·보안 review·W0 전체 acceptance와 동일하지 않다.

## 판정

| ID | 이전 상태 | candidate 상태 | 범위 |
|---|---|---|---|
| U-03 | `CURRENT_CONFIRMED` | `SATISFIED_BY_CANDIDATE` | 로그인 401/423/429 오류를 화면에 소비하고, bootstrap status 401에서 초기 loading이 종료되도록 인증 상태전이를 봉인했다. |

`SATISFIED_BY_CANDIDATE`는 별도 구현 worktree와 현재 테스트 증거가 있다는 뜻이다. PR·최종 보안 review·release 승인 전에는 current-main 해결로 재사용하지 않는다.

## 구현 범위

- `frontend/src/components/auth/LoginForm.tsx`
  - `AuthProvider.error`를 로그인 화면의 alert로 렌더링한다.
  - 실제 PIN 제출 실패에만 별도 `pinError`를 연결해 PIN input의 `aria-invalid`와
    `aria-describedby`가 system/bootstrap 상태 오류를 PIN 오류로 오인하지 않도록 한다.
- `frontend/src/context/AuthProvider.tsx` / `AuthContext.ts`
  - system/auth bootstrap 오류와 401/423/429 PIN 제출 오류를 별도 상태로 유지한다.
- `frontend/src/services/api.ts`
  - `/api/bootstrap/status`의 401은 이미 익명 초기 상태를 확인하는 요청이므로 전역 `AUTH_UNAUTHORIZED_EVENT`를 발생시키지 않는다.
  - 따라서 `AuthProvider.checkAuthStatus`가 generation guard에 막히지 않고 loading을 종료한다.
- `frontend/src/test/Auth.test.tsx`
  - 로그인 401/423/429의 사용자-visible 메시지를 각각 검증한다.
  - bootstrap status 401에서 login form 전환·loading 종료·unauthorized event 부재를 검증한다.
  - bootstrap status 401에서는 PIN input이 invalid/description 상태가 아님도 검증한다.

## 검증 증거

- U-03 focused Vitest (`Auth.test.tsx`): `20 passed`, exit `0`.
- 관련 Vitest (`Auth.test.tsx`, `AppRouting.test.tsx`): `23 passed`, exit `0`.
- 전체 지원 프론트 테스트: `25 files, 232 passed`, exit `0`.
- TypeScript project build (`tsc -b`): exit `0`.
- 변경 파일 oxlint: exit `0`.
- `git diff --check`: exit `0`.

## 남은 경계

- 이 부록은 로컬 Codex Security review 결과가 아니며, 전체 슬라이스 완료 후 최종 후보에서 1회 수행한다.
- 실제 운영 브라우저·네트워크·인증 서버에서의 live 상태전이는 이 candidate에서 검증하지 않았다.
- U-02 backend 422 redaction과 U-04/U-06 로그 안전은 각각 별도 슬라이스다.
