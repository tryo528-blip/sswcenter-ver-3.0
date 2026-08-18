from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


PositiveId = Annotated[int, Field(gt=0, strict=True, json_schema_extra={"format": "int64"})]
PositiveVersion = Annotated[int, Field(gt=0, strict=True)]
NonNegativeOrder = Annotated[int, Field(ge=0, strict=True)]
StrictBool = Annotated[bool, Field(strict=True)]


class OfficialWorkCardKind(StrEnum):
    RECOGNITION_EXPIRY = "RECOGNITION_EXPIRY"
    CONTRACT_EXPIRY = "CONTRACT_EXPIRY"
    PLAN_NOTICE = "PLAN_NOTICE"
    STAFF_REPLACEMENT_CONSULTATION = "STAFF_REPLACEMENT_CONSULTATION"
    NEW_STAFF_WORK = "NEW_STAFF_WORK"


def _month_start(value: date) -> date:
    if value.day != 1:
        raise ValueError("month must be the first day of the month")
    return value


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone offset")
    return value


class ProfessionalAssignmentCreateRequest(StrictModel):
    staff_id: PositiveId
    employment_id: PositiveId
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _ordered(self) -> ProfessionalAssignmentCreateRequest:
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class ProfessionalAssignmentReplaceRequest(StrictModel):
    expected_row_version: PositiveVersion
    staff_id: PositiveId
    employment_id: PositiveId
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _ordered(self) -> ProfessionalAssignmentReplaceRequest:
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class ProfessionalAssignmentResponse(StrictModel):
    id: PositiveId
    recipient_id: PositiveId
    service_month: date
    staff_id: PositiveId
    employment_id: PositiveId
    start_date: date
    end_date: date
    invalidated_at_utc: datetime | None
    replacement_assignment_id: PositiveId | None
    row_version: PositiveVersion


class ProfessionalAssignmentHistoryResponse(StrictModel):
    items: list[ProfessionalAssignmentResponse]


class ServicePlanNoticeCreateRequest(StrictModel):
    recipient_contract_id: PositiveId
    notification_date: date
    applied_start_date: date
    applied_end_date: date | None = None

    @model_validator(mode="after")
    def _ordered(self) -> ServicePlanNoticeCreateRequest:
        if self.applied_end_date is not None and self.applied_start_date > self.applied_end_date:
            raise ValueError("applied_start_date must be on or before applied_end_date")
        return self


class ServicePlanNoticeReplaceRequest(ServicePlanNoticeCreateRequest):
    expected_row_version: PositiveVersion


class ServicePlanNoticeResponse(StrictModel):
    id: PositiveId
    recipient_id: PositiveId
    recipient_contract_id: PositiveId
    notification_date: date
    applied_start_date: date
    applied_end_date: date
    invalidated_at_utc: datetime | None
    replacement_service_plan_notice_id: PositiveId | None
    row_version: PositiveVersion


class ServicePlanNoticeHistoryResponse(StrictModel):
    items: list[ServicePlanNoticeResponse]


class ScheduleStaffInput(StrictModel):
    staff_id: PositiveId
    employment_id: PositiveId


class ScheduleAssignedStaffResponse(StrictModel):
    staff_id: PositiveId
    employment_id: PositiveId


def _unique_assigned_staff(value: list[ScheduleStaffInput]) -> list[ScheduleStaffInput]:
    staff_ids = [item.staff_id for item in value]
    if len(staff_ids) != len(set(staff_ids)):
        raise ValueError("assigned_staff must contain different staff")
    return value


class ScheduleCreateRequest(StrictModel):
    schedule_month: date
    recipient_id: PositiveId
    service_type_id: PositiveId
    assigned_staff: list[ScheduleStaffInput] = Field(min_length=1, max_length=2)
    starts_at_utc: datetime
    ends_at_utc: datetime
    expected_month_row_version: PositiveVersion

    _validate_month = field_validator("schedule_month")(_month_start)
    _validate_start = field_validator("starts_at_utc")(_aware)
    _validate_end = field_validator("ends_at_utc")(_aware)
    _validate_assigned_staff = field_validator("assigned_staff")(_unique_assigned_staff)

    @model_validator(mode="after")
    def _ordered(self) -> ScheduleCreateRequest:
        if self.starts_at_utc >= self.ends_at_utc:
            raise ValueError("starts_at_utc must be before ends_at_utc")
        return self


class ScheduleReplaceRequest(StrictModel):
    expected_month_row_version: PositiveVersion
    expected_row_version: PositiveVersion
    recipient_id: PositiveId
    service_type_id: PositiveId
    assigned_staff: list[ScheduleStaffInput] = Field(min_length=1, max_length=2)
    starts_at_utc: datetime
    ends_at_utc: datetime

    _validate_start = field_validator("starts_at_utc")(_aware)
    _validate_end = field_validator("ends_at_utc")(_aware)
    _validate_assigned_staff = field_validator("assigned_staff")(_unique_assigned_staff)

    @model_validator(mode="after")
    def _ordered(self) -> ScheduleReplaceRequest:
        if self.starts_at_utc >= self.ends_at_utc:
            raise ValueError("starts_at_utc must be before ends_at_utc")
        return self


class ScheduleDeleteRequest(StrictModel):
    expected_month_row_version: PositiveVersion
    expected_row_version: PositiveVersion


class ScheduleFinalizeRequest(StrictModel):
    expected_month_row_version: PositiveVersion


class ScheduleItemResponse(StrictModel):
    id: PositiveId
    schedule_month: date
    recipient_id: PositiveId
    service_type_id: PositiveId
    assigned_staff: list[ScheduleAssignedStaffResponse]
    starts_at_utc: datetime
    ends_at_utc: datetime
    row_version: PositiveVersion


class ScheduleMonthResponse(StrictModel):
    schedule_month: date
    finalized: bool
    finalized_at_utc: datetime | None
    row_version: PositiveVersion
    items: list[ScheduleItemResponse]


class PersonalTodoCreateRequest(StrictModel):
    title: str = Field(min_length=1)
    expected_list_revision: PositiveVersion

    @field_validator("title")
    @classmethod
    def _title_nonblank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("title must not be blank")
        return cleaned


class PersonalTodoUpdateRequest(StrictModel):
    expected_list_revision: PositiveVersion
    expected_row_version: PositiveVersion
    title: str | None = None
    completed: StrictBool | None = None

    @field_validator("title")
    @classmethod
    def _title_nonblank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("title must not be blank")
        return cleaned

    @model_validator(mode="after")
    def _change_present(self) -> PersonalTodoUpdateRequest:
        if self.title is None and self.completed is None:
            raise ValueError("title or completed is required")
        return self


class PersonalTodoDeleteRequest(StrictModel):
    expected_list_revision: PositiveVersion
    expected_row_version: PositiveVersion


class PersonalTodoReorderRequest(StrictModel):
    expected_list_revision: PositiveVersion
    ordered_ids: list[PositiveId]

    @field_validator("ordered_ids")
    @classmethod
    def _unique_ids(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("ordered_ids must not contain duplicates")
        return value


class PersonalTodoResponse(StrictModel):
    id: PositiveId
    title: str
    completed: bool
    sort_order: NonNegativeOrder
    row_version: PositiveVersion


class PersonalTodoListResponse(StrictModel):
    list_revision: PositiveVersion
    items: list[PersonalTodoResponse]


class OfficialWorkCardDisplay(StrictModel):
    work_title: str
    target_name: str
    detail: str
    due_date: date
    d_day: int


class OfficialWorkCardItem(StrictModel):
    id: PositiveId
    row_version: PositiveVersion
    kind: OfficialWorkCardKind
    assignee_staff_id: PositiveId
    assignee_staff_name: str
    display: OfficialWorkCardDisplay


class OfficialWorkCardGroup(StrictModel):
    staff_id: PositiveId
    staff_name: str
    items: list[OfficialWorkCardItem]


class OfficialWorkCardListResponse(StrictModel):
    as_of_date: date
    groups: list[OfficialWorkCardGroup]


class OfficialWorkCardCloseRequest(StrictModel):
    expected_row_version: PositiveVersion


class OfficialWorkCardReassignRequest(StrictModel):
    expected_row_version: PositiveVersion
    assignee_staff_id: PositiveId


class OfficialWorkCardEligibleAssignee(StrictModel):
    staff_id: PositiveId
    staff_name: str


class OfficialWorkCardEligibleAssigneeListResponse(StrictModel):
    as_of_date: date
    items: list[OfficialWorkCardEligibleAssignee]
