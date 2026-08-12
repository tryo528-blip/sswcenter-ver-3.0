# W1C Independent Audit — 6d9ace1

## 판정

- 감사 후보 SHA: `6d9ace1aa48672feace09f981de0b33980f7c7dd`
- 기준 SHA: `5980602f00f47744e2f3786961c4b7d740cae76c`
- 감사 방식: exact SHA 대상 독립 read-only 검토
- 감사 결과: `W1C_AUDIT_REQUIRED_CHANGES`
- 감사자 작업표시: `McClintock`

감사자는 HEAD가 지정 SHA와 같고 작업트리가 깨끗한 상태에서 검토했으며 파일을
변경하지 않았다.

## Finding 1 — HIGH

승인금액 `bigint`가 브라우저의 일반 JSON 숫자 파싱과 JavaScript `Number` 변환을
통과하면서 PostgreSQL 최대값 `9223372036854775807`을 정확히 유지하지 못했다.
응답 OpenAPI에도 `int64` 형식이 빠져 있었다.

요구 보정:

- 응답 모델에도 `int64` 형식 명시
- 프런트 입력을 `BigInt` 범위로 검증
- JSON wire의 integer 형식은 유지하되 GET 파싱과 POST 직렬화에서 정밀도 손실 제거
- 최대 bigint의 POST→GET→UI 정확성 테스트 추가

## Finding 2 — MEDIUM

인정·등급·혜택·승인금액 replacement가 원본 행의 REPLACE 감사만 남기고 새로 생성한
기간사실 행의 CREATE 감사를 남기지 않았다.

요구 보정:

- 원본 REPLACE와 replacement CREATE 감사를 각각 기록
- 같은 transaction, 발생시각, request ID 사용
- replacement 감사의 `entity_pk`와 `after_json`에 새 사실을 기록

## 감사에서 통과한 범위

- 인정 본번호의 수급자별·전역 유일성과 불변성
- recipient-wide GiST 기간 exclusion
- 인정·등급 양방향 containment trigger
- 정확한 혜택 6종과 `GENERAL` 미생성
- DB ACL과 API 권한·CSRF 의존성
- W1B 격리 변경이 W1C GET만 차단하고 W1B 실제 API/DB 경로를 유지하는 점

이 감사 결과는 보정 전 SHA에 대한 기록이다. 보정 뒤 생성되는 새 후보 SHA는 다시
독립 검토해야 한다.
