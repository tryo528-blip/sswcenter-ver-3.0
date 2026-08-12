from __future__ import annotations

from typing import Any, NoReturn

import pytest

from app.main import app

COLLECTION_PATH = "/api/v1/staff/{staff_id}/quarterly-consultations"
ITEM_PATH = f"{COLLECTION_PATH}/{{consultation_id}}"
INVALIDATE_PATH = f"{ITEM_PATH}/invalidate"
REQUIRED_OPERATIONS = {
    COLLECTION_PATH: {"get", "post"},
    ITEM_PATH: {"patch"},
    INVALIDATE_PATH: {"post"},
}
REQUIRED_MODELS = {
    "QuarterlyConsultationStatus",
    "StaffQuarterlyConsultationCreateRequest",
    "StaffQuarterlyConsultationUpdateRequest",
    "StaffQuarterlyConsultationReplaceRequest",
    "StaffQuarterlyConsultationResponse",
    "StaffQuarterlyConsultationListResponse",
}
CONDITIONAL_FIELDS = (
    "counseling_date",
    "content",
    "incomplete_reason_text",
    "exempt_reason_text",
)
FORBIDDEN_PROPERTIES = {
    "care_change_id",
    "care_change_case_id",
    "care_change_consultation_id",
    "file_id",
    "file_key",
    "attachment_id",
    "evidence_file_id",
    "evidence_id",
}


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _document() -> dict[str, Any]:
    try:
        document = app.openapi()
    except Exception:
        _fail("W1A_VS5_OPENAPI_HARNESS_FAILURE: OpenAPI could not be built")
    if not isinstance(document, dict):
        _fail("W1A_VS5_OPENAPI_HARNESS_FAILURE: OpenAPI document is not an object")
    return document


def _schemas(document: dict[str, Any]) -> dict[str, Any]:
    schemas = document.get("components", {}).get("schemas", {})
    if not isinstance(schemas, dict):
        _fail("W1A_VS5_OPENAPI_HARNESS_FAILURE: schemas object is absent")
    return schemas


def _resolved_schema(schemas: dict[str, Any], name: str) -> dict[str, Any]:
    schema = schemas.get(name)
    if not isinstance(schema, dict):
        _fail(f"W1A_VS5_OPENAPI_MODEL_MISSING: {name} is absent")
    reference = schema.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/components/schemas/"):
        resolved = schemas.get(reference.rsplit("/", 1)[-1])
        if isinstance(resolved, dict):
            return resolved
    return schema


def test_vs5_named_routes_are_separate_fastapi_operations() -> None:
    document = _document()
    paths = document.get("paths")
    if not isinstance(paths, dict):
        _fail("W1A_VS5_OPENAPI_MISSING: paths object is absent")
    for path, methods in REQUIRED_OPERATIONS.items():
        operations = paths.get(path)
        if not isinstance(operations, dict):
            _fail("W1A_VS5_OPENAPI_ROUTE_MISSING: quarterly-consultation route is absent")
        missing = sorted(methods - set(operations))
        if missing:
            _fail(
                "W1A_VS5_OPENAPI_ROUTE_MISSING: required operation is absent: "
                + path
                + ":"
                + ",".join(missing)
            )
    if COLLECTION_PATH == ITEM_PATH or "quarterly-consultations" not in COLLECTION_PATH:
        _fail("W1A_VS5_OPENAPI_ROUTE_MISSING: collection and item routes are not separated")


def test_vs5_named_models_status_and_conditional_fields() -> None:
    document = _document()
    schemas = _schemas(document)
    missing = sorted(REQUIRED_MODELS - set(schemas))
    if missing:
        _fail("W1A_VS5_OPENAPI_MODEL_MISSING: named models are absent: " + ",".join(missing))
    status_schema = _resolved_schema(schemas, "QuarterlyConsultationStatus")
    if set(status_schema.get("enum", ())) != {"COMPLETE", "INCOMPLETE", "EXEMPT"}:
        _fail("W1A_VS5_OPENAPI_STATUS_MISSING: exact three-state enum is absent")
    response = _resolved_schema(schemas, "StaffQuarterlyConsultationResponse")
    properties = response.get("properties", {})
    if not isinstance(properties, dict):
        _fail("W1A_VS5_OPENAPI_MODEL_MISSING: response properties are absent")
    expected = {
        "id",
        "staff_id",
        "calendar_year",
        "quarter_no",
        "status",
        *CONDITIONAL_FIELDS,
        "invalidated_at_utc",
        "replacement_staff_quarterly_consultation_id",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    }
    if not expected.issubset(properties):
        _fail("W1A_VS5_OPENAPI_MODEL_MISSING: response fields are incomplete")
    for field in CONDITIONAL_FIELDS:
        description = properties[field].get("description")
        if not isinstance(description, str) or not description.strip():
            _fail(
                "W1A_VS5_OPENAPI_CONDITIONAL_DESCRIPTION_MISSING: conditional field lacks guidance"
            )
    status_description = properties.get("status", {}).get("description", "")
    if not isinstance(status_description, str) or any(
        value not in status_description for value in ("COMPLETE", "INCOMPLETE", "EXEMPT")
    ):
        _fail("W1A_VS5_OPENAPI_CONDITIONAL_DESCRIPTION_MISSING: status truth table is undocumented")
    update = _resolved_schema(schemas, "StaffQuarterlyConsultationUpdateRequest")
    update_properties = update.get("properties", {})
    if not isinstance(update_properties, dict):
        _fail("W1A_VS5_OPENAPI_MODEL_MISSING: update properties are absent")
    if {"calendar_year", "quarter_no"}.intersection(update_properties):
        _fail("W1A_VS5_IMMUTABLE_KEY_EXPOSED: update accepts calendar identity fields")
    if "expected_row_version" not in update_properties:
        _fail("W1A_VS5_OPENAPI_MODEL_MISSING: update version guard is absent")


def test_vs5_mutation_operations_declare_stable_error_responses() -> None:
    document = _document()
    paths = document.get("paths")
    if not isinstance(paths, dict):
        _fail("W1A_VS5_OPENAPI_MISSING: paths object is absent")
    for path in (COLLECTION_PATH, ITEM_PATH, INVALIDATE_PATH):
        operations = paths.get(path)
        if not isinstance(operations, dict):
            _fail("W1A_VS5_OPENAPI_ROUTE_MISSING: mutation path is absent")
        for method in ("post", "patch"):
            operation = operations.get(method)
            if operation is None:
                continue
            responses = operation.get("responses", {})
            if not {"403", "409", "422"}.issubset(responses):
                _fail("W1A_VS5_OPENAPI_ERROR_MISSING: 403/409/422 are absent")


def test_vs5_openapi_has_no_forbidden_properties_on_consultation_models() -> None:
    schemas = _schemas(_document())
    for name, _raw_schema in schemas.items():
        if "QuarterlyConsultation" not in name and "quarterly_consultation" not in name:
            continue
        schema = _resolved_schema(schemas, name)
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            continue
        present = FORBIDDEN_PROPERTIES.intersection(properties)
        if present:
            _fail(
                "W1A_VS5_FORBIDDEN_OPENAPI_FIELD_FOUND: " + name + ":" + ",".join(sorted(present))
            )
