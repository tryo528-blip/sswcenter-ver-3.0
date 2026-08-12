from __future__ import annotations

from typing import NoReturn

import pytest

from app.main import app


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def test_vs4_no_automatic_target_generator_or_side_effect_route() -> None:
    try:
        document = app.openapi()
    except Exception:
        _fail("W1A_VS4_ABSENCE_HARNESS_FAILURE: OpenAPI could not be built")
    paths = document.get("paths", {})
    if not isinstance(paths, dict):
        _fail("W1A_VS4_ABSENCE_HARNESS_FAILURE: OpenAPI paths are not an object")
    forbidden_segments = {
        "generate-target",
        "target-generator",
        "d-day",
        "tasks",
        "attachments",
        "evidence",
    }
    for path, operations in paths.items():
        lowered = str(path).lower()
        if "health" not in lowered and "검진" not in lowered:
            continue
        if any(segment in lowered for segment in forbidden_segments):
            _fail("W1A_VS4_FORBIDDEN_ROUTE_FOUND: automatic target/task/file route exists")
        if "health-check-requirements" in lowered and isinstance(operations, dict):
            if "post" in operations and path.endswith("health-check-requirements"):
                _fail("W1A_VS4_FORBIDDEN_ROUTE_FOUND: public requirement generator/create exists")


def test_vs4_no_target_d_day_task_or_file_property_on_health_models() -> None:
    try:
        schemas = app.openapi().get("components", {}).get("schemas", {})
    except Exception:
        _fail("W1A_VS4_ABSENCE_HARNESS_FAILURE: OpenAPI schema inspection failed")
    forbidden = {
        "d_day",
        "dday",
        "task_id",
        "task_code",
        "file_id",
        "file_key",
        "attachment_id",
        "evidence_file_id",
    }
    for name, schema in schemas.items():
        if "HealthCheck" not in name and "health_check" not in name:
            continue
        present = forbidden.intersection(schema.get("properties", {}))
        if present:
            _fail(
                "W1A_VS4_FORBIDDEN_OPENAPI_FIELD_FOUND: " + name + ":" + ",".join(sorted(present))
            )
