# W2 0027 · 1A Scoped 사용자 승인 봉인 기록

> 봉인 기록 시각: 2026-08-17T18:56:18+09:00
> 상태: `W2_SCOPED_GREEN_SEALED`
> 승인 주체: 형님 명시 승인
> 승인 원문: `승인 w3로 간다`

## 봉인 범위

이번 봉인은 W2 0027 current candidate의 reviewed manifest 98개 경로에 적용한다. 사용자 승인 뒤 작성한 이 봉인 기록, 최종 HTML 보고서, W3 의사결정 패킷은 post-review 산출물이며 reviewed manifest에 포함하지 않는다.

| 항목 | 값 |
|---|---|
| 제품 정본 | `/home/codexctl/workspace/sswcenter-3-0` |
| Git branch | `main` |
| Git HEAD 당시 기준 | `059ecf3dbfb54ac0a896303702d74ef190f8d984` |
| reviewed manifest | `review/evidence/W2_20260817_CURRENT_CANDIDATE_MANIFEST.sha256` |
| manifest entry | `98` |
| manifest SHA-256 | `9b549c3233505413f548232842d1d2ca8b69aa0587f65c9b5aa1936be1c2c597` |
| current plan | `review/plans/CURRENT_W2_SEAL_TO_W3_FAST_TRACK_20260817.md` |
| current plan SHA-256 | `fa019fe82e369de2b90273dd9598d4d1ff73569b672ad1e3b14b9c28a84d5311` |
| 최종 HTML 보고서 | `review/reports/W2_20260817_FINAL_REPORT.html` |
| 보고서 SHA-256 | `cafaa20e8c6c6f97443ad8cc38934a24895d9c1e0a84143cc3d44a458382fb44` |
| W3 결정 패킷 | `review/packets/W3_20260817_FAST_TRACK_DECISION_PACKET.md` |
| W3 패킷 SHA-256 | `b0b0ecdb00fa56fb1bed58cfd0af60cf9260c06d5b420c70ee9ebc95e5af8e47` |
| Sol 최종 독립검수 | `gpt-5.6-sol / ultra`, `STATUS=PASS`, `P0~P3 finding 없음`, `READY_FOR_USER_SEAL_APPROVAL=YES` |

## 승인된 W2 계약

- 새 공식카드는 카드 업무기준일의 월 전문직 담당자에게 자동배정한다.
- 관리자는 열린 미완료 카드의 담당자만 변경할 수 있고 대신 완료하지 못한다.
- 변경창에서 업무종류·대상자·상세업무·마감일·현재 담당자를 재확인한다.
- 새 담당자는 대상일 현재 재직 중인 사회복지사·간호사로 제한한다.
- 카드 ID·종류·마감일·발생키는 유지하고 담당자·`row_version`만 변경한다.
- 변경 전·후 담당자와 실행 관리자를 같은 트랜잭션의 감사이력에 기록한다.
- 같은 갱신 건에서 우선순위 카드로 교체돼도 유효한 수동 변경 담당자를 유지한다.
- 계획서 replacement는 같은 수급자이면 계약이 달라도 허용하고, 다른 수급자는 composite FK로 DB에서 차단한다.

## 완료된 검증

| 게이트 | 결과 |
|---|---|
| 후보 manifest | 98/98 status·SHA-256·bytes exact |
| W2 PostgreSQL | 0026→0027→0026→0027 lifecycle·직접 SQL·경합 포함 `30 passed`, warning 1 |
| 실 브라우저 | real FastAPI·Vite·Chromium 관리자 재배정·409 최신상태 `1 passed` |
| 백엔드 | Ruff PASS, mypy 79 sources PASS, targeted `27 passed` |
| 프런트엔드 | supported `265 passed`, lint 0 errors·기존 warning 5, build PASS·기존 500 kB 경고 |
| W1E 회귀 | 0026 pinned `23 passed`, warning 1, cleanup·manifest delta 0 |
| 복구·계약 | active-0027 backup/restore GREEN, OpenAPI zero drift, `git diff --check` PASS |
| 정리 | listener/process/temp/git delta 모두 0 |

이 표의 PASS에는 완료되어 증거가 남은 실행만 포함한다. 이전 Grok/Terra 재실행 중 timeout 또는 interrupt로 끝난 실행은 성공으로 계산하지 않는다.

첫 Sol 독립검수에서는 `pg_ctl start`가 process를 spawn한 뒤 nonzero로 끝나는 실패경로에서 임시 PostgreSQL cluster cleanup이 누락될 수 있는 P2가 발견되었다. 해당 cleanup을 수정하고 실행 검증한 뒤 Sol ultra follow-up에서 `STATUS=PASS`, `P0~P3 finding 없음`을 확인했다. 따라서 이 봉인은 첫 검수부터 finding이 없었다고 주장하지 않는다.

## 봉인 불변조건

- reviewed manifest 98개 경로는 형님의 승인 전후 동일 바이트로 유지한다.
- 이 봉인 기록, 최종 HTML 보고서, W3 결정 패킷은 post-review 파일이므로 reviewed manifest 98개 row에 포함하지 않는다.
- reviewed manifest 자신과 untracked `.codex/` 설정은 manifest 생성 당시부터 명시적으로 제외된 대상이다.
- W2 후보에 포함된 current plan은 승인 상태를 사후 수정하지 않으며 manifest에 기록된 바이트를 유지한다.
- 후보 manifest가 동결한 mixed dirty tree의 포함은 각 경로의 변경 작성자를 W2로 귀속하지 않는다.
- Starlette TestClient deprecation warning 1건, 기존 프런트 lint warning 5건, 기존 500 kB 초과 chunk 경고는 기록하되 W2 scoped 봉인을 해제하지 않는다.
- stage, commit, merge, push, branch/worktree 변경·삭제는 이번 승인과 봉인에 포함하지 않는다.
- 저장소 전체 release GREEN, 전체 pytest·전체 mypy의 무부채 상태, W3 구현 완료를 주장하지 않는다.

## W3 전환

형님의 승인에 따라 W3 fast track을 시작한다. W3 제품 구현의 첫 gate는 `review/packets/W3_20260817_FAST_TRACK_DECISION_PACKET.md`의 `W3-01`~`W3-09`와 가명 실형상 샘플 기대 결과를 확정하는 것이다. 이 결정 전에는 데이터 의미를 임의로 정하는 migration·model·endpoint·자동적용 로직을 작성하지 않는다.

W4 계산·청구·수납과 W5 범용 파일함·OCR·공식 출력·복구는 W3 범위에 포함하지 않는다.
