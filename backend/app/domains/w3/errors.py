"""Stable W3 API error construction."""

from __future__ import annotations

from typing import Any

from app.domains.recipient.errors import RecipientDomainError

MESSAGES: dict[str, str] = {
    "W3_DATA_ROOT_REQUIRED": "입출력 전용 저장경로가 준비되지 않았습니다.",
    "W3_INVALID_FILE": "승인된 .xlsx 파일을 선택하세요.",
    "W3_PARSE_BLOCKED": "파일 형식 또는 내용이 승인된 입력 규칙과 다릅니다.",
    "W3_RUN_NOT_FOUND": "입력 실행을 찾을 수 없습니다.",
    "W3_RUN_STATE_INVALID": "현재 상태에서는 이 명령을 실행할 수 없습니다.",
    "W3_ROW_VERSION_CONFLICT": "입력 실행이 먼저 변경되었습니다. 최신 상태를 확인하세요.",
    "W3_PREVIEW_DIGEST_MISMATCH": "확인한 미리보기와 서버의 최신 미리보기가 다릅니다.",
    "W3_IDEMPOTENCY_CONFLICT": "같은 명령키가 다른 요청에 이미 사용되었습니다.",
    "W3_REVIEW_PENDING": "검토가 필요한 항목을 모두 해결한 뒤 적용할 수 있습니다.",
    "W3_TYPED_LINK_INVALID": "선택한 수급자·직원·계약·배정·일정 연결이 유효하지 않습니다.",
    "W3_SOURCE_DATE_MISMATCH": "입력 실행의 자료종류 또는 대상일이 일치하지 않습니다.",
    "W3_ACTUAL_WORK_NOT_FOUND": "실제근무 변경판을 찾을 수 없습니다.",
    "W3_START_ONLY_REQUIRED": "종료가 없는 시작전송만 수기 보완할 수 있습니다.",
    "W3_SUPPLEMENT_VERSION_CONFLICT": "수기 보완 이력이 먼저 변경되었습니다.",
    "W3_MONTH_FINALIZED": "확정된 월의 일정 또는 보완은 변경할 수 없습니다.",
    "W3_PLAN_REVIEW_PENDING": "계획정정 후보를 자동으로 하나 확정할 수 없습니다.",
    "W3_STORAGE_FAILURE": "입력 파일을 안전하게 보관하지 못했습니다.",
    "VALIDATION_ERROR": "입력값을 확인하세요.",
    "UNEXPECTED_SERVER_ERROR": "요청을 처리하지 못했습니다.",
}


def domain_error(
    code: str,
    status_code: int,
    *,
    field: str | None = None,
    details: dict[str, Any] | None = None,
) -> RecipientDomainError:
    message = MESSAGES.get(code, MESSAGES["UNEXPECTED_SERVER_ERROR"])
    field_errors = [] if field is None else [{"field": field, "message": message}]
    return RecipientDomainError(
        code=code,
        status_code=status_code,
        message=message,
        field_errors=field_errors,
        details=details or {},
    )
