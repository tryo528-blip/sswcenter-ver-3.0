from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

RULE_VERSION_V1 = "w3-rfid-adjustment-v1"
SERVICE_GRID_SECONDS = 30 * 60
PLAN_GRID_SECONDS = 5 * 60
LONGER_KEEP_THRESHOLD_SECONDS = 1_799
SHORTAGE_MARKER = "ACTUAL_SHORTAGE_YELLOW_DOT"


class ProposalStatus(StrEnum):
    PROPOSED = "PROPOSED"
    REVIEW_PENDING = "REVIEW_PENDING"


@dataclass(frozen=True, slots=True)
class PlanAdjustmentInput:
    planned_start: datetime
    planned_end: datetime
    actual_start: datetime
    actual_end: datetime
    rule_version: str


@dataclass(frozen=True, slots=True)
class PlanWindowCandidate:
    start: datetime
    end: datetime
    total_error_seconds: int


@dataclass(frozen=True, slots=True)
class PlanAdjustmentProposal:
    rule_version: str
    status: ProposalStatus
    reason: str
    service_seconds: int | None
    shortage_seconds: int
    markers: tuple[str, ...]
    candidate_duration_seconds: tuple[int, ...]
    candidate_start: datetime | None
    candidate_end: datetime | None
    candidate_windows: tuple[PlanWindowCandidate, ...]
    minimum_error_seconds: int | None
    plan_write_count: int = 0
    event_write_count: int = 0
    audit_write_count: int = 0


def _whole_seconds(later: datetime, earlier: datetime) -> int:
    seconds = (later - earlier).total_seconds()
    if not seconds.is_integer():
        raise ValueError("timestamps must use whole-second precision")
    return int(seconds)


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _validate(request: PlanAdjustmentInput) -> tuple[int, int]:
    if request.rule_version != RULE_VERSION_V1:
        raise ValueError(f"unsupported rule_version: {request.rule_version}")

    timestamps = (
        request.planned_start,
        request.planned_end,
        request.actual_start,
        request.actual_end,
    )
    if not all(_is_aware(value) for value in timestamps):
        raise ValueError("planned and actual timestamps must be timezone-aware")
    if any(value.microsecond for value in timestamps):
        raise ValueError("planned and actual timestamps must use whole seconds")
    if request.planned_end <= request.planned_start:
        raise ValueError("planned_end must be after planned_start")
    if request.actual_end <= request.actual_start:
        raise ValueError("actual_end must be after actual_start")

    for label, value in (
        ("planned_start", request.planned_start),
        ("planned_end", request.planned_end),
    ):
        if value.minute % 5 or value.second:
            raise ValueError(f"{label} must be on the five-minute planned grid")

    planned_seconds = _whole_seconds(request.planned_end, request.planned_start)
    actual_seconds = _whole_seconds(request.actual_end, request.actual_start)
    if planned_seconds % SERVICE_GRID_SECONDS:
        raise ValueError("planned service duration must use the thirty-minute grid")
    return planned_seconds, actual_seconds


def _duration_choice(
    *, planned_seconds: int, actual_seconds: int
) -> tuple[int | None, tuple[int, ...], str | None]:
    if actual_seconds == planned_seconds:
        return planned_seconds, (planned_seconds,), None

    if actual_seconds > planned_seconds:
        excess_seconds = actual_seconds - planned_seconds
        if excess_seconds <= LONGER_KEEP_THRESHOLD_SECONDS:
            return planned_seconds, (planned_seconds,), None

        lower = actual_seconds // SERVICE_GRID_SECONDS * SERVICE_GRID_SECONDS
        remainder = actual_seconds % SERVICE_GRID_SECONDS
        if remainder == 0:
            return lower, (lower,), None
        upper = lower + SERVICE_GRID_SECONDS
        if remainder == SERVICE_GRID_SECONDS // 2:
            return None, (lower, upper), "SERVICE_DURATION_MIDPOINT"
        selected = lower if remainder < SERVICE_GRID_SECONDS // 2 else upper
        return selected, (selected,), None

    selected = actual_seconds // SERVICE_GRID_SECONDS * SERVICE_GRID_SECONDS
    if selected <= 0:
        return None, (), "NO_POSITIVE_SERVICE_DURATION"
    return selected, (selected,), None


def _floor_plan_grid(value: datetime) -> datetime:
    return value.replace(
        minute=value.minute - value.minute % 5,
        second=0,
        microsecond=0,
    )


def _ceil_plan_grid(value: datetime) -> datetime:
    floor = _floor_plan_grid(value)
    return floor if floor == value else floor + timedelta(seconds=PLAN_GRID_SECONDS)


def _minimum_error_windows(
    request: PlanAdjustmentInput, service_seconds: int
) -> tuple[PlanWindowCandidate, ...]:
    duration = timedelta(seconds=service_seconds)
    second_anchor = request.actual_end - duration
    lower_anchor = min(request.actual_start, second_anchor)
    upper_anchor = max(request.actual_start, second_anchor)
    cursor = _floor_plan_grid(lower_anchor)
    final = _ceil_plan_grid(upper_anchor)
    candidates: list[PlanWindowCandidate] = []

    while cursor <= final:
        end = cursor + duration
        total_error_seconds = int(
            abs((cursor - request.actual_start).total_seconds())
            + abs((end - request.actual_end).total_seconds())
        )
        candidates.append(
            PlanWindowCandidate(
                start=cursor,
                end=end,
                total_error_seconds=total_error_seconds,
            )
        )
        cursor += timedelta(seconds=PLAN_GRID_SECONDS)

    minimum = min(candidate.total_error_seconds for candidate in candidates)
    return tuple(candidate for candidate in candidates if candidate.total_error_seconds == minimum)


def propose_plan_adjustment(
    request: PlanAdjustmentInput,
) -> PlanAdjustmentProposal:
    """Return a deterministic proposal without adopting or persisting a plan.

    Exact thirty-minute midpoints and tied minimum-error five-minute windows are
    deliberately returned for review instead of receiving a hidden bias.
    """

    planned_seconds, actual_seconds = _validate(request)
    shortage_seconds = max(planned_seconds - actual_seconds, 0)
    markers = (SHORTAGE_MARKER,) if shortage_seconds else ()
    service_seconds, duration_candidates, duration_reason = _duration_choice(
        planned_seconds=planned_seconds,
        actual_seconds=actual_seconds,
    )

    if service_seconds is None:
        return PlanAdjustmentProposal(
            rule_version=request.rule_version,
            status=ProposalStatus.REVIEW_PENDING,
            reason=duration_reason or "SERVICE_DURATION_REVIEW_REQUIRED",
            service_seconds=None,
            shortage_seconds=shortage_seconds,
            markers=markers,
            candidate_duration_seconds=duration_candidates,
            candidate_start=None,
            candidate_end=None,
            candidate_windows=(),
            minimum_error_seconds=None,
        )

    windows = _minimum_error_windows(request, service_seconds)
    if len(windows) != 1:
        return PlanAdjustmentProposal(
            rule_version=request.rule_version,
            status=ProposalStatus.REVIEW_PENDING,
            reason="PLAN_WINDOW_TIE",
            service_seconds=service_seconds,
            shortage_seconds=shortage_seconds,
            markers=markers,
            candidate_duration_seconds=duration_candidates,
            candidate_start=None,
            candidate_end=None,
            candidate_windows=windows,
            minimum_error_seconds=windows[0].total_error_seconds,
        )

    selected = windows[0]
    return PlanAdjustmentProposal(
        rule_version=request.rule_version,
        status=ProposalStatus.PROPOSED,
        reason="MINIMUM_ERROR_WINDOW",
        service_seconds=service_seconds,
        shortage_seconds=shortage_seconds,
        markers=markers,
        candidate_duration_seconds=duration_candidates,
        candidate_start=selected.start,
        candidate_end=selected.end,
        candidate_windows=windows,
        minimum_error_seconds=selected.total_error_seconds,
    )
