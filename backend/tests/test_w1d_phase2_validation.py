"""Focused scalar and payload validation for the surviving W1D contract API."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from app.domains.w1d.schemas import (
    ContractCreateRequest,
    ContractEndRequest,
    PositiveVersion,
    ServiceTypeCode,
)


def test_service_type_catalog_is_strict() -> None:
    assert {item.value for item in ServiceTypeCode} == {
        "HOME_CARE",
        "HOME_BATH",
        "TEMP_HOME_CARE",
        "HOSPITAL_ESCORT",
        "BARO_CARE",
    }
    with pytest.raises(ValidationError):
        ContractCreateRequest.model_validate(
            {
                "service_type_code": "UNKNOWN",
                "start_date": date(2026, 1, 1),
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("signer_name", "retired"),
        ("signer_relationship_text", "retired"),
        ("signer_phone", "010"),
        ("preview_token", "retired"),
        ("new_grade_code", "3"),
        ("replacement_contracts", []),
    ],
)
def test_contract_create_rejects_retired_fields(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        ContractCreateRequest.model_validate(
            {
                "service_type_code": "HOME_CARE",
                "start_date": "2026-01-01",
                field: value,
            }
        )


def test_positive_version_accepts_positive_int_rejects_bool_and_coercion() -> None:
    adapter = TypeAdapter(PositiveVersion)
    assert adapter.validate_python(1) == 1
    for invalid in (0, -1, True, False, "1", 1.0, None):
        with pytest.raises(ValidationError):
            adapter.validate_python(invalid)


def test_contract_end_expected_row_version_rejects_bool() -> None:
    with pytest.raises(ValidationError):
        ContractEndRequest(
            expected_row_version=True,
            end_date=date(2026, 7, 1),
        )


def test_contract_dates_and_free_text_remain_independent_fields() -> None:
    created = ContractCreateRequest(
        service_type_code=ServiceTypeCode.HOME_BATH,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        service_start_date=None,
        end_reason_text="자유 입력",
    )
    assert created.start_date == date(2026, 1, 1)
    assert created.end_date == date(2026, 12, 31)
    assert created.service_start_date is None
    assert created.end_reason_text == "자유 입력"
