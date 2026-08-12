from __future__ import annotations

from typing import Any, NoReturn

import pytest

from app.db import models as _models  # noqa: F401
from app.db.base import Base
from app.main import app

CONSULTATION_ROUTE_FRAGMENT = "quarterly-consultations"
FORBIDDEN_ROUTE_FRAGMENTS = {
    "care-change",
    "care_change",
    "attachments",
    "evidence",
    "files",
    "file-upload",
}
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


def _openapi() -> dict[str, Any]:
    try:
        document = app.openapi()
    except Exception:
        _fail("W1A_VS5_ABSENCE_HARNESS_FAILURE: OpenAPI could not be built")
    if not isinstance(document, dict):
        _fail("W1A_VS5_ABSENCE_HARNESS_FAILURE: OpenAPI document is not an object")
    return document


def test_vs5_consultation_surface_has_no_care_change_or_file_routes() -> None:
    paths = _openapi().get("paths", {})
    if not isinstance(paths, dict):
        _fail("W1A_VS5_ABSENCE_HARNESS_FAILURE: OpenAPI paths are not an object")
    for path in paths:
        lowered = str(path).lower()
        if CONSULTATION_ROUTE_FRAGMENT not in lowered:
            continue
        present = sorted(fragment for fragment in FORBIDDEN_ROUTE_FRAGMENTS if fragment in lowered)
        if present:
            _fail(
                "W1A_VS5_FORBIDDEN_ROUTE_FOUND: consultation shares forbidden route surface: "
                + ",".join(present)
            )
    for path in paths:
        lowered = str(path).lower()
        if any(fragment in lowered for fragment in ("care-change", "care_change")):
            if "consult" in lowered or "quarter" in lowered:
                _fail("W1A_VS5_FORBIDDEN_ROUTE_FOUND: care-change consultation route is reused")


def test_vs5_consultation_db_model_has_no_forbidden_fk_or_property() -> None:
    table = Base.metadata.tables.get("staff_quarterly_consultation") or Base.metadata.tables.get(
        "erp.staff_quarterly_consultation"
    )
    if table is None:
        return
    present = FORBIDDEN_PROPERTIES.intersection(column.name for column in table.columns)
    if present:
        _fail("W1A_VS5_FORBIDDEN_DB_FIELD_FOUND: " + ",".join(sorted(present)))
    forbidden_targets = {
        "care_change",
        "care_change_case",
        "care_change_consultation",
        "file",
        "attachment",
        "evidence",
    }
    for foreign_key in table.foreign_keys:
        target = str(foreign_key.target_fullname).lower()
        if any(fragment in target for fragment in forbidden_targets):
            _fail("W1A_VS5_FORBIDDEN_DB_FK_FOUND: consultation references a forbidden surface")


def test_vs5_consultation_schemas_have_no_forbidden_properties() -> None:
    schemas = _openapi().get("components", {}).get("schemas", {})
    if not isinstance(schemas, dict):
        _fail("W1A_VS5_ABSENCE_HARNESS_FAILURE: OpenAPI schemas are not an object")
    for name, schema in schemas.items():
        if "QuarterlyConsultation" not in name and "quarterly_consultation" not in name:
            continue
        if not isinstance(schema, dict):
            continue
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            continue
        present = FORBIDDEN_PROPERTIES.intersection(properties)
        if present:
            _fail(
                "W1A_VS5_FORBIDDEN_OPENAPI_FIELD_FOUND: " + name + ":" + ",".join(sorted(present))
            )


def test_vs5_consultation_does_not_alias_wave2_status_or_entity_names() -> None:
    table_names = {str(name).lower() for name in Base.metadata.tables}
    if "staff_care_change_consultation" in table_names or "care_change_consultation" in table_names:
        consultation_table = Base.metadata.tables.get("staff_quarterly_consultation")
        if consultation_table is not None:
            for foreign_key in consultation_table.foreign_keys:
                if "care_change" in str(foreign_key.target_fullname).lower():
                    _fail("W1A_VS5_FORBIDDEN_DB_FK_FOUND: quarterly ledger aliases care-change")
