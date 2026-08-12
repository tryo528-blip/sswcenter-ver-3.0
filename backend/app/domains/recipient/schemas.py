from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.json_schema import SkipJsonSchema


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RecipientSexCode(StrEnum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class RecipientStatus(StrEnum):
    """Manually assigned recipient display/filter tag (memo-like).

    Stored/API values only. Display labels: ACTIVE=이용중, ENDED=계약종료,
    WAITING=대기중. Independent of recipient_contract periods and other domains.
    """

    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    WAITING = "WAITING"


PositiveVersion = Annotated[int, Field(gt=0)]


class RecipientCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    birth_date: date
    sex_code: RecipientSexCode
    postal_code: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=1000)
    home_phone: str | None = Field(default=None, max_length=100)
    mobile_phone: str | None = Field(default=None, max_length=100)
    memo: str | None = Field(default=None, max_length=4000)


class RecipientUpdateRequest(StrictModel):
    expected_row_version: PositiveVersion
    name: str | None = Field(default=None, min_length=1, max_length=200)
    birth_date: date | None = None
    sex_code: RecipientSexCode | None = None
    # Optional by omission; explicit JSON null is rejected (not nullable).
    recipient_status: RecipientStatus | SkipJsonSchema[None] = Field(default=None)
    postal_code: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=1000)
    home_phone: str | None = Field(default=None, max_length=100)
    mobile_phone: str | None = Field(default=None, max_length=100)
    memo: str | None = Field(default=None, max_length=4000)
    # omit = no change; explicit null = recipient self; positive int = that guardian.
    payer_guardian_id: int | None = Field(default=None)

    @field_validator("recipient_status", mode="before")
    @classmethod
    def _reject_null_recipient_status(cls, value: object) -> object:
        if value is None:
            raise ValueError(
                "recipient_status cannot be null; omit the field to leave it unchanged"
            )
        return value

    @field_validator("payer_guardian_id", mode="before")
    @classmethod
    def _validate_payer_guardian_id(cls, value: object) -> object:
        # Explicit null is allowed (self). Omission is handled via model_fields_set.
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("payer_guardian_id must be a positive integer or null")
        if value <= 0:
            raise ValueError("payer_guardian_id must be a positive integer or null")
        return value


class RecipientResponse(StrictModel):
    id: int
    name: str
    birth_date: date
    sex_code: RecipientSexCode
    recipient_status: RecipientStatus
    recipient_no: str | None
    postal_code: str | None
    address: str | None
    home_phone: str | None
    mobile_phone: str | None
    memo: str | None
    # NULL = recipient self is payer; positive id = selected guardian of this recipient.
    payer_guardian_id: int | None
    row_version: int


class RecipientListStatusFilter(StrEnum):
    """Query filter for GET /recipients list status (manual tag equality)."""

    ALL = "ALL"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    WAITING = "WAITING"


class RecipientListServiceTypeItem(StrictModel):
    service_type_code: str
    display_name: str


class RecipientListServiceGroupItem(StrictModel):
    service_group_code: str
    display_name: str
    service_types: list[RecipientListServiceTypeItem]


class RecipientListItem(StrictModel):
    """List projection: base recipient fields plus today-scoped summary columns.

    Detail GET continues to use RecipientResponse (no list summary fields).
    Columns: grade / name / age(via birth_date) / copayment / services.
    copayment_rate is always null — W1C benefit ledger stores benefit_code only;
    no official numeric rate source is wired in this packet.
    Does not include recipient_status or any derived row status field.
    """

    id: int
    name: str
    birth_date: date
    sex_code: RecipientSexCode
    recipient_no: str | None
    postal_code: str | None
    address: str | None
    home_phone: str | None
    mobile_phone: str | None
    memo: str | None
    row_version: int
    grade_code: str | None
    benefit_code: str | None
    copayment_rate: int | None
    services: list[RecipientListServiceGroupItem]


class RecipientListResponse(StrictModel):
    items: list[RecipientListItem]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


class GuardianCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    address: str | None = Field(default=None, max_length=1000)
    relationship_text: str | None = Field(default=None, max_length=200)


class GuardianUpdateRequest(StrictModel):
    expected_row_version: PositiveVersion
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    address: str | None = Field(default=None, max_length=1000)
    relationship_text: str | None = Field(default=None, max_length=200)


class GuardianResponse(StrictModel):
    id: int
    recipient_id: int
    name: str
    phone: str | None
    email: str | None
    address: str | None
    relationship_text: str | None
    row_version: int


class GuardianListResponse(StrictModel):
    items: list[GuardianResponse]


class PrimaryGuardianPeriodCreateRequest(StrictModel):
    guardian_id: int = Field(gt=0)
    start_date: date
    end_date: date | None = None


class PrimaryGuardianPeriodReplacementRequest(StrictModel):
    expected_row_version: PositiveVersion
    guardian_id: int = Field(gt=0)
    start_date: date
    end_date: date | None = None


class HistoryInvalidateRequest(StrictModel):
    expected_row_version: PositiveVersion


class PrimaryGuardianPeriodResponse(StrictModel):
    id: int
    recipient_id: int
    guardian_id: int
    start_date: date
    end_date: date | None
    invalidated_at_utc: datetime | None
    replacement_primary_guardian_period_id: int | None
    row_version: int


class PrimaryGuardianPeriodListResponse(StrictModel):
    items: list[PrimaryGuardianPeriodResponse]


class PrimaryGuardianPeriodReplacementResponse(StrictModel):
    original: PrimaryGuardianPeriodResponse
    replacement: PrimaryGuardianPeriodResponse


class PayerSnapshotCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    start_date: date
    phone: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=1000)
    relationship_text: str | None = Field(default=None, max_length=200)
    end_date: date | None = None


class PayerSnapshotReplacementRequest(StrictModel):
    expected_row_version: PositiveVersion
    name: str = Field(min_length=1, max_length=200)
    start_date: date
    phone: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=1000)
    relationship_text: str | None = Field(default=None, max_length=200)
    end_date: date | None = None


class PayerSnapshotResponse(StrictModel):
    id: int
    recipient_id: int
    name: str
    phone: str | None
    address: str | None
    relationship_text: str | None
    start_date: date
    end_date: date | None
    invalidated_at_utc: datetime | None
    replacement_payer_snapshot_id: int | None
    row_version: int


class PayerSnapshotListResponse(StrictModel):
    items: list[PayerSnapshotResponse]


class PayerSnapshotReplacementResponse(StrictModel):
    original: PayerSnapshotResponse
    replacement: PayerSnapshotResponse


class PlanNotificationCreateRequest(StrictModel):
    notified_date: date


class PlanNotificationResponse(StrictModel):
    id: int
    recipient_id: int
    notified_date: date
    invalidated_at_utc: datetime | None
    row_version: int


class PlanNotificationListResponse(StrictModel):
    items: list[PlanNotificationResponse]


class RecipientDeadlineKind(StrEnum):
    CERTIFICATION_EXPIRY = "CERTIFICATION_EXPIRY"
    CONTRACT_EXPIRY = "CONTRACT_EXPIRY"
    PLAN_RENEWAL = "PLAN_RENEWAL"


class RecipientDeadlineItem(StrictModel):
    recipient_id: int
    recipient_name: str
    kind: RecipientDeadlineKind
    source_id: int | None
    source_date: date
    due_date: date


class RecipientDeadlineListResponse(StrictModel):
    items: list[RecipientDeadlineItem]


class RecipientErrorField(StrictModel):
    field: str
    message: str


class RecipientErrorBody(StrictModel):
    code: str
    message: str


class RecipientErrorEnvelope(StrictModel):
    error: RecipientErrorBody
    field_errors: list[RecipientErrorField]
    details: dict[str, Any]
    request_id: str
