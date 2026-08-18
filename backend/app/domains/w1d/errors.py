"""Stable W1D error codes and messages."""

from __future__ import annotations

from typing import Any

from app.domains.recipient.errors import RecipientDomainError

STABLE_CODES: frozenset[str] = frozenset(
    {
        "CONTRACT_SERVICE_PERIOD_CONFLICT",
        "CONTRACT_SERVICE_GROUP_PERIOD_CONFLICT",
        "CONTRACT_REACTIVATION_FORBIDDEN",
        "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN",
        "CARE_ASSIGNMENT_CONCURRENT_CONFLICT",
    }
)
ERROR_CODES = STABLE_CODES

MESSAGES: dict[str, str] = {
    "RECIPIENT_NOT_FOUND": "수급자를 찾을 수 없습니다.",
    "CONTRACT_NOT_FOUND": "계약을 찾을 수 없습니다.",
    "CONTRACT_SERVICE_PERIOD_CONFLICT": "동일 서비스의 계약 기간이 겹칩니다.",
    "CONTRACT_SERVICE_GROUP_PERIOD_CONFLICT": ("다른 서비스 그룹의 계약 기간이 겹칩니다."),
    "CONTRACT_REACTIVATION_FORBIDDEN": "종료된 계약은 재활성화할 수 없습니다.",
    "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN": "유효 배정을 고아로 만드는 계약 변경입니다.",
    "CARE_ASSIGNMENT_CONCURRENT_CONFLICT": (
        "다른 요청과 배정기간이 충돌했습니다. 최신 정보를 다시 확인하세요."
    ),
    "SERVICE_TYPE_NOT_FOUND": "서비스 유형을 찾을 수 없습니다.",
    "ROW_VERSION_CONFLICT": ("다른 사용자가 먼저 변경했습니다. 최신 정보를 다시 불러오세요."),
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
    field_errors = []
    if field is not None:
        field_errors.append({"field": field, "message": message})
    return RecipientDomainError(
        code=code,
        status_code=status_code,
        message=message,
        field_errors=field_errors,
        details=details or {},
    )
