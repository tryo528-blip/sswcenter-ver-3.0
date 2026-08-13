from __future__ import annotations

from typing import Any

from app.main import app

FACT_PATH = "/api/v1/staff/{staff_id}/health-checks"
FACT_ITEM_PATH = f"{FACT_PATH}/{{health_check_id}}"
REQUIREMENT_PATH = "/api/v1/staff/{staff_id}/health-check-requirements"


def _document() -> dict[str, Any]:
    document = app.openapi()
    assert isinstance(document, dict)
    return document


def test_health_check_exposes_date_fact_routes_only() -> None:
    paths = _document()["paths"]
    assert {"get", "post"}.issubset(paths[FACT_PATH])
    assert "patch" in paths[FACT_ITEM_PATH]
    assert "post" in paths[f"{FACT_ITEM_PATH}/invalidate"]
    assert REQUIREMENT_PATH not in paths
    assert not any("health-check-requirements" in path for path in paths)


def test_health_check_models_contain_no_requirement_or_status_contract() -> None:
    schemas = _document()["components"]["schemas"]
    assert {
        "StaffHealthCheckCreateRequest",
        "StaffHealthCheckUpdateRequest",
        "StaffHealthCheckResponse",
        "StaffHealthCheckListResponse",
    }.issubset(schemas)
    assert not any("HealthCheckRequirement" in name for name in schemas)

    create_properties = schemas["StaffHealthCheckCreateRequest"]["properties"]
    update_properties = schemas["StaffHealthCheckUpdateRequest"]["properties"]
    response_properties = schemas["StaffHealthCheckResponse"]["properties"]
    assert set(create_properties) == {"check_date"}
    assert set(update_properties) == {"check_date", "expected_row_version"}
    assert {
        "employment_id",
        "check_type_code",
        "result_note",
        "status",
        "health_check_id",
        "exempt_reason_text",
    }.isdisjoint(response_properties)
    assert {"id", "staff_id", "check_date", "row_version"}.issubset(response_properties)


def test_health_check_mutations_keep_stable_error_responses() -> None:
    paths = _document()["paths"]
    for path in (FACT_PATH, FACT_ITEM_PATH, f"{FACT_ITEM_PATH}/invalidate"):
        for method, operation in paths[path].items():
            if method not in {"post", "patch"}:
                continue
            assert {"403", "409", "422"}.issubset(operation["responses"])
