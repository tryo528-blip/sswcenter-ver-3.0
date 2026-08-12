# W1A-VS1 요셉 설계 2차 검토

> 판정일: 2026-07-26 KST
>
> 검토자: 요셉
>
> 검토 대상: 1차 findings, Codex 수정계획, 사용자 권한결정
>
> 전체 판정: `REQUIRED_CHANGES`

사용자가 ADMIN의 주민번호 최초 입력·reveal 범위를 `STAFF_MANAGE`까지 확장한
결정은 유효한 owner policy override다. current PIN·CSRF·`no-store`·성공당
`access_event` 1건 조건도 유지되어 권한 확장 자체는 blocker가 아니다.

| finding | 상태 | severity | 2차 판정 |
|---|---|---|---|
| F01 권한정책 | `RESOLVED` | BLOCKER | 사용자 결정과 action matrix가 일치하고 자동 권한부여를 금지했다. |
| F02 종료·정정 | `RESOLVED` | BLOCKER | close/replacement, expected version, 자식기간 원자 처리, audit/rollback 경계가 확정됐다. |
| F03 reveal 보안 | `RESOLVED` | BLOCKER | 현재 계정, 잠금, 실패 audit, 복호화 오류, audit commit-before-response가 명시됐다. |
| F04 민감 artifact | `RESOLVED` | HIGH | 전 계층 redaction, 민감 Playwright artifact 비활성화, 유출검사가 추가됐다. |
| F05 API 공존 | `UNRESOLVED` | HIGH | 기존 health 경로를 잘못 봉인했다. |
| F06 capability | `UNRESOLVED` | HIGH | 제시한 cache key를 현재 API에서 만들 수 없다. |
| F07 PG/app-role harness | `UNRESOLVED` | BLOCKER | 민감 테이블 권한계약이 API 구현방식과 양립하지 않는다. |
| F08 code 경계 | `UNRESOLVED` | HIGH | 직종은 해결됐지만 역할·성별의 DB 경계가 열려 있다. |
| F09 기존 0-row | `RESOLVED` | MEDIUM | 사후 입력 API·UI 제외와 후속 권한정책이 명시됐다. |
| F10 RED 재현 | `RESOLVED` | HIGH | 파일·명령·기대실패·증거·RED-only commit 경계가 재현 가능하다. |

## 새 발견사항

### R2-N01 — HIGH

계획은 기존 health를 `/api/health`로 적었지만 실제 계약은 `/health/live`,
`/health/ready`다. 공존표가 기존 exact 경로를 보존해야 한다.

### R2-N02 — HIGH

capability 응답은 boolean만 반환하면서 UI cache key에는 기존 API가 제공하지 않는
`session_version`을 요구한다. 권한 부여·회수 때 cache 무효화 계약도 없다.

- 권고: session/capability version 전달·증가 규칙을 확정하거나 capability를
  cache하지 않는다.

### R2-N03 — BLOCKER

계획은 app DSN에서 민감 테이블 직접 변경을 거부한다고 했지만 애플리케이션
암호화와 repository 직접 INSERT/SELECT를 전제로 한다. DB 보안함수 경계가 없는
현재 설계에서는 두 계약을 동시에 구현할 수 없다.

테스트 역할 `sswcenter_app`도 실제 설정의 `erp_app`과 다르다. 운영과 동일한 역할
또는 동일 grant set을 검증해야 한다.

## 남은 F08

catalog를 발명하지 않는 범위 근거는 타당하지만 DB CHECK까지 생략할 근거는 아니다.

- `role_code`는 API regex와 같은 DB 형식 제약이 필요하다.
- `sex_code`는 신규 API의 `MALE/FEMALE`와 합성 `TEST` legacy 예외를 DB와
  bootstrap 경계에서 명시적으로 봉인해야 한다.

## 최종 판정

- 중요한 미해결: F07 BLOCKER, F05·F06·F08 HIGH
- 마르코 인계: 현재 불가
- 조건: health 경로, capability cache, app-role 민감 테이블 권한모델,
  역할·성별 DB 경계를 수정한 뒤 최종안으로 넘긴다.
