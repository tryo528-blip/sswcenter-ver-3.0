from typing import Any

import pytest
from fastapi.testclient import TestClient


def _resolve_enum(schema: dict[str, Any], schemas: dict[str, Any]) -> list[str]:
    if "enum" in schema:
        enum_values = schema["enum"]
        assert isinstance(enum_values, list), "I1_OPENAPI_SEX_ENUM_INVALID"
        return enum_values
    reference = schema.get("$ref")
    assert isinstance(reference, str), "I1_OPENAPI_SEX_ENUM_UNRESOLVABLE"
    name = reference.rsplit("/", 1)[-1]
    referenced_schema = schemas.get(name)
    assert isinstance(referenced_schema, dict), "I1_OPENAPI_SEX_ENUM_REFERENCE_MISSING"
    enum_values = referenced_schema.get("enum")
    assert isinstance(enum_values, list), "I1_OPENAPI_SEX_ENUM_MISSING"
    return enum_values


def test_openapi_w1a_staff_routes_and_schemas_registered() -> None:
    """Verify that FastAPI OpenAPI spec includes all W1A staff endpoints and named schemas."""
    try:
        from app.main import app
    except ImportError:
        pytest.fail("W1A_OA_MISSING: FastAPI app instance missing in app.main")

    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200, "W1A_OA_SPEC_FETCH_FAILED: OpenAPI spec fetch failed"
    spec = response.json()

    paths = spec.get("paths", {})
    required_paths = [
        "/api/v1/staff",
        "/api/v1/staff/{staff_id}",
        "/api/v1/staff/{staff_id}/employments",
        "/api/v1/staff/{staff_id}/employments/{employment_id}/close",
        "/api/v1/staff/{staff_id}/employments/{employment_id}/replacements",
        "/api/v1/staff/{staff_id}/employments/{employment_id}/positions",
        "/api/v1/staff/{staff_id}/employments/{employment_id}/positions/{period_id}/close",
        "/api/v1/staff/{staff_id}/employments/{employment_id}/positions/{period_id}/replacements",
        "/api/v1/staff/{staff_id}/employments/{employment_id}/operational-roles",
        "/api/v1/staff/{staff_id}/employments/{employment_id}/operational-roles/{period_id}/close",
        "/api/v1/staff/{staff_id}/employments/{employment_id}/operational-roles/{period_id}/replacements",
        "/api/v1/staff/{staff_id}/sensitive-identity/reveal",
        "/api/v1/session-capabilities",
    ]
    for required_path in required_paths:
        assert required_path in paths, (
            f"W1A_OA_PATH_MISSING: OpenAPI spec missing required path '{required_path}'"
        )

    schemas = spec.get("components", {}).get("schemas", {})
    required_schemas = [
        "StaffCreateRequest",
        "StaffResponse",
        "StaffDetailResponse",
        "StaffEmploymentResponse",
        "StaffPositionPeriodResponse",
        "StaffOperationalRolePeriodResponse",
        "SensitiveIdentityRevealRequest",
        "SensitiveIdentityRevealResponse",
        "SessionCapabilitiesResponse",
        "ErrorEnvelope",
    ]
    for schema_name in required_schemas:
        assert schema_name in schemas, (
            f"W1A_OA_SCHEMA_MISSING: OpenAPI spec missing required schema '{schema_name}'"
        )


def test_openapi_no_sensitive_or_internal_properties_in_general_schemas() -> None:
    """Verify general schemas omit plaintext, cipher, and internal projections."""
    try:
        from app.main import app
    except ImportError:
        pytest.fail("W1A_OA_MISSING: FastAPI app instance missing in app.main")

    client = TestClient(app)
    spec = client.get("/openapi.json").json()
    schemas = spec.get("components", {}).get("schemas", {})

    forbidden_properties = {
        "resident_number",
        "resident_number_ciphertext",
        "resident_number_nonce",
        "resident_number_lookup_hmac",
        "resident_number_key_version",
        "phone_normalized",
        "current_pin",
    }

    general_schema_names = [
        "StaffResponse",
        "StaffDetailResponse",
        "StaffEmploymentResponse",
        "StaffPositionPeriodResponse",
        "StaffOperationalRolePeriodResponse",
    ]

    for name in general_schema_names:
        schema = schemas.get(name, {})
        props = set(schema.get("properties", {}).keys())
        leakage = props.intersection(forbidden_properties)
        assert not leakage, (
            "W1A_OA_SENSITIVE_LEAKAGE: "
            f"General schema '{name}' leaks forbidden properties {leakage}"
        )


def test_openapi_staff_contracts_expose_exact_sex_and_replacement_nullability() -> None:
    from app.main import app

    schemas = TestClient(app).get("/openapi.json").json()["components"]["schemas"]
    sex_enum = schemas["SexCode"]["enum"]
    assert sex_enum == ["MALE", "FEMALE", "TEST"]

    role_schema = schemas["InitialOperationalRoleRequest"]["properties"]["role_code"]
    assert role_schema["pattern"] == r"^[A-Z][A-Z0-9_]{0,49}$"

    replacement = schemas["StaffEmploymentReplacementRequest"]["properties"]
    assert "null" in str(replacement["position_replacements"])
    assert "null" in str(replacement["operational_role_replacements"])

    position_replacement = schemas["StaffEmploymentPositionReplacement"]
    role_replacement = schemas["StaffEmploymentOperationalRoleReplacement"]
    assert "replacement" in position_replacement["required"]
    assert "replacement" in role_replacement["required"]
    assert "null" in str(position_replacement["properties"]["replacement"])
    assert "null" in str(role_replacement["properties"]["replacement"])


def test_openapi_create_input_excludes_test_but_response_includes_test() -> None:
    from app.main import app

    schemas = TestClient(app).get("/openapi.json").json()["components"]["schemas"]
    create_sex_schema = schemas["StaffCreateRequest"]["properties"]["sex_code"]
    response_sex_schema = schemas["StaffResponse"]["properties"]["sex_code"]

    create_enum = _resolve_enum(create_sex_schema, schemas)
    response_enum = _resolve_enum(response_sex_schema, schemas)
    assert create_enum == ["MALE", "FEMALE"], "I1_CREATE_SEX_ENUM_ADVERTISES_TEST"
    assert response_enum == ["MALE", "FEMALE", "TEST"], "I1_RESPONSE_SEX_ENUM_MISSING_TEST"
    assert create_sex_schema != response_sex_schema, "I1_CREATE_RESPONSE_SEX_ENUM_SHARED"
