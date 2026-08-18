# W3 사용자 의사결정 봉인 기록

> 봉인 기록 시각: 2026-08-17T20:28:13+09:00
> 상태: `W3_DECISIONS_APPROVED / PRE_RED_IMPLEMENTATION`
> 승인 주체: 형님 명시 승인
> 승인 원문: `ㄱㄱ`

## 승인 해석과 대상

형님의 `ㄱㄱ`는 직전 대화에서 요청한 `추천안 전체 승인`에 대한 진행 승인으로
기록한다. 승인 대상은 아래 SHA-256으로 식별한 W3 의사결정 패킷의 추천값
`W3-01`~`W3-09` 전체다. 이 기록은 선택 계약의 확정을 뜻하며 W3 제품 구현,
실제 workbook header profile, parser, matcher, APPLY, API 또는 UI의 완료를 뜻하지 않는다.

| 항목 | 값 |
|---|---|
| 제품 정본 | `/home/codexctl/workspace/sswcenter-3-0` |
| Git branch | `main` |
| Git HEAD 당시 기준 | `059ecf3dbfb54ac0a896303702d74ef190f8d984` |
| W2 승인 봉인 | `review/evidence/W2_20260817_USER_APPROVAL_SEAL.md` |
| W2 승인 봉인 SHA-256 | `e0d5da50721f4e7342edcd84a3a0adedb08b4d9e33c41abaa9c1a5c8eea5b6ab` |
| W2 reviewed manifest | `review/evidence/W2_20260817_CURRENT_CANDIDATE_MANIFEST.sha256` |
| W2 manifest entry / SHA-256 | `98` / `9b549c3233505413f548232842d1d2ca8b69aa0587f65c9b5aa1936be1c2c597` |
| W2 current plan SHA-256 | `fa019fe82e369de2b90273dd9598d4d1ff73569b672ad1e3b14b9c28a84d5311` |
| 승인 대상 W3 packet | `review/packets/W3_20260817_FAST_TRACK_DECISION_PACKET.md` |
| W3 packet SHA-256 | `b0b0ecdb00fa56fb1bed58cfd0af60cf9260c06d5b420c70ee9ebc95e5af8e47` |

## 확정 결정

| ID | 확정값 |
|---|---|
| W3-01 | `FILE_ONLY` |
| W3-02 | `SINGLE_STATEFUL_WORKSPACE` |
| W3-03 | `STABLE_MAPPING_ONLY` |
| W3-04 | `UNIQUE_ONLY_ELSE_REVIEW` |
| W3-05 | `DUAL_IDENTITY` |
| W3-06 | `RAW_ROWS_PLUS_DERIVED_GROUP` |
| W3-07 | `W3_PRIVATE_CONTENT_RECEIPT_TYPED_LINK` |
| W3-08 | `VERSIONED_MANUAL_SUPPLEMENT` |
| W3-09 | `REVIEW_PENDING` |

## 이 승인으로 닫힌 계약

- 초기 RFID 입력은 file-only이며 내부 수집 API를 열지 않는다.
- 한 workspace 안에서 계획·확정 상태와 preview·confirm command를 구분한다.
- 승인된 유일·유효 stable mapping만 직원 자동매칭에 사용한다.
- 계약·인정·배정·대상일·서비스·시간 조건을 모두 통과한 후보가 정확히 하나일 때만
  수급자·서비스·일정을 자동매칭한다.
- receipt 안 물리 원본행 주소, source snapshot identity, 업무 occurrence identity를
  분리한다. row number나 운영체제 파일명은 durable 업무키가 아니다.
- 모든 원본행을 보존하고 승인된 식별자·결정적 signature가 있을 때만 파생 그룹을 만든다.
- W3 private immutable content → receipt → import run → typed FK 경계만 먼저 연다.
- 시작전송 보완은 RFID 원본을 고치지 않고 연결된 versioned manual supplement로 누적한다.
- 30분 정확한 중간값과 5분 계획후보 동률은 자동선택 0건인 `REVIEW_PENDING`이다.

## 구현 게이트

1. 승인값을 정본과 새 W3 current plan에 반영한다.
2. 실제 header를 발명하지 않는 가명 semantic sample·expected와 blocked profile을
   hash manifest로 고정한다.
3. RED-A에서 영속성 없는 `propose_plan_adjustment(...)` 계약과 구현만 닫는다.
4. RED-B에서 0028 source-intake foundation 계약을 먼저 실패로 관찰한 뒤 migration,
   model, postcheck와 PostgreSQL lifecycle을 구현한다.
5. 실제 workbook profile이 승인될 때까지 parser는 `BLOCKED_HEADER_PROFILE_MISSING`으로
   유지한다.
6. parser 뒤에 matcher, APPLY/reconciliation, command/API/UI 순서로 진행한다.

## W2 봉인과 전진 변경

- W2 reviewed manifest 98개와 W2 승인 봉인·최종보고서는 당시 후보의 역사 증거다.
- W2 current plan과 W3 의사결정 패킷은 사후 수정하지 않는다.
- W3 승인 뒤 정본·제품 경로가 의도적으로 전진하면 현재 바이트가 W2 98-path
  manifest와 같다고 주장하지 않는다. W2 봉인 당시 exact였다는 사실은 그대로 유지한다.
- W3 변경은 새 W3 plan·sample manifest·후속 candidate manifest에서 별도로 추적한다.
- stage, commit, merge, push, branch/worktree 변경은 이 승인에 포함되지 않는다.

## 비범위와 남은 증거

- W4 계산·청구·수납은 포함하지 않는다.
- W5 범용 파일함·OCR·공식 출력·제품 복구는 포함하지 않는다.
- 실제 공단 일정·RFID workbook의 sheet명, header명, 필수열, 자료형은 아직 근거가 없다.
  승인된 가명 실형상 profile을 얻기 전에는 parser-ready `.xlsx`를 만들거나 통과로
  주장하지 않는다.
- W3-06 파생 grouping signature, 상세 ACL·보존기간·GC와 세부 UX command는 각 후속
  RED와 승인된 sample 근거로만 구체화한다.
