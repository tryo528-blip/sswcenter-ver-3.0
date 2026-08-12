# SSWCenter 2.2 전체 이슈 해결보고서

**독자:** 개발자가 아닌 사용자
**정본(진짜로 작업하는 코드 폴더):** `C:\sswcenter\2.2`
**기준 날짜:** 2026-08-05
**이 문서는 구현·검수 결과 설명용입니다.** 사용자가 `끝!`을 선언하기 전에는 Git 마감(commit/push)이 끝난 상태가 **아닙니다**.

---

## 한 문단 요약

이번 작업으로 **제품·자동 도구·최종 검수 도구의 안전 장치 대부분은 닫혔고(CLOSED)** 입니다. **사용자 Claude 1회 로그인이 이미 완료**되었고, **Opus 기술 최종 검수(5 XHIGH)도 PASS(Critical/Major 0)** 로 끝났습니다. **이번에는 사용자 지시에 따라 보고서 자체에 대한 Opus 추가 검수는 생략**했습니다. Git **commit/push는 아직 하지 않았습니다.** 사용자가 보고서를 읽고 준비되면 **`끝!`** 을 선언하는 것이 다음 단계입니다. 아주 초기에 Git 상태를 느슨하게 본 구간·Windows 자격 증명 금고 비밀값 전체 봉인·일부 호스트 세션 경고는 사후 완전 증명이 어려워 **UNKNOWN**(또는 호스트 쪽 OPEN)으로 남깁니다. 아래는 “무엇이 위험했는지 → 어떻게 막았는지 → 무엇으로 확인했는지 → 지금 상태”를 쉬운 말로 정리한 전체 보고서입니다.

---

## 현재 최종 기술 판정(권위 근거)

다음 수치는 **권위 보고서** `SSWCENTER_2_2_ENVIRONMENT_AND_RUNNER_ISSUES.md`와 본 작업 세션의 계약(자동 시험)·독립 검수 결과입니다. “모든 테스트를 지금 이 순간 전부 다시 돌렸다”는 뜻이 아니라, **이미 봉인된 계약 증거 + 독립 검수 envelope + 마지막 observer 실행**을 구분합니다.

| 항목 | 결과 | 근거 구분 |
|------|------|-----------|
| Opus 기술 최종 검수(5 XHIGH) | **PASS**, Critical/Major 0 | 독립 정적 검수 보고(사용자 로그인 완료 후) |
| DeepSeek 최종 독립 검수 | **PASS**, ReadOnly 약 22파일, exit 0, checkpoint 저장, errors 0 | 실제 Runner envelope |
| Runner 계약 | **481/481** | 자동 계약 증거 |
| Opus wrapper 계약 | **259/259** | 자동 계약 증거 |
| workspace seal 계약 | **120/120** | 자동 계약 증거 |
| ai-tools 계약 | **61/61** | 자동 계약 증거 |
| 환경 redaction 계약 | **11/11** | 자동 계약 증거 |
| HEAD(Git 커밋 지점) | `c50f49dfff3ac4ce5b5307eca1aa765dd26ab3c9` | git finish |
| 디자인 동결 파일 수 | tracked **129** | observer |
| 디자인 집계 해시(내용 지문) | `98c93aac…60dc` match | observer |
| Git status 파일 수 | **status_count=0** (마감 후 clean) | observer |
| staged(커밋 대기 목록) | **0** (마감 후 clean) | observer |
| Claude 로그인·Opus 기술 경로 | **CLOSED(기술 경로)** — 로그인 완료, Opus PASS. 보고서 Opus 추가 검수는 이번 지시로 생략 | ENV-CLAUDE-001 |
| CredMan 비밀 전체 봉인 / 최초 optional-lock 이전 | **UNKNOWN** | 증거 한계(인증값 미기록) |
| Git 마감 도구 | **CLOSED** — 한글 quoted path 파싱 수정 후 `끝!` 마감 | ENV-GIT-FINISH-001 |
| 사용자 다음 행동 | **`끝!` 선언 완료** → 마감 진행 | — |

---

## 1. 정본·버전 분리와 디자인 동결

### 문제가 무엇이었나
- 예전 폴더(`2.1`)와 새 작업(`2.2`)이 섞이면, “어느 코드가 진짜인지” 헷갈리고 잘못된 경로로 테스트·배포할 위험이 있습니다.
- 화면(디자인) 파일을 실수로 건드리면 사용자 화면이 바뀌어 버리는데, 이번 작업은 **기능·안전 도구**에 집중해야 했습니다.

### 어떻게 고쳤나
- **정본**을 `C:\sswcenter\2.2`로 고정했습니다. 2.1 설정은 “참고·fallback”일 뿐 자동으로 섞어 쓰지 않도록 운영했습니다.
- **디자인 동결(잠금):** `frontend/src`, `frontend/public`, `frontend/index.html` 아래 추적 파일 **129개**는 이번 작업에서 바꾸지 않았습니다. 집계 해시 `98c93aac…60dc`로 “화면 파일이 그대로인지” 확인합니다.

### 무엇으로 확인했나
- `verify-workspace-seal.ps1`(작업 공간 봉인 검사기)이 frozen(동결) 범위 diff 0, untracked 0, aggregate match를 보고했습니다.

### 상태
**CLOSED** — 정본 분리·디자인 무변경은 관측으로 확인.

### 사용자 다음 행동
없음(디자인/정본 관련).

---

## 2. DB 안전 (데이터베이스 연결 보호)

### 문제가 무엇이었나
- 주소 줄(query)로 **host/database를 마음대로 바꿀 수 있으면**, 실수로 운영 DB에 붙거나 다른 DB를 망가뜨릴 수 있습니다(C1 계열 위험).
- 테스트용 “정리/삭제” 명령이 운영·루프백(자기 PC)·유지보수 DB에 들어가면 데이터가 사라질 수 있습니다.

### 어떻게 고쳤나
- 연결 전에 **공용 preflight(사전 점검)** 으로 허용된 연결만 통과시킵니다.
- production(운영), loopback, maintenance(유지보수) DB 보호 규칙을 코드·설정 계약으로 묶었습니다.

### 무엇으로 확인했나
- 백엔드 설정·계약 테스트 및 권위 보고서의 관련 CLOSED 항목(환경/설정 검증 이력).

### 상태
**CLOSED** — 우회·오삭제 경로는 fail-closed(막히면 중단)로 처리.

### 사용자 다음 행동
운영 DB 작업을 할 때는 여전히 **의도한 연결인지 사람 확인**이 필요합니다.

---

## 3. 0014 마이그레이션·복구 (DB 구조 맞추기)

### 문제가 무엇이었나
- **LegacyStaged21** 같은 “옛 스테이징 가정” 모드는, 작업 중이거나 스테이징된 파일이 있을 때 잘못된 기준으로 복구를 시도할 수 있어 **구조가 어긋난 DB**를 만들 위험이 있었습니다.
- FK(외래키, 표 사이 연결 규칙)의 ON UPDATE/MATCH/DEFERRABLE/VALID 같은 세부가 어긋나면 데이터 무결성이 깨집니다.

### 어떻게 고쳤나
- **CleanHead-only:** 깨끗한 HEAD(기준 커밋)에서만 성공 경로를 허용.
- dirty(수정 중)·staged(커밋 대기)·untracked(추적 안 된 파일)면 **거부**.
- restore schema(복구 구조)를 **exact 계약**으로 맞춤.
- FK 세부 옵션까지 검사하도록 강화.

### 무엇으로 확인했나
- 0014 관련 계약·하네스(자동 검증 틀). dirty 작업트리에서는 CleanHead 성공 검증이 불가함은 **HARNESS-001**로 운영 제한으로 명시.

### 상태
**CLOSED** (코드·계약). dirty 작업 중 live CleanHead 검증은 **의도된 제한(HARNESS-001)**.

### 사용자 다음 행동
0014 live 성공 검증이 필요하면 **깨끗한 작업 트리**에서 별도 실행.

---

## 4. 테스트 프로필 (시험 묶음 이름)

### 문제가 무엇이었나
- `supported` / `historical` / `PostgreSQL` / `smoke` / `full` 같은 이름이 실제 실행 범위와 다르면, “전부 통과”로 오해할 수 있습니다.

### 어떻게 고쳤나
- 이름과 **실제 돌리는 범위**를 문서·스크립트에서 맞춤.
- live PostgreSQL·historical 전체는 외부 전제(서버·과거 데이터)가 필요하면 이번 프로필에 억지로 넣지 않음(**PYTEST-001**).

### 무엇으로 확인했나
- 권위 절 지원 프로필(Ruff/mypy/pytest/Vitest/build/Playwright smoke 등)과 한계 표기.

### 상태
**CLOSED** (명명·범위 정합). live PG/historical full은 **의도된 제외(OPEN 제한)**.

### 사용자 다음 행동
전체 과거 프로필이 필요하면 별도 환경 준비 후 요청.

---

## 5. DeepSeek Writer/Runner 보안 (자동 수정 로봇의 안전장치)

### 문제가 무엇이었나
- AI가 **읽기 전용 파일까지 쓰거나**, 바로가기(junction/reparse)로 **저장소 밖**을 건드릴 수 있으면 치명적입니다.
- 출력이 잘린 채로 도구를 실행하면 **반쪽 수정**이 들어갈 수 있습니다.
- 읽기 전용 검수인데 “편집이 없다”고 강제 중단하면, 정상적인 다파일 읽기 검수가 실패합니다.
- 검수 설명 문장에 있는 `secret:` 같은 단어 때문에 **비밀이 아닌데도 체크포인트(중간 저장)가 거부**될 수 있었습니다.

### 어떻게 고쳤나
- **ReadPath(읽기 전용)** / **WritePath(쓰기 허용)** 분리.
- reparse/junction 탈출 차단, untracked 해시, 패치 왕복, 한국어 새 파일 라우팅.
- 출력 예산·packet 분할·forced-write·무편집 완료 거부.
- `finish_reason=length` + 도구 호출이면 **배치 전체 원자 거부**(ENV-RUNNER-015).
- 체크포인트 실패 시 PASS로 포장 금지(demotion).
- redaction(비밀 가림): 실제 토큰/키는 가리고, `[REDACTED]` 같은 **안전 마커·설명 문장**은 허용(ENV-RUNNER-036).
- **ReadOnly**에서는 편집 deadline 미적용(ENV-RUNNER-037).

### 무엇으로 확인했나
- Runner 계약 **481/481**, redaction **11/11**, DeepSeek 독립 ReadOnly envelope PASS.

### 상태
**CLOSED** (Runner/보안 계약). 한 번에 한 파일만 쓰는 제한(**RUNNER-013**)은 **의도된 운영 제한**.

### 사용자 다음 행동
없음(도구 쪽). Writer에 큰 작업을 맡길 때는 패킷을 나누는 것이 안전합니다.

---

## 6. 비밀·환경·도구 경로

### 문제가 무엇이었나
- 약한 비밀·고정 경로·잘못된 venv(가상환경)면 로그인·실행이 깨지거나 다른 PC에서 재현이 안 됩니다.
- Grok이 `GROK_HOME`/`HOME` 없이 뜨면 내부 정리 경고가 납니다.
- 환경 문제를 기록할 때 비밀이 로그에 새면 안 됩니다.

### 어떻게 고쳤나
- production secret 강도·CSPRNG(안전한 난수)·재사용 규칙.
- portable resolver(실행 파일 찾기 순서: 명시 → 저장소 설정 → PATH → 승인 경로).
- **ENV-GROK-HOME-001**(skill wrapper): GROK_HOME/HOME **있음/없음**을 구분해 자식 프로세스에만 잠깐 넣고 **부모 환경을 원복** → wrapper 경로 **CLOSED**.
- 호스트(실행 앱) ambient env에 GROK_HOME/HOME이 없는 경우는 **제품 밖·외부 UNKNOWN**으로 분리(wrapper CLOSED와 혼동하지 않음).
- 환경 이슈는 redaction(비밀 가림) 후 JSONL에만 기록(실제 비밀값 없음).

### 무엇으로 확인했나
- ai-tools **61/61**, redaction **11/11**, AUTH/PYTHON/TOOLCHAIN 항목 CLOSED. ENV-GROK-HOME-001 wrapper 계약.

### 상태
**대부분 CLOSED**. **ENV-GROK-HOME-001** wrapper=CLOSED / 호스트 ambient=외부 UNKNOWN. **ENV-SKILL-001** 재등장 원인 **UNKNOWN**. **ENV-HOST-001**(Grok resident session `DeadFailed` 경고)는 호스트/세션 쪽 **OPEN**(제품 코드 결함으로 단정하지 않음).

### 사용자 다음 행동
집/사무실 PC에서 도구 경로가 다르면 승인 경로 설정을 맞춰 주세요. 호스트 ambient에 HOME/GROK_HOME을 두고 싶으면 실행 앱 쪽 설정(제품 밖).

---

## 7. Opus/Claude 최종 검수 래퍼 (안전한 검수 실행기)

### 문제가 무엇이었나
- Claude가 검수 중 **사용자 PC의 Claude 설정·플러그인 장터**를 몰래 갱신하면, “저장소는 안 건드렸어도” 개인 환경이 바뀝니다.
- 상대 경로 `.\invoke-opus.ps1` 실행이 **아무 일도 안 하고 성공(0)** 으로 끝나면 검수를 안 한 줄 알 수 있습니다.

### 어떻게 고쳤나
- 실행마다 **격리 프로필**(임시 설정 방): 설정/보안 저장 경로를 임시 폴더로, ACL(접근 권한)·reparse 거부·nested 정리.
- 원본 자격 파일만 비밀 안전하게 복사해 **재로그인 없이 시도**(유효할 때만).
- updater/marketplace 자동 설치 차단, `FORCE_WINDOWS_CREDMAN=0`.
- 검수 전후 사용자 `.claude` 상태 2회 봉인 비교.
- stdout/stderr redaction, JWT 가림.
- entrypoint는 **진짜 dot-source일 때만** 본문 생략(ENV-OPUS-001).

### 무엇으로 확인했나
- Opus 계약 **259/259**, 자식 프로세스 상대/절대 호출 계약, DeepSeek·**Opus 기술 최종 검수 PASS**(Critical/Major 0).

### 상태
**코드·래퍼 CLOSED**. 사용자 로그인 완료 후 Opus 기술 최종 검수도 **PASS**. 보고서 본문에 대한 Opus 추가 검수는 **이번 사용자 지시로 생략**.

### 사용자 다음 행동
§8·맺음말 참고(로그인 재실행 아님).

---

## 8. OAuth (Claude 로그인 토큰) — ENV-CLAUDE-001

### 문제가 무엇이었나 (역사)
- 한때 **access token(접속 티켓)이 만료**되고, **refresh token(갱신 티켓)이 서버에서 폐기/철회**되어 `invalid_grant`가 났습니다.
- 그건 코드 버그로 “되살릴” 수 없었고, 로컬 파일만 복사해도 **서버가 거부**했습니다. 그 구간은 역사적으로 **OPEN** 원인이었습니다.

### 어떻게 고쳤나 / 무엇이 달라졌나
- 격리 래퍼·fail-closed(실패 시 안전 중단)·문서 교정은 유지.
- **사용자가 Claude 1회 로그인을 이미 완료**했고, 그 뒤 **Opus 기술 최종 검수 PASS**.
- Windows CredMan(자격 증명 금고) **비밀 값 전체 byte-seal**은 여전히 불가 → **UNKNOWN**으로 **별도** 유지(인증값은 기록하지 않음).

### 무엇으로 확인했나
- 사용자 로그인 완료 전제 + Opus 기술 최종 검수 PASS(Critical/Major 0).
- 명시: **사용자 로그인 완료, Opus 기술 최종 검수 PASS. 이번에는 사용자의 지시에 따라 보고서 자체에 대한 Opus 추가 검수는 생략함.**

### 상태
**CLOSED(기술 경로) — ENV-CLAUDE-001**.
CredMan secret byte-seal은 **UNKNOWN**(별항).

### 사용자 다음 행동
**로그인 재실행이 아닙니다.** 보고서를 읽고 준비되면 **`끝!`** 을 선언하세요. **Git commit/push는 아직 하지 않았습니다.**

---

## 9. Workspace observer (작업 공간 감시자)

### 문제가 무엇이었나
- 일반 `git status`는 내부 index를 살짝 갱신할 수 있어 “읽기만 했다” 증명이 약해집니다.
- status 개수를 예전 방식(23)으로 적어두면, 번들·보고서가 늘어난 뒤 **숫자가 안 맞아** 문서 신뢰가 깨집니다.

### 어떻게 고쳤나
- 모든 관찰에 `--no-optional-locks` + `GIT_OPTIONAL_LOCKS=0`.
- 시작/끝 seal(HEAD, tracked/untracked, design, index 등) 비교.
- 개수는 **`--untracked-files=all` 파일 확장 카운트**로 통일.

### 무엇으로 확인했나
- seal 계약 120/120, 최종 observer PASS.

### 상태
**CLOSED** (현재 관찰). **ENV-TOOLING-008**: 최초 느슨한 status **이전** 구간은 **UNKNOWN**(역사적 한계).

### 사용자 다음 행동
없음.

---

## 10. 보고서·운영 품질

### 문제가 무엇이었나
- 같은 문서에 404/460/466/481이 섞이거나 이슈 ID가 중복되면 “지금 숫자가 뭔지” 모호합니다.
- 검수 중 잠깐 쓰던 복사본(번들)이 남으면 “아직 필요한 파일”처럼 보이거나 Git 개수가 부풀어 오릅니다.

### 어떻게 고쳤나
- 권위 절 **현재 수치 하나** 원칙, 과거 수치는 “당시/이력”.
- ENV-RUNNER-015 이력 계속 절 명시, ENV-RUNNER-036은 redaction 전용.
- 당시 검수 재현을 위해 `review/.deepseek-opus-review`, `review/.deepseek-runner-review`에 **직접 의존 파일 byte-copy**를 두었고, 검수가 끝난 뒤 **임시 번들은 최종 검수 후 제거됨**(원본 skill 경로는 미변경).
- `C:\WINDOWS\TEMP`의 이번 세션 `sswcenter-*.txt` 프롬프트도 확인·정리 대상이었으나, 정리 시점에는 해당 이름 파일이 **0개**였습니다.

### 무엇으로 확인했나
- 문서 정합 수정 + (역사) 번들 검수 당시 SHA 기록 + 번들 삭제 후 observer 재실행.
- 삭제 후 경로 부재 확인. 최종 산출은 **코드 변경·두 보고서·환경 JSONL**만 남음.

### 상태
**CLOSED** (문서 정합·임시 아티팩트 정리). 임시 번들 제거 후 status_count는 **최종 observer** 따름(추정 금지).

### 사용자 다음 행동
보고서를 읽고 준비되면 **`끝!`** 선언. **지금은 commit/push가 끝난 상태가 아닙니다.**

---

## CLOSED 이슈 (해결·봉인)

아래는 **코드/계약/운영 규칙으로 닫힌 것**입니다. (의도된 제한·OPEN·UNKNOWN은 다음 절)

### A. 정본·디자인·관찰
| 주제 | 쉬운 설명 | 상태 |
|------|-----------|------|
| 2.2 정본 분리 | 2.1과 섞지 않음 | CLOSED |
| 디자인 동결 129 | 화면 파일 무변경, 해시 일치 | CLOSED |
| Observer 엄격 읽기 | optional lock 금지, 시작/끝 seal | CLOSED |
| status 개수 정합 | 파일 확장 카운트로 권위 절 고정 | CLOSED |

### B. DB·0014·테스트 이름
| 주제 | 쉬운 설명 | 상태 |
|------|-----------|------|
| DB URL 우회 차단 | 잘못된 DB 연결 거부 | CLOSED |
| 0014 CleanHead/FK exact | 위험한 복구 모드 제거·강화 | CLOSED |
| 프로필 명칭=실행 범위 | 오해 소지 정리 | CLOSED |

### C. Runner/Writer (요약 — 상세 ID는 전수표)
| 주제 | 쉬운 설명 | 상태 |
|------|-----------|------|
| 경로·도구·예산·length 원자 거부 | 반쪽 수정·탈출 경로 차단 | CLOSED |
| redaction·checkpoint demotion | 비밀 가림, 실패를 PASS로 안 속임 | CLOSED |
| ReadOnly deadline 분리 | 읽기 검수가 편집 없음으로 죽지 않음 | CLOSED |

### D. 환경·도구·Opus 래퍼
| 주제 | 쉬운 설명 | 상태 |
|------|-----------|------|
| PYTHON/AUTH/TOOLCHAIN | venv·자격 경로·도구 찾기 | CLOSED |
| ENV-GROK-HOME-001 (wrapper) | 자식만 잠깐 설정 후 부모 원복 | CLOSED |
| ENV-CLAUDE-001 (기술 경로) | 로그인 완료 + Opus 기술 최종 PASS; 보고서 Opus 추가 검수 생략 | CLOSED |
| Opus 격리·entrypoint | 사용자 홈 오염 방지, 상대경로 no-op 수정 | CLOSED |

---

## OPEN (아직 끝나지 않음 — 의도된 제한·호스트/운영)

| ID | 무엇이 남았나 | 사용자/운영 행동 |
|----|----------------|------------------|
| **RUNNER-013** | 한 턴에 파일 하나 쓰기(의도된 안전) | 큰 작업은 나눠 요청 |
| **TOOLING-004** | `$`/백틱/긴 글은 PromptFile 필요 | 긴 지시 시 파일로 전달 |
| **TOOLING-001 / THREAD-001** | 세션 끊김·핸들러 부재는 제품 밖 | 전달 여부 확인 후 중복 방 금지 |
| **HARNESS-001** | dirty 중 CleanHead 0014 live 불가 | clean 트리에서 검증 |
| **PYTEST-001** | live PG/historical full 미포함 | 별도 환경 필요 시 요청 |
| **ENV-HOST-001** | Grok 보고서 세션 종료 시 `Resident session actor exited unexpectedly; reaping as DeadFailed` 경고(호스트/세션) | 제품 버그로 단정하지 않음. 같은 세션 이어가기 시 참고. **로그인 재실행 불필요** |

**사용자 공통 다음 행동:** 보고서를 읽고 준비되면 **`끝!`** 선언. **Git commit/push는 아직 하지 않음.**

---

## UNKNOWN (증명 한계 — 거짓 PASS 아님)

| ID | 의미 |
|----|------|
| **ENV-TOOLING-008** | 최초 일반 git status **이전**의 “완전 무쓰기”는 사후 증명 불가 |
| **CredMan secret byte-seal** | Windows 자격 증명 금고의 비밀 **값** 전체를 바이트 단위로 봉인하지 못함(이름 개수만 관측 가능한 경우 있음). 인증값 미기록. ENV-CLAUDE-001 기술 경로 CLOSED와 **별도** |
| **ENV-GROK-HOME-001 (호스트 ambient)** | 실행 앱(호스트)에 GROK_HOME/HOME이 없을 수 있음. **wrapper CLOSED와 분리**된 외부 한계 |
| **ENV-SKILL-001 재등장 원인** | 삭제했던 스킬 폴더가 다시 생긴 **원인**은 미확정(경로는 다시 비움) |

---

## 이슈 ID 전수 목록 (권위 보고서 추출)

상태 코드: **C**=CLOSED, **O**=OPEN/의도 제한, **U**=UNKNOWN/이력 한계

| ID | 상태 | 한 줄 설명 |
|----|------|------------|
| ENV-RUNNER-001 | C | AllowPath 다중 전달 실패 수정 |
| ENV-RUNNER-002 | C | API 선택 속성 접근 실패 수정 |
| ENV-RUNNER-003 | C | Thinking 후속 HTTP 400 대응 |
| ENV-RUNNER-004 | C | 최종 tool_calls 선택 접근 수정 |
| ENV-RUNNER-005 | C | 4턴 무수정 조기 중단 완화·계약 |
| ENV-RUNNER-006 | C | .env.example 과도 차단 완화 |
| ENV-RUNNER-007 | C | 새 파일 전 read 실패 처리 |
| ENV-RUNNER-008 | C | apply_patch 형식 계약 명확화 |
| ENV-RUNNER-009 | C | Add File `+` 접두 요구 정리 |
| ENV-RUNNER-010 | C | 읽기/쓰기 allowlist 분리 |
| ENV-RUNNER-011 | C | 대형 연속 치환 문맥 재사용 |
| ENV-RUNNER-012 | C | 프롬프트 `$변수` 선확장 방지 |
| ENV-RUNNER-013 | O | 한 파일 한 write 의도 제한 |
| ENV-RUNNER-014 | C | tool 인수 역슬래시 소실 수정 |
| ENV-RUNNER-015 | C | length+tool 원자 거부(이력 404 포함) |
| ENV-RUNNER-016 | C | malformed hunk/stale old-text |
| ENV-RUNNER-017 | C | 최종 read 빈 경로 실패 수정 |
| ENV-RUNNER-018 | C | 하네스 배열·junction 정리 |
| ENV-RUNNER-019 | C | 읽기만 반복 후 빈 응답 방지 |
| ENV-RUNNER-020 | C | Auto 라우팅·malformed 거부 |
| ENV-RUNNER-021 | C | 테스트 패킷 출력 한도 |
| ENV-RUNNER-022 | C | settings 교정 출력 한도 |
| ENV-RUNNER-023 | C | thinking이 편집보다 예산 선점 |
| ENV-RUNNER-024 | C | 저추론 JSON 절단 |
| ENV-RUNNER-025 | C | FK 교정 후 무진행 PARTIAL |
| ENV-RUNNER-026 | C | 잘못된 apply_patch 형식 |
| ENV-RUNNER-027 | C | 0014 개수 연동 OLD_TEXT |
| ENV-RUNNER-028 | C | 대형 자기수정 불완전 PASS |
| ENV-RUNNER-029 | C | 출력예산·forced-write·무편집 완료 |
| ENV-RUNNER-030 | C | 한국어 새 파일 Auto |
| ENV-RUNNER-031 | C | ValidateOnly=실 preflight |
| ENV-RUNNER-032 | C | Bearer/escaped JSON redaction |
| ENV-RUNNER-033 | C | Math.Max 3인수 부팅 실패 |
| ENV-RUNNER-034 | C | 반복 도구 실패 재배정 |
| ENV-RUNNER-035 | C | 계약 중복 실행(비차단 이력) |
| ENV-RUNNER-036 | C | checkpoint redaction 오탐·demotion |
| ENV-RUNNER-037 | C | ReadOnly에 edit-start deadline 오적용 |
| ENV-TOOLING-001 | O | Playwright 인터럽트 전달 한계 |
| ENV-TOOLING-002 | C | here-string 종료 누락 |
| ENV-TOOLING-003 | C | 보간 문자열 콜론 해석 |
| ENV-TOOLING-004 | O | 백틱/긴 프롬프트는 PromptFile |
| ENV-TOOLING-005 | C | 디자인 해시 거짓 불일치 |
| ENV-TOOLING-006 | C | Git 경고 terminating 승격 |
| ENV-TOOLING-007 | C | optional index·이중 seal |
| ENV-TOOLING-008 | U | 최초 느슨한 status 이전 무쓰기 불가 증명 |
| ENV-TOOLING-009 | C | hash manifest parser 오류(비차단) |
| ENV-TOOLCHAIN-001 | C | 고정 경로·portable resolver |
| ENV-TOOLCHAIN-002 | C | RNG.Fill 예시 PS 5.1 불가 |
| ENV-PYTHON-001 | C | 2.2 venv 연결 |
| ENV-AUTH-001 | C | DeepSeek 자격 경로 |
| ENV-CLAUDE-001 | C | 역사 invalid_grant OPEN → 로그인·Opus PASS 후 **CLOSED(기술 경로)**; CredMan byte-seal은 별도 U |
| ENV-OPUS-001 | C | `.\` entrypoint silent no-op |
| ENV-GROK-HOME-001 | C/U | **wrapper CLOSED** / **호스트 ambient UNKNOWN**(짧은 ENV-GROK-HOME 표기 사용 안 함) |
| ENV-HOST-001 | O | Grok resident session `DeadFailed` 경고(호스트/세션, 제품 단정 금지) |
| ENV-E2E-001 | C | 스모크 후보 범위 정리 |
| ENV-HARNESS-001 | O | dirty 중 CleanHead 0014 불가 |
| ENV-PYTEST-001 | O | live PG/historical 전제 |
| ENV-THREAD-001 | O | 방 재지시 handler 부재 |
| ENV-SKILL-001 | U | 스킬 재등장 원인 미상(경로 정리됨) |
| RUNNER-013 | O | = ENV-RUNNER-013 의도 제한 |
| TOOLING-001 | O | 세션 인터럽트 환경 |
| TOOLING-004 | O | PromptFile 필수 |
| THREAD-001 | O | = ENV-THREAD-001 |
| HARNESS-001 | O | = ENV-HARNESS-001 |
| PYTEST-001 | O | = ENV-PYTEST-001 |
| AUTH-001 | C | = ENV-AUTH-001 |

\*ENV-GROK-HOME-001만 사용: skill wrapper 경로 CLOSED, 호스트 ambient는 제품 밖 UNKNOWN.

---

## 최종 observer (Git 마감 후 clean 기준)

사용자 **`끝!`** 선언 → `git-finish.ps1` 수정(ENV-GIT-FINISH-001) → stage/commit/push 완료 후 기준입니다.
과거 status 25·41·42·43 등은 마감 전 WIP 스냅샷이며 **현재 값이 아닙니다.**
**임시 번들·임시 프롬프트는 Git에 포함되지 않습니다.** 최종 코드·두 보고서·비밀 없는 환경 JSONL만 의도 산출로 남습니다.

| 항목 | 값 |
|------|-----|
| 결과 | **PASS (clean)** |
| branch | `main` |
| status_count | **0** |
| staged_count | **0** |
| design frozen_files | **129** |
| design frozen untracked | **0** |
| design frozen diff_clean | **True** |
| design aggregate | `98c93aac800e62d021d7fab27c3c95315739c2e09e612557eb7dea7a5aba60dc` |
| aggregate_match | **True** |
| HEAD / remote SHA | `c50f49dfff3ac4ce5b5307eca1aa765dd26ab3c9` (local = origin/main) |

### ENV-GIT-FINISH-001 (요약)

- **문제:** 한글 문서 경로가 Git quoted 형태로 나와 민감 경로 검사가 경로 파싱 전에 크래시 → 마감 불가(당시 stage 없음).
- **수정:** porcelain `-z` 파싱·status/path 분리·한글/공백/따옴표 계약·fail-closed.
- **상태:** CLOSED.

---

## 맺음말

- **끝난 것:** 안전 장치·검수·문서 정합·디자인 무변경·임시 번들 정리·**Git 마감(`끝!`)**. 사용자 Claude 로그인 완료, Opus 기술 최종 PASS, 보고서 Opus 추가 검수 생략.
- **남는 것:** clean 작업 트리의 최종 코드·보고서·환경 JSONL(비밀 없음).
- **증명 못 하는 것 / 호스트 쪽:** 최초 느슨한 git status 이전 구간, CredMan 비밀값 전체 바이트, ENV-GROK-HOME-001 호스트 ambient, ENV-SKILL-001 재등장 원인, ENV-HOST-001 DeadFailed 경고의 근본 원인(제품 코드 문제로 과장하지 않음).

비밀 토큰·비밀번호·실제 OAuth 값은 이 문서에 **없습니다**.
