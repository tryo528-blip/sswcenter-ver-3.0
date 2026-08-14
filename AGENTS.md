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
- 본진의 Git 최상위는 `C:\sswcenter\3.0`, 독립방의 Git 최상위는 해당 task/thread에 배정된 worktree인지 확인한다.
- `00-먼저읽기-작업환경안내.md`와 `00-오케스트레이션-작업지침.md`를 처음부터 끝까지 읽는다.
- 외부 provider route를 사용할 때만 `$location-operator-writer <장소>-<오퍼레이터>-<라이터>!` 형식을 사용한다. 누락·모호한 route는 추론하지 않는다.
- 외부 provider 호출은 설치된 `secure-ai-workbench` 스킬의 검증 진입점만 사용한다. legacy `warpper`, `deepseek_runner`, provider CLI, 직접 controller 호출은 사용하지 않는다.
- 외부 provider로 보낼 정확한 텍스트와 목적을 형님께 먼저 설명하고 명시 승인을 받는다.
- provider에는 repository path·URL·header·credential·shell·tool·attachment를 전달하지 않는다.

## 고정 경계

- 오퍼레이터는 `Codex` 또는 `Claude Code`, 라이터는 필요할 때 `Grok` 또는 `DeepSeek`다.
- `OPERATOR=CODEX`이면 Codex가 자기 worktree에서 테스트·검수를 직접 수행한다. 본진과 독립방에서 자식 Codex나 Codex CLI를 재호출하지 않는다.
- `OPERATOR=CLAUDE_CODE`이면 Claude는 명시된 한 슬라이스의 read-only 검수자일 뿐이며 구현·Writer 호출·파일 수정·최종 acceptance를 하지 않는다.
- provider는 저장소를 직접 읽거나 쓰지 않는다. Codex가 반환 텍스트를 current byte와 대조하고 형님 승인 후에만 실제 파일을 수정한다.
- provider credential은 설치된 `Set-AiWorkbenchKey.ps1 -Provider <provider>`의 대화형 설정만 사용한다. credential 내용을 읽거나 출력·복사·커밋하지 않는다.
- 활성 설정에서 `C:\sswcenter\2.2`가 발견되면 `CONFIG_DRIFT`로 중단한다. 3.0 내부 과거 report의 2.2 문자열은 역사 기록으로만 취급한다.
- `REMOVE` 및 형님이 제외한 외부 저장소를 근거로 사용하지 않는다.
- 형님을 항상 `형님`이라고 부른다.

prompt와 하네스 작성 지시는 [`00-오케스트레이션-작업지침.md`](00-오케스트레이션-작업지침.md)의 원칙을 따른다.

## Git 정책

- 상태 확인용 `status`, `diff`, `log`, `rev-parse`는 사용할 수 있다.
- `pull`, `stage`, `commit`, `cherry-pick`, `push`, `checkout`, `reset`, `clean`, rebase는 형님이 명시한 경우에만 수행한다.
- 실행 전 대상 저장소·브랜치·변경사항·원격 상태를 확인하고 요청 범위만 수행한다.
- 현재 브랜치와 기존 변경사항을 보존한다. 깨끗한 `main`을 강제하지 않는다.
- worktree 생성은 승인된 독립 작업방을 준비할 때만 허용하며 기존 worktree를 삭제·재설정하지 않는다.

## 참고 문서

문제가 실제로 발생했을 때만 [`docs/운영_트러블슈팅_v1.0.md`](docs/운영_트러블슈팅_v1.0.md)를 읽는다. 이 문서는 정책 정본이 아니며 현재 3.0의 실제 증거보다 우선하지 않는다.
