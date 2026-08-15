# U-12 W1E 요양보호사 배정 API·UI 후보 부록

> 상태: `IMPLEMENTED_REVIEW_PENDING`
> 기준 브랜치: `codex/u12-care-assignment`
> 기준 base: `a55d25d64ea571acf94ca2cbfbfd38bf4eb5e4bf`
> 구현 후보: `e9c5f29` (`feat(w1e): add caregiver assignment API and UI`)

## 범위

- `care_assignment` 기존 0012 원장을 사용하는 W1E domain/repository/service를 추가했다.
- 수급자·계약별 배정 목록/생성/단건 조회/기간사실 정정 API를 등록했다.
- GENERAL/FAMILY 요청을 strict schema로 검증하고 FAMILY 관계 snapshot을 요구한다.
- 배정 정정은 기존 행을 무효화하고 새 행을 삽입한 뒤
  `replacement_assignment_id`를 연결한다. 기존 업무 ID와 history는 유지한다.
- 수급자 상세에 계약 선택, CARE_WORKER 직원 선택, GENERAL/FAMILY 기간 입력,
  관계 snapshot 입력, history와 정정 제어를 추가했다.
- OpenAPI 생성 타입을 갱신했다.

## API surface

```text
GET  /api/v1/recipients/{recipient_id}/contracts/{contract_id}/care-assignments
POST /api/v1/recipients/{recipient_id}/contracts/{contract_id}/care-assignments
GET  /api/v1/recipients/{recipient_id}/contracts/{contract_id}/care-assignments/{assignment_id}
PUT  /api/v1/recipients/{recipient_id}/contracts/{contract_id}/care-assignments/{assignment_id}
```

모든 write는 기존 `RECIPIENT_MANAGE`·CSRF dependency를 사용하고, read는
`RECIPIENT_VIEW` dependency를 사용한다. 기간 충돌·직원 자격·계약/재직 범위
위반은 DB constraint/trigger 진단을 안정 error code로 변환한다.

## 검증 증거

| 검사 | 결과 |
|---|---|
| U-12 backend focused | `28 passed` |
| backend full | `397 passed, 139 skipped`; 기존 fixed-hash 1건만 실패 (`B37B...` 기대 vs 현재 `B0CC...`) |
| U-12 frontend | `2 passed` |
| frontend supported suite | `26 files / 231 passed` |
| frontend build | `tsc -b` + Vite exit `0` |
| OpenAPI generation | `OPENAPI_TYPES_UP_TO_DATE` |
| changed backend Ruff | exit `0` |
| changed frontend oxlint | exit `0` (기존 RecipientsPage hook warning 2건은 unchanged) |
| diff check | exit `0` |

## 남은 경계

- 이 후보에서는 새 migration을 만들지 않았다. FAMILY `family_relationship_text`
  DB `CHECK` 보강과 PostgreSQL mutation gate는 별도 U-14 후보에서 다룬다.
- 기존 W1E migration/PG contract 테스트의 live PostgreSQL gate는 이 후보에서
  재실행하지 않았으며, `SSWCENTER_W1E_REAL_PG=1` 증거가 없는 상태다.
- 전체 backend의 fixed-hash 실패는 U-12 변경과 무관한 기존 원장 drift로 남겨 둔다.
- `/review` 결과와 지적사항 수정 후 최종 SHA를 다시 고정해야 한다. 이 부록은
  W1F PASS·release 승인·보안 최종검사를 의미하지 않는다.
