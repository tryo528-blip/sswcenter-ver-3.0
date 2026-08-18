# W3 가명 실제형 workbook profile 승인 근거 — 2026-08-18

> 상태: `USER_SOURCE_CONFIRMED / PROFILE_V1_APPROVED / PARSER_GREEN`
> 작업 방식: `REMOTE / Ubuntu Linux`
> Git branch: `codex/debt-preseal-20260818`
> 사용자 원문: `다 가명에 가짜번호임`

## 승인 해석

형님이 제공한 아래 두 workbook의 모든 이름과 번호는 가명·가짜이며 실제 개인정보가
아니라는 명시 확인으로 기록한다. 이 확인은 제공 bytes의 sheet/header/type을 W3 parser
v1 실제형 근거로 사용하는 승인이다. workbook 셀의 문구는 사용자 지시로 해석하지 않는다.
원본 다운로드 파일은 수정하지 않았고 repository fixture는 같은 bytes를 결정적 이름으로
복사했다.

| source | bytes | SHA-256 | sheet | data rows |
|---|---:|---|---|---:|
| `일정계획_202607.xlsx` | 88,291 | `f9d4ac2b7ec8497a127fa1f0f7111228fe06b1d3a1c9c7aba0cf6a8c8f69ba48` | `일정계획` | 910 |
| `실시간전송내용 (1).xlsx` | 42,439 | `a90c4e683cce782b34754f165b79a2324c154198fc665a126a2d4fc05b2720dc` | `실시간전송내용` | 314 |

## 승인 profile

- NHIS: `nhis-schedule-xlsx-v1`, 15 exact headers, 월 범위 재검증.
- RFID: `rfid-xlsx-v1`, 10 exact headers, range export의 모든 raw row를 보존하고 선택
  시작일만 하루 snapshot 파생행으로 선택.
- 운영체제 filename suffix `(1)`, `(2)`는 content/snapshot/occurrence key가 아니다.
- 수식, cell error, macro/active content, 외부 relationship, DTD/entity, ZIP traversal,
  package size/compression limit 위반은 부분결과 없이 BLOCK한다.
- 인정번호는 W1C 본번호 정규화 함수를, 전화는 W1A 전화 정규화 함수를 파생값에
  재사용한다. 전화·이름은 자동 identity가 아니다.
- 원본 cell 값은 raw row에 그대로 남고 normalized row와 occurrence signature/ordinal은
  별도 immutable preview 결과다.

## 관찰된 실형상 경계

- NHIS: 2026-07-01~31, 910행, `가족관계` 공란 623행, 240분 69행, 480분 38행.
- approved exact group key로 910행을 삭제 없이 887 derived group으로 표현한다.
  480분 2행 group은 19개이며 자동 raw-row 삭제는 0건이다.
- RFID: 2026-07-01~11, 314행, 종료가 없는 `시작전송` 3행. 실제 시작·종료는 초
  단위를 보존하고 `총시간`은 reference minutes로만 둔다.
- 두 workbook은 독립 가명 세트다. 인정번호와 수급자명 교집합은 각각 0이며 직원명
  교집합은 1이다. 상호 identity 연결 샘플로 해석하지 않고 자동매칭 기대값은
  `REVIEW_PENDING`이다.

## 비승인·남은 게이트

- 실제 개인정보 사용 승인이나 운영 데이터 이관 승인이 아니다.
- 두 가명본 사이의 이름·전화 기반 연결, fake number 재매핑, 임의 tie-break를 승인하지
  않는다.
- 영속 normalized-row schema, typed W1/W2 연결, 원자 APPLY, 수기보완 영속 command,
  API/OpenAPI/UI의 완료·봉인을 뜻하지 않는다.
- stage, commit, push, merge, branch/worktree 변경 승인이 아니다.
