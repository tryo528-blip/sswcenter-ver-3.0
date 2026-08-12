---
name: location-operator-writer
description: "`사무실-코덱스-그록!`처럼 장소·오퍼레이터·라이터를 지정한 SSWCenter 3.0 라우트를 해석하고, 정본 문서의 역할·작업방·호출 경계를 집행한다."
---

# 장소·오퍼레이터·라이터 라우팅

## 1. 정본을 먼저 읽는다

다음 문서를 이 순서로 읽고 내용을 복사하거나 재정의하지 않는다.

1. `C:\sswcenter\3.0\00-먼저읽기-작업환경안내.md`: 장소·경로·인증·Git 경계
2. `C:\sswcenter\3.0\00-오케스트레이션-작업지침.md`: 역할·호출 경계·독립방·모델 배정·프롬프트·보고
3. `C:\sswcenter\3.0\docs\운영_오퍼레이터_등급_정의_v1.0.md`: 테스트·검수 등급의 의미

실제 wrapper·runner 명령은 [runtime-contracts.md](references/runtime-contracts.md), 등급 문서 검색은 [operator-doc-discovery.md](references/operator-doc-discovery.md)를 따른다.

## 2. 라우트를 해석한다

호출 형식:

```text
<장소>-<오퍼레이터>-<라이터>! [작업 내용]
```

명시적 스킬명 형식도 같다.

```text
$location-operator-writer <장소>-<오퍼레이터>-<라이터>! [작업 내용]
```

| 토큰 | 정규 값 | 허용 입력 |
|---|---|---|
| 장소 | `OFFICE` / `HOME` | `사무실` / `집` |
| 오퍼레이터 | `CODEX` / `CLAUDE_CODE` | `코덱스` / `클로드` / `클로드코드` |
| 라이터 | `GROK` / `DEEPSEEK` | `그록` / `딥시크` |

- 2×2×2의 8개 조합을 모두 허용한다.
- `!`는 호출 마커이며 정규 값에서 제거한다.
- 라우트만 입력되면 `ROUTE_SELECTED`만 보고하고 작업방이나 모델을 실행하지 않는다.
- 같은 대화에서 다음 작업 지시가 오면 마지막으로 선택한 라우트를 사용한다.
- 새 라우트가 오면 새 라우트가 이전 선택을 대체한다.
- 세 토큰 중 하나라도 없거나 모호하면 추론하지 않고 `ROUTE_REQUIRED` 또는 `ROUTE_INVALID`로 중단한다.

## 3. 환경을 확인한다

- 활성 대상은 `C:\sswcenter\3.0`이다. 활성 설정이 `C:\sswcenter\2.2`를 가리키면 `CONFIG_DRIFT`로 중단한다.
- 본진에서 시작할 때 Git 최상위는 `C:\sswcenter\3.0`이어야 한다.
- 승인된 독립방에서는 Git 최상위가 그 task/thread에 배정된 worktree와 정확히 같아야 한다.
- `warpper\wrapper-config.json`의 `repositoryRoot`는 `C:\sswcenter\3.0`이어야 한다.
- 선택한 장소의 profile, PowerShell, 필요한 실행파일과 인증 파일의 존재만 확인한다. 누락되면 모델을 호출하지 않고 `BLOCKED`로 보고한다.
- WorkCadence, `REMOVE`, 형님이 제외한 저장소를 근거로 사용하지 않는다.

## 4. 오퍼레이터에 따라 분기한다

### `OPERATOR=CODEX`

1. 오케스트레이션 정본의 room-1~7 표대로 서로 다른 Codex task/thread와 Git worktree를 준비한다.
2. 표의 모델·effort·fast를 **task/thread 생성 시 한 번만** 배정한다.
3. room-1~3은 자기 worktree에서 테스트 명령을 직접 실행한다.
4. room-4~6은 자기 worktree에서 직접 read-only 검수한다.
5. room-7은 Opus를 사용할 수 없을 때만 승인된 예비검수로 사용한다.

금지:

- 본진 Codex 또는 room Codex에서 `invoke-codex.ps1` 실행
- `codex exec`나 다른 방식으로 자식 Codex 세션 실행
- 독립방을 Writer방 또는 관리자방으로 변경
- 하나의 worktree를 여러 방이 공유

### `OPERATOR=CLAUDE_CODE`

1. Codex Desktop의 7개 방을 자동 생성하지 않는다.
2. 필요한 테스트·검수 등급만 `invoke-codex.ps1`로 위임한다.
3. 한 호출에서 하나의 등급과 하나의 완결된 prompt만 전달한다.

`invoke-codex.ps1`는 이 분기에서만 허용된다.

## 5. 라이터에 따라 분기한다

- `WRITER=GROK`: 현재 오퍼레이터가 `invoke-grok.ps1`로 승인된 쓰기 경로만 맡긴다.
- `WRITER=DEEPSEEK`: 현재 오퍼레이터가 고정 DeepSeek runner에 JSON Task Packet과 일치하는 읽기·쓰기 허용 목록을 전달한다.
- 라이터 호출은 구현 단계다. 테스트·검수 방이 라이터나 오퍼레이터를 다시 호출하지 않는다.
- FAIL/BLOCKED 뒤에 다른 라이터나 모델을 자동 호출하지 않는다.

## 6. 작업을 실행하고 보고한다

1. 오케스트레이션 정본의 실행 순서와 프롬프트 원칙을 따른다.
2. Writer의 보고를 실제 diff와 대조한다.
3. 테스트와 검수는 선택한 등급 범위 안에서 수행한다.
4. Git 쓰기 작업은 형님이 명시한 경우에만 수행한다.
5. `STATUS`, 실제 변경 경로, 테스트·검수 결과, Git 수행 여부, 미검증 항목을 짧게 보고한다.

실행 전 선택 보고:

```text
ROUTE=<장소-오퍼레이터-라이터>
REPOSITORY_ROOT=<확인한 Git 최상위>
OPERATOR_EXECUTION=DIRECT_CODEX_ROOMS|CLAUDE_TO_CODEX_WRAPPER
WRITER_EXECUTION=GROK_WRAPPER|DEEPSEEK_RUNNER
GIT=MANUAL_ONLY
```
