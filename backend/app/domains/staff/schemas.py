from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SexCode(StrEnum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    TEST = "TEST"


class StaffCreateSexCode(StrEnum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class PositionCode(StrEnum):
    CARE_WORKER = "CARE_WORKER"
    SOCIAL_WORKER = "SOCIAL_WORKER"
    MANAGER = "MANAGER"
    NURSE = "NURSE"
    OTHER = "OTHER"


class EmploymentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class TrainingCycleType(StrEnum):
    ON_HIRE = "ON_HIRE"
    HALF_YEAR = "HALF_YEAR"
    ANNUAL = "ANNUAL"
    BIENNIAL = "BIENNIAL"


class HealthCheckRequirementStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    EXEMPT = "EXEMPT"


class QuarterlyConsultationStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    EXEMPT = "EXEMPT"


def _normalize_role_input(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


RoleCode = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,49}$", max_length=50),
    BeforeValidator(_normalize_role_input),
]
PositiveVersion = Annotated[int, Field(gt=0)]


class InitialPositionRequest(StrictModel):
    position_code: PositionCode
    start_date: date
    end_date: date | None = None


class InitialOperationalRoleRequest(StrictModel):
    role_code: RoleCode
    start_date: date
    end_date: date | None = None


class InitialEmploymentRequest(StrictModel):
    start_date: date
    initial_positions: list[InitialPositionRequest] = Field(default_factory=list)
    initial_operational_roles: list[InitialOperationalRoleRequest] = Field(default_factory=list)


class StaffCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    birth_date: date
    sex_code: StaffCreateSexCode
    resident_number: str = Field(min_length=13, max_length=14)
    phone: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=1000)
    display_name: str | None = Field(default=None, max_length=200)
    memo: str | None = Field(default=None, max_length=4000)
    initial_employment: InitialEmploymentRequest


class StaffUpdateRequest(StrictModel):
    expected_staff_row_version: PositiveVersion
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=1000)
    display_name: str | None = Field(default=None, max_length=200)
    memo: str | None = Field(default=None, max_length=4000)


class StaffEmploymentCreateRequest(StrictModel):
    expected_staff_row_version: PositiveVersion
    start_date: date


class ChildPeriodVersion(StrictModel):
    period_id: int = Field(gt=0)
    expected_row_version: PositiveVersion


class StaffEmploymentCloseRequest(StrictModel):
    end_date: date
    end_reason_code: str | None = Field(default=None, max_length=50)
    expected_employment_row_version: PositiveVersion
    open_position_versions: list[ChildPeriodVersion] = Field(default_factory=list)
    open_operational_role_versions: list[ChildPeriodVersion] = Field(default_factory=list)


class StaffEmploymentPositionReplacement(StrictModel):
    old_period_id: int = Field(gt=0)
    expected_row_version: PositiveVersion
    replacement: InitialPositionRequest | None


class StaffEmploymentOperationalRoleReplacement(StrictModel):
    old_period_id: int = Field(gt=0)
    expected_row_version: PositiveVersion
    replacement: InitialOperationalRoleRequest | None


class StaffEmploymentReplacementRequest(StrictModel):
    expected_employment_row_version: PositiveVersion
    start_date: date
    end_date: date | None = None
    end_reason_code: str | None = Field(default=None, max_length=50)
    # Every current child must appear exactly once. A null replacement is an
    # explicit removal; omission cannot silently carry or remove existing rows.
    position_replacements: list[StaffEmploymentPositionReplacement] | None = None
    operational_role_replacements: list[StaffEmploymentOperationalRoleReplacement] | None = None


class StaffPositionCreateRequest(StrictModel):
    expected_employment_row_version: PositiveVersion
    position_code: PositionCode
    start_date: date
    end_date: date | None = None


class StaffOperationalRoleCreateRequest(StrictModel):
    expected_employment_row_version: PositiveVersion
    role_code: RoleCode
    start_date: date
    end_date: date | None = None


class StaffPeriodCloseRequest(StrictModel):
    end_date: date
    expected_period_row_version: PositiveVersion


class StaffPositionReplacementRequest(StrictModel):
    expected_period_row_version: PositiveVersion
    position_code: PositionCode
    start_date: date
    end_date: date | None = None


class StaffOperationalRoleReplacementRequest(StrictModel):
    expected_period_row_version: PositiveVersion
    role_code: RoleCode
    start_date: date
    end_date: date | None = None


class StaffEmploymentResponse(StrictModel):
    id: int
    staff_id: int
    employment_no: int
    staff_no: str
    start_date: date
    end_date: date | None
    end_reason_code: str | None
    status: EmploymentStatus
    row_version: int


class StaffPositionPeriodResponse(StrictModel):
    id: int
    staff_id: int
    employment_id: int
    position_code: PositionCode
    start_date: date
    end_date: date | None
    row_version: int


class StaffOperationalRolePeriodResponse(StrictModel):
    id: int
    staff_id: int
    employment_id: int
    role_code: str
    start_date: date
    end_date: date | None
    row_version: int


class StaffResponse(StrictModel):
    id: int
    name: str
    birth_date: date
    sex_code: SexCode
    phone: str | None
    address: str | None
    display_name: str | None
    memo: str | None
    resident_number_masked: str | None
    row_version: int
    current_employment: StaffEmploymentResponse | None
    current_positions: list[StaffPositionPeriodResponse] = Field(default_factory=list)
    current_operational_roles: list[StaffOperationalRolePeriodResponse] = Field(
        default_factory=list
    )


class StaffDetailResponse(StaffResponse):
    employments: list[StaffEmploymentResponse] = Field(default_factory=list)
    positions: list[StaffPositionPeriodResponse] = Field(default_factory=list)
    operational_roles: list[StaffOperationalRolePeriodResponse] = Field(default_factory=list)


class StaffCreateResponse(StaffDetailResponse):
    pass


class StaffListResponse(StrictModel):
    items: list[StaffResponse]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


class TrainingCourseResponse(StrictModel):
    code: str
    display_name: str
    cycle_type: TrainingCycleType
    sort_order: int = Field(gt=0)
    active: bool


class TrainingCourseListResponse(StrictModel):
    items: list[TrainingCourseResponse] = Field(default_factory=list)


class StaffOnboardingTrainingUpdateRequest(StrictModel):
    completed: bool
    expected_row_version: PositiveVersion


class StaffOnboardingTrainingResponse(StrictModel):
    id: int
    staff_id: int
    employment_id: int
    course_code: str
    completed: bool
    invalidated_at_utc: datetime | None
    replacement_onboarding_training_id: int | None
    created_by_account_id: int
    created_at_utc: datetime
    updated_by_account_id: int
    updated_at_utc: datetime
    row_version: int


class StaffOnboardingTrainingListResponse(StrictModel):
    items: list[StaffOnboardingTrainingResponse] = Field(default_factory=list)


class StaffPeriodicTrainingCreateRequest(StrictModel):
    course_code: str = Field(min_length=1, max_length=100)
    period_key: str = Field(min_length=4, max_length=8)
    completed: bool = True
    expected_row_version: PositiveVersion


class StaffPeriodicTrainingUpdateRequest(StrictModel):
    completed: bool
    expected_row_version: PositiveVersion


class StaffPeriodicTrainingInvalidateRequest(StrictModel):
    expected_row_version: PositiveVersion


class StaffPeriodicTrainingResponse(StrictModel):
    id: int
    staff_id: int
    course_code: str
    period_key: str
    completed: bool
    invalidated_at_utc: datetime | None
    replacement_periodic_training_id: int | None
    created_by_account_id: int
    created_at_utc: datetime
    updated_by_account_id: int
    updated_at_utc: datetime
    row_version: int


class StaffPeriodicTrainingListResponse(StrictModel):
    items: list[StaffPeriodicTrainingResponse] = Field(default_factory=list)


class SensitiveIdentityRevealRequest(StrictModel):
    current_pin: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class SensitiveIdentityRevealResponse(StrictModel):
    resident_number: str


class SessionCapabilitiesResponse(StrictModel):
    staff_view: bool = Field(alias="staff.view")
    staff_manage: bool = Field(alias="staff.manage")
    staff_sensitive_identity_reveal: bool = Field(alias="staff.sensitive_identity.reveal")


class ServiceTypeResponse(StrictModel):
    id: int
    code: str
    display_name: str
    service_group_code: str
    service_group_display_name: str
    active: bool


class ServiceCatalogResponse(StrictModel):
    items: list[ServiceTypeResponse] = Field(default_factory=list)


class LicenseTypeResponse(StrictModel):
    id: int
    code: str
    display_name: str
    active: bool


class LicenseTypeListResponse(StrictModel):
    items: list[LicenseTypeResponse] = Field(default_factory=list)


class StaffLicenseCreateRequest(StrictModel):
    license_type_code: str = Field(min_length=1, max_length=100)
    license_number: str = Field(min_length=1, max_length=200)
    issued_date: date
    expected_row_version: PositiveVersion


class StaffLicenseReplacementRequest(StrictModel):
    license_type_code: str = Field(min_length=1, max_length=100)
    license_number: str = Field(min_length=1, max_length=200)
    issued_date: date
    expected_row_version: PositiveVersion


class StaffLicenseInvalidateRequest(StrictModel):
    expected_row_version: PositiveVersion


class StaffLicenseResponse(StrictModel):
    id: int
    staff_id: int
    license_type_code: str
    license_type_display_name: str
    license_number: str
    issued_date: date
    invalidated_at_utc: datetime | None
    replacement_license_id: int | None
    row_version: int


class StaffLicenseListResponse(StrictModel):
    items: list[StaffLicenseResponse] = Field(default_factory=list)


class StaffServiceQualificationCreateRequest(StrictModel):
    employment_id: int = Field(gt=0)
    service_type_code: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date | None = None
    source_license_id: int | None = Field(default=None, gt=0)
    expected_row_version: PositiveVersion


class StaffServiceQualificationCloseRequest(StrictModel):
    end_date: date
    expected_row_version: PositiveVersion


class StaffServiceQualificationReplacementRequest(StrictModel):
    employment_id: int = Field(gt=0)
    service_type_code: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date | None = None
    source_license_id: int | None = Field(default=None, gt=0)
    expected_row_version: PositiveVersion


class StaffServiceQualificationInvalidateRequest(StrictModel):
    expected_row_version: PositiveVersion


class StaffServiceQualificationResponse(StrictModel):
    id: int
    staff_id: int
    employment_id: int
    service_type_code: str
    service_type_display_name: str
    service_group_code: str
    start_date: date
    end_date: date | None
    source_license_id: int | None
    invalidated_at_utc: datetime | None
    replacement_qualification_id: int | None
    row_version: int


class StaffServiceQualificationListResponse(StrictModel):
    items: list[StaffServiceQualificationResponse] = Field(default_factory=list)


class ErrorField(StrictModel):
    field: str
    message: str


class ErrorBody(StrictModel):
    code: str = Field(
        examples=[
            "STAFF_NOT_FOUND",
            "STAFF_EMPLOYMENT_NOT_FOUND",
            "STAFF_ONBOARDING_TRAINING_NOT_FOUND",
            "STAFF_PERIODIC_TRAINING_NOT_FOUND",
            "STAFF_TRAINING_DUPLICATE",
            "STAFF_TRAINING_INVALID_CYCLE",
            "STAFF_TRAINING_PERIOD_INVALID",
            "STAFF_LICENSE_NOT_FOUND",
            "STAFF_LICENSE_DUPLICATE",
            "LICENSE_TYPE_NOT_FOUND",
            "SERVICE_TYPE_NOT_FOUND",
            "STAFF_SERVICE_QUALIFICATION_NOT_FOUND",
            "STAFF_SERVICE_QUALIFICATION_CONFLICT",
            "STAFF_QUALIFICATION_SOURCE_LICENSE_MISMATCH",
            "STAFF_PERIOD_OUTSIDE_EMPLOYMENT",
            "ROW_VERSION_CONFLICT",
            "VALIDATION_ERROR",
        ]
    )
    message: str


class ErrorEnvelope(StrictModel):
    error: ErrorBody
    field_errors: list[ErrorField] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str


class StaffHealthCheckCreateRequest(StrictModel):
    check_date: date
    employment_id: int | None = Field(default=None, gt=0)
    check_type_code: str | None = Field(default=None, min_length=1, max_length=100)
    result_note: str | None = Field(default=None, max_length=4000)


class StaffHealthCheckUpdateRequest(StrictModel):
    check_date: date | None = None
    employment_id: int | None = Field(default=None, gt=0)
    check_type_code: str | None = Field(default=None, min_length=1, max_length=100)
    result_note: str | None = Field(default=None, max_length=4000)
    expected_row_version: PositiveVersion


class StaffHealthCheckResponse(StrictModel):
    id: int
    staff_id: int
    employment_id: int | None
    check_date: date
    check_type_code: str | None
    result_note: str | None
    invalidated_at_utc: datetime | None
    replacement_health_check_id: int | None
    created_by_account_id: int
    created_at_utc: datetime
    updated_by_account_id: int
    updated_at_utc: datetime
    row_version: int


class StaffHealthCheckListResponse(StrictModel):
    items: list[StaffHealthCheckResponse] = Field(default_factory=list)


class StaffHealthCheckRequirementUpdateRequest(StrictModel):
    status: HealthCheckRequirementStatus | None = Field(
        default=None,
        description=(
            "COMPLETE requires a fact and no exemption reason; INCOMPLETE requires neither; "
            "EXEMPT requires a nonblank exemption reason and no fact."
        ),
    )
    health_check_id: int | None = Field(
        default=None,
        gt=0,
        description="Required only for COMPLETE and must reference the same staff's active fact.",
    )
    exempt_reason_text: str | None = Field(
        default=None,
        max_length=4000,
        description="Required and nonblank only for EXEMPT.",
    )
    expected_row_version: PositiveVersion

    @model_validator(mode="after")
    def validate_truth_table(self) -> StaffHealthCheckRequirementUpdateRequest:
        if self.status is None:
            return self
        if self.status is HealthCheckRequirementStatus.COMPLETE:
            if self.health_check_id is None or self.exempt_reason_text is not None:
                raise ValueError("COMPLETE requires a health_check_id and no exempt_reason_text")
        elif self.status is HealthCheckRequirementStatus.INCOMPLETE:
            if self.health_check_id is not None or self.exempt_reason_text is not None:
                raise ValueError("INCOMPLETE cannot reference a fact or exemption reason")
        elif self.status is HealthCheckRequirementStatus.EXEMPT:
            if self.health_check_id is not None or not (self.exempt_reason_text or "").strip():
                raise ValueError("EXEMPT requires a nonblank exempt_reason_text and no fact")
        return self


class StaffHealthCheckRequirementResponse(StrictModel):
    id: int
    staff_id: int
    employment_id: int | None
    target_key: str
    target_rule_version_code: str
    status: Literal["COMPLETE", "INCOMPLETE", "EXEMPT"] = Field(
        description="COMPLETE, INCOMPLETE, or EXEMPT with the corresponding conditional fields."
    )
    health_check_id: int | None
    exempt_reason_text: str | None
    invalidated_at_utc: datetime | None
    replacement_health_check_requirement_id: int | None
    created_by_account_id: int
    created_at_utc: datetime
    updated_by_account_id: int
    updated_at_utc: datetime
    row_version: int


class StaffHealthCheckRequirementListResponse(StrictModel):
    items: list[StaffHealthCheckRequirementResponse] = Field(default_factory=list)


def _normalize_quarterly_text(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def _validate_quarterly_conditional_field(value: object, info: ValidationInfo) -> object:
    status = info.data.get("status")
    field_name = str(info.field_name)
    if not isinstance(status, QuarterlyConsultationStatus):
        return value
    if field_name == "counseling_date":
        if status is QuarterlyConsultationStatus.COMPLETE and value is None:
            raise ValueError("counseling_date is required for COMPLETE")
        if status is not QuarterlyConsultationStatus.COMPLETE and value is not None:
            raise ValueError(f"counseling_date must be empty for {status.value}")
    elif field_name == "content":
        if status is QuarterlyConsultationStatus.COMPLETE and value is None:
            raise ValueError("content is required for COMPLETE")
        if status is not QuarterlyConsultationStatus.COMPLETE and value is not None:
            raise ValueError(f"content must be empty for {status.value}")
    elif field_name == "incomplete_reason_text":
        if status is QuarterlyConsultationStatus.INCOMPLETE and value is None:
            raise ValueError("incomplete_reason_text is required for INCOMPLETE")
        if status is not QuarterlyConsultationStatus.INCOMPLETE and value is not None:
            raise ValueError(f"incomplete_reason_text must be empty for {status.value}")
    elif field_name == "exempt_reason_text":
        if status is QuarterlyConsultationStatus.EXEMPT and value is None:
            raise ValueError("exempt_reason_text is required for EXEMPT")
        if status is not QuarterlyConsultationStatus.EXEMPT and value is not None:
            raise ValueError(f"exempt_reason_text must be empty for {status.value}")
    return value


class StaffQuarterlyConsultationCreateRequest(StrictModel):
    calendar_year: int
    quarter_no: int = Field(ge=1, le=4)
    status: QuarterlyConsultationStatus = Field(
        description="COMPLETE, INCOMPLETE, or EXEMPT with the corresponding conditional fields."
    )
    counseling_date: Annotated[date | None, BeforeValidator(_normalize_quarterly_text)] = Field(
        default=None,
        description="Required only for COMPLETE; empty for INCOMPLETE and EXEMPT.",
        validate_default=True,
    )
    content: Annotated[str | None, BeforeValidator(_normalize_quarterly_text)] = Field(
        default=None,
        min_length=1,
        max_length=4000,
        description="Required and nonblank only for COMPLETE; empty otherwise.",
        validate_default=True,
    )
    incomplete_reason_text: Annotated[str | None, BeforeValidator(_normalize_quarterly_text)] = (
        Field(
            default=None,
            min_length=1,
            max_length=4000,
            description="Required and nonblank only for INCOMPLETE; empty otherwise.",
            validate_default=True,
        )
    )
    exempt_reason_text: Annotated[str | None, BeforeValidator(_normalize_quarterly_text)] = Field(
        default=None,
        min_length=1,
        max_length=4000,
        description="Required and nonblank only for EXEMPT; empty otherwise.",
        validate_default=True,
    )

    _validate_conditionals = field_validator(
        "counseling_date",
        "content",
        "incomplete_reason_text",
        "exempt_reason_text",
        mode="after",
    )(_validate_quarterly_conditional_field)


class StaffQuarterlyConsultationUpdateRequest(StrictModel):
    status: QuarterlyConsultationStatus = Field(
        description="COMPLETE, INCOMPLETE, or EXEMPT with the corresponding conditional fields."
    )
    counseling_date: Annotated[date | None, BeforeValidator(_normalize_quarterly_text)] = Field(
        default=None,
        description="Required only for COMPLETE; empty for INCOMPLETE and EXEMPT.",
        validate_default=True,
    )
    content: Annotated[str | None, BeforeValidator(_normalize_quarterly_text)] = Field(
        default=None,
        min_length=1,
        max_length=4000,
        description="Required and nonblank only for COMPLETE; empty otherwise.",
        validate_default=True,
    )
    incomplete_reason_text: Annotated[str | None, BeforeValidator(_normalize_quarterly_text)] = (
        Field(
            default=None,
            min_length=1,
            max_length=4000,
            description="Required and nonblank only for INCOMPLETE; empty otherwise.",
            validate_default=True,
        )
    )
    exempt_reason_text: Annotated[str | None, BeforeValidator(_normalize_quarterly_text)] = Field(
        default=None,
        min_length=1,
        max_length=4000,
        description="Required and nonblank only for EXEMPT; empty otherwise.",
        validate_default=True,
    )
    expected_row_version: PositiveVersion

    _validate_conditionals = field_validator(
        "counseling_date",
        "content",
        "incomplete_reason_text",
        "exempt_reason_text",
        mode="after",
    )(_validate_quarterly_conditional_field)


class StaffQuarterlyConsultationReplaceRequest(StrictModel):
    status: QuarterlyConsultationStatus = Field(
        description="Replacement status: COMPLETE, INCOMPLETE, or EXEMPT."
    )
    counseling_date: Annotated[date | None, BeforeValidator(_normalize_quarterly_text)] = Field(
        default=None,
        description="Required only for COMPLETE; empty for INCOMPLETE and EXEMPT.",
        validate_default=True,
    )
    content: Annotated[str | None, BeforeValidator(_normalize_quarterly_text)] = Field(
        default=None,
        min_length=1,
        max_length=4000,
        description="Required and nonblank only for COMPLETE; empty otherwise.",
        validate_default=True,
    )
    incomplete_reason_text: Annotated[str | None, BeforeValidator(_normalize_quarterly_text)] = (
        Field(
            default=None,
            min_length=1,
            max_length=4000,
            description="Required and nonblank only for INCOMPLETE; empty otherwise.",
            validate_default=True,
        )
    )
    exempt_reason_text: Annotated[str | None, BeforeValidator(_normalize_quarterly_text)] = Field(
        default=None,
        min_length=1,
        max_length=4000,
        description="Required and nonblank only for EXEMPT; empty for other statuses.",
        validate_default=True,
    )
    expected_row_version: PositiveVersion

    _validate_conditionals = field_validator(
        "counseling_date",
        "content",
        "incomplete_reason_text",
        "exempt_reason_text",
        mode="after",
    )(_validate_quarterly_conditional_field)


class StaffQuarterlyConsultationResponse(StrictModel):
    id: int
    staff_id: int
    calendar_year: int
    quarter_no: int
    status: QuarterlyConsultationStatus = Field(
        description="COMPLETE, INCOMPLETE, or EXEMPT with the corresponding conditional fields."
    )
    counseling_date: date | None = Field(description="Present only for COMPLETE consultations.")
    content: str | None = Field(
        description="Nonblank consultation content only for COMPLETE consultations."
    )
    incomplete_reason_text: str | None = Field(
        description="Nonblank reason only for INCOMPLETE consultations."
    )
    exempt_reason_text: str | None = Field(
        description="Nonblank reason only for EXEMPT consultations."
    )
    invalidated_at_utc: datetime | None
    replacement_staff_quarterly_consultation_id: int | None
    created_by_account_id: int
    created_at_utc: datetime
    updated_by_account_id: int
    updated_at_utc: datetime
    row_version: int


class StaffQuarterlyConsultationListResponse(StrictModel):
    items: list[StaffQuarterlyConsultationResponse] = Field(default_factory=list)
