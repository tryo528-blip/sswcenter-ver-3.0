from __future__ import annotations

from typing import Any, NoReturn

import pytest

from app.main import app

FACT_PATH = "/api/v1/staff/{staff_id}/health-checks"
FACT_ITEM_PATH = f"{FACT_PATH}/{{health_check_id}}"
REQUIREMENT_PATH = "/api/v1/staff/{staff_id}/health-check-requirements"
REQUIREMENT_ITEM_PATH = f"{REQUIREMENT_PATH}/{{requirement_id}}"
REQUIRED_PATHS = {
    FACT_PATH,
    FACT_ITEM_PATH,
    REQUIREMENT_PATH,
    REQUIREMENT_ITEM_PATH,
    f"{FACT_ITEM_PATH}/invalidate",
    f"{REQUIREMENT_ITEM_PATH}/invalidate",
}


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _document() -> dict[str, Any]:
    try:
        document = app.openapi()
    except Exception:
        _fail("W1A_VS4_OPENAPI_HARNESS_FAILURE: OpenAPI could not be built")
    if not isinstance(document, dict):
        _fail("W1A_VS4_OPENAPI_HARNESS_FAILURE: OpenAPI document is not an object")
    return document


def test_vs4_fact_and_requirement_routes_are_separate() -> None:
    document = _document()
    paths = document.get("paths")
    if not isinstance(paths, dict):
        _fail("W1A_VS4_OPENAPI_MISSING: paths object is absent")
    missing = sorted(REQUIRED_PATHS - set(paths))
    if missing:
        _fail("W1A_VS4_OPENAPI_MISSING: health fact/requirement routes are absent")
    if FACT_PATH == REQUIREMENT_PATH or FACT_ITEM_PATH == REQUIREMENT_ITEM_PATH:
        _fail("W1A_VS4_OPENAPI_MISSING: fact and requirement routes are not separated")


def test_vs4_named_models_status_and_conditional_nullable_contract() -> None:
    document = _document()
    schemas = document.get("components", {}).get("schemas", {})
    required_models = {
        "StaffHealthCheckCreateRequest",
        "StaffHealthCheckUpdateRequest",
        "StaffHealthCheckResponse",
        "StaffHealthCheckListResponse",
        "StaffHealthCheckRequirementUpdateRequest",
        "StaffHealthCheckRequirementResponse",
        "StaffHealthCheckRequirementListResponse",
    }
    if not required_models.issubset(schemas):
        _fail("W1A_VS4_OPENAPI_MODEL_MISSING: named fact/requirement models are absent")
    requirement = schemas["StaffHealthCheckRequirementResponse"]
    properties = requirement.get("properties", {})
    status = properties.get("status", {})
    if set(status.get("enum", ())) != {"COMPLETE", "INCOMPLETE", "EXEMPT"}:
        _fail("W1A_VS4_OPENAPI_STATUS_MISSING: exact status enum is absent")
    for field in ("employment_id", "health_check_id", "exempt_reason_text"):
        if field not in properties:
            _fail(f"W1A_VS4_OPENAPI_NULLABLE_MISSING: {field} is absent")
    forbidden = {
        "d_day",
        "dday",
        "task_id",
        "file_id",
        "attachment_id",
        "evidence_file_id",
    }
    for name, schema in schemas.items():
        if "HealthCheck" not in name:
            continue
        present = forbidden.intersection(schema.get("properties", {}))
        if present:
            _fail(
                "W1A_VS4_FORBIDDEN_OPENAPI_FIELD_FOUND: " + name + ":" + ",".join(sorted(present))
            )


def test_vs4_named_mutation_responses_declare_stable_errors() -> None:
    document = _document()
    paths = document.get("paths")
    if not isinstance(paths, dict):
        _fail("W1A_VS4_OPENAPI_MISSING: paths object is absent")
    for path in (FACT_PATH, FACT_ITEM_PATH, REQUIREMENT_ITEM_PATH):
        operations = paths.get(path)
        if not isinstance(operations, dict):
            _fail("W1A_VS4_OPENAPI_MISSING: named health path is not an operation object")
        for method, operation in operations.items():
            if method not in {"post", "patch"}:
                continue
            responses = operation.get("responses", {})
            if not {"403", "409", "422"}.issubset(responses):
                _fail("W1A_VS4_OPENAPI_ERROR_MISSING: 403/409/422 responses are absent")
