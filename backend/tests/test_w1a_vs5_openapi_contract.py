from __future__ import annotations

from typing import Any

from app.main import app

COLLECTION_PATH = "/api/v1/staff/{staff_id}/quarterly-consultations"
ITEM_PATH = f"{COLLECTION_PATH}/{{consultation_id}}"
INVALIDATE_PATH = f"{ITEM_PATH}/invalidate"


def _document() -> dict[str, Any]:
    document = app.openapi()
    assert isinstance(document, dict)
    return document


def test_quarterly_consultation_exposes_list_create_and_toggle_only() -> None:
    paths = _document()["paths"]
    assert {"get", "post"}.issubset(paths[COLLECTION_PATH])
    assert set(paths[ITEM_PATH]).issuperset({"patch"})
    assert INVALIDATE_PATH not in paths


def test_quarterly_consultation_models_are_boolean_only() -> None:
    schemas = _document()["components"]["schemas"]
    assert {
        "StaffQuarterlyConsultationCreateRequest",
        "StaffQuarterlyConsultationUpdateRequest",
        "StaffQuarterlyConsultationResponse",
        "StaffQuarterlyConsultationListResponse",
    }.issubset(schemas)
    assert "QuarterlyConsultationStatus" not in schemas
    assert "StaffQuarterlyConsultationReplaceRequest" not in schemas

    create_properties = schemas["StaffQuarterlyConsultationCreateRequest"]["properties"]
    update_properties = schemas["StaffQuarterlyConsultationUpdateRequest"]["properties"]
    response_properties = schemas["StaffQuarterlyConsultationResponse"]["properties"]
    assert set(create_properties) == {"calendar_year", "quarter_no", "completed"}
    assert set(update_properties) == {"completed", "expected_row_version"}
    assert {
        "status",
        "counseling_date",
        "content",
        "incomplete_reason_text",
        "exempt_reason_text",
        "invalidated_at_utc",
        "replacement_staff_quarterly_consultation_id",
    }.isdisjoint(response_properties)
    assert {
        "id",
        "staff_id",
        "calendar_year",
        "quarter_no",
        "completed",
        "row_version",
    }.issubset(response_properties)


def test_quarterly_mutations_keep_stable_error_responses() -> None:
    paths = _document()["paths"]
    for path in (COLLECTION_PATH, ITEM_PATH):
        for method, operation in paths[path].items():
            if method not in {"post", "patch"}:
                continue
            assert {"403", "409", "422"}.issubset(operation["responses"])
