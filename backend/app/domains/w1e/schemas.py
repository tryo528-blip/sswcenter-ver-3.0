from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssignmentKind(StrEnum):
    GENERAL = "GENERAL"
    FAMILY = "FAMILY"


PositiveVersion = Annotated[int, Field(gt=0, strict=True)]
PositiveId = Annotated[int, Field(gt=0, strict=True, json_schema_extra={"format": "int64"})]


class CareAssignmentCreateRequest(StrictModel):
    staff_id: PositiveId
    employment_id: PositiveId
    assignment_kind: AssignmentKind
    family_relationship_text: str | None = Field(default=None, max_length=200)
    start_date: date
    end_date: date | None = None


class CareAssignmentReplacementRequest(CareAssignmentCreateRequest):
    expected_row_version: PositiveVersion


class CareAssignmentResponse(StrictModel):
    id: PositiveId
    recipient_contract_id: PositiveId
    staff_id: PositiveId
    employment_id: PositiveId
    assignment_kind: AssignmentKind
    family_relationship_text: str | None
    start_date: date
    end_date: date | None
    invalidated_at_utc: datetime | None
    replacement_assignment_id: PositiveId | None
    row_version: PositiveVersion


class CareAssignmentListResponse(StrictModel):
    items: list[CareAssignmentResponse]


class CareAssignmentReplacementResponse(StrictModel):
    original: CareAssignmentResponse
    replacement: CareAssignmentResponse
