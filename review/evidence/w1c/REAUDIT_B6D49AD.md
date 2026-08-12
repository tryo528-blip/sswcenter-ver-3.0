# W1C Concurrency Re-Audit — b6d49ad

## 판정

- 감사 후보 SHA: `b6d49ada90c24266fff1851a54e1f931cdbb83af`
- 직전 후보 SHA: `af501acdec474063ce4c884715690d752c521815`
- 방식: exact SHA detached worktree 대상 독립 감사
- 요셉: `JOSEPH_W1C_B6D49AD_APPROVE`, HIGH/MEDIUM `0`
- Opus: no findings로 동의
- 유효 판정: `W1C_DUAL_REAUDIT_APPROVE`

요셉은 사용자에게 보이는 독립 Codex 작업방에서 exact SHA를 확인하고 실제 격리
PostgreSQL 하네스를 실행했다. Opus는 Claude Code `2.1.215`의 `opus` 모델을 실제
CLI로 호출했으나, 요구한 첫 줄 marker 형식을 지키지 않았다. 또한 해당 detached
환경에는 venv와 PostgreSQL 실행파일이 없어 정적 코드·잠금 추적만 수행했다고
명시했다. 따라서 실DB 승인 근거는 요셉 실행 결과이고 Opus 결과는 보조 근거다.

## RED — 후속 HIGH 재현

직전 후보에는 다음 경합이 있었다.

1. T1이 인정기간의 `invalidated_at_utc`를 UPDATE해 `FOR NO KEY UPDATE`를 보유
2. T2가 같은 인정기간을 참조하는 등급을 INSERT하고 FK의 `FOR KEY SHARE`를 보유
3. 두 lock mode가 충돌하지 않아 양쪽 statement가 동시에 진행
4. 양방향 containment trigger가 상대의 미커밋 변경을 보지 못하고 모두 통과
5. 최종적으로 무효 인정기간 아래 활성 등급이 잔존

`af501ac` 코드에 새 회귀 테스트만 추가한 첫 격리 PostgreSQL 실행은 T2가 차단되지
않고 커밋되어 `1 failed, 5 passed`였다. 실패 지점은 예상한
`ck_recipient_grade_period_containment` 대신 성공 결과 `None`이 반환된
assertion이었다. 하네스의 `finally`가 임시 서버와 cluster를 정상 정리했다.

이 finding은 DB 기간 containment의 영속 무결성을 깨므로 운영규정 v3.5상 HIGH다.
Opus가 처음 붙인 비차단 분류는 채택하지 않았다.

## 보정

- `fn_w1c_assert_grade_containment()`의 부모 인정기간 조회에 `FOR SHARE`를 추가했다.
  이 lock은 부모 UPDATE의 `FOR NO KEY UPDATE`·`FOR UPDATE`와 충돌하고 다른
  `FOR SHARE`와는 호환된다.
- 서비스의 등급 생성·대체 부모 조회에도 `for_update=True`를 추가해 application
  경로를 명시적으로 직렬화했다.
- DB postcheck가 배포된 trigger 함수 본문에 부모 조회, `FOR SHARE`, containment
  constraint가 모두 있는지 검증한다.
- raw SQL 두 connection 회귀가 무효화 우선과 등급 INSERT 우선 순서를 각각
  실행한다. 고유 `application_name`과 `pg_stat_activity.wait_event_type='Lock'`로
  실제 대기를 확인한 뒤 선행 transaction을 커밋한다.
- 무효화 우선은 등급 측
  `ck_recipient_grade_period_containment`, 등급 우선은 부모 측
  `ck_recipient_certification_period_grade_containment`를 확인한다.
- 각 시나리오 뒤 최종 DB 상태를 조회해 orphan 0건 또는 활성 부모+등급 1건을
  검증한다.

## 검증 결과

| Gate | 결과 |
|---|---|
| exact SHA / detached worktree | `b6d49ad...`, clean |
| W1C migration round trip | `0009 → 0010 → 0009 → 0010` |
| 실제 runtime role | `W1C_APP_ROLE_OK`, `erp_app` |
| W1C PostgreSQL/API | `6 passed`, 양방향 동시성 회귀 포함 |
| W1C DB postcheck | `W1C_DB_POSTCHECK_OK` |
| W1C 최종 실DB marker | `W1C_POSTGRES_GREEN` |
| Ruff / format | 통과 / `9 files already formatted` |
| mypy | `44 source files`, 통과 |
| W1C 계약·schema | `7 passed` |
| 비실DB 백엔드 회귀 | `134 passed`, `44 skipped`, `4 deselected` |
| W1C 프런트 집중 | `5 passed` |
| W1C Playwright | 3 viewport, `9 passed` |
| 프런트 lint / build | 통과 / `151 modules transformed` |
| OpenAPI 생성 drift | `OPENAPI_TYPES_UP_TO_DATE` |
| Git whitespace / worktree | 오류 `0` / clean |

FastAPI TestClient의 `httpx2` 전환 경고 1건은 기존 비차단 경고다. 프런트 전체
첫 실행은 감사 프로세스들과 동시 실행한 부하에서 기존 비동기 테스트 2건이
기본 대기시간을 넘겨 `96 passed, 2 failed`였다. 해당 2개 파일을 1 worker로
즉시 재실행해 `16 passed`를 확인했다. W1C 집중 5개와 브라우저 9개는 별도로
전부 통과했다.

요셉은 감사 종료 시 임시 cluster, 대상 listener, 테스트 artifact 잔여가 모두
0임을 확인했다.

## 후속 절차 결과

이 파일을 포함한 evidence commit은
`e1f5e39fb94ba73a81638fbf118aa2746daaed5c`로 생성됐고, 마르코가 그 exact
SHA를 최종 반대검토했다. 결과는 W1B 비기본 포트 하네스 실패 1 HIGH, broad Ruff
format과 SHA 표기 정합성 2 MEDIUM으로 `MARCO_W1C_FINAL_BLOCK`이었다.

세 finding의 보정과 재검증은 `review/evidence/w1c/MARCO_E1F5E39.md`에 이어서
보존한다. 그 보정을 포함하는 새 exact SHA를 같은 마르코 독립 작업방이 재검토하기
전까지 Regina의 최종 `PASS`는 보류한다.
