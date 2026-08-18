"""Strict public schemas for the FILE_ONLY W3 workspace."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from app.domains.staff.schemas import StrictModel


class W3SourceType(StrEnum):
    NHIS_SCHEDULE = "NHIS_SCHEDULE"
    RFID = "RFID"


class W3RunStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PARSING = "PARSING"
    PREVIEW_READY = "PREVIEW_READY"
    CONFIRMED = "CONFIRMED"
    APPLYING = "APPLYING"
    APPLIED = "APPLIED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class W3MatchStatus(StrEnum):
    AUTO_MATCH = "AUTO_MATCH"
    MANUAL_MATCH = "MANUAL_MATCH"
    REVIEW_PENDING = "REVIEW_PENDING"
    BLOCKED = "BLOCKED"


class W3RunCounts(StrictModel):
    raw_rows: int = Field(ge=0)
    normalized_rows: int = Field(ge=0)
    target_rows: int = Field(ge=0)
    derived_groups: int = Field(ge=0)
    auto_matches: int = Field(ge=0)
    manual_matches: int = Field(ge=0)
    review_pending: int = Field(ge=0)
    blocked: int = Field(ge=0)


class W3DecisionItem(StrictModel):
    id: int = Field(gt=0)
    source_occurrence_identity: str
    status: W3MatchStatus
    reason_code: str
    source_row_number: int | None = Field(default=None, gt=0)
    service_date: date
    service_category: str
    event_state: str | None = None
    end_display: str | None = None
    row_version: int = Field(gt=0)


class W3RunSummary(StrictModel):
    id: int = Field(gt=0)
    source_type: W3SourceType
    target_date: date
    original_filename: str
    parser_profile_version: str
    status: W3RunStatus
    row_version: int = Field(gt=0)
    preview_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    warning_codes: list[str] = Field(default_factory=list)
    counts: W3RunCounts
    decisions: list[W3DecisionItem] = Field(default_factory=list)
    created_at_utc: datetime
    can_confirm: bool
    can_apply: bool


class W3ActiveSnapshot(StrictModel):
    snapshot_id: int = Field(gt=0)
    import_run_id: int = Field(gt=0)
    source_type: W3SourceType
    target_date: date
    row_version: int = Field(gt=0)


class W3WorkspaceResponse(StrictModel):
    source_type: W3SourceType
    target_date: date
    active: W3ActiveSnapshot | None = None
    latest_run: W3RunSummary | None = None
    recent_runs: list[W3RunSummary] = Field(default_factory=list)


class W3ConfirmRequest(StrictModel):
    expected_row_version: int = Field(gt=0)
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    command_idempotency_key: str = Field(min_length=8, max_length=200)


class W3ApplyRequest(StrictModel):
    expected_row_version: int = Field(gt=0)
    command_idempotency_key: str = Field(min_length=8, max_length=200)


class W3ResolveDecisionRequest(StrictModel):
    expected_run_row_version: int = Field(gt=0)
    command_idempotency_key: str = Field(min_length=8, max_length=200)
    recipient_id: int = Field(gt=0)
    certification_period_id: int = Field(gt=0)
    staff_id: int = Field(gt=0)
    employment_id: int = Field(gt=0)
    service_type_id: int = Field(gt=0)
    recipient_contract_id: int = Field(gt=0)
    care_assignment_id: int = Field(gt=0)
    w2_schedule_id: int = Field(gt=0)


class W3SupplementAction(StrEnum):
    CREATE = "CREATE"
    CANCEL = "CANCEL"
    REPLACE = "REPLACE"


class W3SupplementRequest(StrictModel):
    action: W3SupplementAction
    expected_row_version: int = Field(ge=0)
    proposed_actual_end: datetime | None = None
    reason: str = Field(min_length=1, max_length=1000)
    command_idempotency_key: str = Field(min_length=8, max_length=200)

    @model_validator(mode="after")
    def validate_end_pair(self) -> W3SupplementRequest:
        if self.action is W3SupplementAction.CANCEL:
            if self.proposed_actual_end is not None:
                raise ValueError("cancel cannot include proposed_actual_end")
        elif self.proposed_actual_end is None:
            raise ValueError("create/replace requires proposed_actual_end")
        return self


class W3SupplementResponse(StrictModel):
    id: int = Field(gt=0)
    actual_work_revision_id: int = Field(gt=0)
    row_version: int = Field(gt=0)
    action: W3SupplementAction
    proposed_actual_end: datetime | None = None
    reason: str
    created_at_utc: datetime


class W3PlanAdjustmentRequest(StrictModel):
    expected_schedule_row_version: int = Field(gt=0)
    expected_month_row_version: int = Field(gt=0)
    rule_version: Literal["w3-rfid-adjustment-v1"]
    reason: str = Field(min_length=1, max_length=1000)
    command_idempotency_key: str = Field(min_length=8, max_length=200)


class W3PlanAdjustmentResponse(StrictModel):
    id: int = Field(gt=0)
    actual_work_revision_id: int = Field(gt=0)
    w2_schedule_id: int = Field(gt=0)
    rule_version: str
    adopted_planned_start: datetime
    adopted_planned_end: datetime
    schedule_row_version: int = Field(gt=0)
    month_row_version: int = Field(gt=0)
    created_at_utc: datetime
