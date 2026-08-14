---
name: location-operator-writer
description: "`사무실-코덱스-그록!`처럼 장소·오퍼레이터·라이터를 지정한 SSWCenter 3.0 route를 해석하고, 정본 문서의 역할·작업방·호출 경계를 집행한다."
---

# 장소·오퍼레이터·라이터 라우팅

## 1. 정본을 먼저 읽는다

다음 문서를 이 순서로 읽고 내용을 복사하거나 재정의하지 않는다.

1. `C:\sswcenter\3.0\00-먼저읽기-작업환경안내.md`: 장소·경로·인증·Git 경계
2. `C:\sswcenter\3.0\00-오케스트레이션-작업지침.md`: 역할·호출 경계·독립방·검증 등급·보고
3. `C:\sswcenter\3.0\docs\운영_오퍼레이터_등급_정의_v1.0.md`: 테스트·검수 등급의 의미

실제 Secure AI Workbench packet·result 형식은 [runtime-contracts.md](references/runtime-contracts.md)가 소유한다.

## 2. route를 해석한다

호출 형식:

```text
<장소>-<오퍼레이터>-<라이터>! [작업 내용]
```

| 토큰 | 정규 값 | 허용 입력 |
|---|---|---|
| 장소 | `OFFICE` / `HOME` | `사무실` / `집` |
| 오퍼레이터 | `CODEX` / `CLAUDE_CODE` | `코덱스` / `클로드` / `클로드코드` |
| 라이터 | `GROK` / `DEEPSEEK` | `그록` / `딥시크` |

- route만 입력되면 `ROUTE_SELECTED`만 보고하고 작업방이나 provider를 실행하지 않는다.
- 같은 대화에서 새 route가 오면 이전 선택을 대체한다.
- 외부 provider를 호출하지 않는 Codex 작업에는 route를 추론하지 않는다.
- 세 토큰 중 하나라도 없거나 모호하면 `ROUTE_REQUIRED` 또는 `ROUTE_INVALID`로 중단한다.

## 3. 환경을 확인한다

- 활성 대상은 `C:\sswcenter\3.0`이다. 활성 설정이 `C:\sswcenter\2.2`를 가리키면 `CONFIG_DRIFT`로 중단한다.
- 본진에서 시작할 때 Git 최상위는 `C:\sswcenter\3.0`이어야 한다. 독립방에서는 배정된 worktree와 정확히 같아야 한다.
- 외부 provider 호출은 설치된 `secure-ai-workbench` 스킬의 검증 진입점만 사용한다. legacy wrapper·runner·provider CLI·직접 controller 호출은 사용하지 않는다.
- provider로 보낼 정확한 텍스트·목적·효과를 형님께 먼저 설명하고 명시 승인을 받는다.
- provider에는 path·URL·header·credential·shell·tool·attachment를 보내지 않는다.
- Workbench preflight·postflight·result schema·error code가 맞지 않으면 호출하지 않고 `CONFIG_DRIFT` 또는 `BLOCKED`로 보고한다.

## 4. 오퍼레이터에 따라 분기한다

### `OPERATOR=CODEX`

1. Codex가 승인된 worktree에서 필요한 테스트·read-only 검수를 직접 수행한다.
2. Codex 검증 슬롯은 현재 슬라이스의 등급에 필요한 만큼만 사용한다.
3. Codex 본진·독립방에서 자식 Codex, Codex CLI, legacy wrapper를 재호출하지 않는다.

### `OPERATOR=CLAUDE_CODE`

1. Claude Code는 형님이 지정한 한 슬라이스의 read-only 검수만 수행한다.
2. 구현·Writer 호출·파일 수정·최종 acceptance 선언은 하지 않는다.
3. 필요한 외부 텍스트 검수는 Secure AI Workbench `claude` provider의 advisory 결과로만 취급한다.

작업방·task/thread를 자동으로 7개 생성하지 않는다. 형님이 명시하거나 Codex 앱이 승인한 방만 사용한다.

## 5. 라이터에 따라 분기한다

- `WRITER=GROK`: Secure AI Workbench `grok` provider로 승인된 텍스트만 보낸다.
- `WRITER=DEEPSEEK`: Secure AI Workbench `deepseek` provider로 승인된 schema `2.0` packet만 보낸다.
- provider는 조언·초안·검수 텍스트만 반환하며 저장소를 직접 수정하지 않는다.
- provider 결과는 현재 파일·diff·테스트와 대조하고 형님 승인 후에만 Codex가 반영한다.
- FAIL/BLOCKED 뒤에 다른 provider·모델·fallback을 자동 호출하지 않는다.

## 6. 작업을 실행하고 보고한다

1. 오케스트레이션 정본의 실행 순서와 prompt 원칙을 따른다.
2. provider 보고가 아니라 실제 diff와 변경 경로를 확인한다.
3. 테스트와 검수는 선택한 슬라이스·등급 범위 안에서 직접 수행한다.
4. 검수는 read-only이며, Git 쓰기 작업은 형님이 명시한 경우에만 수행한다.
5. `STATUS`, 실제 변경 경로, 테스트·검수 결과, Git 수행 여부, 미검증 항목을 짧게 보고한다.

실행 전 선택 보고:

```text
ROUTE=<장소-오퍼레이터-라이터 또는 생략>
REPOSITORY_ROOT=<확인한 Git 최상위>
SLICE=<검증 대상 슬라이스>
OPERATOR_EXECUTION=DIRECT_CODEX|CLAUDE_SLICE_REVIEW
WRITER_EXECUTION=WORKBENCH_GROK|WORKBENCH_DEEPSEEK|NONE
GIT=MANUAL_ONLY
```
