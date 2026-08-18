"""Pure fail-closed W3 candidate matching.

Callers must supply approved stable-mapping and validity facts.  The matcher
does not search by display text or contact projections and performs no writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MatchStatus(StrEnum):
    AUTO_MATCH = "AUTO_MATCH"
    REVIEW_PENDING = "REVIEW_PENDING"


@dataclass(frozen=True, slots=True)
class StableStaffMappingCandidate:
    mapping_id: int
    staff_id: int
    source_external_number: str
    mapping_active: bool
    employment_valid: bool
    care_worker_position_valid: bool

    @property
    def fully_valid(self) -> bool:
        return (
            self.mapping_id > 0
            and self.staff_id > 0
            and bool(self.source_external_number)
            and self.source_external_number == self.source_external_number.strip()
            and self.mapping_active
            and self.employment_valid
            and self.care_worker_position_valid
        )


@dataclass(frozen=True, slots=True)
class ScheduleMatchCandidate:
    schedule_id: int
    staff_id: int
    recipient_certification_valid: bool
    contract_valid: bool
    assignment_valid: bool
    target_date_valid: bool
    service_valid: bool
    time_window_valid: bool
    conflict_free: bool
    manual_protection_clear: bool
    month_unfinalized: bool

    @property
    def fully_valid(self) -> bool:
        return (
            self.schedule_id > 0
            and self.staff_id > 0
            and self.recipient_certification_valid
            and self.contract_valid
            and self.assignment_valid
            and self.target_date_valid
            and self.service_valid
            and self.time_window_valid
            and self.conflict_free
            and self.manual_protection_clear
            and self.month_unfinalized
        )


@dataclass(frozen=True, slots=True)
class MatchRequest:
    source_occurrence_identity: str
    source_staff_external_number: str | None
    staff_mapping_candidates: tuple[StableStaffMappingCandidate, ...]
    schedule_candidates: tuple[ScheduleMatchCandidate, ...]


@dataclass(frozen=True, slots=True)
class MatchDecision:
    source_occurrence_identity: str
    status: MatchStatus
    reason: str
    staff_id: int | None
    schedule_id: int | None
    valid_candidate_ids: tuple[int, ...]
    automatic_match_count: int
    business_write_count: int = 0


def _review(
    request: MatchRequest,
    reason: str,
    *,
    staff_id: int | None = None,
    valid_candidate_ids: tuple[int, ...] = (),
) -> MatchDecision:
    return MatchDecision(
        source_occurrence_identity=request.source_occurrence_identity,
        status=MatchStatus.REVIEW_PENDING,
        reason=reason,
        staff_id=staff_id,
        schedule_id=None,
        valid_candidate_ids=valid_candidate_ids,
        automatic_match_count=0,
    )


def match_unique_schedule(request: MatchRequest) -> MatchDecision:
    """Adopt only one valid stable staff mapping and one valid schedule candidate."""

    if not request.source_occurrence_identity:
        raise ValueError("source occurrence identity is required")
    if not request.source_staff_external_number:
        return _review(request, "STAFF_STABLE_KEY_MISSING")

    valid_staff = tuple(
        sorted(
            (
                candidate
                for candidate in request.staff_mapping_candidates
                if candidate.fully_valid
                and candidate.source_external_number == request.source_staff_external_number
            ),
            key=lambda candidate: (candidate.mapping_id, candidate.staff_id),
        )
    )
    if not valid_staff:
        return _review(request, "STAFF_MATCH_ZERO")
    if len(valid_staff) != 1:
        return _review(request, "STAFF_MATCH_MANY")

    staff_id = valid_staff[0].staff_id
    valid_schedules = tuple(
        sorted(
            (
                candidate
                for candidate in request.schedule_candidates
                if candidate.staff_id == staff_id and candidate.fully_valid
            ),
            key=lambda candidate: candidate.schedule_id,
        )
    )
    candidate_ids = tuple(candidate.schedule_id for candidate in valid_schedules)
    if not valid_schedules:
        return _review(request, "SCHEDULE_MATCH_ZERO", staff_id=staff_id)
    if len(valid_schedules) != 1:
        return _review(
            request,
            "SCHEDULE_MATCH_MANY",
            staff_id=staff_id,
            valid_candidate_ids=candidate_ids,
        )

    return MatchDecision(
        source_occurrence_identity=request.source_occurrence_identity,
        status=MatchStatus.AUTO_MATCH,
        reason="UNIQUE_VALID_CANDIDATE",
        staff_id=staff_id,
        schedule_id=valid_schedules[0].schedule_id,
        valid_candidate_ids=candidate_ids,
        automatic_match_count=1,
    )
