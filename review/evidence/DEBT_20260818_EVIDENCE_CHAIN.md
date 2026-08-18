# 2026-08-18 DEBT 마감 증거 체인

> 상태: `DEBT_PRE_SEAL_READY / HISTORICAL_SEALS_PRESERVED / FINAL_SEAL_NOT_RUN`

## 불변 이력

1. `W2_20260817_CURRENT_CANDIDATE_MANIFEST.sha256`는 사용자 봉인 당시 98개 경로를
   고정한 역사 증거다.
2. `W3_20260817_CURRENT_CANDIDATE_MANIFEST.sha256`는 W2 98개 경로를 모두 포함하며,
   W2 대비 `85 exact + 13 approved W3 canonical changes`를 고정한다.
3. `W3_20260817_PARENT_W2_DELTA.md`의 13개 전진 변경은 현재 작업트리가 아니라 위 W3
   후보 manifest의 바이트를 기준으로 검증한다. 따라서 후속 유지보수 때문에 과거
   W2/W3 증거를 다시 쓰거나 현재 바이트와 같다고 주장하지 않는다.

## 현재 DEBT 후보

`DEBT_20260818_CURRENT_CANDIDATE_MANIFEST.sha256`는 2026-08-18 정적 DEBT와 브라우저
회귀 수정 뒤의 mixed dirty tree 전체를 별도로 고정한다. manifest 자신과 untracked
`.codex/` 작업설정만 제외한다. 경로 포함은 최초 작성자 귀속을 뜻하지 않는다.

- W3 manifest 141개 경로는 현재 dirty tree에도 모두 남아 있다.
- 그중 113개는 W3 manifest와 byte exact이고 28개는 W3 후속 수정·정적 DEBT 정리로
  전진했다.
- W3 manifest 밖 current dirty 경로는 최종 후보 생성 전 47개다. 점검 시작 때 확인한
  45개에 이 증거 문서와 자동 manifest 검사를 더했으며, historical 테스트 프로필
  분리, 타입·포맷 정리, W1C 상세 일괄저장 bigint 수정과 DEBT 보고서를 포함한다.
- W2 부모 98개를 현재와 직접 비교하면 66 exact, 32 changed다. 그 32개는 W3 후보의
  13개 전진 변경과 후속 DEBT 변경을 합친 결과이며, `W2_UNAUTHORIZED_DRIFT=0`을 현재
  바이트에 직접 적용하지 않는다.

## 자동 검증

`backend/tests/test_debt_candidate_manifest.py`는 Git이 보고하는 모든 tracked-modified와
untracked non-ignored 경로 집합, 각 status, SHA-256, bytes를 현재 DEBT manifest와
대조한다. manifest 자신과 `.codex/`만 명시적으로 제외한다.

```text
W2_TO_W3_PARENT_ROWS=98
W2_TO_W3_EXACT=85
W2_TO_W3_INTENTIONAL=13
W3_PARENT_ROWS=141
DEBT_CURRENT_MANIFEST_GATE=REQUIRED
HISTORICAL_SEAL_REWRITE=0
```

## 2026-08-18 최종 봉인 직전 재검증

- 작업 브랜치: `codex/debt-preseal-20260818`
- 기준 HEAD: `059ecf3dbfb54ac0a896303702d74ef190f8d984`
- W3 첫 live 실행: `32 passed, 2 failed`; 테스트의 PostgreSQL DDL·sequence 가정 2건을
  최소 수정했다.
- W3 재실행: `34 passed`, restore green, live green,
  `listener=0 process=0 temp=0 git_delta=0`, `W3_0028_POSTGRES_SEAL_GREEN`.
- W2 재실행: historical `29 passed, 1 deselected`, current-head HTTP `1 passed`,
  real Chromium `1 passed`, restore green, live green,
  `listener=0 process=0 temp=0 git_delta=0`, `W2_0027_POSTGRES_SEAL_GREEN`.
- 공식 지원 프로필: backend `583 passed, 200 skipped`, frontend unit `267 passed`,
  W1C E2E `9 passed`, OpenAPI·mypy·Ruff·build green.
- 최종 staged whitespace는 역사 handoff 2개의 기존 Markdown hard-break/EOF 진단 4개만
  남았다. 두 파일은 W1E/W2/W3 manifest SHA와 byte exact이며, 두 경로를 제외한
  `git diff --cached --check`는 PASS다.
- historical W2/W3 manifest는 수정하지 않았다. DEBT manifest만 현재 후보 바이트에 맞춰
  갱신한다. 최종 봉인 확정은 이 증거에 포함하지 않으며, 후속 Git 처리는 형님의 별도
  명시 지시와 실제 branch ref로 기록한다.
