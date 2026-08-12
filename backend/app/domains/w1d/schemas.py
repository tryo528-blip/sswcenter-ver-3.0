from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServiceTypeCode(StrEnum):
    HOME_CARE = "HOME_CARE"
    HOME_BATH = "HOME_BATH"
    TEMP_HOME_CARE = "TEMP_HOME_CARE"
    HOSPITAL_ESCORT = "HOSPITAL_ESCORT"
    BARO_CARE = "BARO_CARE"


class GradeCode(StrEnum):
    GRADE_1 = "1"
    GRADE_2 = "2"
    GRADE_3 = "3"
    GRADE_4 = "4"
    GRADE_5 = "5"


# Strict positive int: reject bool (Pydantic otherwise coerces True→1).
PositiveVersion = Annotated[int, Field(gt=0, strict=True)]
PositiveId = Annotated[int, Field(gt=0, strict=True, json_schema_extra={"format": "int64"})]
# Strict JSON boolean: reject 0/1 and string forms.
StrictBool = Annotated[bool, Field(strict=True)]


def validate_transition_period_semantics(
    *,
    new_start_date: date,
    new_end_date: date,
    new_grade_start_date: date,
    new_grade_end_date: date,
    replacement_starts: list[date],
    replacement_ends: list[date | None],
) -> None:
    """Pure period rules shared by preview schema and apply signed revalidation.

    Canonical DB 04 §6.2/§6.3: certification and grade start/end/range are all
    NOT NULL, so new_end_date and new_grade_end_date are required finite dates.
    Rejects reversed cert/grade/replacement periods, grade outside the
    certification, and replacement start != new_start_date. Replacement ends may
    stay open (recipient_contract.end_date is nullable per DB 04 §8.2).
    Raises ValueError with a stable message for Pydantic / domain mapping.
    """
    if new_start_date > new_end_date:
        raise ValueError("new_start_date must be on or before new_end_date")
    if new_grade_start_date > new_grade_end_date:
        raise ValueError("new_grade_start_date must be on or before new_grade_end_date")
    if new_grade_start_date < new_start_date:
        raise ValueError("grade start must not precede certification start")
    if new_grade_start_date > new_end_date:
        raise ValueError("grade start must not exceed certification end")
    if new_grade_end_date > new_end_date:
        raise ValueError("grade end must not exceed certification end")
    if len(replacement_starts) != len(replacement_ends):
        raise ValueError("replacement start/end cardinality mismatch")
    for start, end in zip(replacement_starts, replacement_ends, strict=True):
        if end is not None and start > end:
            raise ValueError("replacement start must be on or before end")
        if start != new_start_date:
            raise ValueError("replacement start must equal new_start_date")


class ContractCreateRequest(StrictModel):
    service_type_code: ServiceTypeCode
    start_date: date
    end_date: date | None = None
    service_start_date: date | None = None
    signer_name: str | None = None
    signer_relationship_text: str | None = None
    signer_phone: str | None = None
    end_reason_text: str | None = None


class ContractEndRequest(StrictModel):
    expected_row_version: PositiveVersion
    end_date: date
    end_reason_text: str | None = None


class ContractResponse(StrictModel):
    id: PositiveId
    recipient_id: PositiveId
    service_type_code: str
    service_group_code: str | None
    start_date: date
    end_date: date | None
    service_start_date: date | None
    signer_name: str | None
    signer_relationship_text: str | None
    signer_phone: str | None
    end_reason_text: str | None
    invalidated_at_utc: datetime | None
    replacement_contract_id: PositiveId | None
    row_version: PositiveVersion


class ContractListResponse(StrictModel):
    items: list[ContractResponse]


class TransitionReplacementItem(StrictModel):
    ended_contract_id: PositiveId
    service_type_code: ServiceTypeCode
    start_date: date
    end_date: date | None = None
    service_start_date: date | None = None
    signer_name: str | None = None
    signer_relationship_text: str | None = None
    signer_phone: str | None = None
    end_reason_text: str | None = None

    @model_validator(mode="after")
    def _replacement_period_order(self) -> TransitionReplacementItem:
        if self.end_date is not None and self.start_date > self.end_date:
            raise ValueError("replacement start must be on or before end")
        return self


class CertificationTransitionPreviewRequest(StrictModel):
    new_start_date: date
    new_end_date: date
    new_grade_code: GradeCode
    new_grade_start_date: date
    new_grade_end_date: date
    replacement_contracts: list[TransitionReplacementItem]

    @model_validator(mode="after")
    def _period_semantics(self) -> CertificationTransitionPreviewRequest:
        validate_transition_period_semantics(
            new_start_date=self.new_start_date,
            new_end_date=self.new_end_date,
            new_grade_start_date=self.new_grade_start_date,
            new_grade_end_date=self.new_grade_end_date,
            replacement_starts=[r.start_date for r in self.replacement_contracts],
            replacement_ends=[r.end_date for r in self.replacement_contracts],
        )
        return self


class ReplacementPreviewItem(StrictModel):
    ended_contract_id: PositiveId
    service_type_code: str
    start_date: date
    end_date: date | None


class CertificationTransitionPreviewResponse(StrictModel):
    preview_token: str
    canonical_hash: str
    serialization_version: str
    proposed_end_date: date
    affected_certification_period_ids: list[PositiveId]
    affected_grade_period_ids: list[PositiveId]
    affected_contract_ids: list[PositiveId]
    service_multiset: list[str]
    replacement_preview: list[ReplacementPreviewItem]


class CertificationTransitionApplyRequest(StrictModel):
    preview_token: str | None
    confirmed: StrictBool
    replacement_contracts: list[TransitionReplacementItem]


class CertificationTransitionApplyResponse(StrictModel):
    recipient_id: PositiveId
    ended_certification_period_ids: list[PositiveId]
    ended_grade_period_ids: list[PositiveId]
    ended_contract_ids: list[PositiveId]
    new_certification_period_id: PositiveId
    new_grade_period_id: PositiveId
    new_contract_ids: list[PositiveId]
    # Direct Python/Pydantic field is UUID object (R20); FastAPI JSON wire is
    # canonical lowercase UUID string equal to audit_event.request_id.
    audit_correlation_id: UUID
    recipient_no: str
