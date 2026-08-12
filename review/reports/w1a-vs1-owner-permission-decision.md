# W1A-VS1 직원 권한 사용자 결정

> 결정일: 2026-07-26 KST
>
> 결정자: 사용자
>
> 적용 대상: W1A 직원 vertical slice와 이후 동일 직원정보 기능

## 확정 내용

- `STAFF_VIEW`는 직원 목록·상세의 masked 조회만 허용한다.
- `STAFF_MANAGE`는 masked 조회와 일반 직원정보, 재직, 직종, 업무역할의
  생성·종료·정정을 허용한다.
- 주민등록번호 최초 입력, 향후 정정, 전체번호 reveal은 ADMIN과
  `STAFF_MANAGE`에 동일하게 허용한다.
- 신규 일반직원 등록은 주민번호 필수 원자 command이며 ADMIN과
  `STAFF_MANAGE`에 동일하게 허용한다.
- `birth_date`, `sex_code`는 주민번호 업무검증과 결합되어 있으므로 일반정보
  독립 수정에서 제외하고, 향후 주민번호 정정 command가 구현될 때 주민번호와 함께
  원자적으로 처리한다.
- 기존 USER에게 `STAFF_VIEW`나 `STAFF_MANAGE`를 자동 부여하지 않는다.
- 정본의 “관리자 reveal”은 이 owner decision에 따라 `STAFF_MANAGE`까지 확장한다.
  current PIN·CSRF·`no-store`·성공당 access event 1건 조건은 동일하게 유지한다.

## 현재 slice 경계

W1A-VS1은 정본 test matrix §12에 있는 신규 직원의 주민번호 입력과
ADMIN·`STAFF_MANAGE` reveal을 구현한다. 기존 민감행의 정정과 민감행 0개인 기존
직원의 사후 입력 API·UI는 이번 slice에서 구현하지 않지만, 후속 구현 시에도
ADMIN·`STAFF_MANAGE` 동등 권한이라는 위 정책을 따른다.
