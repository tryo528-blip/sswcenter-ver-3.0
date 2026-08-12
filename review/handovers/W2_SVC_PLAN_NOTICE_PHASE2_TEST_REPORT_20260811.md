# W2 급여계획서(Service Plan Notice) Phase 2 — 테스트 결과 및 재개 보고서

- 작성일: 2026-08-11 (KST)
- 작성자: 레지나
- 대상 저장소: C:\sswcenter\2.2
- 목적: 집에서 W2 Phase 2 작업을 안전하게 재개하기 위한 현재 상태·테스트 결과·남은 작업 인계

## 1. 기준 핸드오프

첨부된 W2 급여계획서(Service Plan Notice) Phase 2 — 세션 핸드오프 B를 기준으로 작업을 재개했다.

핸드오프 시작 상태는 다음과 같았다.

- 브랜치: main
- HEAD: 051c7ef
- 제품 구현: 미커밋
- 변경 파일: 마이그레이션, ORM 모델, 도메인 순수함수, 계약 테스트, PostgreSQL 테스트 등 5개
- 계약 테스트: 4/4 통과
- 래퍼 오프라인 테스트: 기존 검증상 99/99 통과
- W2 PostgreSQL 55개 테스트: 아직 pytest 본문까지 실행되지 않음
- Codex 독립검수 Grade 3: 미실행
- 커밋 승인: 미완료
- 이번 세션 Writer: 형님이 Grok으로 확정

## 2. 이번 세션에서 시행한 내용

### 2.1 C 작업본 확인

실제 작업 위치를 C:\sswcenter\2.2로 확정했다. 시작 시점에는 핸드오프와 동일하게 051c7ef 및 제품 변경 5개와 기존 인계 문서가 확인되었다.

### 2.2 W2 계약 테스트

결과: 4 passed

### 2.3 AI 래퍼 오프라인 회귀

처음 Windows PowerShell 5.1로 호출했을 때는 테스트 파일의 PowerShell 7 요구조건 때문에 실행되지 않았다. 이후 C:\tools\PowerShell7\pwsh.exe로 올바르게 재실행했다.

결과: AI_WRAPPER_OFFLINE total=99 passed=99 failed=0

### 2.4 W2 격리 PostgreSQL 테스트

사용자 Temp 아래에 일회성 PostgreSQL 클러스터를 만들고 다음 순서로 실행했다.

1. initdb
2. pg_ctl start
3. pg_isready
4. createdb
5. alembic upgrade head
6. tests/test_w2_service_plan_notice_postgres.py 전체 실행
7. pg_ctl stop 및 임시 클러스터 삭제

Alembic은 W2 마이그레이션까지 정상 적용됐다.

pytest 결과:

- collected 55 items
- 49 passed
- 5 failed
- 1 skipped

예상된 1개 skip은 test_downgrade_upgrade_downgrade_reupgrade_lifecycle이다. migration lifecycle 전용 환경변수를 의도적으로 설정하지 않았기 때문에 skip됐다.

실패한 5개:

1. test_atomic_correction_invalidate_and_replace
2. test_start_date_before_contract_start_rejected
3. test_deferrable_atomic_contract_shorten_with_plan_correction
4. test_reverse_guard_old_recipient_orphan_detection
5. test_reverse_guard_old_recipient_orphan_detection_cert_period

확인된 대표 오류는 다음과 같다.

- 원자적 수정 테스트에서 SET CONSTRAINTS ALL IMMEDIATE 시 service_plan_outside_certification_period 발생
- 두 orphan detection 테스트에서 immutability trigger 재활성화 시 pending trigger events로 ObjectInUse 발생
- test_start_date_before_contract_start_rejected 및 test_deferrable_atomic_contract_shorten_with_plan_correction의 세부 원인은 별도 집중 분석 필요

정리 결과:

- CLUSTER_DELETED=True
- GIT_STATUS_IDENTICAL=True

임시 PostgreSQL 데이터와 프로세스는 남아 있지 않다.

## 3. 현재 저장소 상태 주의사항

테스트 종료 후 확인한 저장소는 다음 상태였다.

- HEAD: 0f3b811
- 커밋: feat(w2): implement service-plan-notice phase 2
- origin/main도 0f3b811
- 작업 트리: clean

최초 핸드오프의 051c7ef에서 0f3b811로 바뀌었으며, 해당 커밋에는 제품 변경 5개와 인계 문서 2개가 포함되어 있다. 이 커밋은 이번 테스트 세션에서 레지나가 생성하지 않았다. 집에서 재개할 때 반드시 git log와 git show --stat 0f3b811로 유지 여부를 먼저 확인한다.

이 보고서 파일은 현재 새로 추가된 인계 자료이므로 아직 커밋하지 않는다.

## 4. 남은 작업

### 필수

1. 실패한 5개 PostgreSQL 테스트의 원인 분석
2. 필요한 코드 또는 테스트 fixture 수정
3. 새 격리 PostgreSQL에서 전체 W2 테스트 재실행
4. 다음 GREEN 기준 충족 확인
   - 54 passed
   - 1 expected skipped
   - 0 failed
   - fixture setup failure 0
5. GREEN 이후 Codex 독립검수 Grade 3 실행
6. 독립검수 PASS 후 형님에게 커밋 유지·추가 커밋 승인 요청

### 현재 자동으로 하지 않을 것

- 실패 상태에서 자동 재시도하지 않음
- Grade 4로 자동 승격하지 않음
- 실패 원인 확인 전 Grok 자동 재호출하지 않음
- 형님 승인 없이 reset, checkout, 삭제, push하지 않음

## 5. 집에서 재개하는 순서

1. 실제 드라이브 문자를 먼저 확인한다. 집에서도 00-먼저읽기-작업환경안내.md와 00-오케스트레이션-작업지침.md를 먼저 읽는다.
2. 한 작업본만 선택하고, 그 작업본의 저장소·러너·키를 같은 볼륨에서 사용한다. REMOVE 아래 자료는 참고하지 않는다.
3. 새 세션에서는 Writer를 다시 형님에게 확인한다. 이전 세션의 Grok 선택을 자동 승계하지 않는다.
4. 저장소에서 다음을 확인한다.

   git status --short
   git branch --show-current
   git rev-parse HEAD
   git log -3 --oneline --decorate

5. 현재 기준 SHA가 예상과 다르면 작업을 시작하지 말고 형님께 보고한다.
6. 우선 위 5개 실패 테스트만 읽기 전용으로 원인 추적한다. 수정 승인 후에만 변경한다.
7. 수정 후에는 새 임시 PostgreSQL 클러스터에서 전체 55개를 다시 실행한다. 데이터와 로그는 사용자 Temp 아래에만 둔다.
8. GREEN일 때만 Codex Review Grade 3을 실행한다.
9. Review PASS 후에도 커밋·push는 형님 승인을 받은 뒤 진행한다.

## 최종 판정

이번 세션으로 계약 테스트와 래퍼 회귀는 GREEN이 됐다. W2 제품 테스트는 실제 PostgreSQL 본문까지 실행되는 상태로 전진했지만, 5개 실패 때문에 Phase 2 완료로 판정할 수 없다. 다음 작업은 5개 실패의 원인 분석과 재검증이다.

