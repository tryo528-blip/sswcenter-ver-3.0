from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IntakeClassification(StrEnum):
    DUPLICATE_SUCCESS_NOOP = "DUPLICATE_SUCCESS_NOOP"
    RETRY_SAME_SNAPSHOT = "RETRY_SAME_SNAPSHOT"
    BLOCKED_REUPLOAD_REJECTED = "BLOCKED_REUPLOAD_REJECTED"
    REPARSE_SAME_SNAPSHOT = "REPARSE_SAME_SNAPSHOT"
    CANDIDATE_NEW_SNAPSHOT = "CANDIDATE_NEW_SNAPSHOT"


class AttemptStatus(StrEnum):
    # Classifier-only closed state.  It is intentionally absent from the
    # append-only attempt table, whose persisted outcome vocabulary remains
    # SUCCEEDED / FAILED_RETRYABLE / BLOCKED.
    NO_PRIOR_ATTEMPT = "NO_PRIOR_ATTEMPT"
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class SourceIntakeContext:
    same_content_digest: bool
    same_parser_profile: bool
    equivalent_success_exists: bool
    latest_attempt_status: str


@dataclass(frozen=True, slots=True)
class SourceIntakeDecision:
    classification: IntakeClassification
    snapshot_identity: str
    preserve_new_receipt: bool
    new_parse_count: int
    new_apply_count: int
    superseded_count: int
    retry_attempt_allowed: bool
    confirm_required: bool
    same_bytes_profile_bypass_allowed: bool
    active_snapshot_preserved: bool


def _parse_attempt_status(raw: str) -> AttemptStatus:
    if not isinstance(raw, str) or raw == "" or raw != raw.strip():
        raise ValueError("latest attempt status must be a closed exact packet token")
    try:
        return AttemptStatus(raw)
    except ValueError as exc:
        raise ValueError("latest attempt status is not an allowed packet branch") from exc


def _decision(
    classification: IntakeClassification,
    *,
    snapshot_identity: str,
    new_parse_count: int,
    retry_attempt_allowed: bool = False,
    confirm_required: bool = False,
    same_bytes_profile_bypass_allowed: bool = False,
) -> SourceIntakeDecision:
    return SourceIntakeDecision(
        classification=classification,
        snapshot_identity=snapshot_identity,
        preserve_new_receipt=True,
        new_parse_count=new_parse_count,
        new_apply_count=0,
        superseded_count=0,
        retry_attempt_allowed=retry_attempt_allowed,
        confirm_required=confirm_required,
        same_bytes_profile_bypass_allowed=same_bytes_profile_bypass_allowed,
        active_snapshot_preserved=True,
    )


def classify_source_intake(
    context: SourceIntakeContext,
) -> SourceIntakeDecision:
    """Classify an immutable receipt before parsing or applying business facts."""

    if not context.same_content_digest:
        latest_status = _parse_attempt_status(context.latest_attempt_status)
        if latest_status is not AttemptStatus.NO_PRIOR_ATTEMPT:
            raise ValueError("new digest intake requires the closed no-prior-attempt state")
        return _decision(
            IntakeClassification.CANDIDATE_NEW_SNAPSHOT,
            snapshot_identity="NEW",
            new_parse_count=1,
            confirm_required=True,
        )

    latest_status = _parse_attempt_status(context.latest_attempt_status)
    if latest_status is AttemptStatus.NO_PRIOR_ATTEMPT:
        raise ValueError("existing digest intake cannot use the no-prior-attempt state")

    if not context.same_parser_profile:
        return _decision(
            IntakeClassification.REPARSE_SAME_SNAPSHOT,
            snapshot_identity="REUSE",
            new_parse_count=1,
            confirm_required=True,
        )

    if context.equivalent_success_exists:
        if latest_status is not AttemptStatus.SUCCEEDED:
            raise ValueError("equivalent success state requires a successful latest profile result")
        return _decision(
            IntakeClassification.DUPLICATE_SUCCESS_NOOP,
            snapshot_identity="REUSE",
            new_parse_count=0,
        )

    if latest_status is AttemptStatus.FAILED_RETRYABLE:
        return _decision(
            IntakeClassification.RETRY_SAME_SNAPSHOT,
            snapshot_identity="REUSE",
            new_parse_count=1,
            retry_attempt_allowed=True,
            confirm_required=True,
        )

    if latest_status is AttemptStatus.BLOCKED:
        return _decision(
            IntakeClassification.BLOCKED_REUPLOAD_REJECTED,
            snapshot_identity="REUSE",
            new_parse_count=0,
        )

    raise ValueError("successful same-profile result must be represented as equivalent success")
