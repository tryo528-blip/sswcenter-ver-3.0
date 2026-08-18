from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from app.main import app

EXPECTED_PATHS = {
    "/api/v1/catalogs/services",
    "/api/v1/catalogs/license-types",
    "/api/v1/staff/{staff_id}/licenses",
    "/api/v1/staff/{staff_id}/licenses/{license_id}/replacements",
    "/api/v1/staff/{staff_id}/licenses/{license_id}/invalidate",
    "/api/v1/staff/{staff_id}/service-qualifications",
    "/api/v1/staff/{staff_id}/service-qualifications/{qualification_id}/close",
    "/api/v1/staff/{staff_id}/service-qualifications/{qualification_id}/replacements",
    "/api/v1/staff/{staff_id}/service-qualifications/{qualification_id}/invalidate",
}
EXPECTED_OPERATIONS = {
    "/api/v1/catalogs/services": {"get"},
    "/api/v1/catalogs/license-types": {"get"},
    "/api/v1/staff/{staff_id}/licenses": {"get", "post"},
    "/api/v1/staff/{staff_id}/licenses/{license_id}/replacements": {"post"},
    "/api/v1/staff/{staff_id}/licenses/{license_id}/invalidate": {"post"},
    "/api/v1/staff/{staff_id}/service-qualifications": {"get", "post"},
    "/api/v1/staff/{staff_id}/service-qualifications/{qualification_id}/close": {"post"},
    "/api/v1/staff/{staff_id}/service-qualifications/{qualification_id}/replacements": {"post"},
    "/api/v1/staff/{staff_id}/service-qualifications/{qualification_id}/invalidate": {"post"},
}
LICENSE_SCHEMA_TOKENS = ("LicenseType", "StaffLicense")
QUALIFICATION_SCHEMA_TOKENS = ("StaffServiceQualification",)


def _openapi() -> dict[str, Any]:
    try:
        return app.openapi()
    except Exception:
        pytest.fail("W1A_VS2_OPENAPI_MISSING: OpenAPI document could not be generated")


def _schemas(document: dict[str, Any]) -> dict[str, Any]:
    schemas = document.get("components", {}).get("schemas")
    if not isinstance(schemas, dict):
        pytest.fail("W1A_VS2_OPENAPI_MISSING: named components.schemas is absent")
    return schemas


def _all_schema_nodes(value: Any) -> Iterator[dict[Any, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _all_schema_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _all_schema_nodes(child)


def test_named_vs2_routes_and_models_exist() -> None:
    document = _openapi()
    paths = document.get("paths")
    if not isinstance(paths, dict):
        pytest.fail("W1A_VS2_OPENAPI_MISSING: paths object is absent")
    missing_paths = sorted(EXPECTED_PATHS - set(paths))
    if missing_paths:
        pytest.fail("W1A_VS2_OPENAPI_MISSING: named VS2 routes are absent")
    for path, methods in EXPECTED_OPERATIONS.items():
        if not methods.issubset(set(paths[path])):
            pytest.fail("W1A_VS2_OPENAPI_MISSING: named VS2 operation is absent")

    schemas = _schemas(document)
    missing_groups = [
        token
        for token in LICENSE_SCHEMA_TOKENS + QUALIFICATION_SCHEMA_TOKENS
        if not any(token in name for name in schemas)
    ]
    if missing_groups:
        pytest.fail("W1A_VS2_OPENAPI_MISSING: separate license/qualification models absent")


def test_named_error_and_response_contracts_are_declared() -> None:
    document = _openapi()
    _schemas(document)
    paths = document.get("paths")
    if not isinstance(paths, dict):
        pytest.fail("W1A_VS2_OPENAPI_MISSING: paths object is absent")
    serialized = json.dumps(document, ensure_ascii=False)
    expected_error_codes = {
        "STAFF_NOT_FOUND",
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
    }
    if not expected_error_codes.issubset(set(serialized.split('"'))):
        pytest.fail("W1A_VS2_OPENAPI_MISSING: stable VS2 error codes are not declared")

    for path, methods in EXPECTED_OPERATIONS.items():
        for method in methods:
            operation = paths[path][method]
            for response in operation.get("responses", {}).values():
                content = response.get("content", {})
                for media in content.values():
                    schema = media.get("schema", {})
                    if "$ref" not in schema:
                        pytest.fail("W1A_VS2_OPENAPI_MISSING: response uses an unnamed schema")


def test_forbidden_expiry_duplicate_and_future_fk_properties_are_absent() -> None:
    document = _openapi()
    schemas = _schemas(document)
    license_schemas = {
        name: value
        for name, value in schemas.items()
        if "License" in name and "Qualification" not in name
    }
    qualification_schemas = {
        name: value for name, value in schemas.items() if "Qualification" in name
    }
    if not license_schemas or not qualification_schemas:
        pytest.fail("W1A_VS2_OPENAPI_MISSING: separate named schema groups are absent")
    if not any("Request" in name for name in license_schemas):
        pytest.fail("W1A_VS2_OPENAPI_MISSING: named license request schema is absent")
    if not any("Response" in name for name in license_schemas):
        pytest.fail("W1A_VS2_OPENAPI_MISSING: named license response schema is absent")
    if not any("Request" in name for name in qualification_schemas):
        pytest.fail("W1A_VS2_OPENAPI_MISSING: named qualification request schema is absent")
    if not any("Response" in name for name in qualification_schemas):
        pytest.fail("W1A_VS2_OPENAPI_MISSING: named qualification response schema is absent")

    forbidden_license_properties = {"expiry_date", "start_date", "end_date"}
    for schema in _all_schema_nodes(license_schemas):
        properties = set(schema.get("properties", {}))
        if properties.intersection(forbidden_license_properties):
            pytest.fail("W1A_VS2_OPENAPI_MISSING: license expiry fields are exposed")

    for schema in _all_schema_nodes(qualification_schemas):
        properties = set(schema.get("properties", {}))
        if properties.intersection({"license_number", "issued_date"}):
            pytest.fail("W1A_VS2_OPENAPI_MISSING: qualification duplicates license fields")

    vs2_schema_nodes = {
        name: value
        for name, value in schemas.items()
        if any(
            token in name for token in ("ServiceGroup", "ServiceType", "License", "Qualification")
        )
    }
    for node in _all_schema_nodes(vs2_schema_nodes):
        if node.get("maxItems") == 2:
            pytest.fail("W1A_VS2_OPENAPI_MISSING: forbidden general maxItems=2 is exposed")
        properties = set(node.get("properties", {}))
        if properties.intersection({"schedule_id", "assignment_id", "file_id"}):
            pytest.fail("W1A_VS2_OPENAPI_MISSING: future relationship FK is exposed")
