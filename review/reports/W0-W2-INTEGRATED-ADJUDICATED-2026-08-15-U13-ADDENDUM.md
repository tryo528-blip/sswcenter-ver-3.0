# U-13 W1E 전문직 담당 workspace 후보 부록

> 상태: `IMPLEMENTED_REVIEW_PENDING`
> 기준 브랜치: `codex/u13-professional-assignment`
> 기준 base: `a55d25d64ea571acf94ca2cbfbfd38bf4eb5e4bf`
> 최종 후보: `HEAD` (latest DTO, capability, timeline, and context-race fixes)
> 정기 `/review`: 최신 후보 재요청 대기
> Codex Security: 현재 후보에는 실행하지 않음. 최종 수동 보안검수는 형님이 수행한다.

## 범위

- 기존 W2 전문직 담당 API를 generated-client 소비 경로로 연결했다.
- 수급자·서비스월 단위로 현재 담당과 변경 이력을 조회한다.
- 사회복지사·간호사 중 담당 기간 전체를 덮는 재직·전문직 직위 이력이 있는
  직원만 선택지로 노출한다.
- staff 권한이 없는 계정에서도 recipient-month history 조회가 중단되지 않도록
  recipient/staff 로딩을 분리했다.
- 수급자·직원 전체 페이지를 순회하고, employment·position history가 선택 기간과
  전체를 덮는 경우만 담당자로 노출한다. 연속된 position period는 이어 붙여
  검증하며, selection/month generation guard로 stale 응답을 폐기한다.
- `GET /api/v1/professional-assignments/staff-options`의 최소 직원·기간 투영을
  `RECIPIENT_VIEW` 경계로 조회해 `STAFF_VIEW` 없이도 선택지를 구성한다. 전화·주소·
  주민번호·메모 등 직원 상세 필드는 이 투영에 포함하지 않는다.
- staff-options의 employment/position projection은 담당 선택에 필요한 id·기간·직종만
  반환하며 HR 번호·종료사유·row version을 포함하지 않는다.
- `recipient.manage` session capability가 없는 계정에는 추가·정정 controls를 숨긴다.
- 월중 active assignment의 앞·뒤 공백을 각각 `담당 없음` interval로 표시하고,
  선택 기간 시작일에 적용되는 professional position을 label에 사용한다.
- recipient/month 컨텍스트가 저장 중 바뀌어도 새 컨텍스트의 saving 잠금이 남지
  않도록 저장 상태를 독립적으로 해제한다.
- 담당 추가와 기존 담당 정정(행 무효화·replacement history)은 기존 API 계약의
  날짜·row-version payload를 사용한다.
- Social Workers 화면에 토글형 전문직 담당 workspace를 추가했다.

## API surface

```text
GET  /api/v1/professional-assignments/{recipient_id}?service_month=YYYY-MM-01
GET  /api/v1/professional-assignments/staff-options?page=1&page_size=200
POST /api/v1/professional-assignments/{recipient_id}/{service_month}
PUT  /api/v1/professional-assignments/{recipient_id}/{service_month}/{assignment_id}
```

staff-options는 담당자 선택에 필요한 직원명·재직·직위 기간만 반환하는 W2 read
projection이다. 담당 추가·정정 mutation은 기존 `RECIPIENT_MANAGE` API와
backend의 전체기간 검증을 그대로 사용한다. 새 migration은 없으며, backend DB
live 증거를 새로 주장하지 않는다.

## 검증 증거

| 검사 | 결과 |
|---|---|
| U-13 frontend focused (리뷰 후 재실행) | `1 file / 8 passed` |
| frontend supported suite | `26 files / 236 passed` |
| frontend build | `tsc -b` + Vite exit `0` |
| W2/W1A backend contract (리뷰 후 재실행) | `16 passed` |
| OpenAPI generation | `OPENAPI_TYPES_UP_TO_DATE` |
| changed frontend oxlint | exit `0` |
| changed backend Ruff/py_compile | exit `0` |
| diff check | exit `0` |
| backend live PostgreSQL | 이 후보에서 새로 실행하지 않음; 기존 W2 PG evidence 범위로 남김 |

## 남은 경계

- 빈 월은 `담당 없음`으로 표시하지만 월중 부분 공백을 별도 timeline 그래프로
  표현하지 않는다. 상세 공백 시각화는 후속 UI 범위다.
- 실제 PostgreSQL 권한·exclusion·replacement trigger 검증은 기존 W2 backend
  contract/PG evidence의 범위이며 이 후보의 새 live 증거가 아니다.
- 현재 후보의 ordinary `/review`는 아직 재요청 중이며, 최종 보안검수는 형님 수동 절차로 남긴다.
- live PostgreSQL·인증 브라우저·운영 배포 perimeter는 검증하지 않았다. 이 부록은 W1F PASS·release
  승인·전체 W0~W2 acceptance를 의미하지 않는다.
