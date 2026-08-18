from __future__ import annotations

from datetime import date
from typing import Any, cast

import pytest
from pydantic import ValidationError
from sqlalchemy import Table

from app.domains.w1c.policies import normalize_certification_number, validate_period
from app.domains.w1c.schemas import (
    ApprovalAmountPeriodCreateRequest,
    ApprovalAmountPeriodResponse,
    BenefitCode,
    BenefitPeriodCreateRequest,
    CertificationIdentityCreateRequest,
    CertificationIdentityResponse,
    CertificationPeriodCreateRequest,
    GradeCode,
)


def test_certification_number_normalization_accepts_only_the_canonical_input_family() -> None:
    accepted = {
        "L1234567890": "L1234567890",
        "l1234567890": "L1234567890",
        " l1234567890-100 ": "L1234567890",
        "L1234567890-101": "L1234567890",
        "l1234567890-102": "L1234567890",
        "L1234567890-999": "L1234567890",
    }
    for source, expected in accepted.items():
        assert normalize_certification_number(source) == expected, (
            f"W1_CERT_01_NORMALIZATION_MISMATCH: {source}"
        )

    rejected = (
        "",
        "1234567890",
        "A1234567890",
        "L123456789",
        "L12345678901",
        "L1234567890-10",
        "L1234567890-1000",
        "L1234567890-x00",
        "L１２３４５６７８９０",
        "L1234567890-100-junk",
    )
    for source in rejected:
        with pytest.raises(ValueError, match="VALIDATION_ERROR"):
            normalize_certification_number(source)


def test_w1c_public_enums_and_period_validation_are_exact() -> None:
    assert {item.value for item in GradeCode} == {"1", "2", "3", "4", "5"}
    assert {item.value for item in BenefitCode} == {
        "GENERAL",
        "BASIC_LIVELIHOOD",
        "REDUCTION_6",
        "REDUCTION_9",
        "MEDICAL_6",
        "MEDICAL_9",
    }

    validate_period(date(2026, 7, 1), date(2026, 7, 1))
    validate_period(date(2026, 7, 1), None)
    with pytest.raises(ValueError, match="VALIDATION_ERROR"):
        validate_period(date(2026, 7, 2), date(2026, 7, 1))

    with pytest.raises(ValidationError):
        CertificationPeriodCreateRequest.model_validate(
            {
                "grade_code": "COGNITIVE_SUPPORT",
                "start_date": date(2026, 7, 1),
                "end_date": date(2026, 7, 31),
            }
        )
    with pytest.raises(ValidationError):
        BenefitPeriodCreateRequest.model_validate({"benefit_code": "UNCONFIRMED_RATE"})
    with pytest.raises(ValidationError):
        ApprovalAmountPeriodCreateRequest(
            amount_krw=-1,
            start_date=date(2026, 7, 1),
        )
    with pytest.raises(ValidationError):
        ApprovalAmountPeriodCreateRequest(
            amount_krw=9_223_372_036_854_775_808,
            start_date=date(2026, 7, 1),
        )
    for non_integer in ("1000", 1000.5, True):
        with pytest.raises(ValidationError):
            ApprovalAmountPeriodCreateRequest(
                amount_krw=non_integer,  # type: ignore[arg-type]
                start_date=date(2026, 7, 1),
            )


def test_w1c_schemas_exclude_unapproved_fields_and_defaults() -> None:
    identity_input = CertificationIdentityCreateRequest.model_json_schema()
    identity_output = CertificationIdentityResponse.model_json_schema()
    assert "issued_date" not in identity_input.get("properties", {})
    assert "issued_date" not in identity_output.get("properties", {})
    assert identity_input["properties"]["certification_number"]["pattern"] == (
        r"^\s*[lL][0-9]{10}(?:-[0-9]{3})?\s*$"
    )
    assert identity_output["properties"]["certification_number"]["pattern"] == (r"^L[0-9]{10}$")

    certification_properties = CertificationPeriodCreateRequest.model_json_schema()["properties"]
    assert "grade_code" in certification_properties
    assert "certification_period_id" not in certification_properties
    assert "grade_changed_date" not in certification_properties
    benefit_properties = BenefitPeriodCreateRequest.model_json_schema()["properties"]
    assert "start_text" in benefit_properties
    assert "start_date" not in benefit_properties
    assert "end_date" not in benefit_properties
    assert "rate" not in benefit_properties
    assert "benefit_rate" not in benefit_properties
    assert "default" not in benefit_properties["benefit_code"]
    approval_properties = ApprovalAmountPeriodCreateRequest.model_json_schema()["properties"]
    assert "monthly_maximum" not in approval_properties
    assert approval_properties["amount_krw"]["type"] == "integer"
    assert approval_properties["amount_krw"]["format"] == "int64"
    assert "maximum" not in approval_properties["amount_krw"]
    approval_response_properties = ApprovalAmountPeriodResponse.model_json_schema()["properties"]
    assert approval_response_properties["amount_krw"]["type"] == "integer"
    assert approval_response_properties["amount_krw"]["format"] == "int64"


def test_w1c_openapi_routes_and_named_models_are_registered() -> None:
    from app.main import app

    spec = app.openapi()
    paths: dict[str, Any] = spec["paths"]
    collection_paths = (
        "/api/v1/recipients/{recipient_id}/certification-identity",
        "/api/v1/recipients/{recipient_id}/certification-periods",
        "/api/v1/recipients/{recipient_id}/benefit-periods",
        "/api/v1/recipients/{recipient_id}/approval-amount-periods",
    )
    for path in collection_paths:
        assert {"get", "post"} <= set(paths[path]), f"W1C_OPENAPI_METHOD_MISSING: {path}"

    action_bases = (
        "/api/v1/recipients/{recipient_id}/certification-periods/{period_id}",
        "/api/v1/recipients/{recipient_id}/benefit-periods/{period_id}",
        "/api/v1/recipients/{recipient_id}/approval-amount-periods/{period_id}",
    )
    for base in action_bases:
        assert "post" in paths[f"{base}/invalidate"]
        assert "post" in paths[f"{base}/replacements"]

    assert not any("grade-period" in path for path in paths)
    assert not any("effective" in path and "benefit-period" in path for path in paths)

    schemas: dict[str, Any] = spec["components"]["schemas"]
    required_schemas = {
        "CertificationIdentityCreateRequest",
        "CertificationIdentityResponse",
        "CertificationPeriodCreateRequest",
        "CertificationPeriodListResponse",
        "CertificationPeriodReplacementRequest",
        "BenefitPeriodCreateRequest",
        "BenefitPeriodListResponse",
        "ApprovalAmountPeriodCreateRequest",
        "ApprovalAmountPeriodListResponse",
        "HistoryInvalidateRequest",
    }
    assert required_schemas <= set(schemas)
    assert schemas["GradeCode"]["enum"] == ["1", "2", "3", "4", "5"]
    assert schemas["BenefitCode"]["enum"] == [
        "GENERAL",
        "BASIC_LIVELIHOOD",
        "REDUCTION_6",
        "REDUCTION_9",
        "MEDICAL_6",
        "MEDICAL_9",
    ]
    assert schemas["ApprovalAmountPeriodResponse"]["properties"]["amount_krw"]["format"] == "int64"


def test_w1c_database_models_preserve_required_absences() -> None:
    from app.db.models import (
        RecipientBenefitPeriod,
        RecipientCertificationIdentity,
        RecipientCertificationPeriod,
        RecipientLocalApprovalAmountPeriod,
    )

    tables = (
        cast(Table, RecipientCertificationIdentity.__table__),
        cast(Table, RecipientCertificationPeriod.__table__),
        cast(Table, RecipientBenefitPeriod.__table__),
        cast(Table, RecipientLocalApprovalAmountPeriod.__table__),
    )
    all_columns = {column.name for table in tables for column in table.columns}
    assert "issued_date" not in all_columns
    assert "grade_changed_date" not in all_columns
    assert "benefit_rate" not in all_columns
    assert "monthly_maximum" not in all_columns
    assert "grade_code" in RecipientCertificationPeriod.__table__.c
    assert "start_text" in RecipientBenefitPeriod.__table__.c
    assert {"start_date", "end_date", "benefit_period"}.isdisjoint(
        RecipientBenefitPeriod.__table__.c.keys()
    )

    identity_table = cast(Table, RecipientCertificationIdentity.__table__)
    identity_constraints = {constraint.name for constraint in identity_table.constraints}
    assert "uq_recipient_certification_identity_certification_number" in identity_constraints
    assert identity_table.primary_key.columns.keys() == ["recipient_id"]
