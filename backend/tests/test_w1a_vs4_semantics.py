from __future__ import annotations

import ast
from pathlib import Path
from typing import NoReturn

import pytest
from sqlalchemy import Table

from app.db import models as _models  # noqa: F401
from app.db.base import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT / "backend" / "alembic" / "versions" / ("20260728_0006_w1a_staff_health_check.py")
)
VS4_REVISION = "20260728_0006_w1a_staff_health_check"
HEALTH_TABLES = {"staff_health_check", "staff_health_check_requirement"}
FORBIDDEN_HEALTH_FIELDS = {
    "d_day",
    "dday",
    "task_id",
    "task_code",
    "file_id",
    "file_key",
    "attachment_id",
    "evidence_file_id",
}


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _migration_source() -> str:
    if not MIGRATION_PATH.is_file():
        _fail("W1A_VS4_MIGRATION_MISSING: 0006 health-check migration is absent")
    try:
        return MIGRATION_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        _fail("W1A_VS4_MIGRATION_MISSING: 0006 migration is not UTF-8 readable")


def _literal_strings(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        _fail("W1A_VS4_MIGRATION_MISSING: 0006 migration is not valid Python")
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            values.add(node.value)
    return values


def _mapped_tables() -> dict[str, Table]:
    tables = Base.metadata.tables
    resolved: dict[str, Table] = {}
    for name in HEALTH_TABLES:
        table = tables.get(name) or tables.get(f"erp.{name}")
        if table is not None:
            resolved[name] = table
    missing = sorted(HEALTH_TABLES - set(resolved))
    if missing:
        _fail(f"W1A_VS4_MODEL_MISSING: health tables are not mapped: {','.join(missing)}")
    return resolved


def _columns(table: Table) -> set[str]:
    return {column.name for column in table.columns}


def _constraint_columns(item: object) -> set[str]:
    return {column.name for column in getattr(item, "columns", ())}


def _has_same_staff_fk(table: Table, local_fk: set[str], target_table: str) -> bool:
    for item in table.constraints:
        if item.__class__.__name__ != "ForeignKeyConstraint":
            continue
        elements = getattr(item, "elements", ())
        local = {getattr(element.parent, "name", "") for element in elements}
        target = str(item)
        if local_fk.issubset(local) and target_table in target:
            return True
    return False


def test_vs4_revision_and_required_contract_fragments() -> None:
    source = _migration_source()
    literals = _literal_strings(source)
    required = {
        VS4_REVISION,
        "staff_health_check",
        "staff_health_check_requirement",
        "health_check_id",
        "target_key",
        "target_rule_version_code",
        "COMPLETE",
        "INCOMPLETE",
        "EXEMPT",
        "20260727_0005_w1a_staff_training",
    }
    missing = sorted(required - literals)
    if missing:
        _fail(
            "W1A_VS4_MIGRATION_MISSING: revision/table/status contract is incomplete: "
            + ",".join(missing)
        )


def test_vs4_fact_shape_allows_same_date_and_nullable_same_staff_employment() -> None:
    tables = _mapped_tables()
    fact = tables["staff_health_check"]
    columns = _columns(fact)
    required = {
        "id",
        "staff_id",
        "employment_id",
        "check_date",
        "check_type_code",
        "result_note",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
        "invalidated_at_utc",
        "replacement_health_check_id",
    }
    if not required.issubset(columns):
        _fail("W1A_VS4_FACT_COLUMNS_MISSING: health fact shape is incomplete")
    if fact.c.check_date.nullable:
        _fail("W1A_VS4_FACT_CHECK_DATE_MISSING: check_date must be required")
    if not fact.c.employment_id.nullable:
        _fail("W1A_VS4_FACT_EMPLOYMENT_NULLABLE_MISSING: employment_id must be nullable")
    if not _has_same_staff_fk(fact, {"staff_id", "employment_id"}, "staff_employment"):
        _fail("W1A_VS4_FACT_STAFF_EMPLOYMENT_FK_MISSING: employment is not same-staff guarded")
    if any(
        getattr(item, "unique", False) and _constraint_columns(item) == {"staff_id", "check_date"}
        for item in set(fact.indexes).union(fact.constraints)
    ):
        _fail("W1A_VS4_FACT_DATE_UNIQUE_FORBIDDEN: same-date facts must be plural")


def test_vs4_requirement_shape_and_same_staff_fact_fk() -> None:
    tables = _mapped_tables()
    requirement = tables["staff_health_check_requirement"]
    columns = _columns(requirement)
    required = {
        "id",
        "staff_id",
        "employment_id",
        "target_key",
        "target_rule_version_code",
        "status",
        "health_check_id",
        "exempt_reason_text",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
        "invalidated_at_utc",
        "replacement_health_check_requirement_id",
    }
    if not required.issubset(columns):
        _fail("W1A_VS4_REQUIREMENT_COLUMNS_MISSING: requirement shape is incomplete")
    if not requirement.c.employment_id.nullable or not requirement.c.health_check_id.nullable:
        _fail("W1A_VS4_REQUIREMENT_NULLABILITY_MISSING: nullable requirement links are absent")
    if not _has_same_staff_fk(
        requirement,
        {"staff_id", "employment_id"},
        "staff_employment",
    ):
        _fail("W1A_VS4_REQUIREMENT_EMPLOYMENT_FK_MISSING: employment is not same-staff guarded")
    if not _has_same_staff_fk(
        requirement,
        {"staff_id", "health_check_id"},
        "staff_health_check",
    ):
        _fail("W1A_VS4_REQUIREMENT_FACT_FK_MISSING: health fact is not same-staff guarded")


def test_vs4_active_target_unique_truth_table_and_forbidden_fields() -> None:
    source = _migration_source()
    tables = _mapped_tables()
    requirement = tables["staff_health_check_requirement"]
    source_upper = source.upper()
    if (
        "COMPLETE" not in source_upper
        or "INCOMPLETE" not in source_upper
        or "EXEMPT" not in source_upper
    ):
        _fail("W1A_VS4_STATUS_ENUM_MISSING: exact three health statuses are absent")
    if "INVALIDATED_AT_UTC IS NULL" not in source_upper:
        _fail("W1A_VS4_ACTIVE_UNIQUE_MISSING: active-row predicate is absent")
    if not any(
        getattr(item, "unique", False)
        and _constraint_columns(item) == {"staff_id", "target_key"}
        and "uq_staff_health_check_requirement_active" in str(item)
        for item in set(requirement.indexes).union(requirement.constraints)
    ):
        _fail("W1A_VS4_ACTIVE_TARGET_UNIQUE_MISSING: active target key is not unique")
    present_forbidden = sorted(FORBIDDEN_HEALTH_FIELDS.intersection(_columns(requirement)))
    if present_forbidden:
        _fail(
            "W1A_VS4_FORBIDDEN_DB_FIELD_FOUND: health requirement has "
            + ",".join(present_forbidden)
        )
    if "DEFERRABLE INITIALLY DEFERRED" not in source_upper:
        _fail("W1A_VS4_DEFERRED_CONSTRAINT_MISSING: deferred same-staff guard is absent")
