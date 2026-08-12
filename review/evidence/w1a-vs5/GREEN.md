# W1A-VS5 직원 분기상담 GREEN 최종 검증 증거

> 상태: `PASS / GREEN_SEALED`
>
> 최종 검증 시각: 2026-07-28 15:02 KST
>
> 기준 branch: `wip/w1a-office-handoff`
>
> backend 체크포인트: `78570838ae3b7932d4c685ad3c9b54713dcee795`
>
> 총괄·최종판정: 김부장(Codex 본진 / SOL Max)
>
> 검증 중 push: 수행하지 않음

## 1. 최종 판정

`W1A-VS5` 직원 분기상담을 실제 PostgreSQL 17, FastAPI, 생성 OpenAPI
TypeScript, React UI와 실제 Chromium 3개 viewport에서 입증했다.

직원·달력연도·분기별 active unique, exact `COMPLETE` / `INCOMPLETE` /
`EXEMPT` truth table, stale·wrong-staff·duplicate·field validation, 생성·수정,
무효화·대체와 두 audit의 원자성을 확인했다. 공개 API는 collection GET/POST,
item PATCH, invalidate POST만 존재하며 item GET과 Wave 2 교체상담·Wave 5
file/evidence 의존은 없다.

UI는 독립 `분기상담` 탭, 상태별 조건부 필드, `STAFF_VIEW` read-only,
`STAFF_MANAGE`·ADMIN mutation, 입력 보존, 직원·세션 전환의 abort/cache 격리를
충족한다. 따라서 `W1A-VS5 PASS / GREEN_SEALED`로 판정한다.

이 판정은 W1A 전체 완료가 아니다. 초기 직원 이관과 내부
`staff_legacy_mapping`은 후속 `W1A-VS6`에서 계속한다.

## 2. 담당별 결과

| 담당 | 범위 | 판정 |
|---|---|---|
| Grok Build | VS5 다중 모델·경계·실패조건 1차 설계 | PASS |
| 김루나 | `0007` migration, backend·DB·API·OpenAPI 구현 | PASS |
| 박루나 | 생성 타입 기반 adapter, 독립 탭·폼·상태관리 | PASS |
| 이루나 | backend와 frontend 계약 독립 교차검증 | PASS |
| 김부장 | 하네스 교정, 전체 runtime 재현, 실제 PG 브라우저 최종판정 | PASS |

## 3. PostgreSQL·backend 증거

| 검증 | Exit | 결과 |
|---|---:|---|
| VS5 focused non-PG pytest | 0 | 14 passed, 5 skipped |
| backend 전체 pytest | 0 | 101 passed, 38 skipped |
| Ruff format/check | 0 / 0 | PASS |
| 제품파일 mypy | 0 | issue 0 |
| VS5 실제 PostgreSQL harness | 1 | 내부 19 passed, 0 failed/skipped/errors |
| OpenAPI TypeScript 생성 후 check | 0 | `OPENAPI_TYPES_UP_TO_DATE` |
| PowerShell AST | 0 | restore·VS5 harness 모두 PASS |
| 이루나 독립 focused 검증 | 0 | 19 passed, 2 skipped |

실제 PostgreSQL harness의 wrapper exit 1은 RED 전용 실행기가 제품 부재 marker를
찾지 못해 `W1A_VS5_RED_NOT_REPRODUCED`를 반환한 의도된 GREEN 전환 결과다.

- fresh DB migration upgrade: PASS
- `0007 → 0006 → 0007` 반복 lifecycle: PASS
- offline SQL 생성·별도 DB 적용·검증: PASS
- DB 계약 19/19: PASS
- postcheck: `W1A_VS5_BASELINE_DB_POSTCHECK_OK`
- backup/restore revision:
  `20260728_0007_w1a_staff_quarterly_consultation`
- PostgreSQL stop·DB drop·temp cluster·listener 잔류: 모두 0

## 4. Frontend·실브라우저 증거

| 검증 | Exit | 결과 |
|---|---:|---|
| VS5 focused Vitest | 0 | 6/6 |
| frontend 전체 Vitest | 0 | 14 files, 85/85 |
| oxlint | 0 | PASS |
| TypeScript·Vite build | 0 | 147 modules |
| 실제 PG VS5 Playwright | 0 | workers 1, 3/3 passed |

실제 PG Playwright viewport:

- `1440x1000`
- `1440x900`
- `1366x768`

각 viewport에서 trusted synthetic fixture의 세 상태를 조회하고, COMPLETE 생성,
INCOMPLETE 수정, EXEMPT replacement를 포함한 무효화, payload·row version·후속
GET을 검증했다. 직원 A↔B 선택, 검색·정렬·page·실제 scroll·tab·browser-back
문맥, 로그아웃, popup 0, 가로 overflow 0, 금지 surface·내부 오류·secret 부재도
확인했다.

최종 cleanup:

- backend listener: 0
- frontend listener: 0
- Playwright artifact: 0
- PostgreSQL temp cluster: 0

## 5. 검증 중 발견·보정한 결함

제품 assertion을 삭제하거나 약화하지 않았다.

1. item 경로에 PATCH만 공개하는 정본과 달리, 미존재 행 테스트가 GET을 사용해
   정상 FastAPI의 405를 404 실패로 오인했다.
   - 미존재 행 검증을 계약된 PATCH와 유효 payload로 교정했다.
2. VS3 역사적 future-scope 부재 테스트가 현재 통합 app의 인접 import 문맥까지
   검사해 VS5를 누수로 오인했다.
   - immutable `0005` training migration의 범위 부재를 검사하도록 좁혔다.
3. 현재 metadata exact 목록에 새 `staff_quarterly_consultation` 테이블이 빠져
   전체 회귀가 실패했다.
   - 현재 schema 기대 목록에 승인된 테이블을 추가했다.
4. 실브라우저에서 section의 `aria-label="분기상담"`이 폼의 `분기` label과
   충돌했다.
   - 중복 section label을 제거하고 내부 heading을 유지했다.
5. 생성·무효화 폼과 기존 읽기전용 행이 같은 필드 label을 동시에 노출했다.
   - mutation form이 열린 동안 기존 행은 값 요약 텍스트로 전환하고, 일반
     조회와 행별 수정에서는 접근 가능한 label을 유지했다.

각 보정 후 focused test, lint, build와 실제 PG Playwright를 다시 실행했다.

## 6. 금지 범위 확인

- item GET API 없음
- Wave 2 care-change 상담 route·status·table 공유 없음
- file·attachment·evidence FK/property/UI 없음
- legacy mapping/import surface 없음
- 일반 응답·DOM에 내부 SQL·constraint·DSN·secret 없음
- 운영 DB·실 개인정보 사용 없음
- Git push 없음

## 7. 다음 단계

`W1A-VS5`는 다시 열지 않는다. `W1A-VS6`에서 공개 import API/UI 없이 내부
`staff_legacy_mapping`과 합성 구조화 레코드 기반 one-off 초기 직원 이관을
RED → GREEN으로 완료한 뒤 W1A 전체 통합 gate를 수행한다.
