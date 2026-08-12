# W1E-A1 Luna Pilot R2 Writer 실행 패킷

> 상태: `EXECUTED_ARCHIVED`
> 작성일: 2026-08-01 KST
> 운용서: `review/plans/W1E_A1_LUNA_PILOT_R2_RUNBOOK.md`
> 실행 평가: `review/reports/W1E_A1_LUNA_PILOT_R2_EVALUATION_db5516b.md`
> 대상: `W1E-A1-G1 STATIC FOUNDATION`
> 모델: `gpt-5.6-luna`, reasoning `max`, Fast intent

## 1. 임무

승인된 W1E-A1 GENERAL care-assignment RED 계약을 약화하지 않고 다음 두 제품
경로만 구현하여 정적 GREEN 후보를 만든다.

1. `backend/alembic/versions/20260801_0012_w1e_care_assignment.py`
2. `backend/app/db/models.py`의 `CareAssignment` ORM

실 PostgreSQL GREEN, service/API/UI, FAMILY 필수 규칙, 월별 전문인력,
care-change는 이번 후보의 완료 주장이 아니다.

## 2. 실행 봉인

작업 시작 프롬프트에 Regina가 다음 값을 정확히 제공한다.

```text
PILOT_R2_BASE_SHA=<dispatch 직전 clean base SHA>
BRANCH=codex/w1e-assignment
MODEL=gpt-5.6-luna
REASONING=max
FAST_INTENT=ON
WRITER_TIMEBOX=15m
EXPECTED_NET_ADD=600..900
LIVE_POSTGRES=NOT_RUN
```

writer는 시작하자마자 실제 cwd, HEAD, branch, four-way status를 기록하고 예상
순증과 구현 단위를 보고한다. 예상 순증이 900줄을 넘거나 허용 경로 밖 의미 변경이
필요하면 제품 파일을 쓰지 않고 `PILOT_R2_WRITER_RESULT=BLOCKED`로 반환한다.

## 3. 허용·금지 경계

### 허용 write path

- `backend/alembic/versions/20260801_0012_w1e_care_assignment.py`
- `backend/app/db/models.py`

### 금지

- 기존 migration `0001`~`0011` 수정
- `backend/tests/test_w1e_contract.py` 수정
- `backend/tests/test_w1e_postgres.py` 수정
- plan, packet, 정본 문서 수정
- dependency 설치, 전역 환경 변경, 데이터베이스 기동
- 실 PostgreSQL 실행 또는 runtime GREEN 주장
- service/API/UI/FAMILY/monthly/care-change 구현
- 하위 에이전트·병렬 writer 생성
- stage, commit, push

기존 사용자 WIP를 건드리지 않는다. 허용 경로 밖 변경 필요성은 결과에 blocker로만
기록한다.

## 4. 기준 계약 인덱스

전체 저장소를 먼저 재탐색하지 말고 아래 근거부터 읽는다. index에 없는 근거가 꼭
필요할 때만 marker 중심으로 추가 탐색하고 읽은 경로를 결과에 기록한다.

### RED 계약

`backend/tests/test_w1e_contract.py`

- 39~42: basis, W1D head, 0012 revision/file
- 44~61: 정확한 16개 column과 순서
- 62~75: 정확한 10개 named constraint
- 77~88: 정확한 8개 function target
- 89~99: 정확한 7개 신규 trigger target
- 465: 기존 chain self-check
- 470: direct-child revision
- 475~818: offline SQL 구조·binding·side-effect·column·constraint 검사
- 899~1106: ORM schema/type/default/FK/exclusion exact 계약

### 설계 계약

`review/plans/W1E_CARE_ASSIGNMENT_PLAN.md`

- 99~117: `erp.care_assignment` exact table 설계
- 118~131: active 동일 계약+직원 기간 exclusion
- 133~160: 정방향 계약/재직/CARE_WORKER/서비스자격 guard
- 161~178: 부모 변경에 대한 역방향 guard
- 180~189: PERIOD_FACT 정정 방향과 active 의미
- 208~225: revision, upgrade, downgrade 안전성
- 304~315: RED에서 정적 GREEN으로 가는 경계

### 승인 패킷

`review/packets/W1E_ASSIGNMENT_PACKET_v1.0.md`

- scope seal과 included contract
- PERIOD_FACT 규칙
- executable RED package
- 명시적 제외 범위와 독립검수 경계

### 구현 참고

`backend/app/db/models.py`

- 708~785: generated `DATERANGE`, actor, exclusion ORM 패턴
- 1925~2003: `RecipientContract` identity/default/FK/self-replacement 패턴

`backend/alembic/versions/20260730_0011_w1d_recipient_contract.py`

- revision/down_revision, upgrade/downgrade, grant/revoke 패턴

`backend/alembic/versions/20260727_0004_w1a_staff_qualifications.py`

- 368~428: 0011 시점 공유 employment reverse guard의 복원 기준

## 5. 반드시 구현할 DB 계약

### 테이블·ORM

- schema/table: `erp.care_assignment`
- columns, 순서, nullable/type/default/computed는 RED exact 계약과 일치
- `id`: bigint identity, PK `pk_care_assignment`
- `recipient_contract_id`: `erp.recipient_contract.id`, RESTRICT
- `(staff_id, employment_id)`: composite FK to
  `erp.staff_employment(staff_id, id)`, RESTRICT
- `assignment_kind`: `GENERAL|FAMILY` check
- `assignment_period`: stored generated
  `daterange(start_date, end_date + 1, '[)')`
- replacement self-FK: RESTRICT, DEFERRABLE INITIALLY DEFERRED
- actor FKs: `erp.user_account.id`, RESTRICT
- timestamps: timezone aware, `now()` defaults
- `row_version`: integer default 1, positive check
- active exclusion: recipient contract + staff + overlapping assignment period

정확한 10개 이름은 `W1E_CONSTRAINT_NAMES`를 그대로 따른다. unnamed 또는 중복
constraint로 통과시키지 않는다.

### 정방향 guard

유효 행(`invalidated_at_utc IS NULL`)에 대해 네 constraint trigger를
`DEFERRABLE INITIALLY DEFERRED`로 구현한다.

1. 계약기간 완전 포함
2. 재직기간 완전 포함
3. GENERAL 배정의 CARE_WORKER 직종 coverage
4. GENERAL 배정의 계약 service_type 제공자격 coverage

coverage는 단일 행 포함이 아니라 인접한 유효 기간들의 합집합에 미보장일이 0인
의미다. 자격증 보유만으로 직종 또는 서비스자격 coverage를 대체하지 않는다.

### 역방향 guard

- recipient contract: 단축·무효화·대체로 배정을 orphan으로 만들지 못함
- staff employment: 기존 공유 함수를 `CREATE OR REPLACE`로 확장
- staff position: CARE_WORKER coverage를 깨지 못함
- staff service qualification: 서비스자격 coverage를 깨지 못함

동명 함수 문자열이 존재하는 것으로 끝내지 말고 실제 trigger OID가 올바른 함수와
대상 table에 결속되어야 한다.

### PERIOD_FACT

정정 시 old 행을 무효화하고 새 행을 insert한다. **old 행의**
`replacement_assignment_id`가 new 행의 ID를 가리키며 new 행의 replacement는 NULL이다.
무효 행은 exclusion과 모든 guard의 유효 집합에서 제외된다.

## 6. downgrade 안전성 — 필수

0012는 기존 공유 함수
`erp.fn_staff_employment_child_periods_reverse_guard()`를 확장한다. downgrade는
care-assignment 참조만 제거한 **0011 상태**로 이 함수를 복원해야 한다.

복원 기준은
`backend/alembic/versions/20260727_0004_w1a_staff_qualifications.py:372`의
`CREATE OR REPLACE FUNCTION` 본문이며 다음 세 child를 모두 유지한다.

1. `staff_position_period`
2. `staff_operational_role_period`
3. `staff_service_qualification_period`

더 오래된 두-child 함수로 되돌리거나, care-assignment table drop 뒤 dangling 참조를
남기면 안 된다. 0012가 새로 추가한 contract/position/qualification reverse
trigger·function과 grant는 역순으로 제거한다.

## 7. 시작 mutation corpus

구현 전에 다음 false-pass 공격면을 고려한다.

1. 함수 문자열 속 canonical `CREATE TABLE` decoy와 실제 table 변이
2. 함수 문자열 속 canonical version update decoy와 실제 top-level update 변이
3. 실제 FK/check/exclusion 변이, unnamed/duplicate constraint
4. extra single-quoted `DO`, duplicate/decorated `COMMIT`
5. 동명 함수·trigger OID 오결속과 executable side effect
6. ORM schema/table, identity/default/computed, FK action, exclusion deferrability 변이
7. CARE_WORKER·인접 qualification·reverse guard·replacement 방향 변이
8. FAMILY/API/UI/service 범위 유입

RED나 fixture를 바꾸어 mutation을 피하지 않는다.

## 8. 완료 명령

검증 interpreter는 다음 절대 경로다.

```text
C:\sswcenter\2.1\backend\.venv\Scripts\python.exe
```

writer worktree에 venv가 없어도 설치하지 말고 위 interpreter를 사용한다. 각 명령의
cwd, exit code, count/marker를 결과에 남긴다.

```powershell
& 'C:\sswcenter\2.1\backend\.venv\Scripts\python.exe' -m pytest backend/tests/test_w1e_contract.py -q
# expected: 4 passed, exit 0

& 'C:\sswcenter\2.1\backend\.venv\Scripts\python.exe' -m pytest backend/tests/test_w1e_contract.py backend/tests/test_w1e_postgres.py --collect-only -q
# expected: 10 collected, exit 0

Remove-Item Env:SSWCENTER_W1E_REAL_PG -ErrorAction SilentlyContinue
& 'C:\sswcenter\2.1\backend\.venv\Scripts\python.exe' -m pytest backend/tests/test_w1e_postgres.py -q
# expected: 6 skipped, exit 0

Push-Location backend
& 'C:\sswcenter\2.1\backend\.venv\Scripts\python.exe' -m alembic heads
& 'C:\sswcenter\2.1\backend\.venv\Scripts\python.exe' -m alembic upgrade 20260801_0012_w1e_care_assignment --sql
Pop-Location
# expected: sole head 20260801_0012_w1e_care_assignment; offline SQL exit 0

& 'C:\sswcenter\2.1\backend\.venv\Scripts\python.exe' -m ruff check backend/app/db/models.py backend/alembic/versions/20260801_0012_w1e_care_assignment.py
& 'C:\sswcenter\2.1\backend\.venv\Scripts\python.exe' -m py_compile backend/app/db/models.py backend/alembic/versions/20260801_0012_w1e_care_assignment.py
git diff --check
```

Ruff가 해당 interpreter에 설치되지 않은 환경 문제면 설치하지 말고 exact error를
기록한다. 다른 검증을 생략했다는 뜻은 아니다.

## 9. 인계 형식

15분 hard cap에서 현재 상태를 인계한다. 결과에는 반드시 다음을 포함한다.

```text
PILOT_R2_WRITER_RESULT=READY_FOR_REVIEW|TIMEBOX_STOP|BLOCKED
PILOT_R2_BASE_SHA=<sha>
PILOT_R2_WRITER_HEAD=<sha or UNCOMMITTED>
EXPECTED_NET_ADD=<number>
ACTUAL_NET_ADD=<number>
CHANGED_PATHS=<exact list>
LIVE_POSTGRES=NOT_RUN
```

그리고 다음을 짧게 보고한다.

- 시작/종료 KST와 활성 시간
- 설계 요약
- 실행한 명령별 cwd/exit/count
- 자기발견 문제와 해결
- 남은 위험·미실행 항목
- 추가로 읽은 근거 경로

`READY_FOR_REVIEW`는 독립 승인이나 W1E runtime GREEN이 아니다.

## 10. 준비 단계 trouble log

제품 판정과 분리하여 다음 observer 문제를 기록한다.

1. 다중 파일 증거 출력 중 PowerShell `Math.Min` 인자형 오류로 한 read-only 명령이
   exit 1이었다. 파일 변경 없이 marker 중심 명령으로 재수집했다.
2. Windows에서 `backend/alembic/versions/*.py` Unix-style wildcard를 `rg`에 넘겨
   OS error 123이 발생했다. 파일 변경 없이 정확한 파일/디렉터리 경로로 재실행했다.

두 건 모두 제품 바이트·RED 결과를 바꾸지 않았다.

## 11. 실행 후 보정 부록 — 당시 writer 입력 아님

이 절은 R1~R3에서 드러난 false pass와 observer 문제를 다음 패킷에서 반복하지 않기
위한 사후 보정이다. 위 본문은 실제 writer에게 전달된 입력으로 보존한다.

### 추가할 mutation

1. CARE_WORKER position fact의 `staff_id`·`employment_id`를 다른 유효 key로 바꾸어
   OLD key의 활성 GENERAL 배정이 orphan 되는 갱신
2. qualification fact의 `staff_id`·`employment_id`·`service_type_id`를 바꾸어 OLD
   key의 활성 GENERAL 배정이 orphan 되는 갱신
3. 활성 배정이 있는 recipient contract의 `service_type_id`를 바꾸어 기존 서비스
   자격 coverage가 사라지는 갱신
4. PERIOD_FACT replacement의 self-link, 유효 행을 old로 가리키는 link, 새 행의
   non-NULL replacement link
5. downgrade SQL의 공유 employment reverse guard 복원 count:
   position 1, operational-role 1, qualification 1, care-assignment 0

### 안전한 offline·syntax 관측

offline Alembic도 애플리케이션 설정 로딩 때문에 URL이 필요하다. 실제 접속하지 않는
process-scoped dummy URL을 사용하고 원래 값을 복원한다.

```powershell
$priorW1eDbUrl = [Environment]::GetEnvironmentVariable(
    'SSWCENTER_DATABASE_URL', 'Process'
)
try {
    [Environment]::SetEnvironmentVariable(
        'SSWCENTER_DATABASE_URL',
        'postgresql+psycopg://offline:offline@127.0.0.1:1/offline',
        'Process'
    )
    Push-Location backend
    try {
        & 'C:\sswcenter\2.1\backend\.venv\Scripts\python.exe' -m alembic heads
        & 'C:\sswcenter\2.1\backend\.venv\Scripts\python.exe' -m alembic upgrade 20260801_0012_w1e_care_assignment --sql
        & 'C:\sswcenter\2.1\backend\.venv\Scripts\python.exe' -m alembic downgrade 20260801_0012_w1e_care_assignment:20260730_0011_w1d_recipient_contract --sql
    }
    finally {
        Pop-Location
    }
}
finally {
    [Environment]::SetEnvironmentVariable(
        'SSWCENTER_DATABASE_URL', $priorW1eDbUrl, 'Process'
    )
}
```

`py_compile`은 `__pycache__`를 만들 수 있으므로 read-only syntax gate는 source를 읽어
`compile()`만 호출한다.

```powershell
@'
from pathlib import Path

for path in (
    "backend/app/db/models.py",
    "backend/alembic/versions/20260801_0012_w1e_care_assignment.py",
):
    compile(Path(path).read_text(encoding="utf-8"), path, "exec")
'@ | & 'C:\sswcenter\2.1\backend\.venv\Scripts\python.exe' -
```

이 부록은 반려된 `db5516b`를 승인으로 바꾸지 않는다. 새 RED와 제품 SHA가 만들어지면
독립 승인 연속횟수는 0부터 다시 센다.
