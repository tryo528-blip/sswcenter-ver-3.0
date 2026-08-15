from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.json_schema import SkipJsonSchema


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RecipientInputSexCode(StrEnum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class RecipientSexCode(StrEnum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    TEST = "TEST"


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
    name: str | None = Field(default=None, max_length=200)
    birth_date: date | None = None
    sex_code: RecipientInputSexCode | None = None
    postal_code: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=1000)
    mobile_phone: str = Field(min_length=1, max_length=100)
    memo: str | None = Field(default=None, max_length=4000)


class RecipientUpdateRequest(StrictModel):
    expected_row_version: PositiveVersion
    name: str | None = Field(default=None, max_length=200)
    birth_date: date | None = None
    sex_code: RecipientInputSexCode | None = None
    # Optional by omission; explicit JSON null is rejected (not nullable).
    recipient_status: RecipientStatus | SkipJsonSchema[None] = Field(default=None)
    postal_code: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=1000)
    # Optional by omission; explicit JSON null is rejected because mobile is required.
    mobile_phone: str | SkipJsonSchema[None] = Field(
        default=None,
        min_length=1,
        max_length=100,
    )
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

    @field_validator("mobile_phone", mode="before")
    @classmethod
    def _reject_null_mobile_phone(cls, value: object) -> object:
        if value is None:
            raise ValueError(
                "mobile_phone cannot be null; omit the field to leave it unchanged"
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
    name: str | None
    birth_date: date | None
    sex_code: RecipientSexCode | None
    recipient_status: RecipientStatus
    recipient_no: str | None
    postal_code: str | None
    address: str | None
    mobile_phone: str
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
    name: str | None
    birth_date: date | None
    sex_code: RecipientSexCode | None
    recipient_no: str | None
    postal_code: str | None
    address: str | None
    mobile_phone: str
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
    name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    address: str | None = Field(default=None, max_length=1000)
    relationship_text: str | None = Field(default=None, max_length=200)


class GuardianUpdateRequest(StrictModel):
    expected_row_version: PositiveVersion
    name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=320)
    address: str | None = Field(default=None, max_length=1000)
    relationship_text: str | None = Field(default=None, max_length=200)


class GuardianResponse(StrictModel):
    id: int
    recipient_id: int
    slot_no: Literal[1, 2]
    name: str | None
    phone: str | None
    email: str | None
    address: str | None
    relationship_text: str | None
    row_version: int


class GuardianListResponse(StrictModel):
    items: list[GuardianResponse]


class HistoryInvalidateRequest(StrictModel):
    expected_row_version: PositiveVersion


class RecipientDeadlineKind(StrEnum):
    CERTIFICATION_EXPIRY = "CERTIFICATION_EXPIRY"
    CONTRACT_EXPIRY = "CONTRACT_EXPIRY"
    PLAN_RENEWAL = "PLAN_RENEWAL"


class RecipientDeadlineItem(StrictModel):
    recipient_id: int
    recipient_name: str | None
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
