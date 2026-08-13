from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServiceTypeCode(StrEnum):
    HOME_CARE = "HOME_CARE"
    HOME_BATH = "HOME_BATH"
    TEMP_HOME_CARE = "TEMP_HOME_CARE"
    HOSPITAL_ESCORT = "HOSPITAL_ESCORT"
    BARO_CARE = "BARO_CARE"


PositiveVersion = Annotated[int, Field(gt=0, strict=True)]
PositiveId = Annotated[int, Field(gt=0, strict=True, json_schema_extra={"format": "int64"})]


class ContractCreateRequest(StrictModel):
    service_type_code: ServiceTypeCode
    start_date: date
    end_date: date | None = None
    service_start_date: date | None = None
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
    end_reason_text: str | None
    invalidated_at_utc: datetime | None
    replacement_contract_id: PositiveId | None
    row_version: PositiveVersion


class ContractListResponse(StrictModel):
    items: list[ContractResponse]
