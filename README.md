# SSWCenter v3.0-alpha

## 업무 시작 전 필수 절차

모든 작업자는 다음 순서를 지킨다.

1. 루트 [`00-먼저읽기-작업환경안내.md`](00-먼저읽기-작업환경안내.md)를 처음부터 끝까지 읽는다.
2. Linux Git 최상위가 `/home/codexctl/workspace/sswcenter-3-0`인지 확인한다.
3. branch와 status를 확인하고 기존 변경을 보존한다.
4. AI 작업이면 [`00-오케스트레이션-작업지침.md`](00-오케스트레이션-작업지침.md)를 읽고 현재 요청의 actor와 action을 정한다.
5. 활성 작업 packet이 지정한 정본의 최하위 절·anchor와 matrix ID만 읽는다.
6. 소유권이나 범위가 불명확할 때만 [정본 문서 목록](docs/00_정본_문서_목록.md)을 확인한다.

원격 비교가 필요하면 먼저 상태와 upstream을 확인한다. `pull`, checkout, reset, clean, commit, push 등 Git 변경은 형님이 명시한 경우에만 수행한다. 로컬 변경이나 충돌을 임의로 폐기·덮어쓰기·병합하지 않는다.

## Linux 실행환경

- 현재 개발환경은 Ubuntu Linux 원격 전용이다.
- 모든 Markdown·Python·설정 파일은 UTF-8을 사용한다.
- Grok·DeepSeek 프로젝트 작업은 `/home/codexctl/.local/bin/ssw-agent`만 사용한다.
- 준비 상태는 `ssw-agent status`, 격리 경계는 `ssw-agent self-test`로 확인한다.
- Windows 도구와 Windows 저장소 복사본은 이 프로젝트 실행환경이 아니다.

W0 기반시설 검증은 Linux 저장소 루트에서 다음 두 명령으로 실행한다.

```bash
pwsh -NoProfile -File scripts/test.ps1 -FoundationOnly
pwsh -NoProfile -File scripts/test-w0-postgres-linux.ps1
```

정확한 버전·설치 경로·사용자 영역 경계는 [작업환경 안내](00-먼저읽기-작업환경안내.md)를 따른다.

## 운영 비밀값

`.env.example`의 모든 값은 의도적으로 유효하지 않은 placeholder다. 운영 환경에서 그대로 사용하면 시작이 거부되어야 한다. 실제 비밀값은 저장소 밖에서 운영자가 독립적으로 생성한다.

- PIN pepper, PIN lookup, CSRF signing, transition token은 서로 다른 값이며 원시 문자열 기준 최소 32자 이상이어야 한다.
- `SSWCENTER_RESIDENT_NUMBER_KEY_V1`과 `SSWCENTER_RESIDENT_NUMBER_LOOKUP_KEY`는 각각 독립적인 32바이트 난수를 표준 RFC 4648 base64로 인코딩한 값이어야 하며 디코딩된 바이트열이 달라야 한다.
- 운영 DB 비밀번호는 높은 다양성을 갖추고 최소 16자 이상이어야 하며 애플리케이션 비밀값과 재사용하지 않는다.
- 애플리케이션 검증은 생성 출처까지 증명하지 못하므로 운영자는 CSPRNG 기반 도구를 사용한다.

개념용 Linux 생성 예시:

```bash
openssl rand -hex 32
openssl rand -base64 32
```

생성한 실제 값은 터미널 기록, prompt, Git, 보고서에 남기지 않는다.

## AI 운영 정본

- [작업환경 안내](00-먼저읽기-작업환경안내.md): Linux 경로·인증·sandbox·Git 경계
- [오케스트레이션 지침](00-오케스트레이션-작업지침.md): Codex 단일 창구와 요청별 actor/action
- [프로젝트 에이전트 실행계약](docs/AI_프로젝트_에이전트_실행계약_v1.0.md): Grok 월구독 CLI·DeepSeek API·실행 결과

형님의 최신 명시 지시가 최우선이다. 활성 작업 packet은 해당 작업의 범위·기준 SHA·쓰기 경로를 소유하지만 위 AI 운영 경계를 임의로 바꾸지 않는다.
