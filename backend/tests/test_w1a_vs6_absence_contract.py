from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, NoReturn

import pytest
from fastapi.routing import APIRoute

from app.db import models as _models  # noqa: F401
from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT / "backend" / "alembic" / "versions" / "20260728_0008_w1a_staff_legacy_mapping.py"
)
PUBLIC_PRODUCT_FILES = (
    REPO_ROOT / "backend" / "app" / "api" / "staff.py",
    REPO_ROOT / "backend" / "app" / "domains" / "staff" / "schemas.py",
    REPO_ROOT / "backend" / "app" / "domains" / "staff" / "service.py",
    REPO_ROOT / "backend" / "app" / "domains" / "staff" / "repository.py",
    REPO_ROOT / "frontend" / "src" / "pages" / "StaffPage.tsx",
    REPO_ROOT / "frontend" / "src" / "services" / "staffApi.ts",
    REPO_ROOT / "frontend" / "src" / "generated" / "sswcenter-api.ts",
)
PUBLIC_SURFACE_FRAGMENTS = {
    "legacy_staff_key",
    "staff_legacy_mapping",
    "legacy-import",
    "legacy_import",
    "import-run",
    "import_run",
}
FORBIDDEN_INPUT_FRAGMENTS = {
    "alias_name",
    "employment_type",
    "employment_status",
    "account_number",
    "bank_account",
    "payroll",
    "insurance",
    "severance",
    "service_unit_price",
    "past_health_check",
    "care_change_id",
    "file_id",
    "attachment_id",
    "document_id",
    "ocr_run_id",
}
FORBIDDEN_NEW_STRUCTURE_FRAGMENTS = {
    "import_run",
    "import_row",
    "staging",
    "filebox",
    "ocr_run",
    "document_record",
    "generated_document",
    "evidence_file",
}


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _read(path: Path, marker: str) -> str:
    if not path.is_file():
        _fail(marker)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        _fail(marker)


def _openapi() -> dict[str, Any]:
    try:
        document = app.openapi()
    except Exception:
        _fail("W1A_VS6_ABSENCE_HARNESS_FAILURE: OpenAPI could not be built")
    if not isinstance(document, dict):
        _fail("W1A_VS6_ABSENCE_HARNESS_FAILURE: OpenAPI document is not an object")
    return document


def _hidden_public_route_hits() -> list[str]:
    hits: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        endpoint = route.endpoint
        endpoint_source = ""
        try:
            endpoint_source = inspect.getsource(endpoint)
        except (OSError, TypeError):
            _fail("W1A_VS6_ABSENCE_HARNESS_FAILURE: public route source is unavailable")
        route_surface = " ".join(
            (
                str(route.path),
                str(route.name),
                str(getattr(endpoint, "__module__", "")),
                str(getattr(endpoint, "__qualname__", "")),
                endpoint_source,
            )
        ).lower()
        if any(fragment in route_surface for fragment in PUBLIC_SURFACE_FRAGMENTS):
            hits.append(str(route.path))
    return sorted(set(hits))


def test_vs6_00_public_openapi_has_no_legacy_mapping_import_surface() -> None:
    document = _openapi()
    hidden_route_hits = _hidden_public_route_hits()
    if hidden_route_hits:
        _fail("W1A_VS6_PUBLIC_IMPORT_ROUTE_FOUND: " + ",".join(hidden_route_hits))
    serialized = json.dumps(document, ensure_ascii=False).lower()
    present = sorted(fragment for fragment in PUBLIC_SURFACE_FRAGMENTS if fragment in serialized)
    if present:
        _fail("W1A_VS6_PUBLIC_IMPORT_PROPERTY_FOUND: " + ",".join(present))
    paths = document.get("paths", {})
    if not isinstance(paths, dict):
        _fail("W1A_VS6_ABSENCE_HARNESS_FAILURE: OpenAPI paths are not an object")
    path_hits = sorted(
        str(path)
        for path in paths
        if any(fragment in str(path).lower() for fragment in PUBLIC_SURFACE_FRAGMENTS)
    )
    if path_hits:
        _fail("W1A_VS6_PUBLIC_IMPORT_ROUTE_FOUND: " + ",".join(path_hits))


def test_vs6_01_public_staff_files_do_not_expose_legacy_key_or_import() -> None:
    for path in PUBLIC_PRODUCT_FILES:
        source = _read(path, "W1A_VS6_ABSENCE_HARNESS_FAILURE: public product file is unreadable")
        lowered = source.lower()
        present = sorted(fragment for fragment in PUBLIC_SURFACE_FRAGMENTS if fragment in lowered)
        if present:
            _fail(
                "W1A_VS6_PUBLIC_PRODUCT_SURFACE_FOUND: "
                + str(path.relative_to(REPO_ROOT))
                + ":"
                + ",".join(present)
            )


def test_vs6_02_staff_public_contract_has_no_banned_legacy_input_fields() -> None:
    for path in PUBLIC_PRODUCT_FILES:
        source = _read(path, "W1A_VS6_ABSENCE_HARNESS_FAILURE: public product file is unreadable")
        lowered = source.lower()
        present = sorted(fragment for fragment in FORBIDDEN_INPUT_FRAGMENTS if fragment in lowered)
        if present:
            _fail(
                "W1A_VS6_FORBIDDEN_PUBLIC_INPUT_FIELD_FOUND: "
                + str(path.relative_to(REPO_ROOT))
                + ":"
                + ",".join(present)
            )


def test_vs6_03_new_product_files_do_not_add_wave5_import_file_or_ocr_structures() -> None:
    paths = []
    if MIGRATION_PATH.is_file():
        paths.append(MIGRATION_PATH)
    importer = REPO_ROOT / "backend" / "app" / "domains" / "staff" / "legacy_import.py"
    if importer.is_file():
        paths.append(importer)
    for path in paths:
        source = _read(path, "W1A_VS6_ABSENCE_HARNESS_FAILURE: new product file is unreadable")
        lowered = source.lower()
        present = sorted(
            fragment for fragment in FORBIDDEN_NEW_STRUCTURE_FRAGMENTS if fragment in lowered
        )
        if present:
            _fail(
                "W1A_VS6_FORBIDDEN_STRUCTURE_FOUND: "
                + str(path.relative_to(REPO_ROOT))
                + ":"
                + ",".join(present)
            )


def test_vs6_04_general_license_surface_remains_unbounded_by_import_limit() -> None:
    document = _openapi()
    schemas = document.get("components", {}).get("schemas", {})
    if not isinstance(schemas, dict):
        _fail("W1A_VS6_ABSENCE_HARNESS_FAILURE: OpenAPI schemas are not an object")
    for name, schema in schemas.items():
        if "license" not in str(name).lower() or not isinstance(schema, dict):
            continue
        if schema.get("maxItems") == 2:
            _fail(
                "W1A_VS6_GENERAL_LICENSE_MAX_ITEMS_FOUND: general license schema is capped at two"
            )
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for property_schema in properties.values():
                if isinstance(property_schema, dict) and property_schema.get("maxItems") == 2:
                    _fail("W1A_VS6_GENERAL_LICENSE_MAX_ITEMS_FOUND: license list is capped at two")
