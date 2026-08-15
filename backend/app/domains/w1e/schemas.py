from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssignmentKind(StrEnum):
    GENERAL = "GENERAL"
    FAMILY = "FAMILY"


PositiveId = Annotated[int, Field(gt=0, strict=True, json_schema_extra={"format": "int64"})]
PositiveVersion = Annotated[int, Field(gt=0, strict=True)]


def _validate_period(start_date: date, end_date: date | None) -> None:
    if end_date is not None and start_date > end_date:
        raise ValueError("start_date must be on or before end_date")


class CareAssignmentCreateRequest(StrictModel):
    staff_id: PositiveId
    employment_id: PositiveId
    assignment_kind: AssignmentKind = AssignmentKind.GENERAL
    family_relationship_text: str | None = Field(default=None, max_length=200)
    start_date: date
    end_date: date | None = None

    @model_validator(mode="after")
    def _validate_contract(self) -> CareAssignmentCreateRequest:
        _validate_period(self.start_date, self.end_date)
        if self.assignment_kind is AssignmentKind.FAMILY:
            if self.family_relationship_text is None or not self.family_relationship_text.strip():
                raise ValueError("family_relationship_text is required for FAMILY assignments")
            self.family_relationship_text = self.family_relationship_text.strip()
        elif self.family_relationship_text is not None:
            self.family_relationship_text = self.family_relationship_text.strip() or None
        return self


class CareAssignmentReplaceRequest(CareAssignmentCreateRequest):
    expected_row_version: PositiveVersion


class CareAssignmentResponse(StrictModel):
    id: PositiveId
    recipient_id: PositiveId
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
