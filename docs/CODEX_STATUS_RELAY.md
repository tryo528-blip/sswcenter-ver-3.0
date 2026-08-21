# Codex Status Relay

Windows Codex 앱을 수정하거나 제어하지 않고, 로컬 상태를 **읽기 전용**으로 관찰해 Slack으로 상태 변화만 알려주는 보조 도구입니다.

## 무엇을 감지하나

- `APP_OFF`: Codex 프로세스가 보이지 않음
- `APP_ON_NO_SESSION`: 앱은 켜져 있으나 세션 파일을 찾지 못함
- `ACTIVE_RECENT`: 최근 세션 파일이 계속 갱신됨
- `QUIET`: 최근 세션 파일 갱신이 멈춤
- `ACTIVE_RECENT -> QUIET` 후 일정 시간이 지나면 `작업 종료 추정` 알림

> `작업 종료 추정`은 공식 Codex 완료 이벤트가 아닙니다. Windows 앱의 로컬 세션 활동을 기준으로 한 추정값입니다.

## 1회 진단

PowerShell 7에서:

```powershell
pwsh -File C:\sswcenter\3.0\scripts\codex-status-relay.ps1 -Once -NoSlack
```

출력에서 `CODEX_HOME`, 상태, 최근 프로젝트 힌트가 정상인지 먼저 확인합니다.

## Slack 알림 설정

Slack Incoming Webhook URL을 현재 사용자 환경변수로 저장합니다.

```powershell
[Environment]::SetEnvironmentVariable(
  'SLACK_WEBHOOK_URL',
  'https://hooks.slack.com/services/REPLACE_ME',
  'User'
)
```

새 PowerShell 창을 연 뒤 실행:

```powershell
pwsh -File C:\sswcenter\3.0\scripts\codex-status-relay.ps1
```

Webhook URL은 저장소 파일이나 `.env`에 넣지 않습니다.

## 기본 판정값

- 15초마다 확인
- 최근 45초 이내 세션 갱신이면 `ACTIVE_RECENT`
- 120초 이상 조용하면 `작업 종료 추정`

조정 예시:

```powershell
pwsh -File C:\sswcenter\3.0\scripts\codex-status-relay.ps1 `
  -PollSeconds 10 `
  -ActiveWindowSeconds 30 `
  -CompletionQuietSeconds 90
```

## 자동 시작

1차 검증 후 Windows 작업 스케줄러나 시작프로그램에 등록하면 됩니다. 처음부터 자동 시작시키지 말고, `-Once -NoSlack`과 수동 상시 실행으로 오탐 여부를 먼저 확인합니다.

## 안전 경계

- Codex 세션 파일은 읽기만 합니다.
- 프로젝트 파일, Git 상태, Codex 세션을 수정하지 않습니다.
- Codex CLI나 App Server를 실행하지 않습니다.
- Slack으로는 상태명, 프로젝트 경로 힌트, 마지막 활동시간만 보냅니다.
- 프롬프트/응답 본문은 Slack으로 보내지 않습니다.

## 다음 단계

1차 버전에서 오탐이 적으면 다음 단계로 진행합니다.

1. 실제 Codex App Server 완료 이벤트를 Windows 앱과 병행 관찰할 수 있는지 검증
2. 가능하면 `작업 종료 추정`을 공식 `turn/completed` 이벤트 기반으로 교체
3. 여러 프로젝트/스레드별 상태를 각각 분리해 Slack에 표시
