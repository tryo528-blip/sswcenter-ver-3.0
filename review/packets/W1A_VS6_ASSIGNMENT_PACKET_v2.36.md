# W1A-VS6 활성 작업 패킷 v2.36

> 작업: 직원 legacy mapping·합성 one-off 이관
>
> 상태: `IMPLEMENTATION_WIP / WRITE_BLOCKED`
>
> RED: `RED_VALID_PENDING_PRODUCT`
>
> 고정 후보 SHA: 없음

## 1. 기준·위험·의존성

- branch/worktree: `wip/w1a-office-handoff` / 현재 shared worktree
- 현재 구현 기반 SHA:
  `2494d409e1d6f238b1bd383ce1d1765a213205ec`
- 기반 검증 SHA:
  `6db858ac687f6db183a3a4b2b271ad3c0f5ddbb9`
- 봉인 RED:
  `d9b426f98e084a644801f402d6c385cc9a358f5a`
- 강화 RED:
  `c6fc47509dc9067a58c0a2be00c7c0d1360a75eb`
- 위험등급: `HIGH`
- 영향태그: `MIGRATION / DB / AUTH / PII / DOMAIN / FILE`
- 의존 계열 ID: `W1A-MIGRATION-20260728-0008`
- 직접 의존: W1A-VS5 PASS와 봉인·강화 RED
- 독립 진행: 같은 migration 계열은 불가, 다른 PASS 기반 도메인은 가능
- 실패 영향: 0008 migration, 직원 초기이관, 주민번호 암호화, 재직·직종·
  자격증 사실, ACL·복구 gate

역사 증거는 다음 두 파일이 소유하며 현재 패킷이 재작성하지 않는다.

- `review/packets/W1A_VS6_ASSIGNMENT_PACKET_v2.32.md`
- `review/evidence/w1a-vs6/RED.md`

## 2. 필수 정본·matrix

- `02#fr-staff-core`, `02#fr-staff-sensitive`, `02#fr-staff-legacy`
- `04#db-staff-core`, `04#db-staff-sensitive`, `04#db-staff-employment`,
  `04#db-staff-legacy`
- `05#migration`, `05#resident-security`, `05#file-boundary`
- 06 §2의 W1A·legacy mapping 행
- matrix: `W1-CMN-03`, `W1-CMN-05~07`, `W1-STF-00~05`,
  `W1-ABS-13`, `W1-ABS-15~17`

## 3. 역할 배정·인계

배정 상태: `CONFIRMED(default)`

```text
Codex-총책임
Grok-설계
김루나-구현
이루나-백검증
마르코-반대검토
```

프론트·프론트검증은 공개 HTTP/UI가 없는 이번 slice에 미배정한다.
설계·반대검토는 read-only다. 구현과 독립검증은 서로 다른 직원이다.

현재 dirty WIP의 작성 주체에서 김루나-구현으로 넘어가는 인계 수락이 아직
없으므로 새 제품 write는 차단한다. 인계자는 exact `git status --short`와 diff를
읽고 `인계 수락 / 확인한 기반 SHA / 첫 수정 대상`을 반환해야 한다. 이 문서
정합화 작업은 VS6 제품 write 재개 지시가 아니다.

## 4. 파일소유권

구현:

- `backend/alembic/versions/20260728_0008_w1a_staff_legacy_mapping.py`
- `backend/app/db/models.py`
- `backend/app/domains/staff/legacy_import.py`

백검증:

- `backend/app/db/postcheck_w1a_vs1.py`
- `backend/tests/test_w1a_vs6_*.py`
- `scripts/test-w1a-vs6-postgres.ps1`
- `scripts/restore-drill.ps1`
- `review/evidence/w1a-vs6/GREEN.md`

그 밖의 기존 migration·제품·프런트·공개 API/OpenAPI·정본 파일은 수정하지
않는다. 새 파일이 필요하면 write 전에 이 표를 갱신한다.

## 5. OPEN HIGH 결함 반환

다음은 요셉(SOL Max) 재감사에서 확인된 현재 WIP 결함이다. Codex가 제품코드를
대신 고치지 않고 구현·백검증 역할에 반환한다.

1. 자격증 입력 계약은 `type / number / issued_date`인데 importer가
   `license_type / license_number / issued_date`만 수용한다.
2. 정확한 재직기간이 없을 때 기존 첫 재직을 재사용해 재입사 사실을 잃는다.
3. mapping create audit만 있고 무효화·대체 명령과 해당 audit 검증이 없다.
4. SQLAlchemy 예외를 원인으로 연결해 traceback·로그에 PII SQL parameter가
   노출될 수 있다.

각 결함은 실패하는 focused test 또는 leak self-test로 먼저 고정한 뒤 수정한다.

## 6. 완료조건

1. 인계 수락과 OPEN HIGH 네 건의 RED·수정·자체 focused GREEN
2. 이루나-백검증의 독립 PostgreSQL·복구·leak focused GREEN
3. Grok-설계의 계약·diff·증거 감사와 마르코 HIGH 반대검토
4. exact 후보 SHA 고정
5. 별도 clean worktree의 v2.36 `MANUAL_FALLBACK` 고위험 통합 gate
6. PASS 증거와 후보 SHA 일치 뒤에만 Codex-총책임 승격 판정
