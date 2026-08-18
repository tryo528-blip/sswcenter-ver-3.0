"""Pure versioned-reconciliation planning for a confirmed W3 snapshot."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ReconciliationStatus(StrEnum):
    APPLY_READY = "APPLY_READY"
    DUPLICATE_NOOP = "DUPLICATE_NOOP"
    CONFIRM_REQUIRED = "CONFIRM_REQUIRED"
    REVIEW_PENDING = "REVIEW_PENDING"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class AppliedFact:
    revision_id: int
    business_key: str
    payload_digest: str


@dataclass(frozen=True, slots=True)
class CandidateFact:
    business_key: str
    payload_digest: str


@dataclass(frozen=True, slots=True)
class ReconciliationInput:
    source_type: str
    target_date: date
    active_snapshot_id: int | None
    candidate_snapshot_id: int
    confirmed: bool
    blocking_count: int
    review_pending_count: int
    current_facts: tuple[AppliedFact, ...]
    candidate_facts: tuple[CandidateFact, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationOperation:
    kind: str
    business_key: str
    prior_revision_id: int | None
    payload_digest: str | None


@dataclass(frozen=True, slots=True)
class ReconciliationPlan:
    status: ReconciliationStatus
    reason: str
    active_snapshot_before: int | None
    active_snapshot_after: int | None
    operations: tuple[ReconciliationOperation, ...]
    planned_insert_count: int
    planned_supersede_count: int
    history_delete_count: int = 0
    business_write_count: int = 0


def _closed_plan(
    request: ReconciliationInput,
    status: ReconciliationStatus,
    reason: str,
) -> ReconciliationPlan:
    return ReconciliationPlan(
        status=status,
        reason=reason,
        active_snapshot_before=request.active_snapshot_id,
        active_snapshot_after=request.active_snapshot_id,
        operations=(),
        planned_insert_count=0,
        planned_supersede_count=0,
    )


def _validate_request(request: ReconciliationInput) -> None:
    if request.source_type not in {"RFID", "NHIS_SCHEDULE"}:
        raise ValueError("unsupported source_type")
    if request.candidate_snapshot_id <= 0:
        raise ValueError("candidate_snapshot_id must be positive")
    if request.active_snapshot_id is not None and request.active_snapshot_id <= 0:
        raise ValueError("active_snapshot_id must be positive")
    if request.blocking_count < 0 or request.review_pending_count < 0:
        raise ValueError("decision counts cannot be negative")
    for current_fact in request.current_facts:
        if (
            current_fact.revision_id <= 0
            or not current_fact.business_key
            or not _SHA256.fullmatch(current_fact.payload_digest)
        ):
            raise ValueError("current applied fact is invalid")
    for candidate_fact in request.candidate_facts:
        if not candidate_fact.business_key or not _SHA256.fullmatch(candidate_fact.payload_digest):
            raise ValueError("candidate fact is invalid")


def plan_snapshot_reconciliation(request: ReconciliationInput) -> ReconciliationPlan:
    """Produce atomic append/supersede intent without mutating a ledger."""

    _validate_request(request)
    if request.blocking_count:
        return _closed_plan(request, ReconciliationStatus.BLOCKED, "BLOCKING_DECISION_PRESENT")
    if request.review_pending_count:
        return _closed_plan(
            request,
            ReconciliationStatus.REVIEW_PENDING,
            "REVIEW_PENDING_DECISION_PRESENT",
        )
    if not request.confirmed:
        return _closed_plan(
            request,
            ReconciliationStatus.CONFIRM_REQUIRED,
            "EXPLICIT_CONFIRM_REQUIRED",
        )

    current_by_key: dict[str, AppliedFact] = {}
    for current_fact in request.current_facts:
        if current_fact.business_key in current_by_key:
            raise ValueError("current projection contains duplicate business keys")
        current_by_key[current_fact.business_key] = current_fact

    candidate_by_key: dict[str, CandidateFact] = {}
    for candidate_fact in request.candidate_facts:
        if candidate_fact.business_key in candidate_by_key:
            return _closed_plan(
                request,
                ReconciliationStatus.BLOCKED,
                "DUPLICATE_CANDIDATE_BUSINESS_KEY",
            )
        candidate_by_key[candidate_fact.business_key] = candidate_fact

    operations: list[ReconciliationOperation] = []
    for business_key in sorted(current_by_key.keys() | candidate_by_key.keys()):
        current = current_by_key.get(business_key)
        candidate = candidate_by_key.get(business_key)
        if current is not None and candidate is not None:
            if current.payload_digest == candidate.payload_digest:
                operations.append(
                    ReconciliationOperation(
                        kind="KEEP",
                        business_key=business_key,
                        prior_revision_id=current.revision_id,
                        payload_digest=current.payload_digest,
                    )
                )
            else:
                operations.extend(
                    (
                        ReconciliationOperation(
                            kind="SUPERSEDE",
                            business_key=business_key,
                            prior_revision_id=current.revision_id,
                            payload_digest=None,
                        ),
                        ReconciliationOperation(
                            kind="INSERT",
                            business_key=business_key,
                            prior_revision_id=current.revision_id,
                            payload_digest=candidate.payload_digest,
                        ),
                    )
                )
        elif current is not None:
            operations.append(
                ReconciliationOperation(
                    kind="SUPERSEDE",
                    business_key=business_key,
                    prior_revision_id=current.revision_id,
                    payload_digest=None,
                )
            )
        else:
            assert candidate is not None
            operations.append(
                ReconciliationOperation(
                    kind="INSERT",
                    business_key=business_key,
                    prior_revision_id=None,
                    payload_digest=candidate.payload_digest,
                )
            )

    insert_count = sum(operation.kind == "INSERT" for operation in operations)
    supersede_count = sum(operation.kind == "SUPERSEDE" for operation in operations)
    exact_same_snapshot = (
        request.active_snapshot_id == request.candidate_snapshot_id
        and insert_count == 0
        and supersede_count == 0
    )
    return ReconciliationPlan(
        status=(
            ReconciliationStatus.DUPLICATE_NOOP
            if exact_same_snapshot
            else ReconciliationStatus.APPLY_READY
        ),
        reason=("EQUIVALENT_CURRENT_PROJECTION" if exact_same_snapshot else "ATOMIC_SWAP_READY"),
        active_snapshot_before=request.active_snapshot_id,
        active_snapshot_after=request.candidate_snapshot_id,
        operations=tuple(operations),
        planned_insert_count=insert_count,
        planned_supersede_count=supersede_count,
    )
