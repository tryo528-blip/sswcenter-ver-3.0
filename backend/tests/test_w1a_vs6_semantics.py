from __future__ import annotations

import ast
from pathlib import Path
from typing import NoReturn

import pytest
from sqlalchemy import ForeignKeyConstraint, Index, Table

from app.db import models as _models  # noqa: F401
from app.db.base import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT / "backend" / "alembic" / "versions" / "20260728_0008_w1a_staff_legacy_mapping.py"
)
MAPPING_PATH = REPO_ROOT / "backend" / "app" / "db" / "models.py"
IMPORTER_PATH = REPO_ROOT / "backend" / "app" / "domains" / "staff" / "legacy_import.py"
REVISION = "20260728_0008_w1a_staff_legacy_mapping"
PARENT_REVISION = "20260728_0007_w1a_staff_quarterly_consultation"
PREDECESSOR_MIGRATION_FILENAMES = (
    "20260724_0001_wave0_schema.py",
    "20260724_0002_wave0_auth_audit.py",
    "20260726_0003_w1a_staff.py",
    "20260727_0004_w1a_staff_qualifications.py",
    "20260728_0005_w1a_staff_training.py",
    "20260728_0006_w1a_staff_health_check.py",
    "20260728_0007_w1a_staff_quarterly_consultation.py",
)
TABLE_NAME = "staff_legacy_mapping"
REQUIRED_COLUMNS = {
    "id",
    "source_system_code",
    "legacy_staff_key",
    "staff_id",
    "source_row_fingerprint",
    "invalidated_at_utc",
    "replacement_staff_legacy_mapping_id",
    "created_by_account_id",
    "created_at_utc",
    "updated_by_account_id",
    "updated_at_utc",
    "row_version",
}
FORBIDDEN_FIELDS = {
    "alias",
    "alias_name",
    "employment_type",
    "employment_status",
    "account_number",
    "salary",
    "insurance",
    "severance",
    "service_unit_price",
    "past_health_check_id",
    "care_change_id",
    "file_id",
    "attachment_id",
    "document_id",
    "ocr_run_id",
    "import_run_id",
    "import_row_id",
}


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _read_utf8(path: Path, marker: str) -> str:
    if not path.is_file():
        _fail(marker)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        _fail(marker)


def _migration_source() -> str:
    return _read_utf8(
        MIGRATION_PATH,
        "W1A_VS6_MIGRATION_MISSING: 0008 staff legacy mapping migration is absent",
    )


def _literal_strings(source: str, marker: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        _fail(marker)
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _mapped_table() -> Table:
    table = Base.metadata.tables.get(TABLE_NAME) or Base.metadata.tables.get(f"erp.{TABLE_NAME}")
    if table is None:
        _fail("W1A_VS6_MODEL_MISSING: staff legacy mapping table is not mapped")
    return table


def _has_staff_fk(table: Table) -> bool:
    for constraint in table.constraints:
        if not isinstance(constraint, ForeignKeyConstraint):
            continue
        local = {element.parent.name for element in constraint.elements}
        targets = {str(element.target_fullname) for element in constraint.elements}
        if local == {"staff_id"} and any(
            target in {"erp.staff.id", "staff.id"} for target in targets
        ):
            return True
    return False


def _has_replacement_fk(table: Table) -> bool:
    for constraint in table.constraints:
        if not isinstance(constraint, ForeignKeyConstraint):
            continue
        local = {element.parent.name for element in constraint.elements}
        targets = {str(element.target_fullname) for element in constraint.elements}
        if local == {"replacement_staff_legacy_mapping_id"} and any(
            target in {"erp.staff_legacy_mapping.id", "staff_legacy_mapping.id"}
            for target in targets
        ):
            return True
    return False


def _active_unique_index(table: Table) -> Index | None:
    for index in table.indexes:
        if not index.unique:
            continue
        if {column.name for column in index.columns} != {
            "source_system_code",
            "legacy_staff_key",
        }:
            continue
        options = index.dialect_options.get("postgresql")
        where = options.get("where") if options is not None else None
        if where is not None and "invalidated_at_utc" in str(where).lower():
            return index
    return None


def test_vs6_00_revision_and_required_contract_fragments() -> None:
    source = _migration_source()
    literals = _literal_strings(
        source,
        "W1A_VS6_MIGRATION_MISSING: 0008 migration is not valid Python",
    )
    required = {
        REVISION,
        PARENT_REVISION,
        TABLE_NAME,
        "source_system_code",
        "legacy_staff_key",
        "staff_id",
        "source_row_fingerprint",
        "invalidated_at_utc",
        "replacement_staff_legacy_mapping_id",
        "created_by_account_id",
        "updated_by_account_id",
        "row_version",
    }
    missing = sorted(required - literals)
    if missing:
        _fail(
            "W1A_VS6_MIGRATION_MISSING: revision/table contract is incomplete: " + ",".join(missing)
        )


def test_vs6_01_table_shape_fk_and_audit_metadata() -> None:
    source = _migration_source()
    table = _mapped_table()
    missing = sorted(REQUIRED_COLUMNS - {column.name for column in table.columns})
    if missing:
        _fail("W1A_VS6_DB_SCHEMA_MISSING: required columns are absent: " + ",".join(missing))
    if not table.c.id.primary_key:
        _fail("W1A_VS6_DB_SCHEMA_MISSING: id is not the primary key")
    for name in (
        "source_system_code",
        "legacy_staff_key",
        "staff_id",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    ):
        if table.c[name].nullable:
            _fail(f"W1A_VS6_DB_SCHEMA_MISSING: {name} must be NOT NULL")
    for name in (
        "source_row_fingerprint",
        "invalidated_at_utc",
        "replacement_staff_legacy_mapping_id",
    ):
        if not table.c[name].nullable:
            _fail(f"W1A_VS6_DB_SCHEMA_MISSING: {name} must be nullable")
    if not _has_staff_fk(table):
        _fail("W1A_VS6_STAFF_FK_MISSING: mapping does not reference staff.id")
    if not _has_replacement_fk(table):
        _fail("W1A_VS6_REPLACEMENT_FK_MISSING: replacement mapping FK is absent")
    if _active_unique_index(table) is None:
        _fail("W1A_VS6_ACTIVE_UNIQUE_MISSING: active source/key unique is absent")
    if "ON DELETE RESTRICT" not in source.upper():
        _fail("W1A_VS6_STAFF_FK_MISSING: mapping FK is not RESTRICT")


def test_vs6_02_active_predicate_audit_actions_and_no_wave5_tables() -> None:
    source = _migration_source().upper()
    importer_source = _read_utf8(
        IMPORTER_PATH,
        "W1A_VS6_SERVICE_MISSING: internal legacy importer is absent",
    ).upper()
    table = _mapped_table()
    constraints = "\n".join(
        str(getattr(item, "sqltext", item)) for item in table.constraints
    ).upper()
    if "INVALIDATED_AT_UTC IS NULL" not in source and _active_unique_index(table) is None:
        _fail("W1A_VS6_ACTIVE_UNIQUE_MISSING: active predicate is absent")
    if "ROW_VERSION > 0" not in source and "ROW_VERSION > 0" not in constraints:
        _fail("W1A_VS6_ROW_VERSION_CHECK_MISSING: positive row_version check is absent")
    if not any(
        token in importer_source
        for token in ("AUDIT_EVENT", "AUDITEVENT", "_AUDIT", "CREATED_FROM")
    ):
        _fail("W1A_VS6_AUDIT_PATH_MISSING: importer has no observable audit write path")
    if any(
        token.upper() in source
        for token in (
            "IMPORT_RUN",
            "IMPORT_ROW",
            "FILEBOX",
            "OCR_RUN",
            "DOCUMENT_RECORD",
            "GENERATED_DOCUMENT",
        )
    ):
        _fail("W1A_VS6_FORBIDDEN_STRUCTURE_FOUND: migration imports a Wave 5 structure")


def test_vs6_03_old_migrations_are_unchanged_and_importer_is_not_model_surface() -> None:
    _migration_source()
    migration_directory = REPO_ROOT / "backend" / "alembic" / "versions"
    old_paths = [migration_directory / filename for filename in PREDECESSOR_MIGRATION_FILENAMES]
    missing_paths = [path.name for path in old_paths if not path.is_file()]
    if missing_paths:
        _fail(
            "W1A_VS6_MIGRATION_MISSING: 0001-0007 migrations are incomplete: "
            + ",".join(missing_paths)
        )
    for path in old_paths:
        source = _read_utf8(path, "W1A_VS6_MIGRATION_MISSING: existing migration is unreadable")
        if REVISION in source or TABLE_NAME in source:
            _fail("W1A_VS6_OLD_MIGRATION_MODIFIED: 0008 surface leaked into an old migration")
    if (
        IMPORTER_PATH.exists()
        and "router"
        in _read_utf8(IMPORTER_PATH, "W1A_VS6_SERVICE_MISSING: importer is unreadable").lower()
    ):
        _fail("W1A_VS6_PUBLIC_IMPORT_ROUTE_FOUND: internal importer refers to a router")
