"""Stable W1E care-assignment error codes and messages."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.domains.recipient.errors import RecipientDomainError

W1E_ADVISORY_LOCK_LOSS_SQLSTATE = "55P03"
W1E_ADVISORY_LOCK_LOSS_MESSAGE = "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"

STABLE_CODES: frozenset[str] = frozenset(
    {
        "CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD",
        "CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD",
        "CARE_ASSIGNMENT_STAFF_INELIGIBLE",
        "CARE_ASSIGNMENT_FAMILY_RELATIONSHIP_REQUIRED",
        "CARE_ASSIGNMENT_PERIOD_CONFLICT",
        "CARE_ASSIGNMENT_CONCURRENT_CONFLICT",
        "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN",
    }
)
ERROR_CODES = STABLE_CODES

MESSAGES: dict[str, str] = {
    "RECIPIENT_NOT_FOUND": "수급자를 찾을 수 없습니다.",
    "CONTRACT_NOT_FOUND": "계약을 찾을 수 없습니다.",
    "CARE_ASSIGNMENT_NOT_FOUND": "배정을 찾을 수 없습니다.",
    "CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD": "배정기간이 계약기간을 벗어납니다.",
    "CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD": "배정기간이 재직기간을 벗어납니다.",
    "CARE_ASSIGNMENT_STAFF_INELIGIBLE": "배정 요건을 충족하지 않는 직원입니다.",
    "CARE_ASSIGNMENT_FAMILY_RELATIONSHIP_REQUIRED": "가족요양은 관계를 입력해야 합니다.",
    "CARE_ASSIGNMENT_PERIOD_CONFLICT": "같은 계약·직원의 배정기간이 겹칩니다.",
    "CARE_ASSIGNMENT_CONCURRENT_CONFLICT": (
        "다른 요청과 배정기간이 충돌했습니다. 최신 정보를 다시 확인하세요."
    ),
    "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN": "유효 배정을 고아로 만드는 계약 변경입니다.",
    "ROW_VERSION_CONFLICT": "다른 사용자가 먼저 변경했습니다. 최신 정보를 다시 불러오세요.",
    "VALIDATION_ERROR": "입력값을 확인하세요.",
    "UNEXPECTED_SERVER_ERROR": "요청을 처리하지 못했습니다.",
}


def iter_dbapi_exception_layers(error: BaseException) -> Iterator[object]:
    """Yield SQLAlchemy and nested DBAPI layers once each.

    ``orig`` is inspected even when it is not a ``BaseException``.  SQLAlchemy
    attaches the DBAPI payload there, and tests/drivers may expose a plain
    object with ``sqlstate``/``diag`` instead of a live exception instance.
    """

    seen: set[int] = set()
    current: object | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        original = getattr(current, "orig", None)
        if original is not None and id(original) not in seen:
            current = original
            continue
        if isinstance(current, BaseException):
            cause = current.__cause__
            if isinstance(cause, BaseException):
                current = cause
                continue
            if current.__suppress_context__:
                break
            context = current.__context__
            current = context if isinstance(context, BaseException) else None
            continue
        current = None


def sqlstate_of_dbapi_error(error: BaseException) -> str | None:
    for layer in iter_dbapi_exception_layers(error):
        sqlstate = getattr(layer, "sqlstate", None)
        if sqlstate is None:
            sqlstate = getattr(layer, "pgcode", None)
        if sqlstate is None:
            diagnostics = getattr(layer, "diag", None)
            sqlstate = getattr(diagnostics, "sqlstate", None)
        if sqlstate is not None:
            return str(sqlstate)
    return None


def message_primary_of_dbapi_error(error: BaseException) -> str | None:
    for layer in iter_dbapi_exception_layers(error):
        diagnostics = getattr(layer, "diag", None)
        message = getattr(diagnostics, "message_primary", None)
        if message is not None:
            return str(message)
    return None


def _layer_advisory_lock_loss_message(layer: object) -> str | None:
    """Return one layer's primary message without scanning wrapper or SQL text.

    A full ``str(layer)`` can include the executed statement, parameters, or
    retry wrappers.  Substring matching that blob would relabel an unrelated
    ``55P03`` lock timeout as a care-assignment conflict whenever the SQL or
    wrapper happened to mention ``CARE_ASSIGNMENT_CONCURRENT_CONFLICT``.
    """

    diagnostics = getattr(layer, "diag", None)
    message = getattr(diagnostics, "message_primary", None)
    if message is not None:
        return str(message)
    rendered = str(layer).strip()
    if not rendered:
        return None
    first_line = rendered.splitlines()[0].strip()
    if first_line == W1E_ADVISORY_LOCK_LOSS_MESSAGE:
        return first_line
    if first_line.startswith("("):
        separator = first_line.find(") ")
        if separator != -1:
            remainder = first_line[separator + 2 :].strip()
            if remainder == W1E_ADVISORY_LOCK_LOSS_MESSAGE:
                return remainder
    return None


def is_w1e_advisory_lock_loss(error: BaseException) -> bool:
    """True only for the W1E non-waiting advisory-lock RAISE.

    Application connections set ``lock_timeout = '5s'``.  Unrelated
    ``55P03`` outcomes such as ``canceling statement due to lock timeout``
    or ``FOR UPDATE NOWAIT`` must not be relabeled as a care-assignment
    conflict.  The current helpers raise SQLSTATE ``55P03`` with the exact
    message ``CARE_ASSIGNMENT_CONCURRENT_CONFLICT``.
    """

    for layer in iter_dbapi_exception_layers(error):
        sqlstate = getattr(layer, "sqlstate", None)
        if sqlstate is None:
            sqlstate = getattr(layer, "pgcode", None)
        diagnostics = getattr(layer, "diag", None)
        if sqlstate is None:
            sqlstate = getattr(diagnostics, "sqlstate", None)
        message = _layer_advisory_lock_loss_message(layer)
        if (
            sqlstate is not None
            and str(sqlstate) == W1E_ADVISORY_LOCK_LOSS_SQLSTATE
            and message == W1E_ADVISORY_LOCK_LOSS_MESSAGE
        ):
            return True
    return False


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
