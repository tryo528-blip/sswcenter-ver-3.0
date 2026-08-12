# SSWCenter 3.0 repository instructions

> 적용 위치: `C:\sswcenter\3.0`

## 지시 우선순위

1. 형님의 최신 명시 지시
2. 이 `AGENTS.md`
3. [`00-먼저읽기-작업환경안내.md`](00-먼저읽기-작업환경안내.md)
4. [`00-오케스트레이션-작업지침.md`](00-오케스트레이션-작업지침.md)
5. [`docs/운영_오퍼레이터_등급_정의_v1.0.md`](docs/운영_오퍼레이터_등급_정의_v1.0.md)
6. 현재 슬라이스의 승인된 handoff·packet·plan

충돌하면 위 순서를 따르고 임의로 절충하지 않는다.

## 작업 시작 전 필수

- 현재 장소를 `HOME` 또는 `OFFICE`로 확정한다.
- Git 최상위가 정확히 `C:\sswcenter\3.0`인지 확인한다.
- 위 작업환경 안내와 오케스트레이션 지침을 처음부터 끝까지 읽는다.
- Codex에서는 `$location-operator-writer <장소>-<오퍼레이터>-<라이터>!` 형식 또는 `!`까지 붙인 라우트만 적은 `<장소>-<오퍼레이터>-<라이터>!` 형식의 스킬 호출을 실행 어댑터로 사용한다. 예: `사무실-코덱스-그록!` 또는 `집-클로드-딥시크!`.
- 장소 2개·오퍼레이터 2개·라이터 2개의 8개 조합을 모두 허용한다. 유효한 라우트라도 선택한 환경의 실제 경로·인증이 없으면 실행 단계에서만 `BLOCKED` 또는 `CONFIG_DRIFT`로 보고한다.
- 호출명의 세 토큰이 장소·오퍼레이터·라이터를 확정하며, 누락·모호한 호출은 추론하지 않고 중단한다.
- 라우트만 입력되면 현재 대화의 활성 조합으로 선택을 확인하고, 작업 내용이 오면 그 조합으로 실행한다.
- `C:\sswcenter\3.0\warpper\wrapper-config.json`의 `repositoryRoot`가 `C:\sswcenter\3.0`인지 확인한다.
- 래퍼 호출에는 `C:\sswcenter\3.0` 또는 선택한 room worktree의 정확한 Git 최상위를 명시한다.
- DeepSeek는 `C:\sswcenter\3.0\deepseek_runner\invoke-deepseek-writer.ps1`만 사용한다.

## 고정 경계

- 오퍼레이터는 `Codex` 또는 `Claude Code`, 라이터는 `Grok` 또는 `DeepSeek`다.
- 라이터는 승인된 쓰기 경로만 수정한다. 검수자는 read-only다.
- DeepSeek Writer는 JSON Task Packet과 명시적 읽기·쓰기 허용 목록을 사용한다.
- Codex 오퍼레이터의 독립 작업방은 서로 다른 task/thread와 Git worktree를 사용한다.
- API 키는 `C:\sswcenter\api-keys.local.env`에서만 읽는다. 다른 위치를 탐색하거나 프로세스 환경변수로 대체하지 않는다.
- 키와 인증 홈의 내용은 출력·복사·프롬프트 삽입·커밋하지 않는다.
- 활성 설정에서 `C:\sswcenter\2.2`가 발견되면 `CONFIG_DRIFT`로 중단한다. 3.0 내부의 과거 handoff/report에 남은 2.2 문자열은 역사 기록으로만 취급하고 해당 경로를 따라가지 않는다.
- WorkCadence, `REMOVE` 및 형님이 제외한 외부 저장소를 작업 근거로 사용하지 않는다.
- 형님을 항상 `형님`이라고 부른다.

## Git 정책

- 상태 확인용 `status`, `diff`, `log`, `rev-parse`는 사용할 수 있다.
- `pull`, `stage`, `commit`, `cherry-pick`, `push`, `checkout`, `reset`, `clean`, rebase를 자동 실행하지 않는다.
- 형님이 Git 작업을 명시적으로 요청한 경우에만 대상 브랜치·커밋·diff를 먼저 확인하고 요청 범위만 실행한다.
- 현재 브랜치와 기존 변경사항을 보존한다. 깨끗한 `main`을 작업 시작 조건으로 강제하지 않는다.
- worktree 생성은 승인된 독립 작업방을 준비할 때만 허용하며, 기존 worktree의 삭제·재설정·정리는 별도 명시 없이는 수행하지 않는다.

## 참고 문서

문제가 실제로 발생했을 때만 [`docs/운영_트러블슈팅_v1.0.md`](docs/운영_트러블슈팅_v1.0.md)를 읽는다. 이 문서는 정책 정본이 아니며 현재 3.0의 실제 증거보다 우선하지 않는다.
