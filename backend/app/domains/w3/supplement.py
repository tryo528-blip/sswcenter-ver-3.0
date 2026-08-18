"""Pure planner for append-only manual supplements to start-only RFID events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SupplementAction(StrEnum):
    CREATE = "CREATE"
    CANCEL = "CANCEL"
    REPLACE = "REPLACE"


class SupplementResult(StrEnum):
    VERSION_CREATED = "VERSION_CREATED"
    CANCEL_EVENT_CREATED = "CANCEL_EVENT_CREATED"
    REPLACEMENT_VERSION_CREATED = "REPLACEMENT_VERSION_CREATED"
    REJECT_409 = "REJECT_409"
    REJECT_FINALIZED_MONTH = "REJECT_FINALIZED_MONTH"


@dataclass(frozen=True, slots=True)
class SupplementCommand:
    source_occurrence_identity: str
    source_event_state: str
    source_actual_start: datetime
    action: SupplementAction
    expected_row_version: int
    current_row_version: int
    currently_active: bool
    proposed_actual_end: datetime | None
    reason: str
    month_finalized: bool


@dataclass(frozen=True, slots=True)
class SupplementEvent:
    action: SupplementAction
    row_version: int
    prior_row_version: int | None
    actual_end: datetime | None
    reason: str


@dataclass(frozen=True, slots=True)
class SupplementPlan:
    result: SupplementResult
    event_to_append: SupplementEvent | None
    source_bytes_changed: bool = False
    history_delete_count: int = 0
    planned_event_count: int = 0
    business_write_count: int = 0


def _reject(result: SupplementResult) -> SupplementPlan:
    return SupplementPlan(result=result, event_to_append=None)


def _aware_whole_second(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    if value.microsecond:
        raise ValueError(f"{label} must preserve whole-second precision")


def plan_manual_supplement(command: SupplementCommand) -> SupplementPlan:
    """Validate one command and return the single event that may be appended."""

    if not command.source_occurrence_identity:
        raise ValueError("source occurrence identity is required")
    if command.source_event_state != "START_ONLY":
        raise ValueError("manual supplement requires a START_ONLY source event")
    _aware_whole_second(command.source_actual_start, "source_actual_start")
    if command.expected_row_version < 0 or command.current_row_version < 0:
        raise ValueError("row versions cannot be negative")
    if command.expected_row_version != command.current_row_version:
        return _reject(SupplementResult.REJECT_409)
    if command.month_finalized:
        return _reject(SupplementResult.REJECT_FINALIZED_MONTH)
    if not command.reason or command.reason != command.reason.strip():
        raise ValueError("reason must be nonblank without edge whitespace")

    if command.action is SupplementAction.CREATE:
        if command.current_row_version != 0 or command.currently_active:
            raise ValueError("CREATE requires no prior supplement")
        result = SupplementResult.VERSION_CREATED
    elif command.action is SupplementAction.CANCEL:
        if command.current_row_version == 0 or not command.currently_active:
            raise ValueError("CANCEL requires an active supplement")
        if command.proposed_actual_end is not None:
            raise ValueError("CANCEL cannot supply a replacement end")
        result = SupplementResult.CANCEL_EVENT_CREATED
    elif command.action is SupplementAction.REPLACE:
        if command.current_row_version == 0:
            raise ValueError("REPLACE requires prior supplement history")
        result = SupplementResult.REPLACEMENT_VERSION_CREATED
    else:  # pragma: no cover - StrEnum closes this branch for typed callers.
        raise ValueError("unsupported supplement action")

    if command.action is not SupplementAction.CANCEL:
        if command.proposed_actual_end is None:
            raise ValueError("supplement end is required")
        _aware_whole_second(command.proposed_actual_end, "proposed_actual_end")
        if command.proposed_actual_end <= command.source_actual_start:
            raise ValueError("supplement end must be after source start")

    event = SupplementEvent(
        action=command.action,
        row_version=command.current_row_version + 1,
        prior_row_version=command.current_row_version or None,
        actual_end=command.proposed_actual_end,
        reason=command.reason,
    )
    return SupplementPlan(
        result=result,
        event_to_append=event,
        planned_event_count=1,
    )
