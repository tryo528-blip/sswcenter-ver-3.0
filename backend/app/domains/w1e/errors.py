"""Stable W1E caregiver-assignment error codes and messages."""

from __future__ import annotations

from typing import Any

from app.domains.recipient.errors import RecipientDomainError

STABLE_CODES: frozenset[str] = frozenset(
    {
        "CARE_ASSIGNMENT_PERIOD_CONFLICT",
        "CARE_ASSIGNMENT_STAFF_INELIGIBLE",
        "CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD",
        "CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD",
        "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN",
        "CARE_ASSIGNMENT_EMPLOYMENT_ORPHAN_FORBIDDEN",
        "CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN",
        "CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN",
    }
)
ERROR_CODES = STABLE_CODES

MESSAGES: dict[str, str] = {
    "RECIPIENT_NOT_FOUND": "수급자를 찾을 수 없습니다.",
    "CONTRACT_NOT_FOUND": "계약을 찾을 수 없습니다.",
    "CARE_ASSIGNMENT_NOT_FOUND": "배정을 찾을 수 없습니다.",
    "CARE_ASSIGNMENT_PERIOD_CONFLICT": "같은 계약·직원의 배정 기간이 겹칩니다.",
    "CARE_ASSIGNMENT_STAFF_INELIGIBLE": "선택한 직원은 해당 기간의 요양보호사 자격이 없습니다.",
    "CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD": "배정 기간이 계약 기간을 벗어납니다.",
    "CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD": "배정 기간이 재직 기간을 벗어납니다.",
    "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN": "배정을 남기는 계약 변경은 허용되지 않습니다.",
    "CARE_ASSIGNMENT_EMPLOYMENT_ORPHAN_FORBIDDEN": "배정을 남기는 재직 변경은 허용되지 않습니다.",
    "CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN": "배정을 남기는 직종 변경은 허용되지 않습니다.",
    "CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN": (
        "배정을 남기는 제공자격 변경은 허용되지 않습니다."
    ),
    "ROW_VERSION_CONFLICT": "다른 사용자가 먼저 변경했습니다. 최신 정보를 다시 불러오세요.",
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
