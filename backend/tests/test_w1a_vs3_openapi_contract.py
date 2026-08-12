from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, NoReturn

import pytest

from app.main import app

EXPECTED_OPERATIONS = {
    "/api/v1/staff/training-courses": {"get"},
    "/api/v1/staff/{staff_id}/onboarding-trainings": {"get"},
    "/api/v1/staff/{staff_id}/onboarding-trainings/{training_id}": {"patch"},
    "/api/v1/staff/{staff_id}/periodic-trainings": {"get", "post"},
    "/api/v1/staff/{staff_id}/periodic-trainings/{training_id}": {"patch"},
    "/api/v1/staff/{staff_id}/periodic-trainings/{training_id}/invalidate": {"post"},
}
SCHEMA_TOKENS = ("TrainingCourse", "OnboardingTraining", "PeriodicTraining")
STABLE_ERRORS = {
    "STAFF_NOT_FOUND",
    "STAFF_EMPLOYMENT_NOT_FOUND",
    "STAFF_ONBOARDING_TRAINING_NOT_FOUND",
    "STAFF_PERIODIC_TRAINING_NOT_FOUND",
    "STAFF_TRAINING_DUPLICATE",
    "STAFF_TRAINING_INVALID_CYCLE",
    "STAFF_TRAINING_PERIOD_INVALID",
    "ROW_VERSION_CONFLICT",
    "VALIDATION_ERROR",
}
FORBIDDEN_PROPERTIES = {
    "training_hours",
    "duration_minutes",
    "completion_date",
    "completed_date",
    "training_center",
    "completion_center",
    "file_id",
    "evidence_id",
    "task_id",
    "work_card_id",
}


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _openapi() -> dict[str, Any]:
    try:
        document = app.openapi()
    except Exception:
        _fail("W1A_VS3_OPENAPI_MISSING: OpenAPI document could not be generated")
    if not isinstance(document, dict):
        _fail("W1A_VS3_OPENAPI_MISSING: OpenAPI document is not an object")
    return document


def _schemas(document: dict[str, Any]) -> dict[str, Any]:
    schemas = document.get("components", {}).get("schemas")
    if not isinstance(schemas, dict):
        _fail("W1A_VS3_OPENAPI_MISSING: named components.schemas is absent")
    return schemas


def _schema_nodes(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _schema_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _schema_nodes(child)


def test_vs3_named_routes_and_separate_models_exist() -> None:
    document = _openapi()
    paths = document.get("paths")
    if not isinstance(paths, dict):
        _fail("W1A_VS3_OPENAPI_MISSING: paths object is absent")
    missing = sorted(set(EXPECTED_OPERATIONS) - set(paths))
    if missing:
        _fail("W1A_VS3_OPENAPI_MISSING: named training routes are absent")
    for path, methods in EXPECTED_OPERATIONS.items():
        if not methods.issubset(set(paths[path])):
            _fail("W1A_VS3_OPENAPI_MISSING: named training operation is absent")

    schemas = _schemas(document)
    if not all(any(token in name for name in schemas) for token in SCHEMA_TOKENS):
        _fail("W1A_VS3_OPENAPI_MISSING: onboarding/periodic/course models are not separate")


def test_vs3_named_responses_errors_and_boolean_only_properties() -> None:
    document = _openapi()
    paths = document.get("paths")
    if not isinstance(paths, dict):
        _fail("W1A_VS3_OPENAPI_MISSING: paths object is absent")
    schemas = _schemas(document)
    serialized = json.dumps(document, ensure_ascii=False)
    if not STABLE_ERRORS.issubset(set(serialized.split('"'))):
        _fail("W1A_VS3_OPENAPI_MISSING: stable training errors are not declared")

    for path, methods in EXPECTED_OPERATIONS.items():
        for method in methods:
            operation = paths[path][method]
            for response in operation.get("responses", {}).values():
                for media in response.get("content", {}).values():
                    schema = media.get("schema", {})
                    if "$ref" not in schema:
                        _fail("W1A_VS3_OPENAPI_MISSING: response uses an unnamed schema")

    training_schemas = {
        name: value
        for name, value in schemas.items()
        if any(token in name for token in SCHEMA_TOKENS)
    }
    if not any("Request" in name for name in training_schemas) or not any(
        "Response" in name for name in training_schemas
    ):
        _fail("W1A_VS3_OPENAPI_MISSING: named training request/response models are absent")
    for node in _schema_nodes(training_schemas):
        if set(node.get("properties", {})).intersection(FORBIDDEN_PROPERTIES):
            _fail("W1A_VS3_FORBIDDEN_PROPERTY_FOUND: non-boolean training field is exposed")
