from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Table

from app.db import models as _models  # noqa: F401
from app.db.base import Base

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
VS2_MIGRATION = (
    WORKSPACE_ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "20260727_0004_w1a_staff_qualifications.py"
)

VS2_TABLES = {
    "service_group",
    "service_type",
    "license_type",
    "staff_license",
    "staff_service_qualification_period",
}


def _migration_source() -> str:
    if not VS2_MIGRATION.is_file():
        pytest.fail("W1A_VS2_SEMANTICS_MISSING: 20260727_0004_w1a_staff_qualifications.py")
    try:
        return VS2_MIGRATION.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        pytest.fail("W1A_VS2_SEMANTICS_MISSING: VS2 migration is not readable as UTF-8")


def _require_mapped_tables() -> dict[str, Table]:
    tables = Base.metadata.tables
    mapped_keys = {name: name if name in tables else f"erp.{name}" for name in VS2_TABLES}
    missing = sorted(name for name, key in mapped_keys.items() if key not in tables)
    if missing:
        pytest.fail("W1A_VS2_SEMANTICS_MISSING: mapped VS2 tables are absent")
    return {name: tables[key] for name, key in mapped_keys.items()}


def _require_fragments(source: str, fragments: set[str], contract: str) -> None:
    missing = sorted(fragment for fragment in fragments if fragment not in source)
    if missing:
        pytest.fail(f"W1A_VS2_SEMANTICS_MISSING: {contract} fragments are absent")


def _table_columns(table: Table) -> set[str]:
    return {column.name for column in table.columns}


def _constraint_columns(constraint: object) -> set[str]:
    columns = getattr(constraint, "columns", ())
    return {column.name for column in columns}


def test_vs2_migration_declares_catalog_tables_and_revision() -> None:
    source = _migration_source()
    _require_fragments(
        source,
        {
            'revision: str = "20260727_0004_w1a_staff_qualifications"',
            "service_group",
            "service_type",
            "license_type",
        },
        "VS2 migration and catalog tables",
    )


def test_license_and_qualification_are_separate_unbounded_ledgers() -> None:
    tables = _require_mapped_tables()
    service_type_columns = _table_columns(tables["service_type"])
    license_columns = _table_columns(tables["staff_license"])
    qualification_columns = _table_columns(tables["staff_service_qualification_period"])

    if "service_group_id" not in service_type_columns:
        pytest.fail("W1A_VS2_SEMANTICS_MISSING: service_type group FK is absent")
    if "group_code" in service_type_columns:
        pytest.fail("W1A_VS2_SEMANTICS_MISSING: service_type duplicates group_code")

    required_license_columns = {
        "staff_id",
        "license_type_id",
        "license_number",
        "issued_date",
        "row_version",
    }
    required_qualification_columns = {
        "staff_id",
        "employment_id",
        "service_type_id",
        "start_date",
        "end_date",
        "source_license_id",
        "row_version",
    }
    if not required_license_columns.issubset(license_columns):
        pytest.fail("W1A_VS2_SEMANTICS_MISSING: license fact columns are incomplete")
    if not required_qualification_columns.issubset(qualification_columns):
        pytest.fail("W1A_VS2_SEMANTICS_MISSING: qualification period columns are incomplete")
    if license_columns.intersection({"start_date", "end_date", "expiry_date"}):
        pytest.fail("W1A_VS2_SEMANTICS_MISSING: license ledger has forbidden expiry fields")
    if qualification_columns.intersection({"license_number", "issued_date"}):
        pytest.fail("W1A_VS2_SEMANTICS_MISSING: qualification duplicates license facts")


def test_license_duplicate_invalidation_replacement_and_unbounded_count_contract() -> None:
    source = _migration_source()
    _require_fragments(
        source,
        {
            "invalidated_at_utc",
            "replacement_license_id",
            "license_type_id",
            "license_number",
            "STAFF_LICENSE_DUPLICATE",
            "STAFF_LICENSE_NOT_FOUND",
        },
        "license duplicate and correction history",
    )
    tables = _require_mapped_tables()
    license_table = tables["staff_license"]
    unique_objects = set(license_table.indexes).union(license_table.constraints)
    if not any(
        getattr(item, "unique", False)
        and _constraint_columns(item) == {"license_type_id", "license_number"}
        and getattr(item, "name", None) == "uq_staff_license_type_number_active"
        and "invalidated_at_utc"
        in str(getattr(item, "dialect_options", {}).get("postgresql", {}).get("where", ""))
        for item in unique_objects
    ):
        pytest.fail("W1A_VS2_SEMANTICS_MISSING: active license partial uniqueness is absent")
    if not any(
        (getattr(item, "unique", False) or item.__class__.__name__ == "UniqueConstraint")
        and _constraint_columns(item) == {"staff_id", "id"}
        and getattr(item, "name", None) == "uq_staff_license_staff_id_id"
        for item in unique_objects
    ):
        pytest.fail("W1A_VS2_SEMANTICS_MISSING: same-staff license key is absent")


def test_qualification_source_employment_overlap_and_deferred_transaction_contract() -> None:
    source = _migration_source()
    _require_fragments(
        source,
        {
            "source_license_id",
            "daterange",
            "ex_staff_service_qualification_period",
            "ct_staff_service_qualification_within_employment",
            "ct_staff_employment_child_periods_reverse_guard",
            "DEFERRABLE INITIALLY DEFERRED",
            "STAFF_QUALIFICATION_SOURCE_LICENSE_MISMATCH",
            "STAFF_SERVICE_QUALIFICATION_CONFLICT",
        },
        "qualification source, employment containment, overlap, and deferral",
    )
    _require_mapped_tables()


def test_audit_row_version_acl_and_forbidden_future_relationship_contract() -> None:
    source = _migration_source()
    _require_fragments(
        source,
        {
            "updated_by_account_id",
            "updated_at_utc",
            "row_version",
            "audit_event",
            "erp_app",
            "erp_backup",
        },
        "audit, optimistic locking, and runtime ACL",
    )
