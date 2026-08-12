# W2 급여계획서(Service Plan Notice) Phase 2 — 세션 핸드오프

- 작성일: 2026-08-11 (KST)
- 최종 갱신: 2026-08-11, Codex 래퍼 5등급 체계 및 장애 수정 반영
- 저장소: `C:\sswcenter\2.2`
- 브랜치/HEAD: `main`, `051c7ef`; `origin/main`과 ahead/behind `0/0`
- 오늘 세션 Writer: **Grok** (형님 직접 선정)
- 오케스트레이터: Claude Code
- 상태: **제품 구현 미커밋, Phase 2 진행 중**
- 현재 핵심 판단: Codex 래퍼 병목은 코드 수정 및 오프라인 회귀까지 완료. 제품의 자기완결적 PostgreSQL fixture와 실제 트리거 검증, 실제 Codex 독립검수는 아직 남음.

## 0. 한눈에 보는 현재 상태

### 완료

- W2 급여계획서 Phase 2 구현 파일 3개 생성/수정
- DB-free 계약 테스트 **4/4 통과**
- 임시 PostgreSQL GREEN 게이트에서 18개 마이그레이션 전체 적용 성공
- PostgreSQL 테스트 55개가 실행 단계까지 진입
- Codex 테스트/검수 **각 5등급** 라우팅 구현
- Codex exec 전면 차단 원인 후보 수정
- Codex `.git/index.lock` 계열 watcher 오탐 예방 조치
- Codex 자동 업데이트 해시 경로 drift 자동 복구 구현
- AI 래퍼 전체 오프라인 회귀 **97/97 통과**

### 남음

- PostgreSQL fixture가 빈 DB에서도 자체 시드되도록 수정
- 실패했던 42개 트리거/제약 테스트를 실제로 실행해 GREEN 확인
- 실제 Codex 테스트 호출로 exec 차단 해소 확인
- 실제 Codex 검수 호출로 watcher 오탐 해소 및 Grok 구현 독립검수 확인
- 모든 검증 후 형님 승인하에 커밋

## 1. 작업환경 및 세션 시작 컨텍스트

- `C:\sswcenter\2.1` 구 저장소는 세션 초반 형님이 직접 삭제함. 현재 작업 저장소는 `C:\sswcenter\2.2`.
- `C:\sswcenter\2.2`는 `fd3018f`에서 `051c7ef`로 fast-forward한 뒤 Wave 2 급여계획서 Phase 1(RED-only) 완료 상태에서 시작함.
- 정본으로 안내된 `E:\sswcenter\00-먼저읽기-작업환경안내.md`와 `E:\sswcenter\00-오케스트레이션-작업지침.md`는 현재 PC에 없음. `D:\sswcenter\00-오케스트레이션-작업지침.md`는 존재함. 드라이브 배치 차이는 다음 세션에서도 먼저 확인할 것.
- Writer는 형님이 세션 시작 때 **Grok**으로 선정함. Grok Writer 선정 방식과 `invoke-grok.ps1` 동작은 이번 래퍼 정비에서 변경하지 않음.

## 2. 오늘 한 일 — 시간 순 기록

1. `2.1`과 `2.2` 저장소를 pull함. 이후 `2.1`은 형님이 삭제함.
2. `2.2` 현황을 확인하고 Wave 2 급여계획서 슬라이스가 RED-only Phase 1 완료 상태임을 확인함.
3. 오케스트레이션 지침과 작업환경의 실제 드라이브 차이를 확인함.
4. 형님이 오늘 Writer로 **Grok**을 지정함.
5. 테스트 매트릭스 2개 파일, 총 4,233줄을 정독해 스키마·트리거·함수·순수함수 요구사항을 추출하고 Phase 2 Task Packet을 작성함.
6. `invoke-grok.ps1`로 구현을 배정함.
   - 1차에는 `pwsh -File`로 배열형 `-WriteAllowPath @(…)`를 넘겨 PowerShell 인자가 깨짐.
   - PowerShell 7 세션에서 `& .\invoke-grok.ps1 -WriteAllowPath @(…)`로 직접 호출해 재실행함.
   - Grok이 마이그레이션, ORM, 순수함수 모듈을 생성함.
7. DB-free 계약 테스트 1차 실행 결과 4개 중 2개가 실패함.
   - CHECK 제약 이름이 `ck_recipient_service_plan_notice_ck_service_plan_notice_*`처럼 이중 접두됨.
   - Alembic offline SQL에 `;;`가 4곳 생김.
8. Grok 2라운드에서 두 문제를 정밀 수정함.
   - CHECK 이름은 SQLAlchemy naming convention을 고려해 `conv()` 패턴으로 정리됨.
   - `op.execute()` 블록 끝의 자체 세미콜론을 조정함.
   - 실제 파일 수정은 정확했으나 최종 JSON의 `tests`가 배열이 아닌 문자열이라 래퍼는 `GROK_REPORT_TESTS_TYPE_INVALID`로 보고서를 거부함. 변경분은 `git diff`로 직접 확인함.
9. 계약 테스트 재실행 결과 3/4 통과함. DO/COMMIT 블록 완전일치 검사가 Alembic의 자동 세미콜론 때문에 어떤 정상 구현으로도 통과할 수 없음을 최소 재현으로 확인함.
10. 형님 승인 후 계약 테스트의 DO/COMMIT 조건을 `\s*;?` 허용 정규식으로 수정함. 이후 **4/4 전부 통과**함.
11. 임시 PostgreSQL GREEN 검증 스크립트를 작성하고 네 차례 보정함.
    - 1차: `createdb.exe` 직접 호출과 파이프/배경 실행 조합에서 콘솔 I/O 상속 hang 발생.
    - 2차: native exe를 `Start-Process`와 stdout/stderr 파일 redirect로 바꿔 hang 해소. 이후 `pg_ctl --options` 공백 인자 분리 문제 발견.
    - 3차: `--options` 값을 따옴표로 보정. 이후 Alembic 작업 디렉터리 누락으로 `script_location` 오류 발견.
    - 4차: `-WorkingDirectory`를 지정해 성공. 18개 마이그레이션 전체 적용 확인.
12. PostgreSQL pytest 55개 실행 결과 **12 통과, 42 실패, 1 스킵**.
    - 42개 실패는 모두 `_insert_fixture_data`의 `SELECT id FROM erp.user_account LIMIT 1`이 빈 DB에서 0행을 반환해 발생한 `NoResultFound` 단일 원인.
    - 이 때문에 Grok이 구현한 42개 트리거/제약 검증 본문은 아직 한 번도 실제로 실행되지 못함.
13. 형님 피드백에 따라 오케스트레이터가 직접 진단·검수까지 떠안지 않고 Codex로 테스트와 검수를 위임하는 방향을 확정함.
14. 기존 Codex 위임에서 세 장애가 확인됨.
    - Codex CLI 자동 업데이트로 `wrapper-config.json`의 해시 폴더 경로가 stale해짐.
    - Spark SimpleTest에서 `python`, `pytest`, `git --version`까지 0ms에 `rejected: blocked by policy`로 차단됨.
    - Sol review에서 실제 최종 저장소 delta가 없는데 `CODEX_READ_ONLY_REPOSITORY_MUTATED`가 발생함.
15. 형님과 Codex 테스트/검수 5등급 정책을 확정함. 세션 시작 때 Codex 모델·effort·fast를 묻는 방식은 폐기하고, 호출 때 테스트/검수 종류와 등급만 넘기도록 결정함.
16. `invoke-codex.ps1`을 현재 파일 기준으로 다시 정리함.
    - `-TestGrade 1..5` 또는 `-ReviewGrade 1..5` 중 정확히 하나를 필수화함.
    - `-SimpleTest`는 테스트 1등급 호환 별칭으로 유지함.
    - 모델·effort·fast·sandbox/network 조합을 등급 정책에서만 계산함.
    - 기존 `-ReviewEffort`, `-FastMode`, `-UltraFast`와 인터랙티브 질문을 제거함.
17. exec 전면 차단 원인을 재진단함.
    - 공식 설정상 `approval_policy="never"`는 비대화형 실행에 맞는 값이므로 유지함.
    - 현재 래퍼의 `allow_login_shell=false`는 `login=true` 요청을 즉시 거부하는 설정이며 0ms 전면 차단 증상과 직접 일치함. 해당 강제값을 제거함.
    - 사용자 config를 무시해도 이 PC의 native Windows sandbox가 유지되도록 `windows.sandbox="elevated"`를 명시함.
18. watcher 오탐 예방을 보강함.
    - AI 자식 환경에 `GIT_OPTIONAL_LOCKS=0`, `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`를 추가함.
    - `.git/index.lock` 이벤트를 사후에 무시하는 방식은 채택하지 않음. transient mutation 감시 계약은 유지하고 선택적 Git lock이 애초에 생기지 않도록 함.
19. Codex 실행파일 자동 복구를 구현함.
    - 설정 경로가 `%LOCALAPPDATA%\OpenAI\Codex\bin\<16자리 해시>\codex.exe` 형식이고 해당 파일만 사라진 경우에 한해 같은 `bin`의 직접 하위 해시 폴더에서 최신 정상 `codex.exe`를 선택함.
    - 재귀 검색, PATH 추측, reparse-point 후보, 설정 JSON 자동 덮어쓰기는 하지 않음.
    - 실제 PC에서 stale 가상 해시를 넣은 resolver 점검 결과 `8e8bf206e63ac436\codex.exe`를 정상 선택함.
20. 래퍼 문서와 오프라인 테스트를 갱신하고 전체 회귀를 실행함. 결과는 **97/97 통과**함. 실제 유료 Codex 작업 호출은 실행하지 않음.

## 3. 제품 저장소 변경분

현재 제품 변경은 4개 파일이며 모두 미커밋이다. 핸드오프 문서 자체는 `review/handovers/` 아래 untracked 상태다.

| 파일 | 변경 내용 | 작성/수정 | 검증 상태 |
|---|---|---|---|
| `backend/alembic/versions/20260809_0018_w2_service_plan_notice.py` | 신규 마이그레이션: 테이블, 트리거 7개, 함수 7개, grant | Grok | 계약 테스트 통과, 실제 트리거 본문 미검증 |
| `backend/app/db/models.py` | `RecipientServicePlanNotice` ORM 클래스 추가, 58줄 | Grok | 계약 테스트 통과 |
| `backend/app/domains/recipient/service_plan_notice.py` | 순수함수 4개: `default_end_date`, `deadline_date`, `d100_date`, `d45_date` | Grok | 계약 테스트 통과, 라이브 PG 관련 6개 테스트 통과 |
| `backend/tests/test_w2_service_plan_notice_contract.py` | DO/COMMIT 검사에서 Alembic 자동 세미콜론 허용 | Claude, 형님 승인 | 계약 테스트 4/4 통과 |

현재 tracked diff 요약은 `backend/app/db/models.py` 58줄 추가, 계약 테스트 2줄 추가/2줄 삭제다. 신규 마이그레이션과 신규 domain 모듈은 untracked라 일반 `git diff --stat`에는 나오지 않는다.

## 4. 래퍼 변경분

래퍼 경로는 `C:\sswcenter\warpper`다.

| 파일 | 반영 내용 | 상태 |
|---|---|---|
| `invoke-codex.ps1` | 테스트/검수 5등급, 등급 필수화, 인터랙티브 설정 제거, `allow_login_shell=false` 제거, elevated Windows sandbox, 등급별 sandbox/network | 완료, parse 통과 |
| `ai-wrapper-core.ps1` | Codex 해시 경로 자동 복구, AI 자식의 Git optional-lock/프롬프트 차단 환경, 등급 오류 종료 코드 64 매핑 | 완료, parse 통과 |
| `test-ai-wrappers-offline.ps1` | 테스트 5등급 + 검수 5등급, 누락/충돌, 경로 복구, login-shell 차단 재발 방지, Git 환경 검증 | 완료 |
| `README.md` | 5등급 표, 호출법, DB/E2E 권한, 장애 원인과 운영 주의사항 | 완료 |
| `wrapper-config.json` | 세션 초반 office Codex 경로를 현재 해시로 수동 갱신 | 현재 경로 존재; 이번 최종 래퍼 정비에서는 추가 수정하지 않음 |
| `invoke-grok.ps1` | 변경 없음 | Writer 동작 그대로 유지 |

## 5. Codex 5등급 정책

### 5.1 테스트

| 등급 | 대표 범위 | 모델 | effort | fast | sandbox/network |
|---:|---|---|---|---|---|
| 1 | 정적·문법·import·compile·단일 smoke | Spark | `xhigh` | off | `read-only`, network off |
| 2 | bounded unit·component·contract | Spark | `xhigh` | off | `read-only`, network off |
| 3 | 격리 PostgreSQL·DB integration | Luna | `max` | on | `workspace-write`, network on |
| 4 | API·frontend·service·E2E | Luna | `max` | on | `workspace-write`, network on |
| 5 | 운영·복구·migration lifecycle·security·최종 acceptance | Sol | `max` | on | `workspace-write`, network on |

- 정확한 모델 ID는 Spark `gpt-5.3-codex-spark`, Luna `gpt-5.6-luna`, Sol `gpt-5.6-sol`.
- 테스트 3~5등급의 쓰기/network 허용은 격리 임시 디렉터리, disposable test DB, 명시한 로컬 테스트 서비스를 위한 것.
- public internet, package download/install, production/shared/식별 불가 DB는 금지.
- sandbox가 workspace write를 허용해도 제품 저장소와 Git state는 불변이어야 하며 wrapper watcher/fingerprint에서 변화가 한 건이라도 발견되면 실패.

### 5.2 검수

| 등급 | 대표 범위 | 모델 | effort | fast | sandbox |
|---:|---|---|---|---|---|
| 1 | 빠른 집중 검수 | Luna | `max` | on | `read-only` |
| 2 | 일반 정확성·회귀·테스트 적정성 검수 | Luna | `max` | on | `read-only` |
| 3 | cross-layer·data flow·integration·edge 검수 | Sol | `xhigh` | on | `read-only` |
| 4 | architecture·security·concurrency·recovery·운영 검수 | Sol | `xhigh` | on | `read-only` |
| 5 | 최종 adversarial acceptance 검수 | Sol | `ultra` | off | `read-only` |

### 5.3 호출 계약

- Codex 래퍼는 세션 시작에 모델·effort·fast를 묻지 않음.
- 매 호출에 `-TestGrade` 또는 `-ReviewGrade` 중 정확히 하나를 전달함.
- 등급 누락 또는 테스트/검수 등급 동시 전달은 인증·작업 native 호출 0회, 종료 코드 64.
- 모델·effort·fast를 임의로 조합하는 public parameter는 없음.
- 테스트가 끝난 뒤 필요한 검수 등급을 별도로 선정해 검수를 수행함.

## 6. 검증 결과

### 6.1 제품 검증

| 검증 | 결과 | 해석 |
|---|---|---|
| DB-free 계약 테스트 | 4/4 통과 | 스키마/DDL 계약과 순수함수 정적 계약 통과 |
| Alembic base→W2 | 18개 migration 적용 성공 | 전체 migration chain 적용 가능 |
| PostgreSQL pytest | 12 통과, 42 실패, 1 스킵 | fixture seed 단일 원인으로 트리거 본문 진입 전 실패 |
| Grok 구현 독립검수 | 미완료 | Codex live review 재실행 필요 |

### 6.2 래퍼 검증

```text
AI_WRAPPER_OFFLINE total=97 passed=97 failed=0
```

포함된 주요 계약:

- 테스트 1~5와 검수 1~5의 모델·effort·fast·sandbox/network 정확성
- 등급 누락/충돌 시 native 호출 0회
- `allow_login_shell=false` 재도입 방지
- elevated Windows sandbox 인자
- `GIT_OPTIONAL_LOCKS=0`, `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`
- stale Codex 해시 경로에서 최신 native exe 선택
- 인증/작업 mutation, transient restore, ignored 파일, dirty WIP, watcher callback drain
- timeout, output limit, process tree 종료, UTF-8, 비밀 환경 격리
- Grok/Opus 기존 계약 회귀

주의: 이 테스트는 실제 AI·원격 모델·과금을 사용하지 않는다. 따라서 Spark exec와 Sol watcher 문제는 **코드 수정 및 오프라인 계약 검증 완료**, **실제 Codex live 호출 확인만 남음**으로 기록한다.

## 7. 해결 또는 정정된 환경·래퍼 이슈

### 7.1 Spark exec 전면 차단

- 과거 추정: `approval_policy="never"`가 Windows에서 모든 외부 exe를 막는 것 같았음.
- 정정: 공식 설정에서 `never`는 비대화형 실행용이며 그대로 유지함.
- 현재 코드에서 0ms 거부 증상과 직접 맞는 값은 `allow_login_shell=false`였음. login-shell 요청을 정책 단계에서 즉시 거부하므로 제거함.
- Windows sandbox는 사용자 config를 무시하는 실행에서도 `elevated`로 명시함.
- `codex sandbox -P :read-only ... git --version`의 native sandbox 자체 실행은 이 PC에서 성공했음.
- 실제 Spark 모델 호출로 최종 확인은 아직 하지 않음.

### 7.2 Sol `CODEX_READ_ONLY_REPOSITORY_MUTATED`

- 기존 watcher는 최종 delta가 없어도 transient `.git/index.lock` 이벤트를 실제 mutation으로 간주할 수 있음.
- watcher 이벤트를 무시하거나 감시를 약화하지 않음.
- AI 자식이 optional Git lock을 만들지 않도록 `GIT_OPTIONAL_LOCKS=0`을 주입함.
- Git credential prompt도 `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`로 차단함.
- mutation/원복/ignored 변경을 계속 reject하는 오프라인 테스트는 모두 통과함.
- 실제 Sol review 재실행 확인은 아직 남음.

### 7.3 Codex 실행파일 path drift

- 초기에는 `cfac6bda2d141e07` 경로가 stale해 `8e8bf206e63ac436`로 수동 갱신함.
- 이제 같은 공식 hashed-bin 레이아웃 안에서만 최신 정상 native exe를 자동 복구함.
- 성공 시 stderr에 `CODEX_EXECUTABLE_AUTO_RECOVERED=<path>`를 남김.
- 다른 임의 경로, PATH, 재귀 폴더는 추측하지 않음.

### 7.4 콘솔 I/O 상속 hang

- 임시 PostgreSQL 스크립트에서 native exe를 파이프/배경 직접 호출했을 때 실제 hang을 재현함.
- 임시 스크립트는 처음부터 `Start-Process -RedirectStandardOutput/-RedirectStandardError`를 사용할 것.
- 공용 wrapper core는 이미 redirect된 `ProcessStartInfo`, 비동기 stdout/stderr drain, Windows Job Object를 사용하므로 같은 패턴의 콘솔 핸들 상속을 피함.

### 7.5 PowerShell 배열 인자

- `pwsh -File script.ps1 -Param @(…)` 형식으로 배열을 넘기지 않음.
- 배열이 필요하면 PowerShell 7 세션에서 `& .\script.ps1 -Param @(…)`로 직접 호출함.

### 7.6 Grok 최종 JSON 불일치

- `invoke-grok.ps1`은 정상적으로 구현을 수행함.
- Grok이 간헐적으로 최종 JSON schema를 어겨도 wrapper가 자동 재호출하지 않음.
- 보고서 실패와 실제 변경 성공은 별개이므로 항상 `git status`, `git diff`, 신규 파일 원문을 직접 확인함.

## 8. 아직 못 고친 제품 이슈

### 8.1 PostgreSQL fixture 시드 공백

- 위치: `backend/tests/test_w2_service_plan_notice_postgres.py`, `_insert_fixture_data`, 기존 기록상 255~260줄 근처.
- 현재 구현은 `SELECT id FROM erp.user_account LIMIT 1`로 기존 행을 기대하지만 새 임시 DB에는 행이 없음.
- 참고 패턴: `test_w1e_postgres.py`는 `_insert_id`, `_service_id` 헬퍼로 staff→account를 직접 생성해 자기완결적임.
- 선택지:
  1. W1E 패턴처럼 테스트 파일 자체에 시드 로직 추가.
  2. 별도 GREEN gate가 명시적으로 시드를 넣도록 구성.
- 추천 방향: 테스트 독립성과 재현성을 위해 테스트 fixture 자체를 자기완결적으로 만드는 방안을 Writer에게 배정하고, 기존 테스트 매트릭스 의도와 충돌하지 않는지 확인.

### 8.2 트리거/제약 실측 미완료

- 42개 테스트는 fixture 단계에서 모두 중단됐으므로 Grok의 트리거/제약 구현 정확성을 아직 증명하지 못함.
- 시드 수정 후 격리 PostgreSQL에서 같은 전체 테스트를 다시 실행해야 함.
- 이 작업은 **테스트 3등급**이 기본이며, 운영·migration lifecycle까지 넓히면 4~5등급을 별도로 고려함.

### 8.3 실제 Codex 독립검수 미완료

- 래퍼 수정 전에는 Spark exec와 Sol watcher 오류 때문에 독립검수에 한 번도 성공하지 못함.
- 래퍼 수정 후에는 실제 유료 모델 호출을 의도적으로 생략했으므로 독립검수 결과는 아직 없음.
- 제품 테스트 GREEN 후 최소 **검수 3등급**으로 data flow·migration·trigger 상호작용을 검수함.
- architecture/security/recovery 위험까지 최종 확인해야 하면 **검수 4등급**으로 올림.

### 8.4 미커밋 상태

- 제품 변경 4개 파일과 handover 문서가 미커밋 상태.
- wrapper 변경은 제품 저장소 바깥 `C:\sswcenter\warpper`에 있음.
- 제품 테스트 GREEN과 독립검수 PASS 전에는 커밋하지 않음.
- 커밋은 형님 승인 후 진행함.

## 9. 오케스트레이터에게 남은 역할

1. **세션 시작 Writer 선정**
   - 형님에게 Writer만 확인함.
   - Grok Writer 호출과 쓰기 allowlist를 관리함.
2. **각 Codex 호출의 종류와 등급 결정**
   - 테스트인지 검수인지 구분함.
   - 범위·위험·소요시간에 따라 1~5등급만 선택함.
   - 모델·effort·fast는 선택하지 않고 wrapper 정책에 맡김.
3. **작업 순서 관리**
   - Writer 구현 → 필요한 테스트 등급 → 필요한 검수 등급 순으로 진행함.
   - FAIL/BLOCKED 결과를 보고 재작업·등급 상향·범위 조정을 결정함.
4. **증거와 상태 확인**
   - Grok 최종 JSON 오류 여부와 관계없이 실제 `git diff`를 확인함.
   - 테스트가 실제 대상 로직까지 진입했는지 확인함. fixture 단계 실패를 구현 검증 실패와 구분함.
   - wrapper가 저장소를 자동 복구하지 않으므로 mutation 오류 때 실제 상태를 직접 확인함.
5. **승인 경계 유지**
   - commit/push, production/shared DB, 범위 확장은 형님 승인 없이 진행하지 않음.

오케스트레이터가 더 이상 할 필요가 없는 일:

- Codex 모델·effort·fast를 세션 시작마다 질문하거나 직접 조합하는 일
- Spark/Luna/Sol 모델 ID를 호출마다 수동 계산하는 일
- stale hashed Codex 경로를 매번 수동으로 찾는 일
- wrapper 내부 문제를 피하려고 임의 fallback 모델을 재호출하는 일

## 10. 다음 세션 실행 순서

1. 이 문서와 현재 상태를 확인함.

```powershell
git -C 'C:\sswcenter\2.2' status --short
git -C 'C:\sswcenter\2.2' diff --stat
git -C 'C:\sswcenter\2.2' diff
```

2. 형님에게 그날 Writer만 확인함.
3. PostgreSQL fixture 시드 방향을 확정하고 Writer에게 해당 테스트 파일 범위만 배정함.
4. 변경 후 DB-free 계약 테스트를 먼저 재실행함.
5. Codex **테스트 3등급**으로 격리 PostgreSQL 전체 검증을 실행함.

```powershell
& 'C:\sswcenter\warpper\invoke-codex.ps1' `
  -RepositoryRoot 'C:\sswcenter\2.2' `
  -TestGrade 3 `
  -Prompt 'W2 service plan notice의 자기완결적 fixture와 격리 PostgreSQL 전체 테스트를 실행하고, 42개 트리거/제약 테스트가 실제 본문까지 진입했는지 증거와 함께 보고해.'
```

6. 55개 PostgreSQL 테스트 결과를 확인함. fixture 단계가 아니라 실제 트리거/제약 본문이 실행됐는지 반드시 확인함.
7. 모든 제품 테스트가 GREEN이면 Codex **검수 3등급**을 실행함.

```powershell
& 'C:\sswcenter\warpper\invoke-codex.ps1' `
  -RepositoryRoot 'C:\sswcenter\2.2' `
  -ReviewGrade 3 `
  -Prompt '현재 W2 service plan notice 변경분을 data flow, migration, ORM, PostgreSQL trigger/constraint, 테스트 적정성 관점에서 독립검수해.'
```

8. 중요 migration·security·recovery 위험이 남으면 검수 4등급으로 추가 검수함.
9. 테스트 GREEN과 독립검수 PASS를 확보한 뒤 형님에게 결과를 보고하고 커밋 승인을 받음.
10. 승인 후에만 의도한 파일을 선별 커밋함. 자동 stage/commit/push는 하지 않음.

## 11. 종료 판단

이 Phase 2는 아직 완료가 아니다. 완료 조건은 다음 네 가지다.

1. 빈 임시 DB에서도 PostgreSQL fixture가 자기완결적으로 준비됨.
2. 현재 실패한 42개 테스트가 트리거/제약 본문까지 실제로 실행되고 기대 결과를 통과함.
3. Codex 독립검수가 실제 호출에서 PASS함.
4. 형님이 결과를 확인하고 커밋을 승인함.

현재는 **래퍼 병목 해소 및 오프라인 검증 완료, 제품 라이브 검증과 실제 독립검수 대기** 상태다.
