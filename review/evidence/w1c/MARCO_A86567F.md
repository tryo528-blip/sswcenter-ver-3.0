# W1C Marco Exact-SHA Re-Review — a86567f

## 판정

- 최종 후보 SHA: `a86567fe5c3b88bc9148c04b97f3626e0972ed75`
- 후보 parent: `111b77a59f8195ce4623035a9f699f79ca001bd8`
- 후보 branch: `codex/w1c-certification-ledgers`
- 검수 경로: `C:\sswcenter\2.1`
- 독립 검수 시간: 2026-07-30 18:57:40~19:08:39 KST
- 최종 marker: `MARCO_W1C_REVIEW_RESULT=APPROVE`
- 확정 결함: `0`
- 남은 HIGH/MEDIUM blocker: `0`
- 최종 PASS 권한: 레지나

## exact-SHA hard gate

마르코 read-only 작업방은 검수 시작과 종료에 다음을 직접 확인했다.

| 항목 | 결과 |
|---|---|
| `git rev-parse HEAD` | exact `a86567f...` |
| staged / unstaged / untracked | 모두 `0` |
| candidate parent delta | evidence 파일 `4`개 |
| 누적 W1C delta | 고유 경로 `38`, 삭제 `0` |
| migration topology | `0010`은 `0009`의 direct child |
| 기존 migration blob | 변경 `0` |
| `git fsck --full --connectivity-only HEAD` | exit `0` |
| `git diff --check` | exit `0` |
| 최종 listener | `55491`, `18091`, `14191`, `55493` 모두 `0` |

## 마르코 1차 finding 폐쇄

1. HIGH — W1B 비기본 backend/frontend 포트
   - W1B wrapper가 두 포트를 Playwright 자식 프로세스에 전달한다.
   - Playwright는 전달된 frontend port와 `--strictPort`를 사용한다.
   - Vite proxy는 전달된 backend port를 사용한다.
   - exact code-equivalent 실하네스 증거는 `55491/18091/14191`,
     Playwright `3 passed`, `W1B_E2E_GREEN`, 잔여 `0`이다.
2. MEDIUM — broad Ruff format
   - `ruff check --no-cache app tests`: exit `0`
   - `ruff format --check --no-cache app tests`: exit `0`,
     `84 files already formatted`
   - W1B 정적 회귀: `7 passed`, `4 deselected`
3. MEDIUM — evidence SHA 역할
   - 누적 기준, 기술 재감사 코드, 마르코 1차 SHA, self-reference 없는 exact
     `HEAD` 절차가 서로 구분됐다.
   - 과거 BLOCK 기록은 역사 증거로 유지되고 현재 후보 승인과 혼동되지 않는다.

## false-green 점검

- W1C 코드·migration blob은 기술 재감사 SHA `b6d49ad...`부터 최종 후보까지
  byte-identical이다.
- trigger·lock·ACL·postcheck 계약과 dependency override 없는 실제
  인증·권한·CSRF 테스트 경계를 확인했다.
- W1C 계약/schema: `7 passed`
- OpenAPI 생성 재현성: `OPENAPI_TYPES_UP_TO_DATE`
- W1B Playwright 비기본 포트 수집: viewport `3`, exit `0`

독립 작업방의 새 W1C PostgreSQL 실행은 Windows restricted-token startup
제약으로 preflight에서 exit `1`, focused frontend 재실행은 read-only profile의
`.vite-temp` 생성 거부로 시작되지 않았다. 두 항목은 제품 assertion 실패가 아니다.
검수자는 해당 실행 뒤 listener·임시 cluster·artifact 잔여 `0`과 clean Git을
확인하고, runtime 대상 blob이 기존 exact 실행 증거와 동일함을 확인해 그 증거를
재사용했다.

## 로그 봉인

```text
C:\tmp\sswcenter-independent-reviews\W1C-Marco-a86567f-r1\codex.stdout.log
size=2437
sha256=DAD9435AC7C7CD286A29D49DB61DE864E39B367874820464A3BA6313D2A89A19

C:\tmp\sswcenter-independent-reviews\W1C-Marco-a86567f-r1\codex.stderr.log
size=1035499
sha256=784016A4CB1F81146D1D070709FFE5DD50168F1910B68737E52C5ED4A3FAC177
```

임시 로그는 영구 증거 저장소가 아니므로, 이 문서가 검수 결과·명령·수치·경계를
저장소 안에 보존한다.

## 레지나 수용 판정

동일 후보 SHA에서 이전 HIGH/MEDIUM finding이 모두 폐쇄됐고 새 제품 blocker가
없다. 레지나는 2026-07-30 19:45 KST에
`W1C_PASS / GREEN_SEALED`를 최종 판정했다.

이 문서와 `GREEN.md`를 담는 후속 evidence-only commit은 검증대상
`a86567f...`와 구분하며, 제품·테스트·마이그레이션·계약 파일을 변경하지 않는다.
