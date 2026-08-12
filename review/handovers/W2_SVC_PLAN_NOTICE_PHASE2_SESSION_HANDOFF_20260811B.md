# W2 급여계획서(Service Plan Notice) Phase 2 — 세션 핸드오프 B (래퍼 수리 반영본)

- 작성일: 2026-08-11 (KST)
- 최종 갱신: 2026-08-11 (KST), Codex wrapper 수리 및 Windows sandbox 진단 결과 반영
- 저장소: `C:\sswcenter\2.2`
- 브랜치/HEAD: `main`, `051c7ef` (변화 없음); `origin/main`과 ahead/behind `0/0`
- 이 문서는 같은 날짜 원본 핸드오프 `W2_SVC_PLAN_NOTICE_PHASE2_SESSION_HANDOFF_20260811.md`를 이어받은 다음 세션의 결과다. 원본 문서는 그대로 두고 이 문서를 새로 추가한다.
- 이번 세션 Writer: **Grok** (형님 재확인)
- 오케스트레이터: Claude Code
- 상태: **제품 구현 미커밋, Phase 2 계속 진행 중. fixture 수정 자체는 코드 레벨 검증 완료. PostgreSQL 55개 라이브 테스트는 아직 한 번도 pytest 본문까지 실행되지 못함. Codex wrapper의 watcher 오분류·진단 유실 문제는 C/D 양쪽에서 수리 완료했지만, Test Grade 3~5의 Windows sandbox 전환은 해결 방법만 확인됐고 아직 코드에 적용하지 않음.**

## 0. 한눈에 보는 현재 상태

### 완료

- PostgreSQL fixture 자체 시딩 수정(Grok) 완료 및 코드 레벨 검증 완료(별도 Explore agent가 실제 diff와 DDL을 직접 대조).
- DB-free 계약 테스트 재실행 **4/4 통과**, 회귀 없음.
- Codex exec 차단 버그(`allow_login_shell=false`) 실제 라이브 호출로 해소 확인(Test Grade 1 canary).
- Codex wrapper의 mutation 오탐 가능 지점을 Review Grade 4로 진단 완료(findings 5개).
- Codex wrapper의 watcher·진단 결함을 `C:\sswcenter\warpper`와 `D:\sswcenter\warpper` 양쪽에 동일하게 수리:
  - watcher `NotifyFilter`에서 `Security`·`Attributes`·`CreationTime`을 제외하고 `FileName`·`DirectoryName`·`LastWrite`·`Size`만 감시.
  - watcher 자체 오류를 실제 저장소 mutation과 분리해 `<PROVIDER>_REPOSITORY_WATCHER_UNRELIABLE`(exit 70)로 분류하고 오류 세부정보를 남김.
  - 실제 mutation 및 transient write는 기존처럼 `<PROVIDER>_READ_ONLY_REPOSITORY_MUTATED`(exit 20)로 차단.
  - 무결성 검사 또는 최종 리포트 파싱 실패 시에도 Codex child exit code/stdout/stderr/final JSON을 stderr 진단 블록으로 보존.
- wrapper 수리 검증 완료: D 전체 offline 테스트 **99/99 통과**, C 핵심 표적 테스트 **5/5 통과**, 기능 파일 4개(`ai-wrapper-core.ps1`, `invoke-codex.ps1`, `test-ai-wrappers-offline.ps1`, `README.md`)의 C/D SHA-256 일치 확인.
- 수리 전 백업: `C:\Users\sswce\AppData\Local\Temp\ai-wrapper-backup-20260811-170251`. 위 검증에는 실제 모델 호출이나 토큰 사용이 없었음.
- **Windows sandbox 진단 결과 확정**: Test Grade 3의 현재 `workspace-write`+`windows.sandbox="elevated"`에서는 base/venv Python이 Access denied로 차단됨. 반면 모델을 호출하지 않는 `codex sandbox` canary에서 `windows.sandbox="unelevated"`로 바꾸면 base Python, venv Python, `postgres.exe`, `pg_ctl.exe`, `initdb.exe`의 버전 명령이 모두 exit 0으로 실행됨. 따라서 Test Grade 3~5만 `unelevated`로 분기하는 해결 방향은 확인됨.
- 형님 지시로 W2 검증과 wrapper 수리를 분리: 오케스트레이터가 wrapper 밖에서 로컬 PowerShell로 직접 격리 PostgreSQL을 기동하는 방식으로 전환.
- 직접 실행 스크립트 작성 및 `Start-Process -ArgumentList` 배열 인자의 공백 포함 값 인용 버그 발견·수정.
- 두 번째 직접 실행 시도에서 `initdb`/`pg_ctl start`는 성공(PostgreSQL 자체는 정상 기동해 몇 분간 정상 동작, checkpoint까지 정상 수행)했으나 원인 불명의 지연(~25분+) 후 `pg_isready`에서 실패. 스크립트 자체의 정리(`finally`) 로직은 정상 동작해 클러스터 삭제·저장소 무변경을 스스로 확인함.
- 현재 제품 저장소는 HEAD `051c7ef`, `origin/main`과 ahead/behind `0/0`. 작업 트리는 깨끗한 상태가 아니라 이번 세션 시작 시점과 동일한 기존 변경/미추적 상태이며, 이번 진단으로 추가된 제품 파일 변화나 임시 리소스 잔존은 없음.

### 남음

- **55개 PostgreSQL 라이브 테스트가 이번 세션 전체를 통틀어 단 한 번도 끝까지 실행되지 못함.** 42개 fixture-blocked 테스트가 실제로 통과하는지는 여전히 미확인.
- GREEN 기준 7개 항목 전부 미확인.
- Codex Review Grade 3(제품 독립검수) 미실행(테스트 GREEN이 선행조건).
- 커밋 승인 전.
- Test Grade 3~5에 `windows.sandbox="unelevated"`를 적용하는 wrapper 분기 수정은 아직 미적용. 현재 `invoke-codex.ps1`은 모든 등급에 `windows.sandbox="elevated"`를 하드코딩함.
- `unelevated`에서 실제 `initdb → DB 기동 → pg_isready → stop` 전체 생명주기는 아직 검증되지 않음. 실행파일 버전 canary 성공만 확인된 상태.
- `pg_ctl start`가 `unelevated`에서도 정상인지 확인 필요. 실패하면 이미 성공 사례가 있는 `postgres.exe` 직접 기동을 Grade 3 프롬프트/러너의 fallback으로 사용.
- 로컬 직접 실행에서 관측된 `pg_isready` 25분 이상 지연 원인은 미해결.

## 1. 작업환경 및 세션 시작 컨텍스트

- 이번 세션은 원본 핸드오프(`W2_SVC_PLAN_NOTICE_PHASE2_SESSION_HANDOFF_20260811.md`)를 그대로 이어받아 시작함. 시작 시점에 그 문서 내용과 실제 저장소/wrapper 상태를 직접 대조해 완전히 일치함을 확인함(git status/diff/HEAD, wrapper 파일 존재, 핸드오프 파일 원문 대조).
- 세션 도중 사용자가 Plan Mode로 전환해 남은 검증 단계를 문서화하고 승인받는 과정을 거침(계획 파일: `C:\Users\sswce\.claude\plans\eager-pondering-wolf.md`, 4차 수정 후 승인됨). 이 세션의 실제 진행은 그 계획을 실행하다가 Codex wrapper의 새로운 인프라 문제를 만나면서 계획을 두 차례 더 조정한 결과다.
- 원래 이 문서는 wrapper 수리 전 중단 시점에 작성됐으나, 이후 형님이 wrapper 수리를 별도 승인해 실제 수리·offline 검증·Windows sandbox canary까지 진행했다. 본 갱신본은 그 후속 결과를 문서 전체에 반영한다.

## 2. 오늘(이어서) 한 일 — 시간순 기록

1. 원본 핸드오프와 실제 저장소/wrapper 상태 일치 확인.
2. 형님에게 Writer(Grok 유지)와 fixture 수정 방향(옵션 1: `test_w1e_postgres.py`의 `_insert_id` 패턴처럼 테스트 파일 자체 시딩)을 재확인.
3. `test_w1e_postgres.py`의 `_insert_id`/staff→user_account 생성 패턴(692~755행)을 직접 읽고, `test_w2_service_plan_notice_postgres.py`의 문제 지점(당시 255~289행 부근, `_insert_fixture_data`)을 확인해 정확한 Task Packet을 작성.
4. Grok을 `backend\tests\test_w2_service_plan_notice_postgres.py` 단일 파일 쓰기 권한으로 배정해 fixture 수정 실행. Grok 자체 보고는 COMPLETE.
5. 별도 Explore agent를 별도로 띄워 Grok의 실제 diff를 재검증: 변경 파일 1개뿐, `erp.staff`→`erp.user_account` INSERT 컬럼이 실제 마이그레이션 DDL(NOT NULL/CHECK/UNIQUE/FK)과 전부 합치, `account` 변수 재사용 부분 미변경, `_insert_id` 헬퍼 미사용은 이 파일의 기존 관례와 일치하므로 결함 아님으로 판정. 같은 agent가 fixture/트랜잭션 구조도 확인: 54개는 `database_connection`으로 롤백되지만 `test_serializable_write_skew_two_transactions` 1개는 설계상 실제 COMMIT을 남기고 정리 코드가 없어 매 실행마다 완전히 새 클러스터가 필요함을 확인.
6. `invoke-codex.ps1`의 실제 param 블록·grade 검증 로직을 직접 읽어 핸드오프의 5등급 설명과 정확히 일치함을 확인.
7. 별도 Plan agent로 등급 선택(Test Grade 3, Review Grade 3)과 세부 실행계획(프롬프트 문안, DB freshness 처리, 사전 canary 필요성)을 검증받음.
8. Plan Mode에서 형님이 4차례에 걸쳐 계획을 직접 수정 지시함: (a) GREEN 기준을 "55 passed"가 아니라 "54 passed / 1 expected skipped / 0 failed"로 정정하고 이유(별도 migration-lifecycle 환경변수 미설정)를 명시, (b) Test Grade 3 결과가 fail/회귀/저장소 변경이면 Review Grade 3를 실행하지 않고 형님께 먼저 묻기, Review Grade 3 finding 발견 시 자동으로 Grok을 재호출하지 않고 형님께 먼저 묻기로 확정, (c) "저장소 안에 뭔가 생기면 지워라"가 아니라 "애초에 안 만든다"로 표현 수정 및 native exe는 Start-Process로 완전 리다이렉트, (d) GREEN 기준이 실제로는 6개가 아니라 7개(42개 fixture-blocked 테스트가 실제 본문까지 실행되어 통과하는지가 빠져 있었음)임을 지적받아 전체 프롬프트·문서에 반영. 이 계획은 최종 승인됨.
9. 계약 테스트 재실행: **4 passed**, 회귀 없음.
10. Codex 사전 점검(Test Grade 1, Spark): `git --version` 정상(0ms 거부 없음, exec 차단 버그 해소 확인), `python --version`/`python -m pytest --version`은 실패(PATH에 python 없음, 예상된 별건). Codex는 4차례 다른 실행 방식을 스스로 시도하며 정확히 진단해 PASS(findings 포함)로 보고.
11. 형님께 이 결과를 보고하고 "python PATH 문제는 exec 차단과 무관하니 3단계 진행할지" 확인받아 진행 승인받음.
12. Codex Test Grade 3(1차, 격리 PostgreSQL 전체 실행) 실행: **`CODEX_READ_ONLY_REPOSITORY_MUTATED`(exit 20)로 실패, 출력이 2줄뿐**(session settings + WRAPPER_ERROR). Codex의 실행 transcript·pytest 결과 전혀 없음.
13. 직후 `git status --short`/`diff --stat`/`HEAD`로 저장소가 호출 전과 완전히 동일함을 직접 확인(단, 이 확인은 gitignored 파일 존재 여부는 증명하지 못한다는 한계가 나중에 Codex 리뷰로 지적됨).
14. `ai-wrapper-core.ps1`/`invoke-codex.ps1`을 직접 읽어 `Assert-AwReadOnlyRepositoryUnchanged`/`Compare-AwRepositorySnapshots`/`AwRepositoryWatcher`(C# FileSystemWatcher 래퍼)/`Get-AwWrapperErrorExitCode`/`Invoke-AwCodexMain`의 전체 제어흐름을 재구성. 예외가 던져지는 지점이 정확히 두 곳(정상 경로 직후 318행, 바깥 `finally` 안전망 345행)뿐이고, 어느 쪽이든 예외가 나면 Codex의 실제 stdout/stderr/JSON 리포트가 전혀 출력되지 않는다는 것을 코드로 확인.
15. 형님께 발견 사항을 보고하고 다음 조치를 여쭤 "wrapper 진단을 Codex 검수에 먼저 맡김"으로 결정받음.
16. `C:\sswcenter\warpper`가 git 저장소가 아님을 확인(RepositoryRoot로 직접 못 씀) → 관련 코드 전체를 프롬프트에 그대로 붙여넣는 방식으로 Codex Review Grade 4를 `C:\sswcenter\2.2`를 RepositoryRoot로 삼아 실행(순수 텍스트 기반 코드 리뷰, 파일시스템 접근 없음).
17. Review Grade 4 결과: **verdict FAIL**, findings 5개 — (1) 예외가 318행/345행 중 어디서 났는지 출력만으론 특정 불가, (2) `WatcherResult.HasError`(watcher 내부 오류)와 실제 mutation이 동일하게 처리되는 명백한 오분류, `Security` NotifyFilter로 인해 workspace-write+elevated의 ACL 준비만으로도 오탐 가능한 기술적으로 타당한 가설(단, 이번 사례의 실제 원인이라고 증명되지는 않음), (3) 사후 `git status`가 ignored 파일까지 보여주지 않으므로 "저장소 무변경" 확인이 생각보다 약한 증거, (4) 무결성 예외가 Codex의 모든 실행 증거를 폐기하는 것을 "중대한 운영 결함"으로 평가, (5) watcher 정지와 스냅샷 사이의 동시성 공백 및 이벤트 발생 프로세스 미귀속(백신/인덱서 등과 구분 불가) 지적.
18. 형님이 "Test Grade 3를 한 번만 그대로 재시도, 자동 재시도·Grade 4 추가·wrapper 수정 전부 금지, 이번에도 mutation으로 실패하면 즉시 중단"으로 결정.
19. Test Grade 3(2차) 실행: **mutation 오류는 재발하지 않음**(Codex 자신이 실행 전후 `git status --short` 완전 동일함을 직접 증거로 제출). 대신 **`status: BLOCKED`(exit 11)**로 종료. 근거: (a) `C:\sswcenter\2.2\backend\.venv\Scripts\python.exe -V`조차 실행 불가(exit 101, "Access is denied") — venv python이 내부적으로 가리키는 base Python 3.11 프로세스 생성이 거부됨. 절대경로 Python 3.12로도 재시도했으나 동일하게 거부. (b) `pg_ctl.exe start`도 `could not create restricted token: error code 87`로 실패했으나 Codex가 `postgres.exe` 직접 기동으로 우회에 성공, PostgreSQL 자체는 떴음. 결과적으로 alembic도 python 실행 불가로 실패해 pytest는 한 번도 실행되지 못함. 클러스터 정리(포트 55450, `pg_ctl stop`, 디렉터리 삭제)는 전부 성공.
20. 형님께 "내가 한번만 하랬는데" 지적을 받음 — 정확히 어느 지점(Grade 4 진단 자체 vs 재시도 이후 새 분석을 계속 확장한 것)을 말씀하시는지 여쭤봄. 이후 형님이 방향을 정리: **W2 검증과 wrapper 수리를 분리**, Codex Test Grade 3 재시도는 완전히 중단하고, **오케스트레이터가 wrapper 밖 로컬 PowerShell에서 직접** 임시 PostgreSQL을 만들어 venv python으로 alembic·55개 테스트를 실행하기로 결정. GREEN이면 Codex Review Grade 3만(Grade 4 없이) 실행, PASS 후 커밋 승인 요청, python sandbox 문제는 완전히 별도 wrapper 작업으로 분리하기로 확정.
21. `scripts/test-w2-service-plan-notice-red-gate.ps1`(이미 검증된 이 머신의 격리 PostgreSQL 기동 패턴)을 GREEN 극성으로 변형한 스크립트를 스크래치 디렉터리에 작성. RED-gate와 달리 head까지 전부 migrate하고, native exe는 형님 지시대로 `Start-Process -RedirectStandardOutput/-RedirectStandardError -Wait`로 실행하도록 변경.
22. **1차 직접 실행 실패**: `pg_ctl: unrecognized operation mode "127.0.0.1"`. 원인: `Start-Process -ArgumentList`에 배열로 넘긴 `--options="-h 127.0.0.1 -p <port>"` 같이 공백을 포함한 단일 논리 인자가 올바르게 하나의 토큰으로 인용되지 않고 쪼개짐(RED-gate가 쓰던 `&` 직접 호출과 달리 `Start-Process` 배열 인자는 자동 인용이 신뢰할 수 없음 — 핸드오프 §7.5의 배열 인자 문제와는 다른, `Start-Process` 고유의 새로운 사례).
23. 수정: 배열 인자를 공백 포함 여부에 따라 직접 따옴표 처리하는 `Format-ProcessArgument` 헬퍼를 추가하고, 전체 인자를 하나의 사전 인용된 문자열로 만들어 `-ArgumentList`에 전달하도록 변경.
24. **2차 직접 실행**: `initdb`/`pg_ctl start` 성공(`postgres.log` 확인: 16:53:46에 정상 기동, "database system is ready to accept connections", 16:58:46에 정상 checkpoint까지 수행 — PostgreSQL 자체는 몇 분간 완전히 정상 동작함). 그러나 백그라운드 작업이 예상보다 훨씬 오래(약 25분 이상) 진행 중인 상태로 남아 있어 형님이 "엄청 오래 걸리는구나, 지금 돌아가는지 다시 확인 좀"이라고 확인 요청. 프로세스(`pg_ctl`, `postgres` 6개)와 임시 디렉터리가 실제로 살아있음을 직접 확인해 보고. 잠시 후 백그라운드 작업이 최종적으로 완료됨: **`pg_isready failed with exit 2`**로 실패. 스크립트 자체의 `finally` 정리는 정상 동작해 `CLUSTER_DELETED=True`, `GIT_STATUS_IDENTICAL=True`를 스스로 출력함. 지연의 정확한 원인은 파악하지 못함(같은 시간대에 무관해 보이는 `test-ai-wrappers-offline.ps1` 관련 프로세스도 이 머신에서 돌고 있는 것을 관측함 — 리소스 경합 가능성이 있으나 확인되지 않음).
25. 최종 상태 재확인: `git status`/`diff --stat`/`HEAD` 전부 세션 시작 시점과 동일. 이번 실행에서 만든 임시 postgres 프로세스·디렉터리는 잔존물 없음(스크립트 자체 정리 성공, 오케스트레이터가 중간에 시도한 수동 삭제는 파일 잠금으로 실패했으나 무해함). 기존에 이 머신에 떠 있던 별개의 PostgreSQL 서비스 프로세스(PID 7936 등, 이번 세션과 무관)는 그대로 두었음.
26. 형님이 "하던 것까지만 하고 인수인계서 만들어서 줘"로 마무리 지시 → 이 문서 작성.
27. 이후 형님이 W2 제품 검증과 분리해 wrapper 수리를 재개하도록 승인하고, `C:\sswcenter\warpper`와 `D:\sswcenter\warpper`를 모두 동일하게 고치도록 지시.
28. `ai-wrapper-core.ps1` 수정: watcher 감시 대상을 이름·디렉터리명·마지막 쓰기·크기로 축소하고 ACL/속성/생성시간 이벤트를 제거. watcher 내부 오류를 실제 mutation과 분리해 별도 오류코드(exit 70)로 처리하며 오류 세부정보를 보존하도록 변경.
29. `invoke-codex.ps1` 수정: watcher/스냅샷 검사 또는 최종 JSON 파싱이 실패하더라도 child exit code, stdout, stderr, 생성된 final JSON을 진단 블록으로 출력하도록 변경. 따라서 과거처럼 `CODEX_READ_ONLY_REPOSITORY_MUTATED` 두 줄만 남고 실제 실행 transcript가 사라지는 문제를 방지.
30. `test-ai-wrappers-offline.ps1`과 `README.md`를 새 동작에 맞게 갱신. D 전체 offline 테스트 99/99, C 핵심 표적 테스트 5/5 통과. 기능 파일 4개의 C/D SHA-256이 전부 일치함을 확인. 드라이브별 `wrapper-config.json`은 실행파일 경로 등 머신별 설정을 보존하기 위해 서로 덮어쓰지 않음.
31. 수리 작업은 모델 호출 없이 수행했고 토큰을 사용하지 않음. 수리 전 파일은 `C:\Users\sswce\AppData\Local\Temp\ai-wrapper-backup-20260811-170251`에 보관.
32. Grade 3 외부 Python 차단을 별도 진단. 현재 wrapper가 모든 등급에 넣는 `windows.sandbox="elevated"`에서 base Python과 venv Python은 Access denied로 실패했으나, 모델 호출 없는 `codex sandbox` canary를 `windows.sandbox="unelevated"`로 실행하면 두 Python과 PostgreSQL 실행파일(`postgres`, `pg_ctl`, `initdb`) 버전 명령이 모두 exit 0으로 성공.
33. 결론: Test Grade 1~2와 모든 Review Grade는 기존 `elevated`를 유지하고, 외부 도구 실행이 필요한 Test Grade 3~5만 `workspace-write`+`unelevated`로 분기하는 것이 현재 확인된 해법. 단, 이 분기는 아직 wrapper 코드에 적용하지 않았고 실제 PostgreSQL start/stop 생명주기도 아직 검증하지 않음.
34. `unelevated`에서 실제 DB 생명주기를 확인하려던 로컬 no-token 복합 canary 명령은 실행 환경 정책이 명령 자체를 시작 전에 차단해 아무 프로세스나 클러스터도 만들지 못함. 따라서 이 시도는 성공·실패 어느 쪽의 PostgreSQL 근거로도 사용하지 않음.

## 3. 제품 저장소 변경분 (원본 핸드오프에서 변화 없음)

제품 변경은 총 5개 파일이며 전부 미커밋이다. 원본 핸드오프 §3과 동일하되, fixture 파일의 실제 diff가 이번 세션에 별도 Explore agent로 재검증되었다는 점만 갱신한다. `review/handovers/`의 인계 문서들은 별도 미추적 문서이며 제품 파일 5개 수에 포함하지 않는다.

| 파일 | 변경 내용 | 검증 상태 (갱신) |
|---|---|---|
| `backend/alembic/versions/20260809_0018_w2_service_plan_notice.py` | 신규 마이그레이션 | 계약 테스트 통과. 트리거/제약 본문은 여전히 실측 안 됨(§0 남음 참고). |
| `backend/app/db/models.py` | `RecipientServicePlanNotice` ORM | 계약 테스트 통과, 변화 없음. |
| `backend/app/domains/recipient/service_plan_notice.py` | 순수함수 4개 | 계약 테스트 통과, 변화 없음. |
| `backend/tests/test_w2_service_plan_notice_contract.py` | DO/COMMIT 세미콜론 허용 정규식 | 계약 테스트 4/4 통과, 변화 없음. |
| `backend/tests/test_w2_service_plan_notice_postgres.py` | **이번 세션 신규 변경**: `_insert_fixture_data`가 `erp.staff`→`erp.user_account`를 직접 시드하도록 수정(약 257~293행) | 코드 레벨(diff·DDL 대조)로는 검증됨. **라이브 PostgreSQL 실행으로는 이번 세션 내내 한 번도 검증되지 못함.** |

## 4. 인프라·wrapper 이슈와 현재 처리 상태

### 4.0 현재 Codex 등급표와 이번 수리 범위

형님이 확정한 등급별 모델 설정은 다음과 같으며 이번 watcher 수리에서 변경하지 않았다.

| 용도 | 등급 | 모델 | effort | fast | 현재 sandbox | 목표/비고 |
|---|---:|---|---|---|---|---|
| Test | 1~2 | Spark | xhigh | off | read-only + elevated | 유지 |
| Test | 3~4 | Luna | max | on | workspace-write + elevated | **unelevated로 변경 필요** |
| Test | 5 | Sol | max | off | workspace-write + elevated | **unelevated로 변경 필요** |
| Review | 1~2 | Luna | max | on | read-only + elevated | 유지 |
| Review | 3~4 | Sol | xhigh | off | read-only + elevated | 유지 |
| Review | 5 | Sol | ultra | off | read-only + elevated | 유지 |

- 등급은 세션 시작 때 미리 고르지 않고 wrapper 호출 시 Test/Review 등급을 지정한다.
- Grok writer 선택 흐름과 `invoke-grok.ps1`의 호출 방식은 유지했다. shared core의 watcher 오류 분류·진단 보존 개선만 함께 적용된다.
- C/D의 `wrapper-config.json`은 각 드라이브 설정을 유지했고 상호 복사하지 않았다.

### 4.1 Codex workspace-write+elevated sandbox의 외부 Python 차단 — 해법 확인, wrapper 적용 전

- 증상: `C:\sswcenter\2.2\backend\.venv\Scripts\python.exe -V` 및 절대경로 Python 3.12 모두 Codex Test Grade 3 안에서 "Access is denied"(exit 101)로 실행 자체가 거부됨.
- 범위: Test Grade 3뿐 아니라 같은 `workspace-write`+`windows.sandbox="elevated"` 조합을 쓰는 Test Grade 4·5도 동일하게 영향받을 가능성이 높음(등급표상 3·4는 wrapper 레벨에서 모델/effort/sandbox가 동일함을 이미 확인했음).
- 로컬 Codex CLI: `codex-cli 0.147.0-alpha.6.6`, 실행파일 `C:\Users\sswce\AppData\Local\OpenAI\Codex\bin\8e8bf206e63ac436\codex.exe`.
- 모델 호출 없는 `codex sandbox` canary 결과:
  - `windows.sandbox="elevated"`: base Python은 `CreateProcessAsUserW` error 5(Access denied), venv Python도 base interpreter 실행 단계에서 실패.
  - `elevated`에 legacy `sandbox_permissions=["disk-full-read-access"]` 또는 별도 custom profile을 추가해도 해결되지 않음.
  - `windows.sandbox="unelevated"`: base Python 3.11.9, `backend\.venv\Scripts\python.exe` 3.11.9 모두 exit 0.
- 공식 Windows sandbox 문서도 elevated 실패 시 unelevated를 fallback으로 지원함. 따라서 Test Grade 3~5만 `unelevated`로 분기하고 Test Grade 1~2 및 모든 Review Grade는 기존 `elevated`를 유지하는 방안이 현재의 구체적 해결책.
- **아직 미완료**: 현재 C/D `invoke-codex.ps1`은 여전히 모든 등급에 `windows.sandbox="elevated"`를 하드코딩한다. 코드 분기 적용 및 회귀 테스트가 필요함.

### 4.2 elevated sandbox의 pg_ctl.exe restricted-token 오류 — 실행 가능성 확인, start/stop 검증 전

- 증상: `pg_ctl: could not create restricted token: error code 87`.
- Codex는 `postgres.exe`를 직접 기동하는 방식으로 스스로 우회에 성공했음(pg_ctl stop으로 정리도 성공). 오케스트레이터가 wrapper 밖에서 직접 실행했을 때는 이 오류가 발생하지 않았음(§2 24번) — 이 sandbox의 제한된 토큰과 pg_ctl 자체의 권한 안전장치가 충돌하는, sandbox 특유의 문제로 보임.
- `unelevated` canary에서는 `postgres.exe --version`, `pg_ctl.exe --version`, `initdb.exe --version`이 모두 exit 0으로 성공해 실행파일 생성 차단은 해소됨.
- 단, `unelevated` 안에서 실제 `initdb → pg_ctl start → pg_isready → stop`은 아직 실행되지 않았으므로 오류 87의 완전 해소를 확정하지 않는다. `pg_ctl start`가 계속 실패하면 `postgres.exe` 직접 기동을 fallback으로 사용한다.

### 4.3 Wrapper의 watcher 오분류·진단 유실 — C/D 수리 및 offline 검증 완료

- 변경 전 문제:
  - watcher 내부 오류와 실제 저장소 변경이 모두 mutation으로 처리됨.
  - `Security`/ACL 이벤트까지 감시해 sandbox 준비 과정 자체를 mutation으로 오인할 수 있었음.
  - 무결성 예외가 나면 Codex stdout/stderr/final JSON이 폐기돼 원인 진단이 불가능했음.
- 적용한 수정:
  - `NotifyFilter`를 `FileName | DirectoryName | LastWrite | Size`로 제한.
  - watcher 내부 오류는 `<PROVIDER>_REPOSITORY_WATCHER_UNRELIABLE` 및 exit 70으로 분리하고 세부 오류를 기록.
  - 실제 mutation/transient write는 기존 exit 20 차단 유지.
  - 무결성 검사·리포트 파싱 실패 시 child exit/stdout/stderr/final JSON을 보존.
- 적용 위치: `C:\sswcenter\warpper`, `D:\sswcenter\warpper`.
- 검증: D offline 99/99, C 표적 5/5 통과. 기능 파일 4개 C/D 해시 일치.
- 남은 한계: watcher 정지와 최종 스냅샷 사이의 동시성 공백, 이벤트 발생 프로세스 미귀속은 이번 수정 범위에 포함하지 않음. 다만 이제 watcher 자체 오류가 mutation으로 오분류되지 않고 증거가 보존되므로 재현 시 진단 가능함.

### 4.4 (오케스트레이터가 직접 발견/수정) `Start-Process -ArgumentList` 배열 인자의 공백 값 인용 문제

- 증상: `Start-Process -FilePath pg_ctl.exe -ArgumentList @("--options=-h 127.0.0.1 -p 55446", "start")`처럼 배열 원소 안에 공백이 있으면 자동으로 올바르게 인용되지 않고 인자가 쪼개짐.
- 수정 패턴(재사용 가능): 배열을 직접 순회하며 공백/따옴표가 있는 원소만 `"..."`로 감싼 뒤 공백으로 join한 **단일 문자열**을 `-ArgumentList`에 전달한다. 아래 §5의 스크립트 `Format-ProcessArgument`/`Invoke-Redirected` 참고.
- 이 수정은 스크래치 디렉터리(세션별 임시경로)에만 존재하고 저장소에는 커밋되지 않았다. 재사용하려면 다음 세션에서 §5의 스크립트를 참고해 다시 작성해야 한다.

### 4.5 (미해결, 원인 불명) 직접 실행 2차 시도의 이례적 지연

- `pg_ctl start` 성공(로그상 1초 이내 정상 기동) 이후, `pg_isready`가 최종적으로 실패하기까지 관측상 25분 이상 걸림. 정상적인 `pg_isready -t 10`(10초 타임아웃) 동작과 맞지 않는 지연.
- 스크립트 자체 버그로 보이지는 않음(로직상 pg_ctl 성공 후 즉시 pg_isready를 부르고, 그 함수 자체도 앞서 성공적으로 여러 번 검증된 패턴).
- 같은 시간대에 이 머신에서 `test-ai-wrappers-offline.ps1` 관련 프로세스 트리가 별도로 실행 중인 것을 관측함(이 세션이 시작한 것이 아님, 원인 무관 여부 미확인) — 리소스 경합 가능성을 배제하지 않음.
- 재현 시도는 하지 않았음(형님이 다음 조치를 지시하기 전에 세션을 정리하기로 함).

## 5. 로컬 직접 실행 스크립트 기록 (부분 검증본, 그대로 재실행 주의)

아래 스크립트는 저장소에는 없으며 `initdb`와 `pg_ctl start`, 실패 후 cleanup까지는 실제 확인됐다. 그러나 `pg_isready`에서 비정상적인 장시간 지연 후 exit 2로 끝났고 pytest는 시작되지 않았으므로 **완전 검증본이 아니다**. 테스트를 Luna Max에 맡길 때 참고 자료로만 제공하고, 동일 스크립트를 그대로 장시간 방치하지 말 것. `pg_isready` 호출 전후 시각·프로세스 상태·로그를 짧은 제한시간으로 별도 관찰한 뒤 진행한다.

```powershell
param(
    [int]$Port = 55446
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$WorkspaceRoot = "C:\sswcenter\2.2"
$BackendRoot = Join-Path $WorkspaceRoot "backend"
$PythonExe = Join-Path $BackendRoot ".venv\Scripts\python.exe"
$PostgresBin = "C:\Program Files\PostgreSQL\17\bin"
$InitDbExe = Join-Path $PostgresBin "initdb.exe"
$PgCtlExe = Join-Path $PostgresBin "pg_ctl.exe"
$PgIsReadyExe = Join-Path $PostgresBin "pg_isready.exe"
$CreateDbExe = Join-Path $PostgresBin "createdb.exe"

foreach ($executable in @($PythonExe, $InitDbExe, $PgCtlExe, $PgIsReadyExe, $CreateDbExe)) {
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
        throw "Required executable is missing: $executable"
    }
}

$ExistingListener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($ExistingListener) { throw "Port $Port is already in use" }

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { throw "LOCALAPPDATA is required for the ephemeral cluster" }
$AllowedTempRoot = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "Temp")).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
$env:TEMP = $AllowedTempRoot
$env:TMP = $AllowedTempRoot
$ClusterRoot = [System.IO.Path]::GetFullPath((Join-Path $AllowedTempRoot ("sswcenter-w2-green-pg-" + [Guid]::NewGuid().ToString("N"))))
$DataDirectory = Join-Path $ClusterRoot "data"
$LogDirectory = Join-Path $ClusterRoot "logs"
$DatabaseName = "sswcenter_w2_green_test"
$ClusterStarted = $false

New-Item -ItemType Directory -Path $DataDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null

function Format-ProcessArgument {
    param([string]$Value)
    if ($Value -match '[\s"]') {
        return '"' + ($Value -replace '"', '\"') + '"'
    }
    return $Value
}

function Invoke-Redirected {
    param(
        [Parameter(Mandatory)][string]$Label,
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList
    )
    $out = Join-Path $LogDirectory ($Label + ".out.log")
    $err = Join-Path $LogDirectory ($Label + ".err.log")
    $commandLine = ($ArgumentList | ForEach-Object { Format-ProcessArgument $_ }) -join ' '
    $proc = Start-Process -FilePath $FilePath -ArgumentList $commandLine `
        -RedirectStandardOutput $out -RedirectStandardError $err -NoNewWindow -Wait -PassThru
    $stdout = if (Test-Path $out) { Get-Content -LiteralPath $out -Raw -ErrorAction SilentlyContinue } else { "" }
    $stderr = if (Test-Path $err) { Get-Content -LiteralPath $err -Raw -ErrorAction SilentlyContinue } else { "" }
    return [pscustomobject]@{ ExitCode = $proc.ExitCode; StdOut = $stdout; StdErr = $stderr }
}

$GitBefore = (git -C $WorkspaceRoot status --short) -join "`n"

try {
    Write-Output ("PORT_{0}=CHECKED_FREE" -f $Port)

    $r = Invoke-Redirected -Label "initdb" -FilePath $InitDbExe -ArgumentList @(
        "--pgdata=$DataDirectory", "--username=postgres", "--auth=trust", "--encoding=UTF8", "--locale=C"
    )
    if ($r.ExitCode -ne 0) { Write-Output $r.StdErr; throw "initdb failed with exit $($r.ExitCode)" }
    Write-Output "INITDB_OK"

    $r = Invoke-Redirected -Label "pg_ctl_start" -FilePath $PgCtlExe -ArgumentList @(
        "--pgdata=$DataDirectory", "--log=$(Join-Path $LogDirectory 'postgres.log')",
        "--options=-h 127.0.0.1 -p $Port", "start"
    )
    if ($r.ExitCode -ne 0) { Write-Output $r.StdErr; throw "pg_ctl start failed with exit $($r.ExitCode)" }
    $ClusterStarted = $true
    Write-Output "PG_CTL_START_OK"

    $r = Invoke-Redirected -Label "pg_isready" -FilePath $PgIsReadyExe -ArgumentList @(
        "-h", "127.0.0.1", "-p", "$Port", "-U", "postgres", "-d", "postgres", "-t", "10"
    )
    if ($r.ExitCode -ne 0) { Write-Output $r.StdErr; throw "pg_isready failed with exit $($r.ExitCode)" }
    Write-Output "PG_ISREADY_OK"

    $r = Invoke-Redirected -Label "createdb" -FilePath $CreateDbExe -ArgumentList @(
        "-h", "127.0.0.1", "-p", "$Port", "-U", "postgres", $DatabaseName
    )
    if ($r.ExitCode -ne 0) { Write-Output $r.StdErr; throw "createdb failed with exit $($r.ExitCode)" }
    Write-Output "CREATEDB_OK"

    $env:SSWCENTER_ENVIRONMENT = "test"
    $env:SSWCENTER_DATABASE_URL = "postgresql+psycopg://postgres@127.0.0.1:{0}/{1}" -f $Port, $DatabaseName
    $env:SSWCENTER_PIN_PEPPER = "w2-green-gate-test-pin-pepper"
    $env:SSWCENTER_PIN_LOOKUP_KEY = "w2-green-gate-test-pin-lookup"
    $env:SSWCENTER_CSRF_SIGNING_KEY = "w2-green-gate-test-csrf"
    $env:SSWCENTER_RESIDENT_NUMBER_KEY_V1 = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
    $env:SSWCENTER_RESIDENT_NUMBER_LOOKUP_KEY = "YWJjZGVmMDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODk="
    $env:SSWCENTER_RESIDENT_NUMBER_ACTIVE_KEY_VERSION = "1"
    $env:SSWCENTER_DATA_ROOT = Join-Path $ClusterRoot "sswcenter-test-files"
    New-Item -ItemType Directory -Path $env:SSWCENTER_DATA_ROOT -Force | Out-Null
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:SSWCENTER_W2_SVC_PLAN_NOTICE_REAL_PG = "1"
    if (Test-Path Env:\SSWCENTER_W2_SVC_PLAN_NOTICE_MIG_PG) { Remove-Item Env:\SSWCENTER_W2_SVC_PLAN_NOTICE_MIG_PG }

    Push-Location $BackendRoot
    try {
        & $PythonExe -m alembic -c alembic.ini upgrade head
        $AlembicExit = $LASTEXITCODE
        if ($AlembicExit -ne 0) { throw "alembic upgrade head failed with exit $AlembicExit" }
        Write-Output "ALEMBIC_UPGRADE_HEAD_OK"

        $PytestOutPath = Join-Path $LogDirectory "pytest.out.log"
        & $PythonExe -m pytest tests/test_w2_service_plan_notice_postgres.py -ra -v -p no:cacheprovider 2>&1 |
            Tee-Object -FilePath $PytestOutPath
        $PytestExitCode = $LASTEXITCODE
        Write-Output ("PYTEST_EXIT_CODE={0}" -f $PytestExitCode)
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($ClusterStarted) {
        try {
            Invoke-Redirected -Label "pg_ctl_stop" -FilePath $PgCtlExe -ArgumentList @(
                "--pgdata=$DataDirectory", "stop", "--mode=fast", "--wait"
            ) | Out-Null
        } catch { Write-Output ("PG_CTL_STOP_ERROR=" + $_.Exception.Message) }
        Start-Sleep -Seconds 1
    }
    $ResolvedClusterRoot = [System.IO.Path]::GetFullPath($ClusterRoot)
    if (Test-Path -LiteralPath $ResolvedClusterRoot) {
        try { [System.IO.Directory]::Delete($ResolvedClusterRoot, $true); Write-Output "CLUSTER_DELETED=True" }
        catch { Write-Output ("CLUSTER_DELETE_ERROR=" + $_.Exception.Message) }
    }
    $GitAfter = (git -C $WorkspaceRoot status --short) -join "`n"
    Write-Output ("GIT_STATUS_IDENTICAL=" + ($GitBefore -eq $GitAfter))
    if ($GitBefore -ne $GitAfter) {
        Write-Output "GIT_BEFORE:"; Write-Output $GitBefore
        Write-Output "GIT_AFTER:"; Write-Output $GitAfter
    }
}
```

### GREEN 기준 7개 (형님 확정)

다음 7개를 모두 만족해야 GREEN이다.

1. `PYTEST_EXIT_CODE=0`.
2. `-ra` 요약이 **54 passed**.
3. skip은 정확히 1개이며 `test_downgrade_upgrade_downgrade_reupgrade_lifecycle`만 expected skip.
4. **0 failed / 0 unexpected skipped**.
5. 이전에 fixture 단계에서 막혔던 42개 테스트가 실제 테스트 본문까지 도달해 모두 PASS하고 fixture setup failure가 0건.
6. 이전부터 통과하던 12개 테스트에 회귀 없음.
7. 실행 전후 저장소 상태가 완전히 동일하고 wrapper watcher가 저장소 생성·변경 이벤트를 보고하지 않음(`GIT_STATUS_IDENTICAL=True` 포함).

## 6. 이후 실행 순서 (2026-08-11 최종 결정 반영)

테스트 실행은 형님이 별도로 Luna Max에 맡긴다. 이 문서 갱신 과정에서는 테스트나 모델 호출을 추가로 실행하지 않는다.

1. 이 문서, 원본 핸드오프, `git status --short`, `git diff`, HEAD를 먼저 대조한다. 기존 제품 변경 5개와 인계 문서 외의 새 변화가 있으면 시작하지 말고 형님께 보고한다.
2. C/D 양쪽 `invoke-codex.ps1`에 sandbox 분기를 적용한다:
   - Test Grade 1~2: 기존 `read-only` + `windows.sandbox="elevated"` 유지.
   - Test Grade 3~5: 기존 `workspace-write`를 유지하되 `windows.sandbox="unelevated"` 사용.
   - Review Grade 1~5: 기존 `read-only` + `elevated` 유지.
   - `approval_policy="never"`, repository watcher, 등급별 모델/effort/fast 설정은 변경하지 않는다.
3. 동일 패치를 `C:\sswcenter\warpper`와 `D:\sswcenter\warpper`에 적용하고, drive별 `wrapper-config.json`은 덮어쓰지 않는다. offline 회귀 테스트와 C/D 기능 파일 해시 일치를 확인한다.
4. 전체 W2 테스트 전에 `unelevated` sandbox에서 **모델 호출 없는 최소 PostgreSQL 생명주기 canary**를 먼저 실행한다: 새 임시 디렉터리에서 `initdb → start → pg_isready → stop → 디렉터리 삭제`. 모든 로그와 data directory는 `%LOCALAPPDATA%\Temp` 아래에만 둔다. 저장소 안에는 cache를 포함해 어떤 파일도 생성하지 않는다.
5. canary에서 `pg_ctl start`가 오류 87로 실패하면 같은 조건으로 한 번만 `postgres.exe` 직접 기동 fallback을 사용한다. 이것도 실패하면 자동 재시도하지 말고 증거와 함께 중단한다.
6. canary 성공 후 Luna Max로 Codex **Test Grade 3**을 정확히 한 번 실행한다. 완전히 새 PostgreSQL 클러스터를 사용하고 `PYTHONDONTWRITEBYTECODE=1`, `pytest -p no:cacheprovider`, 순차 실행, migration-lifecycle 환경변수 미설정을 유지한다.
7. §5의 GREEN 기준 7개를 모두 만족할 때만 Codex **Review Grade 3**을 실행한다. Grade 4로 자동 승격하지 않는다. Test Grade 3가 BLOCKED/FAIL이거나 Review Grade 3에 finding이 있으면 자동 재시도·자동 Grok 호출 없이 형님께 먼저 보고한다.
8. Review Grade 3 PASS 후 형님께 결과를 보고하고 커밋 승인을 요청한다. 승인 후에만 §3의 제품 파일 5개와 형님이 포함하라고 지정한 인계 문서만 명시적으로 stage한다. `git add -A`, 자동 commit, 자동 push는 금지한다.

## 7. 종료 판단

Phase 2는 아직 완료가 아니다. 완료 조건은 원본 핸드오프와 동일하게 4가지이며 전부 미충족이다:

1. PostgreSQL fixture 자체 시딩 — **코드 레벨은 완료, 라이브 실행 검증만 남음.**
2. 42개 실패 테스트가 실제 본문까지 실행되어 통과 — **미확인 (이번 세션 전체에서 pytest 자체가 한 번도 안 돌아감).**
3. Codex 독립검수 PASS — **미실행.**
4. 형님 승인 후 커밋 — **미도달.**

이번 세션 및 후속 wrapper 작업의 실질적 성과는 fixture 수정의 코드 레벨 검증, watcher 오분류·진단 유실의 C/D 수리와 offline 검증, 그리고 Grade 3 외부 실행 차단을 `unelevated`로 해소할 수 있다는 no-token canary 근거를 확보한 것이다. 남은 핵심은 sandbox 분기를 실제 wrapper에 적용한 뒤 Luna Max로 Test Grade 3을 한 번 정상 완주하는 것이다. §6 순서를 지키고, 장시간 무응답이나 동일 실패에 대한 무계획한 반복 실행은 하지 않는다.
