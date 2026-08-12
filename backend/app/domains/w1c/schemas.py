from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GradeCode(StrEnum):
    GRADE_1 = "1"
    GRADE_2 = "2"
    GRADE_3 = "3"
    GRADE_4 = "4"
    GRADE_5 = "5"


class BenefitCode(StrEnum):
    GENERAL = "GENERAL"
    BASIC_LIVELIHOOD = "BASIC_LIVELIHOOD"
    REDUCTION_6 = "REDUCTION_6"
    REDUCTION_9 = "REDUCTION_9"
    MEDICAL_6 = "MEDICAL_6"
    MEDICAL_9 = "MEDICAL_9"


PositiveVersion = Annotated[int, Field(gt=0)]
PostgresBigIntAmount = Annotated[
    int,
    Field(
        strict=True,
        ge=0,
        json_schema_extra={"format": "int64"},
    ),
]


class CertificationIdentityCreateRequest(StrictModel):
    certification_number: str = Field(
        min_length=11,
        max_length=32,
        pattern=r"^\s*[lL][0-9]{10}(?:-[0-9]{3})?\s*$",
        description=(
            "L 또는 l + 숫자 10자리. 선택적인 3자리 suffix는 제거되어 "
            "canonical L+숫자 10자리로 저장됩니다."
        ),
    )


class CertificationIdentityResponse(StrictModel):
    recipient_id: int
    certification_number: str = Field(pattern=r"^L[0-9]{10}$")
    row_version: int


class CertificationPeriodCreateRequest(StrictModel):
    start_date: date
    end_date: date


class CertificationPeriodReplacementRequest(CertificationPeriodCreateRequest):
    expected_row_version: PositiveVersion


class CertificationPeriodResponse(StrictModel):
    id: int
    recipient_id: int
    start_date: date
    end_date: date
    invalidated_at_utc: datetime | None
    replacement_certification_period_id: int | None
    row_version: int


class CertificationPeriodListResponse(StrictModel):
    items: list[CertificationPeriodResponse]


class CertificationPeriodReplacementResponse(StrictModel):
    original: CertificationPeriodResponse
    replacement: CertificationPeriodResponse


class GradePeriodCreateRequest(StrictModel):
    certification_period_id: int = Field(gt=0)
    grade_code: GradeCode
    start_date: date
    end_date: date


class GradePeriodReplacementRequest(GradePeriodCreateRequest):
    expected_row_version: PositiveVersion


class GradePeriodResponse(StrictModel):
    id: int
    recipient_id: int
    certification_period_id: int
    grade_code: GradeCode
    start_date: date
    end_date: date
    invalidated_at_utc: datetime | None
    replacement_grade_period_id: int | None
    row_version: int


class GradePeriodListResponse(StrictModel):
    items: list[GradePeriodResponse]


class GradePeriodReplacementResponse(StrictModel):
    original: GradePeriodResponse
    replacement: GradePeriodResponse


class BenefitPeriodCreateRequest(StrictModel):
    benefit_code: BenefitCode
    start_date: date
    end_date: date | None = None


class BenefitPeriodReplacementRequest(BenefitPeriodCreateRequest):
    expected_row_version: PositiveVersion


class BenefitPeriodResponse(StrictModel):
    id: int
    recipient_id: int
    benefit_code: BenefitCode
    start_date: date
    end_date: date | None
    invalidated_at_utc: datetime | None
    replacement_benefit_period_id: int | None
    row_version: int


class BenefitPeriodListResponse(StrictModel):
    items: list[BenefitPeriodResponse]


class EffectiveBenefitResponse(StrictModel):
    on_date: date
    item: BenefitPeriodResponse | None


class BenefitPeriodReplacementResponse(StrictModel):
    original: BenefitPeriodResponse
    replacement: BenefitPeriodResponse


class ApprovalAmountPeriodCreateRequest(StrictModel):
    amount_krw: PostgresBigIntAmount
    start_date: date
    end_date: date | None = None

    @field_validator("amount_krw")
    @classmethod
    def validate_postgres_bigint(cls, value: int) -> int:
        if value > 9_223_372_036_854_775_807:
            raise ValueError("amount_krw exceeds PostgreSQL bigint")
        return value


class ApprovalAmountPeriodReplacementRequest(ApprovalAmountPeriodCreateRequest):
    expected_row_version: PositiveVersion


class ApprovalAmountPeriodResponse(StrictModel):
    id: int
    recipient_id: int
    amount_krw: PostgresBigIntAmount
    start_date: date
    end_date: date | None
    invalidated_at_utc: datetime | None
    replacement_local_approval_amount_period_id: int | None
    row_version: int


class ApprovalAmountPeriodListResponse(StrictModel):
    items: list[ApprovalAmountPeriodResponse]


class ApprovalAmountPeriodReplacementResponse(StrictModel):
    original: ApprovalAmountPeriodResponse
    replacement: ApprovalAmountPeriodResponse
