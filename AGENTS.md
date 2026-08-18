# SSWCenter 3.0 repository instructions

> 적용 위치: `/home/codexctl/workspace/sswcenter-3-0`

## 지시 우선순위

1. 형님의 최신 명시 지시
2. 이 `AGENTS.md`
3. [`00-먼저읽기-작업환경안내.md`](00-먼저읽기-작업환경안내.md)
4. [`00-오케스트레이션-작업지침.md`](00-오케스트레이션-작업지침.md)
5. [`docs/운영_테스트_검수_등급_정의_v1.1.md`](docs/운영_테스트_검수_등급_정의_v1.1.md)
6. 현재 슬라이스의 승인된 handoff·packet·plan

충돌하면 위 순서를 따르고 임의로 절충하지 않는다.

## 작업 시작 전 필수

- 작업 방식은 `REMOTE`, 실행 OS는 Ubuntu Linux로 고정한다.
- 제품 Git 최상위가 정확히 `/home/codexctl/workspace/sswcenter-3-0`인지 확인한다.
- `00-먼저읽기-작업환경안내.md`와 `00-오케스트레이션-작업지침.md`를 처음부터 끝까지 읽는다.
- 형님은 Codex에게만 자연어로 지시한다. 장소·오퍼레이터·라이터를 조합한 특수 호출문을 요구하지 않는다.
- 매 요청마다 `ACTOR=CODEX|GROK|DEEPSEEK`와 `ACTION=IMPLEMENT|REVIEW|FIX`를 새로 정한다. 이전 요청의 역할은 다음 요청으로 승계하지 않는다.
- 형님이 actor를 지정하면 그대로 따르고, 지정하지 않으면 Codex가 작업 성격과 현재 가용성을 기준으로 선택한다.

## AI 실행 경계

- Codex, Grok, DeepSeek 모두 요청에 따라 구현·검수·수정을 맡을 수 있다.
- Codex가 유일한 사용자 창구이며 provider 호출, 결과 대조, 추가 검증, 최종 보고를 책임진다.
- Grok은 Ubuntu의 공식 Grok CLI와 형님의 월구독 계정 로그인을 사용한다.
- DeepSeek는 Ubuntu의 프로젝트 전용 API 키와 공식 API를 사용한다.
- Grok·DeepSeek는 현재 역할에 필요한 저장소 파일을 직접 읽고, `IMPLEMENT`·`FIX`에서는 수정하고, 프로젝트 명령과 테스트를 실행할 수 있다.
- `REVIEW`는 실행 단위 전체가 read-only다. 같은 AI도 다음 요청에서 다른 역할을 새로 받을 수 있다.
- provider 실행은 `/home/codexctl/.local/bin/ssw-agent`만 사용한다. 이 명령은 프로젝트 밖 사용자 파일과 시스템 쓰기를 차단하고 `.git`을 read-only로 둔다.
- provider credential은 저장소 밖 사용자 전용 경로에만 둔다. 값이나 인증 파일 내용을 읽거나 출력·복사·prompt 삽입·커밋하지 않는다.
- 모든 actor의 실행환경은 저장소의 ignored `backend/.venv`를 공유한다. provider dispatch 전
  `pwsh -NoProfile -File scripts/ensure-runtime.ps1`와
  `pwsh -NoProfile -File scripts/verify-runtime.ps1`를 실행하고,
  `SSWCENTER_RUNTIME_GREEN` 없이는 runtime PASS를 선언하지 않는다. dispatch 환경에는
  `VIRTUAL_ENV=/home/codexctl/workspace/sswcenter-3-0/backend/.venv`와 그 `bin`을 PATH 앞에 둔다.
- 저장소의 과거 provider 실행 자료와 프로젝트 스킬은 현재 실행 경로가 아니다. 실행하거나 현재 정책 근거로 사용하지 않는다.
- Windows의 개인용 AI 도구와 `C:\sswcenter` 복사본은 이 프로젝트의 실행환경·정본·작업본이 아니다.
- 형님을 항상 `형님`이라고 부른다.

## 작업 원칙

- 시작 전에 현재 branch, status, 작업 범위, 완료조건을 확인하고 기존 변경을 보존한다.
- 구현·수정 actor는 실제 diff와 테스트 결과를 남긴다.
- 검수 actor는 파일을 바꾸지 않고 finding, 근거, 미검증 범위를 남긴다.
- provider의 완료 선언보다 현재 바이트, diff, 실행한 테스트를 우선한다.
- 외부 actor로 바꾸거나 역할을 바꿨다는 사실은 숨기지 않고 최종 보고에 남긴다.

## Git 정책

- `status`, `diff`, `log`, `rev-parse` 등 읽기 전용 Git 명령은 사용할 수 있다.
- `pull`, `stage`, `commit`, `cherry-pick`, `push`, `checkout`, `switch`, `reset`, `clean`, `rebase`, `merge`는 형님이 명시한 경우에만 Codex가 수행한다.
- Grok·DeepSeek 실행에서는 `.git`이 read-only이므로 위 Git 변경 작업을 하지 않는다.
- 현재 브랜치와 기존 변경사항을 보존한다. 깨끗한 `main`을 강제하지 않는다.
- worktree 생성·삭제·재설정은 형님이 명시한 경우에만 수행한다.

## 참고 문서

문제가 실제로 발생했을 때만 [`docs/운영_트러블슈팅_v1.0.md`](docs/운영_트러블슈팅_v1.0.md)를 읽는다. 이 문서는 정책 정본이 아니며 현재 Linux 저장소의 실제 증거보다 우선하지 않는다.
