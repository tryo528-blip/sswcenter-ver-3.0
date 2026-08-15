# AI 프로젝트 에이전트 실행계약 v1.0

> 지위: Grok·DeepSeek Linux 실행, 인증, sandbox, 결과·exit 형식의 정본
> 적용 기준: 2026-08-15

## 1. 고정 진입점

```text
PROJECT_ROOT=/home/codexctl/workspace/sswcenter-3-0
ENTRYPOINT=/home/codexctl/.local/bin/ssw-agent
```

Codex는 Grok·DeepSeek 프로젝트 작업에 `ssw-agent`만 사용한다. 형님은 이 명령을 직접 조합할 필요가 없다.

```text
ssw-agent run <grok|deepseek> <implement|review|fix>
```

작업 prompt는 기본적으로 UTF-8 stdin으로 전달한다. 한 실행은 한 actor와 한 action만 가지며 다음 실행으로 역할이나 memory를 자동 승계하지 않는다.

## 2. 인증

| provider | 방식 | 설정 명령 | 저장 위치 |
|---|---|---|---|
| Grok | 형님의 월구독 계정 device authentication | `ssw-agent auth grok` | `/home/codexctl/.grok/` |
| DeepSeek | 프로젝트 전용 API 키 | `ssw-agent auth deepseek` | `/home/codexctl/.config/sswcenter-agent/deepseek_api_key` |

- Grok에 xAI API 키를 요구하지 않는다.
- DeepSeek 키 파일과 상위 디렉터리는 각각 mode `0600`, `0700`이어야 한다.
- status는 인증 파일의 존재와 권한만 확인한다. credential 본문은 읽거나 출력하지 않는다.
- DeepSeek API key는 API 요청을 만드는 상위 runner에서만 읽고 project command 환경에는 전달하지 않는다.
- provider별 인증이 없으면 해당 실행은 `*_AUTH_REQUIRED`로 실패한다. 다른 provider로 몰래 대체하지 않는다.

## 3. Grok 실행

- 공식 Linux Grok CLI를 형님의 월구독 로그인으로 사용한다.
- 현재 설치 release는 `grok 1.0.4 (d846eb93d9)`, binary SHA-256은 `79f49625f153923db491a5c290e9b04c3444da488b6b9d6aac533ccb5bff2455`로 pin한다. 자동 update는 끈다.
- CLI는 고정 repository root에서 headless fresh session으로 실행한다.
- `IMPLEMENT`·`FIX`: custom profile `sswcenter_work`를 사용한다.
- `REVIEW`: custom profile `sswcenter_review`를 사용한다.
- project의 `.grok/config.toml`과 `.grok/sandbox.toml`은 runner에 pin된 SHA-256과 일치해야 한다. 실행 전후 다르면 `GROK_POLICY_DRIFT`로 실패한다.
- runner가 먼저 별도 `bubblewrap` mount namespace로 다른 사용자 파일과 host provider 정책을 숨긴다. host 파일은 수정하지 않는다.
- 그 안에서 custom profile을 다시 적용하며 Linux kernel sandbox 적용에 실패하면 실행을 거부한다.
- Grok session memory는 작업마다 끄고, permission prompt는 sandbox 안에서 자동 승인한다.
- project 밖 시스템은 read-only이고 다른 사용자 파일은 읽을 수 없다. `.git`은 read-only다.

## 4. DeepSeek 실행

- 공식 endpoint `https://api.deepseek.com/chat/completions`를 사용한다.
- 기본 모델은 `deepseek-v4-pro`, 빠른 대안은 `deepseek-v4-flash`다.
- thinking mode와 tool calls를 사용하고 tool-call assistant message의 `reasoning_content`를 다음 API 요청에 보존한다.
- provider에 제공하는 도구는 project-relative file read/list/search, sandbox command이며 `IMPLEMENT`·`FIX`에만 write/replace/mkdir/delete를 추가한다.
- path는 실제 경로로 해석한 뒤 고정 root 내부인지 재검사한다. symlink나 `..`로 root를 벗어나면 거부한다.
- `.git` 쓰기와 project root 자체 삭제를 거부한다. 디렉터리 삭제는 빈 디렉터리 한 개만 허용한다.
- command는 문자열 shell이 아니라 argv 배열로 받고 `bubblewrap` 안에서 실행한다. 명령이 명시적으로 shell을 실행하더라도 같은 OS 경계를 벗어나지 못한다.

## 5. Sandbox 경계

| 항목 | `IMPLEMENT`·`FIX` | `REVIEW` |
|---|---|---|
| project root | read-write | read-only |
| `.git` | read-only | read-only |
| `/usr`, `/bin`, `/lib`, `/etc` 등 시스템 | read-only | read-only |
| 다른 사용자 홈·Windows `/mnt/*` | mount하지 않음 | mount하지 않음 |
| provider credential | child command에서 보이지 않음 | child command에서 보이지 않음 |
| `/tmp` | 실행별 임시 영역 | 실행별 임시 영역 |
| network | provider API와 개발 명령에 허용 | provider API와 read-only 명령에 허용 |

DeepSeek command sandbox는 user·PID·IPC·UTS·cgroup namespace를 분리하고 nested user namespace를 막는다. Grok은 outer `bubblewrap`과 공식 CLI의 strict 기반 custom profile을 겹쳐 동일한 project-only 목적을 집행한다.

## 6. 로컬 검증

```bash
ssw-agent status
ssw-agent self-test
```

`self-test`의 필수 check는 다음과 같다.

```text
grok_binary_pinned=true
worktree_write_allowed=true
git_write_blocked=true
system_write_blocked=true
credential_read_blocked=true
review_write_blocked=true
grok_worktree_write_allowed=true
grok_git_write_blocked=true
grok_review_write_blocked=true
grok_system_write_blocked=true
host_provider_policy_hidden=true
grok_deepseek_key_read_blocked=true
path_escape_blocked=true
git_path_guard=true
review_write_tools_absent=true
deepseek_file_tool_write_allowed=true
empty_file_read_supported=true
git_internals_not_enumerated=true
```

하나라도 false면 provider 구현·수정 실행을 시작하지 않는다.

## 7. 결과 schema와 exit

성공과 실패 모두 stdout에 JSON 객체 하나를 반환한다.

```text
schema_version: "1.0"
provider: grok | deepseek | local
action: implement | review | fix | none
status: succeeded | failed
output: string
error_code: string | null
model: string | null
duration_ms: integer | null
```

| exit | 의미 |
|---:|---|
| `0` | 실행 성공 또는 local status/self-test PASS |
| `2` | prompt·인자·고정 root·로컬 요청 오류 |
| `3` | 설치 또는 인증 미준비 |
| `4` | provider·transport·timeout·result 오류 |
| `5` | sandbox 또는 pinned policy 오류 |
| `130` | 사용자 중단 |

nonzero exit를 성공이나 부분 성공으로 낮추지 않는다. output에 credential, raw authorization header, 인증 파일 본문을 포함하지 않는다.

## 8. Git과 최종 판정

- provider는 working tree 파일을 구현·수정할 수 있지만 Git metadata는 수정할 수 없다.
- commit·push·pull·checkout·reset·clean·merge·rebase는 형님이 명시한 경우에만 Codex가 별도로 수행한다.
- provider result는 advisory 실행 결과다. Codex가 실제 status·diff·테스트와 현재 바이트를 확인한 뒤 최종 보고한다.
