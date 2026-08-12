# W1A-VS6 활성 작업 패킷 v2.37

> 작업: 직원 legacy mapping·합성 one-off 이관
>
> 상태: `G1_FINAL_GATE_PASS / GIT_CLOSEOUT_AUTHORIZED`
>
> RED: `RED_CORRECTIONS_ACCEPTED`
>
> GREEN: `G1_FINAL_GATE_PASS`
>
> 고정 Git 후보 SHA: Git commit·remote reference가 소유(문서 자기참조 방지)

## 1. 기준·위험·의존성

- branch/worktree:
  `wip/w1a-office-handoff` /
  `C:\Users\USER\Documents\sswcenter-ver-2.1 2`
- 제품 구현 기반 HEAD:
  `cb5f49937e2abbb2373f52ee4564f790101ca21f`
- 현재 exact 후보 파일:

| 파일 | SHA-256 |
|---|---|
| `backend/tests/test_w1a_vs6_import_contract.py` | `8DD16C69025FD9B03752316725610F634DE08FCCFCC6483006846B3944D58DCA` |
| `backend/tests/test_w1a_vs6_postgres.py` | `7D1F042E5DC1866BAF8794CF91E85C28EA94FF0B4E6062A59A3D6EC3D258A3EB` |
| `scripts/test-w1a-vs6-postgres.ps1` | `1224092AB972A361BD1F3EE08D5141807D499EF8496AA25EAEBE51EEA4AEAD3D` |
| `backend/app/domains/staff/legacy_import.py` | `1470390AAE9C4D1D083654B30A8868CBCFF5CECE417ECBB29CA100C6AFC16104` |
| `backend/tests/test_schema_contract.py` | `0232D8120756691222F46FD05621B4391204F78505422F35544FC46E57858944` |
| `backend/tests/test_w1a_vs5_semantics.py` | `A879B502B3F5426412E0CD2EBBDE381C8CB7F7B757F546CE68A7B29773B3BE94` |

현재 후보는 commit 전 WIP이므로 Git SHA라고 부르지 않는다. exact 후보 식별자는
기반 HEAD와 위 여섯 파일 SHA-256의 묶음이며, stage·commit 권한을 받기 전에는
보호 branch 승격이나 Git SHA 기반 `G1` 최종 PASS를 선언하지 않는다.

F2 반례로 확인된 import contract helper의 동일 handler 이중 부착은
root-only capture, immutable pre/post-redaction snapshot, importer count `1`
probe로 보정됐으며 위 표는 보정 후 exact 묶음이다.

독립 B2 GREEN 증거는
`review/evidence/w1a-vs6/GREEN.md`
(`EB97391C45251876E4C4090541A4BE5D80CD56A4005032611E3B7A9CB5CB1CFE`)가
소유한다.

- 위험등급: `HIGH`
- 영향태그: `MIGRATION / DB / AUTH / PII / DOMAIN / FILE`
- 의존 계열 ID: `W1A-MIGRATION-20260728-0008`
- 직접 의존: W1A-VS5 PASS와 승인 RED에서 파생된 위 exact GREEN 후보
- 독립 진행: 같은 migration 계열은 불가, 다른 PASS 기반 도메인은 가능
- 실패 영향: 0008 migration, 직원 초기이관, 주민번호 암호화, 재직·직종·
  자격증 사실, mapping 수명주기, ACL·복구 gate

역사 증거는 다음 파일이 소유하며 현재 패킷이 재작성하지 않는다.

- `review/packets/W1A_VS6_ASSIGNMENT_PACKET_v2.32.md`
- `review/packets/W1A_VS6_ASSIGNMENT_PACKET_v2.36.md`
- `review/evidence/w1a-vs6/RED.md`

## 2. 필수 정본·matrix

- `02#fr-staff-core`, `02#fr-staff-sensitive`, `02#fr-staff-legacy`
- `04#db-staff-core`, `04#db-staff-sensitive`, `04#db-staff-employment`,
  `04#db-staff-legacy`
- `05#migration`, `05#resident-security`, `05#file-boundary`
- 06 §2의 W1A·legacy mapping 행
- matrix: `W1-CMN-03`, `W1-CMN-05~07`, `W1-STF-00~05`,
  `W1-ABS-13`, `W1-ABS-15~17`

## 3. 업무석 배정·승계

배정 상태: `CONFIRMED(default)`

```text
[P0] 관제·통합실 — Codex
[D1] 계약·설계실 — Opus → Grok → 요셉
[B1] 백엔드 구현실 — 김루나
[B2] 백엔드 검증실 — 이루나
[F1] 프론트 구현실 — 박루나
[F2] 프론트 검증실 — 송루나
[R1] 반대검토실 — 마르코
[G1] 통합게이트실 — Grok → 요셉 → 새 가용 독립검수자
```

- 이 패킷의 현재 실행 단계는 모든 독립 gate 완료 후 `P0` commit 전 WIP
  봉인이다.
- Opus가 가용하면 `D1=Opus`, `G1=Grok`이다. Opus가 quota·인증·모델
  장애이면 `D1=Grok`, `G1=요셉`으로 즉시 승계한다.
- Opus와 Grok이 모두 불가하면 `D1=요셉`으로 승계하고, `P0`가 `G1`에
  별도 가용 독립검수자를 배정한다.
- 같은 후보에서 한 직원이 `D1`과 `G1`을 겸하지 않는다. 한도가 풀려도 진행 중
  임무는 회수하지 않고 다음 임무부터 기본 우선순위로 복귀한다.
- Grok의 `efa3611f-830a-4417-a8bd-649c7289c92f` 재감사는 이 패킷의
  RED 승인 근거다. 제품 후보가 생긴 뒤 수행할 `G1` 통합 gate를 대신하지 않는다.
- 2026-07-28 23:39 KST에 Opus Max는 session
  `3db9e378-2138-4132-9fec-735ce343dce0`에서 `429 session limit`,
  2026-07-29 02:20 KST 해제를 반환했다. 현재 `D1`은 Grok session
  `a3c41abe-ef70-49aa-a093-830a594b7352`로 승계했고 `G1`은 요셉이
  대기한다. 02:20에 진행 중 감사를 회수하지 않는다.
- VS6에는 프론트 제품 범위가 없다. `F1`·`F2`는 VS6 파일을 수정하지 않고
  별도 독립 큐를 계속한다.
- `D1`·`R1`·`G1`은 read-only이며 메인 담당자가 최종판정과 근거 통합을
  책임진다. 자체 하부에이전트는 별도 독립검수자로 세지 않는다.

## 4. 파일소유권

`B1` 수정 가능:

- `backend/app/domains/staff/legacy_import.py`

`B2` 수정 가능:

- `backend/tests/test_w1a_vs6_import_contract.py`
- `backend/tests/test_w1a_vs6_postgres.py`
- `scripts/test-w1a-vs6-postgres.ps1`
- `review/evidence/w1a-vs6/GREEN.md`
- P0가 확인한 회귀 하네스 오탐 보정에 한해
  `backend/tests/test_schema_contract.py`,
  `backend/tests/test_w1a_vs5_semantics.py`

현재 승인 RED 세 파일은 `B1` 구현 동안 read-only다.
다음 파일도 현재 구현 범위에서는 read-only이며, 필요하면 추정 수정하지 말고
`P0`에 범위 갱신을 요청한다.

- `backend/alembic/versions/20260728_0008_w1a_staff_legacy_mapping.py`
- `backend/app/db/models.py`
- `backend/app/db/postcheck_w1a_vs1.py`
- `scripts/restore-drill.ps1`

그 밖의 기존 migration·제품·프런트·공개 API/OpenAPI·정본 파일은 수정하지
않는다. 새 파일이나 소유권 변경이 필요하면 write 전에 이 패킷을 갱신한다.

## 5. 승인 RED와 OPEN HIGH

승인된 독립 RED 결과:

- PostgreSQL wrapper exit `1`은 제품 미구현에 따른 기대 결과
- 수집 `39`, PASS `23`, FAIL `16`, SKIP `0`, ERROR `0`
- 최초 marker: `W1A_VS6_ALLOWLIST_MISSING`
- lifecycle·postcheck·restore·cleanup 정상
- synthetic leak self-test: `False / True / True`
- static·leak gate GREEN

제품 구현이 해결해야 할 HIGH 계약:

1. 자격증 입력 계약 `type / number / issued_date`와 canonical type
   `0 / 1 / 2`
2. exact·비중첩·중첩 재입사 기간의 생성·재사용·실패 및 전체 rollback
3. mapping create·무효화·대체의 lock/version/audit와 동시성
4. 두 session 실행모드에서 SQLAlchemy 예외·traceback·로그로 PII SQL
   parameter가 새지 않는 안전한 공개 오류

RED 자체의 오타·하네스 결함이 확인될 때만 `B2`가 수정하고 `D1` 재감사를
받는다. 제품을 테스트에 맞춘 허위 metadata로 통과시키지 않는다.

## 6. 실행·반환

현재 검증 결과:

- B1 비PostgreSQL: import `12/12`, semantics `4/4`, absence `5/5`, Ruff GREEN
- B2 1차 보정 후 PostgreSQL wrapper: 수집 `39`, PASS `39`, FAIL `0`,
  SKIP `0`, ERROR `0`, `W1A_VS6_GREEN`
- offline apply/verify, lifecycle, postcheck, restore, cleanup GREEN
- synthetic fail-close `False / True / True`
- leak normal `233 files / W1A_LEAK_GATE_GREEN`, SelfTest
  `W1A_LEAK_GATE_SELF_TEST_OK`
- B2는 기존 세 실패를 모두 `HARNESS_DEFECT`로 분류했다. mapping audit의
  expected `before_json=None`은 실제 bool projection에 맞게 `False`로
  정정했으며 이 변경은 D1 재감사에서 승인됐다.
- outer-log 두 건의 보정은 D1 재감사에서 다시 차단됐다. 같은
  `_SurfaceCaptureHandler` 객체를 outer logger filter와 root handler로
  함께 사용해, no-SensitiveDataFilter 환경에서는 관찰 횟수 `2`,
  SensitiveDataFilter-first 환경에서는 `1`이 되는 순서 의존 false
  RED/GREEN이 확인됐다.
- 따라서 위 `39/39`는 현재 승격 증거로 인정하지 않는다. B2는 dedicated
  pre-redaction `logging.Filter`와 emit-only capture handler로 분리한 뒤
  비PostgreSQL 양 환경과 전체 PostgreSQL wrapper를 재실행한다.
- 구제품 `legacy_import.py` SHA
  `F46921297660B2F3E17C2965B0A0C30DDF3C53DFAE202AD18625355BEBF4A7C1`은
  D1 재감사 시점까지 불변으로 확인됐다.
- B2 반환 중 full-app `mypy app`에서 `legacy_import.py:601`의
  `dict.get(Any | None)` 타입 오류 1건이 확인됐고 P0도 exit `1`,
  `30 source files / 1 error`로 독립 재현했다. B1은 같은 제품 한 파일에서
  constraint name의 최소 타입 narrowing만 수행했다. 새 제품 SHA는
  `1470390AAE9C4D1D083654B30A8868CBCFF5CECE417ECBB29CA100C6AFC16104`이며
  Ruff, full-app mypy `30 files`, compileall, VS6 비PostgreSQL `21/21`이
  모두 exit `0`이다. 현재 B2의 PostgreSQL 실행은 구제품 SHA의 동작 증거로만
  보존하며, 이 새 제품 SHA에 대해 B2와 D1 gate를 다시 실행한다.
- P0도 primary exact 후보에서 DATA_ROOT를 제거한 뒤 Ruff format/check,
  full-app mypy `30 files`, VS6 비PostgreSQL `21/21`을 모두 exit `0`으로
  독립 재현했다. staged 변경은 없다.
- B2는 dedicated pre-redaction filter와 emit-only capture handler로 분리한
  새 exact 후보를 다시 검증했다. 양 logging 환경의 outer observer는 각각
  `count=1`, PostgreSQL wrapper는 수집 `39`, PASS `39`, FAIL/SKIP/ERROR
  `0/0/0`, offline/lifecycle/postcheck/restore/cleanup 전부 GREEN이다.
  leak normal은 `233 files / W1A_LEAK_GATE_GREEN`, SelfTest는
  `W1A_LEAK_GATE_SELF_TEST_OK`이며 GREEN evidence SHA는 위 값이다.
- B2는 전체 회귀에서 확인된 두 오탐을 제품·migration 변경 없이 테스트
  하네스에서만 보정했다. metadata exact set에
  `erp.staff_legacy_mapping`을 추가했고, VS5 이전 migration 검사는
  정확히 `0001~0006`만 선택해 현재 `0007`과 미래 `0008`을 제외한다.
  focused `2/2`, 비PG 전체 `122 passed / 38 skipped / 1 warning`,
  Ruff, full-app mypy `30 files`, compileall, diff-check가 모두 exit `0`이다.
- P0는 위 두 파일과 GREEN evidence를 SHA 일치 상태로 primary에 인계한 뒤
  비PG 전체 `122 passed / 38 skipped / 1 warning`과 static gate를 독립
  재현했다. normal leak gate는 현재 WIP 문서·증거까지 `237 files`를
  검사해 GREEN, 이어 실행한 SelfTest도 exit `0`이다. staged 변경은 `0`이다.
- F2는 두 logging 환경의 `vs6_10/11`을 각각 `2 passed`, 격리
  configure_logging 로그의 synthetic vector hit `0`으로 확인했다. 병렬
  작업 중 한 SelfTest에서 일시 RED를 관찰해 원인 분리 중이며, P0의 작업 종료
  뒤 순차 재현은 GREEN이다. F2 최종 판정 전에는 보안 gate를 닫지 않는다.
- F2 재검증에서 importer logger의 `propagate=True` 상태로 동일
  `_SurfaceCaptureHandler`를 importer와 root에 함께 부착하면 같은
  `LogRecord` ID가 handler에 `2`회 도달하는 행동 반례가 확인됐다. 현재 제품의
  logger emit은 없지만 테스트 capture가 순서·후속 redaction mutation에
  의존할 수 있으므로 B2가 root-only capture와 불변 pre-redaction snapshot,
  importer count `1` probe로 최소 보정한다. 기존 D1 승인은 위 이전 hash에
  대한 역사 증거이며 새 hash delta 재감사를 받아야 한다.
- B2 보정 후 두 logging 환경은 각각 outer `1`, importer `1`, pre/post
  snapshot vectors `0`이며 focused `2/2`, 비PG `122/38`, PG `39/39`,
  static·offline·lifecycle·postcheck·restore·cleanup·normal leak
  `234 files`·SelfTest가 모두 exit `0`이다. 새 import-test와 GREEN evidence
  SHA는 위 표·증거 항목 값이다.
- R1은 이 exact 후보에서 제품 핵심 transaction의 확정 기능 결함 대신 세
  HIGH 증거 공백을 행동 재현했다. (1) mapping replacement rollback이
  `replacement_staff_id=-1`로 mutation 전에 끝나 post-mutation rollback을
  증명하지 못함, (2) pytest summary 전
  `PytestUnhandledThreadExceptionWarning` traceback이 wrapper에서
  `WouldGreen=True`가 됨, (3) VS6 PG temp prefix와 generic leak auto-scan
  prefix가 달라 runtime log가 삭제 전에 검사되지 않음. B2는 실제 PostgreSQL
  post-mutation fault trigger, thread-warning synthetic fail-close, 삭제 전
  explicit runtime artifact leak gate로 보정하고 PG wrapper 전체를 재실행한다.
- F2 room에서는 독점 lane SelfTest가 line 455에서 RED였으나, P0 direct
  실행환경은 shared temp root `0`을 확인한 동일 strict normal→SelfTest를
  두 차례 GREEN으로 재현했다. B2와 G1은 자체 clean worktree에서 독점 lane
  marker를 다시 봉인하며, 실행환경 차이와 제품 누출을 분리한다.
- G1 clean worktree의 제품 상태는 깨끗하지만 target-local `.venv`와
  `node_modules`가 없다. 새 의존성 설치나 junction 없이 backend 후보는 clean
  worktree에서 primary Python으로, 변경 없는 frontend/OpenAPI는 primary의
  source가 HEAD와 동일함을 먼저 확인한 뒤 기존 의존성으로 실행하는 분할
  gate를 사용한다.
- B2는 R1의 세 HIGH 증거 공백을 모두 보정한 exact 후보를 전체 재실행했다.
  실제 replacement staff와 PostgreSQL `AFTER INSERT` fault trigger로 old mapping
  무효화·`row_version=2` 이후 실패와 mapping/audit 완전 rollback을 확인했고,
  trigger/function catalog 잔존은 `0`이다. wrapper는 수집 `39`, PASS `39`,
  FAIL/SKIP/ERROR `0/0/0`, offline/lifecycle/postcheck/restore/cleanup 전부
  GREEN이다.
- wrapper는 summary 이전 `PytestUnhandledThreadExceptionWarning`과
  `Exception in thread`를 fail-close하며 synthetic 결과는
  `False / True / True`다. 삭제 전 runtime artifact root를 generic leak gate에
  명시 전달한 검사는 exit `0`, `238 files`, `W1A_LEAK_GATE_GREEN`; 이어 normal
  leak은 `234 files`, SelfTest도 exit `0`이다. 비PG 전체는
  `122 passed / 38 skipped / 1 warning`, static·collect·PowerShell AST·
  diff-check도 모두 exit `0`이다.
- P0는 B2 최종 세 파일을 primary에 바이트 단위로 인계하고 SHA-256 일치를
  확인했다. staged 변경은 `0`이며, `D1`·`F2`·`R1`이 위 exact 묶음을
  독립 재검토한 뒤 모두 승인한 경우에만 `G1` 분할 통합 gate로 진행한다.
- F2 델타 재검토에서 `Invoke-Psql`이 `ArtifactPsqlRoot` 아래 SQL 파일을
  만들지만 함수 `finally`에서 즉시 삭제해, 뒤의 explicit runtime artifact
  leak gate가 해당 PSQL SQL 입력을 실제로 보지 못하는 증거 공백이 확인됐다.
  P0도 코드 순서를 독립 재현했다. 당시 exact 묶음과 당시 D1 승인은 이
  공백으로 승격 근거에서 무효화했고, B2는 PSQL SQL을 scan 시점까지
  보존하고 scan 직전 존재 개수를 fail-close한 새 PS1·GREEN evidence를
  재검증했다.
- B2 최종 보정은 `Invoke-Psql`의 조기 삭제를 제거하고 explicit scan 직전
  `vs6-*.sql`이 dedicated ArtifactRoot 경계 안에 하나 이상 존재해야만
  GREEN이 되도록 고정했다. 전체 wrapper는 `39/39`, PSQL artifact
  `count=1 / assertion=1`, runtime leak `239 files / exit 0 / GREEN`,
  cleanup 잔존 `0`으로 통과했다. 비PG `122/38`, static, normal leak
  `234 files`, SelfTest도 모두 exit `0`이다. stale evidence prefix를 실제
  `sswcenter-w1a-vs6-artifacts-*`로 바로잡은 뒤 위 새 해시를 primary에
  바이트 일치로 인계했다.
- D1(Grok)은 새 PS1·GREEN evidence와 동결된 다섯 제품/테스트 해시를
  모두 대조하고 `D1_DELTA_APPROVE`를 반환했다. F2는 자신이 재현한 PSQL
  조기삭제 반례가 더는 성립하지 않고 root-only logging·thread fail-close가
  보존됐음을 확인해 `F2_SECURITY_APPROVE`, R1은 삭제 0건·assertion 선행·
  scan 후 cleanup·GREEN 의존성을 독립 재현해 `R1_DELTA_APPROVE`를
  반환했다.
- P0는 기준 HEAD의 clean G1 worktree에 위 여섯 tracked 후보와 GREEN
  evidence만 SHA 일치로 인계했다. G1은 primary Python을 명시 사용해
  backend/VS6를 clean worktree에서, HEAD 대비 변경 `0`인 frontend와
  OpenAPI·기존 W1A real-PG Playwright를 primary에서 순차 검증했다.
- G1 최종 gate는 exact 7파일 hash를 재확인하고 VS6 PostgreSQL
  `39/39`, PSQL artifact `1/1`, runtime leak `239 files`, 비PG
  `122 passed / 38 skipped`, normal leak `234 files`→SelfTest를 clean
  worktree에서 모두 exit `0`으로 재현했다. lifecycle·offline·postcheck·
  restore와 listener/temp/artifact/media cleanup도 모두 `0`이다.
- primary의 frontend tracked diff는 HEAD 대비 `0`이며 lint, Vitest
  `14 files / 85 tests`, build `147 modules`, OpenAPI drift check가 모두
  exit `0`이다. 기존 VS1 full real-PG migration round-trip·offline·권한·
  backup/restore는 `W1A_POSTGRES_HARNESS_OK`, Playwright는
  `--workers=1`의 3 viewport `3/3`을 warning 없는 환경에서 재현했다.
  마지막 primary leak는 `237 files / GREEN`→SelfTest, 포트
  `55433/55439/8000/4173` listener는 모두 `0`이다.
- G1이 처음 실행한 범위 과다 pytest는 DB URL 없이 VS6 PG 파일을 포함해
  `17 failed / 123 passed / 38 skipped`, exit `1`로 fail-close했다. 이는
  첫 실패를 숨기지 않고 기록한 실행범위 오류이며, 정식 non-PG 명령의
  `--ignore=tests/test_w1a_vs6_postgres.py` 재실행은 위 `122/38` GREEN이다.
  필수 미실행 항목은 `0`; 제품 결함과 남은 승인 blocker는 없다.

1. `B1`은 시작 전에 기반 HEAD, exact `git status --short`, 승인 RED 세 파일
   hash와 단일 제품 write 범위를 확인해 `인계 수락`을 반환한다.
2. `B1`은 `legacy_import.py`만 수정하고 자체 static·focused GREEN과 남은
   위험을 반환한다.
3. `B2`는 별도 독립방·분리 worktree에서 PostgreSQL wrapper, lifecycle,
   rollback, leak gate를 재실행한다.
4. `P0`가 제품 후보 SHA를 고정한다.
5. `D1`은 계약·diff·증거를 감사하고 `R1`은 HIGH 반례·복구위험을 검토한다.
6. `G1`은 exact 후보 SHA의 전체 회귀·교차영향·복구·leak gate를 독립
   재현한다.
7. `P0`가 모든 결과의 후보 SHA 일치를 확인한 뒤에만 최종 PASS·승격을
   판정한다.

모든 반환에는 명령, exit code, 수치, 최초 실패, 미실행 항목, 변경 파일,
`git status --short`, 남은 위험을 포함한다. 이 패킷은 stage·commit·push를
직접 허가하지 않으며, 별도 명시적 `퇴근!` 요청이 있을 때만 workday Git
절차로 실행한다.

## 7. 완료조건

1. `B1` OPEN HIGH 네 건 구현과 자체 focused GREEN
2. `B2` 독립 PostgreSQL·복구·leak focused GREEN
3. `D1` 계약·diff·증거 감사와 `R1` HIGH 반대검토
4. exact 제품 후보 SHA 고정
5. `G1` 별도 clean worktree 고위험 통합 gate
6. 모든 PASS 증거와 후보 SHA 일치
7. `P0` 최종 판정

위 1~7은 exact 후보 묶음에서 모두 충족됐다. 사용자의 별도 명시적 `퇴근!`
요청으로 Git closeout 권한을 받았으며, `P0`는 workday 절차에 따라 현재
branch를 commit·push한다. 자기 commit SHA를 문서 안에 넣는 순환 참조는
만들지 않고 local·remote SHA 일치는 Git 기록과 최종 closeout 보고가 소유한다.
