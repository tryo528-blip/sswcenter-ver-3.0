# W1A-VS6 직원 legacy mapping·합성 one-off 이관 RED 봉인

> 상태: `RED_VALID_PENDING_PRODUCT`
>
> 최종 검증 시각: 2026-07-28 15:22 KST
>
> 기준 branch: `wip/w1a-office-handoff`
>
> 기준 SHA: `6db858ac687f6db183a3a4b2b271ad3c0f5ddbb9`
>
> 정본: `docs/AI_업무분담_운영규정_v2.32.md`
>
> RED 작성: 송루나 / 독립 재현·최종판정: 김부장(Codex 본진)
>
> push·pull·reset·rebase·checkout·stash: 수행하지 않음

## 1. 판정

W1A-VS6의 제품 부재를 import/collection/환경 실패가 아닌 안정적인 제품 marker로
재현했다. 첫 marker는 다음과 같다.

```text
W1A_VS6_MIGRATION_MISSING
```

공개 API·OpenAPI·UI에 legacy mapping/import surface가 없다는 부재 계약 5건은
기준 SHA에서도 통과했다. 따라서 이 증거는 GREEN이 아니며
`RED_VALID_PENDING_PRODUCT`다.

## 2. 봉인 파일

1. `review/plans/W1A_VS6_STAFF_LEGACY_IMPORT_PLAN.md`
2. `review/packets/W1A_VS6_ASSIGNMENT_PACKET_v2.32.md`
3. `backend/tests/test_w1a_vs6_semantics.py`
4. `backend/tests/test_w1a_vs6_import_contract.py`
5. `backend/tests/test_w1a_vs6_postgres.py`
6. `backend/tests/test_w1a_vs6_absence_contract.py`
7. `scripts/test-w1a-vs6-postgres.ps1`
8. `review/evidence/w1a-vs6/RED.md`

제품 코드, 기존 migration·테스트, 프런트엔드, 생성 타입과 정본 원문은 RED 작성
단계에서 수정하지 않았다.

## 3. 정적·수집 검증

| 검증 | Exit | 결과 |
|---|---:|---|
| Ruff format check | 0 | 4 files already formatted |
| Ruff check | 0 | All checks passed |
| Mypy | 0 | 4 files, issue 0 |
| Compileall | 0 | PASS |
| PowerShell AST | 0 | `W1A_VS6_PS_AST_OK` |
| Pytest collect-only | 0 | 19 tests collected, collection error 0 |

`prepare` 계약은 문자열 존재 검사만 사용하지 않는다. 합성 구조화 행으로
`ALREADY_MAPPED`, batch 전체 `DUPLICATE_SOURCE_KEY`, one-off 자격증 최대 2개와
반환값의 counts/reason-only 구조를 실제 실행하도록 RED에 고정했다.

## 4. 구현 전 focused RED

실행:

```text
backend\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider \
  tests/test_w1a_vs6_semantics.py \
  tests/test_w1a_vs6_import_contract.py \
  tests/test_w1a_vs6_postgres.py \
  tests/test_w1a_vs6_absence_contract.py
```

결과:

- exit: `1`
- passed: `5`
- failed: `14`
- skipped: `0`
- errors: `0`
- 첫 실패: `W1A_VS6_MIGRATION_MISSING`
- migration·service·PostgreSQL 제품 부재 외 collection/setup 오류: `0`

## 5. 격리 PostgreSQL 17 RED

실행:

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass \
  -File scripts/test-w1a-vs6-postgres.ps1 -Port 55439
```

wrapper exit `1`은 유효 RED 판정이다.

| 항목 | 결과 |
|---|---|
| initdb / PostgreSQL start / role·DB bootstrap | `0 / 0 / 0` |
| 기준 head 적용 | `0`, 제품 부재 기준 `0007` |
| lifecycle | down/up/down/up 모두 `0` |
| offline SQL 별도 DB 적용·검증 | `0 / 0 / 0` |
| pytest | 19 collected, 5 passed, 14 failed, 0 skipped/errors |
| W1A postcheck | `0`, `W1A_VS6_POSTCHECK_OK=1` |
| dump/create/restore/revision verify | 모두 `0` |
| restore revision | `20260728_0007_w1a_staff_quarterly_consultation` |
| first marker | `W1A_VS6_MIGRATION_MISSING` |
| RED markers | `W1A_VS6_MIGRATION_MISSING`, `W1A_VS6_OFFLINE_MISSING` |
| 최종 판정 | `W1A_VS6_RED_VALID` |

cleanup:

```text
W1A_VS6_TEMP_CLUSTER_REMAINING=0
W1A_VS6_LISTENER_REMAINING=0
W1A_VS6_ARTIFACT_REMAINING=0
W1A_VS6_MEDIA_REMAINING=0
```

## 6. 누출 게이트

| 검증 | Exit | 결과 |
|---|---:|---|
| negative self-test | 0 | `W1A_LEAK_GATE_SELF_TEST_OK` |
| normal scan | 0 | 231 files, `W1A_LEAK_GATE_GREEN` |

테스트·문서·하네스에는 실제 개인정보, 운영 DB, 비밀키 또는 운영 파일을 넣지
않았다.

## 7. 검수 중 보정

제품 assertion을 삭제하거나 약화하지 않았다.

1. 기준 SHA를 축약값이 아닌 정확한 40자리 SHA로 고정했다.
2. PostgreSQL helper의 `Connection` 타입을 명시해 Mypy 오류 1건을 제거했다.
3. 테스트 data-root leaf를 설정 안전규칙에 맞는 `sswcenter-runtime`으로 고쳐
   환경 오류를 제품 RED로 오인하지 않게 했다.
4. 하네스 실패 진단은 세 합성 비밀번호와 DSN을 redaction하고 최대 40행으로
   제한했다.
5. `prepare`의 중복·재실행·제한·요약-only 동작을 합성값으로 실행하는
   test를 추가했다.

## 8. GREEN 전환 조건과 남은 경계

- additive `0008` migration과 ORM mapping
- 공개 router/OpenAPI/UI에 연결하지 않은 내부 `prepare`/`apply`
- 허용 필드만 반영하고 금지 필드는 안전한 reason으로 제외
- 포함행 전체 단일 transaction과 실패 시 exact 0-row rollback
- 주민번호 기존 AES-256-GCM 경로, 평문 출력 0
- active re-run과 batch duplicate의 안정 counts/reason
- 기존 `display_name`·`memo` 보존, 일반 자격증 CRUD 3건 이상 유지
- fresh/lifecycle/offline/ACL/FK/race/postcheck/restore와 전체 W1A 회귀 통과

실제 workbook parser·upload·preview UI, persistent staging/import run, file/OCR 구조는
가명 workbook과 source 정책이 확정되지 않은 후속 범위이므로 이번 slice에 만들지
않는다.
