"""Stable W2 error envelope inputs."""

from __future__ import annotations

from typing import Any

from app.domains.recipient.errors import RecipientDomainError

MESSAGES: dict[str, str] = {
    "RECIPIENT_NOT_FOUND": "수급자를 찾을 수 없습니다.",
    "STAFF_NOT_FOUND": "직원을 찾을 수 없습니다.",
    "SERVICE_TYPE_NOT_FOUND": "서비스 유형을 찾을 수 없습니다.",
    "PROFESSIONAL_ROLE_REQUIRED": "사회복지사 또는 간호사만 담당할 수 있습니다.",
    "PROFESSIONAL_ASSIGNMENT_NOT_FOUND": "월별 전문직 담당을 찾을 수 없습니다.",
    "PROFESSIONAL_ASSIGNMENT_CONFLICT": "월별 전문직 담당이 먼저 변경되었습니다.",
    "PROFESSIONAL_ASSIGNMENT_PERIOD_INVALID": "담당기간은 해당 서비스월 안이어야 합니다.",
    "PROFESSIONAL_ASSIGNMENT_OUTSIDE_EMPLOYMENT": "담당기간이 재직기간 밖입니다.",
    "PROFESSIONAL_ASSIGNMENT_POSITION_REQUIRED": (
        "담당기간 전체에 사회복지사 또는 간호사 직종이어야 합니다."
    ),
    "SERVICE_PLAN_NOTICE_NOT_FOUND": "급여계획서 통보 기록을 찾을 수 없습니다.",
    "SERVICE_PLAN_CONTRACT_NOT_FOUND": "연결할 수급자 계약을 찾을 수 없습니다.",
    "SERVICE_PLAN_CONTRACT_MISMATCH": "해당 수급자의 계약만 연결할 수 있습니다.",
    "SERVICE_PLAN_OUTSIDE_CONTRACT": "적용기간이 유효 계약기간을 벗어납니다.",
    "SERVICE_PLAN_OUTSIDE_CERTIFICATION": "적용기간을 보장하는 인정기간이 없습니다.",
    "SERVICE_PLAN_NOTICE_REPLACED": "이미 정정된 급여계획서 통보 기록입니다.",
    "SCHEDULE_NOT_FOUND": "일정을 찾을 수 없습니다.",
    "SCHEDULE_MONTH_FINALIZED": "확정된 월의 일정은 변경할 수 없습니다.",
    "SCHEDULE_MONTH_REOPEN_FORBIDDEN": "확정된 월은 다시 열 수 없습니다.",
    "SCHEDULE_OVERLAP": "수급자 또는 직원 일정이 겹칩니다.",
    "SCHEDULE_STAFF_COUNT_INVALID": "서비스 종류에 맞는 요양보호사 수를 배정해야 합니다.",
    "SCHEDULE_STAFF_FACT_INVALID": "담당 직원의 재직 사실을 찾을 수 없습니다.",
    "SCHEDULE_OUTSIDE_EMPLOYMENT": "재직기간 밖 일정이 있어 월을 확정할 수 없습니다.",
    "SCHEDULE_CARE_WORKER_POSITION_REQUIRED": (
        "요양보호사 직종기간 밖 일정이 있어 월을 확정할 수 없습니다."
    ),
    "SCHEDULE_OUTSIDE_QUALIFICATION": "자격기간 밖 일정이 있어 월을 확정할 수 없습니다.",
    "ROW_VERSION_CONFLICT": "다른 사용자가 먼저 변경했습니다. 최신 정보를 확인하세요.",
    "TODO_NOT_FOUND": "개인 할 일을 찾을 수 없습니다.",
    "TODO_LIST_REVISION_CONFLICT": "개인 할 일 순서가 먼저 변경되었습니다.",
    "TODO_REORDER_SET_MISMATCH": "현재 할 일 전체를 정확히 한 번씩 보내야 합니다.",
    "CARD_NOT_FOUND": "업무카드를 찾을 수 없습니다.",
    "CARD_ACCESS_FORBIDDEN": "본인에게 배정된 업무카드만 처리할 수 있습니다.",
    "CARD_ALREADY_CLOSED": "이미 닫힌 업무카드는 다시 열 수 없습니다.",
    "ADMIN_CARD_MUTATION_FORBIDDEN": "관리자는 업무카드를 대신 처리할 수 없습니다.",
    "ADMIN_CARD_ASSIGNEE_FORBIDDEN": "관리자에게는 업무카드를 배정할 수 없습니다.",
    "CARD_OCCURRENCE_CONFLICT": "같은 원천의 업무카드가 이미 존재합니다.",
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
