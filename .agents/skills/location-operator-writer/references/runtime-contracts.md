# AI 호출 런타임 계약

이 문서는 **설치된 Secure AI Workbench의 packet·result·exit 형식만** 소유한다. 역할·호출 권한·검증 등급은 [`00-오케스트레이션-작업지침.md`](../../../../00-오케스트레이션-작업지침.md), 경로·인증·Git 경계는 [`00-먼저읽기-작업환경안내.md`](../../../../00-먼저읽기-작업환경안내.md)를 따른다.

## 호출 권한

| 호출 | 허용 조건 |
|---|---|
| Secure AI Workbench `grok` | `WRITER=GROK`이고 형님이 보낼 텍스트를 승인한 경우 |
| Secure AI Workbench `deepseek` | `WRITER=DEEPSEEK`이고 형님이 보낼 packet을 승인한 경우 |
| Secure AI Workbench `claude` | 명시된 한 슬라이스의 advisory read-only 검수이고 형님이 승인한 경우 |

legacy `warpper`, `deepseek_runner`, provider CLI, 직접 controller 호출은 현재 계약에서 금지한다. Claude는 최종 acceptance나 구현 역할로 승격하지 않는다.

## 공통 사전확인

1. 대상 repository root가 본진 또는 승인된 worktree의 정확한 Git 최상위인지 확인한다.
2. 현재 장소·오퍼레이터·provider·슬라이스와 쓰기/읽기 범위를 확정한다.
3. provider로 보낼 정확한 텍스트·목적·효과를 형님께 설명하고 명시 승인을 받는다.
4. provider에는 path·URL·header·credential·shell·tool·attachment를 넣지 않는다.
5. 설치된 Workbench의 deterministic preflight를 통과하지 못하면 호출하지 않고 `CONFIG_DRIFT` 또는 `BLOCKED`로 보고한다.

## 검증 진입점

Codex는 설치된 `secure-ai-workbench` 스킬의 `scripts/Invoke-VerifiedAiWorkbench.ps1`만 사용한다. 실제 설치 root는 세션에서 해석하며 이 문서에 사용자별 절대경로를 고정하지 않는다.

```powershell
$packetJson | & $pwsh -NoProfile -File '<secure-ai-workbench skill>/scripts/Invoke-VerifiedAiWorkbench.ps1' -Provider <provider>
```

- packet은 UTF-8 stdin으로만 전달하고 stdin을 닫는다.
- packet 파일·argv·환경변수에 packet이나 credential을 저장하지 않는다.
- 호출 전후 preflight/postflight 사이에 다른 외부 동작을 끼우지 않는다.
- verified entrypoint가 반환한 strict result schema와 동일 `task_id`·`provider`만 신뢰한다.

## Provider와 모델

| provider | 기본 모델 | 허용 모델 |
|---|---|---|
| `deepseek` | `deepseek-v4-pro` | `deepseek-v4-pro`, `deepseek-v4-flash` |
| `grok` | `grok-4.5` | `grok-4.5`, `grok-4.3` |
| `claude` | `claude-sonnet-5` | `claude-sonnet-5`, `claude-opus-5`, `claude-haiku-4-5-20251001` |

model은 현재 Workbench contract가 허용한 값만 packet의 선택 필드로 넣는다. Claude provider는 한 슬라이스의 텍스트 검수만 수행하며 독립 최종 acceptance를 소유하지 않는다.

## Task packet schema `2.0`

필수 필드는 다음과 같다.

```text
schema_version: "2.0"
task_id: ^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$
provider: deepseek | grok | claude
instruction: non-empty string, <= 262144 characters
timeout_seconds: integer 5..900
max_output_bytes: integer 1024..4194304
max_tokens: integer 1..262144
```

허용 선택 필드는 `context`와 선택적 `model`뿐이다. `metadata`와 그 밖의 모든 필드(path·URL·file·working-directory·header·tool·shell·attachment 포함)는 사용하지 않는다. 일반 slice는 `max_tokens=131072`를 사용하고, 더 큰 작업은 독립적으로 검토 가능한 slice로 나눈다.

## Result와 exit 계약

verified entrypoint는 다음 필드를 정확히 하나씩 포함한 JSON 결과를 반환한다.

```text
schema_version, run_id, task_id, provider, status, started_at,
finished_at, duration_ms, output, error_code, truncated, provider_metadata
```

- exit `0`: `status=succeeded`이고 `error_code=null`인 경우만 성공이다.
- exit `2`: local packet rejection이며 `LOCAL_REQUEST_REJECTED`로 보고한다.
- exit `3`: controller·integrity·Ubuntu·result-contract failure이며 `CONTROLLER_INTEGRITY_ERROR`로 보고한다.
- exit `4`: **검증된 operational failure**다. `workbench_error`, `configuration_error`, `validation_error`, `identity_error`, `credential_error`, `transport_error`, `provider_error`, `provider_timeout`, `storage_error` 중 반환된 `error_code`만 보고한다.
- 어떤 nonzero exit도 성공이나 부분 성공으로 낮추지 않는다.
- raw bridge stdout/stderr, 내부 경로, credential, provider 원문은 사용자에게 노출하지 않는다.

## Credential과 종료

- credential 설정은 설치된 `Set-AiWorkbenchKey.ps1 -Provider <provider>`를 대화형으로 실행할 때만 수행한다.
- credential 파일을 읽거나 출력·복사·prompt 삽입·Git 커밋하지 않는다.
- verified entrypoint의 postflight가 실패하면 provider output을 폐기한다.
- provider 결과는 현재 authoritative source·diff·테스트와 대조한 뒤에만 조언으로 사용한다.
- 실패해도 reset·checkout·clean으로 자동 복구하거나 다른 provider·모델을 자동 재호출하지 않는다.
