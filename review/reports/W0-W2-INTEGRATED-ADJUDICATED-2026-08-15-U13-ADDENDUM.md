# U-13 W1E 전문직 담당 workspace 후보 부록

> 상태: `IMPLEMENTED_REVIEW_PENDING`
> 기준 브랜치: `codex/u13-professional-assignment`
> 기준 base: `a55d25d64ea571acf94ca2cbfbfd38bf4eb5e4bf`
> 구현 후보: `771afb6` (`feat(w1e): add professional assignment workspace`)

## 범위

- 기존 W2 전문직 담당 API를 generated-client 소비 경로로 연결했다.
- 수급자·서비스월 단위로 현재 담당과 변경 이력을 조회한다.
- 사회복지사·간호사 중 현재 재직·현 직위가 유효한 직원만 선택지로 노출한다.
- 담당 추가와 기존 담당 정정(행 무효화·replacement history)은 기존 API 계약의
  날짜·row-version payload를 사용한다.
- Social Workers 화면에 토글형 전문직 담당 workspace를 추가했다.

## API surface

```text
GET  /api/v1/professional-assignments/{recipient_id}?service_month=YYYY-MM-01
POST /api/v1/professional-assignments/{recipient_id}/{service_month}
PUT  /api/v1/professional-assignments/{recipient_id}/{service_month}/{assignment_id}
```

이 후보는 backend route/domain/schema/migration을 변경하지 않았다. 기존 W2 API의
권한·검증·원장 semantics를 프론트엔드가 그대로 호출하며, backend DB live 증거를
새로 주장하지 않는다.

## 검증 증거

| 검사 | 결과 |
|---|---|
| U-13 frontend focused | `1 file / 2 passed` |
| frontend supported suite | `26 files / 231 passed` |
| frontend build | `tsc -b` + Vite exit `0` |
| changed frontend oxlint | exit `0` |
| diff check | exit `0` |
| backend source/test execution | 이 후보에서 backend 파일을 바꾸지 않았고, 현재 worktree의 시스템 Python에는 SQLAlchemy가 없어(`ModuleNotFoundError`) 별도 실행 증거를 만들지 않음 |

## 남은 경계

- 빈 월은 `담당 없음`으로 표시하지만 월중 부분 공백을 별도 timeline 그래프로
  표현하지 않는다. 상세 공백 시각화는 후속 UI 범위다.
- 실제 PostgreSQL 권한·exclusion·replacement trigger 검증은 기존 W2 backend
  contract/PG evidence의 범위이며 이 후보의 새 live 증거가 아니다.
- `/review` 결과와 지적사항 수정 후 최종 SHA를 다시 고정해야 한다. 이 부록은
  W1F PASS·release 승인·최종 보안검사를 의미하지 않는다.
