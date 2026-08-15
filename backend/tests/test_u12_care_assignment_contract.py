from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.db.models import CareAssignment
from app.domains.w1e.errors import STABLE_CODES
from app.domains.w1e.schemas import (
    AssignmentKind,
    CareAssignmentCreateRequest,
    CareAssignmentReplaceRequest,
    CareAssignmentResponse,
)
from app.domains.w1e.service import W1EService
from app.main import app


def test_u12_request_requires_family_relationship_and_orders_period() -> None:
    family = CareAssignmentCreateRequest(
        staff_id=11,
        employment_id=12,
        assignment_kind=AssignmentKind.FAMILY,
        family_relationship_text="  배우자  ",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
    )
    assert family.family_relationship_text == "배우자"

    with pytest.raises(ValidationError, match="family_relationship_text"):
        CareAssignmentCreateRequest(
            staff_id=11,
            employment_id=12,
            assignment_kind="FAMILY",
            start_date=date(2026, 8, 1),
        )
    with pytest.raises(ValidationError, match="start_date"):
        CareAssignmentCreateRequest(
            staff_id=11,
            employment_id=12,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 8, 31),
        )


def test_u12_request_rejects_unknown_fields_and_non_strict_ids() -> None:
    with pytest.raises(ValidationError):
        CareAssignmentCreateRequest(
            staff_id=True,
            employment_id=12,
            start_date=date(2026, 8, 1),
            unexpected="field",
        )

    replace = CareAssignmentReplaceRequest(
        staff_id=11,
        employment_id=12,
        expected_row_version=2,
        start_date=date(2026, 8, 1),
    )
    assert replace.expected_row_version == 2


def test_u12_care_assignment_model_has_period_fact_columns() -> None:
    columns = {column.name for column in CareAssignment.__table__.columns}
    assert columns == {
        "id",
        "recipient_contract_id",
        "staff_id",
        "employment_id",
        "assignment_kind",
        "family_relationship_text",
        "start_date",
        "end_date",
        "assignment_period",
        "invalidated_at_utc",
        "replacement_assignment_id",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    }
    assert {
        constraint.name
        for constraint in CareAssignment.__table__.constraints
        if constraint.name
    } >= {
        "pk_care_assignment",
        "fk_care_assignment_recipient_contract",
        "fk_care_assignment_employment",
        "fk_care_assignment_replacement",
        "ck_care_assignment_kind",
        "ck_care_assignment_date_order",
        "ck_care_assignment_row_version_positive",
        "ex_care_assignment_same_contract_staff_period",
    }


def test_u12_routes_are_registered_with_read_and_write_boundaries() -> None:
    spec = app.openapi()
    list_path = "/api/v1/recipients/{recipient_id}/contracts/{contract_id}/care-assignments"
    item_path = f"{list_path}/{{assignment_id}}"
    assert set(spec["paths"][list_path]) == {"get", "post"}
    assert set(spec["paths"][item_path]) == {"get", "put"}
    assert spec["paths"][list_path]["get"]["operationId"] == "listRecipientCareAssignments"
    assert spec["paths"][list_path]["post"]["operationId"] == "createRecipientCareAssignment"
    assert spec["paths"][item_path]["put"]["operationId"] == "replaceRecipientCareAssignment"


def test_u12_stable_error_codes_are_exported() -> None:
    assert {
        "CARE_ASSIGNMENT_PERIOD_CONFLICT",
        "CARE_ASSIGNMENT_STAFF_INELIGIBLE",
        "CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD",
        "CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD",
    } <= STABLE_CODES


def test_u12_response_preserves_history_and_replacement_identity() -> None:
    row = SimpleNamespace(
        id=101,
        recipient_contract_id=202,
        staff_id=303,
        employment_id=404,
        assignment_kind="GENERAL",
        family_relationship_text=None,
        start_date=date(2026, 8, 1),
        end_date=None,
        invalidated_at_utc=datetime(2026, 8, 15, 1, 2, 3),
        replacement_assignment_id=505,
        row_version=2,
    )
    response = W1EService._response(row, recipient_id=606)
    assert isinstance(response, CareAssignmentResponse)
    assert response.recipient_id == 606
    assert response.invalidated_at_utc is not None
    assert response.replacement_assignment_id == 505


def test_u12_error_mapping_is_fail_closed_for_unknown_database_errors() -> None:
    class UnknownDiagnostic:
        constraint_name = None

    class UnknownOriginal:
        diag = UnknownDiagnostic()

        def __str__(self) -> str:
            return "opaque database failure"

    from sqlalchemy.exc import IntegrityError

    error = IntegrityError("statement", {}, UnknownOriginal())
    mapped = W1EService._map_integrity_error(error)
    assert mapped.code == "UNEXPECTED_SERVER_ERROR"
    assert mapped.status_code == 500
