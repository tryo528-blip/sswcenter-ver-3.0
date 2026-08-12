from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, NoReturn

import pytest
from sqlalchemy import Table

from app.db import models as _models  # noqa: F401
from app.db.base import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
VS3_MIGRATION = (
    REPO_ROOT / "backend" / "alembic" / "versions" / "20260728_0005_w1a_staff_training.py"
)
VS3_TABLES = {
    "training_course",
    "staff_onboarding_training",
    "staff_periodic_training_status",
}
EXPECTED_COURSES = (
    (1, "NEW_HIRE_ORIENTATION", "신규직원교육", "ON_HIRE"),
    (2, "ELDER_RIGHTS", "노인인권", "HALF_YEAR"),
    (3, "DISABLED_ABUSE", "장애인학대 신고의무자교육", "ANNUAL"),
    (4, "ELDER_ABUSE", "노인학대 신고의무자교육", "ANNUAL"),
    (5, "SEXUAL_HARASSMENT", "직장 내 성희롱 예방교육", "ANNUAL"),
    (6, "WORKPLACE_BULLYING", "직장 내 괴롭힘 예방교육", "ANNUAL"),
    (7, "PRIVACY", "개인정보보호교육", "ANNUAL"),
)


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _migration_source() -> str:
    if not VS3_MIGRATION.is_file():
        _fail("W1A_VS3_MIGRATION_MISSING: expected 0005 training migration is absent")
    try:
        return VS3_MIGRATION.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        _fail("W1A_VS3_MIGRATION_MISSING: training migration is not readable as UTF-8")


def _literal_records(source: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        _fail("W1A_VS3_MIGRATION_MISSING: training migration is not valid Python")
    records: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        record: dict[str, Any] = {}
        for key, value in zip(node.keys, node.values, strict=False):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                try:
                    record[key.value] = ast.literal_eval(value)
                except (SyntaxError, TypeError, ValueError):
                    continue
        if record:
            records.append(record)
    return records


def _mapped_tables() -> dict[str, Table]:
    tables = Base.metadata.tables
    resolved: dict[str, Table] = {}
    for name in VS3_TABLES:
        key = name if name in tables else f"erp.{name}"
        table = tables.get(key)
        if table is not None:
            resolved[name] = table
    missing = sorted(VS3_TABLES - set(resolved))
    if missing:
        _fail("W1A_VS3_SEMANTICS_MISSING: training tables are not mapped")
    return resolved


def _columns(table: Table) -> set[str]:
    return {column.name for column in table.columns}


def _constraint_columns(item: object) -> set[str]:
    return {column.name for column in getattr(item, "columns", ())}


def _is_staff_employment_fk(constraint: object) -> bool:
    if constraint.__class__.__name__ != "ForeignKeyConstraint":
        return False
    elements = getattr(constraint, "elements", ())
    local_names = {getattr(element.parent, "name", "") for element in elements}
    return {"staff_id", "employment_id"}.issubset(local_names) and "staff_employment" in str(
        constraint
    )


def test_vs3_exact_training_course_seed_and_order() -> None:
    source = _migration_source()
    records = [
        record
        for record in _literal_records(source)
        if {"code", "display_name", "cycle_type", "sort_order"}.issubset(record)
    ]
    normalized = sorted(
        (
            int(record["sort_order"]),
            str(record["code"]),
            str(record["display_name"]),
            str(record["cycle_type"]),
        )
        for record in records
    )
    if normalized != list(EXPECTED_COURSES):
        _fail("W1A_VS3_COURSE_SEED_MISSING: exact seven course rows/order/cycle are absent")


def test_vs3_training_tables_and_boolean_only_fact_shape() -> None:
    tables = _mapped_tables()
    course_columns = _columns(tables["training_course"])
    onboarding_columns = _columns(tables["staff_onboarding_training"])
    periodic_columns = _columns(tables["staff_periodic_training_status"])
    if not {"code", "display_name", "cycle_type", "sort_order", "active"}.issubset(course_columns):
        _fail("W1A_VS3_COURSE_COLUMNS_MISSING: course catalog columns are incomplete")
    required_onboarding = {
        "staff_id",
        "employment_id",
        "course_code",
        "completed",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
        "invalidated_at_utc",
    }
    required_periodic = {
        "staff_id",
        "course_code",
        "period_key",
        "completed",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
        "invalidated_at_utc",
    }
    if not required_onboarding.issubset(onboarding_columns):
        _fail("W1A_VS3_ONBOARDING_COLUMNS_MISSING: onboarding fact shape is incomplete")
    if not required_periodic.issubset(periodic_columns):
        _fail("W1A_VS3_PERIODIC_COLUMNS_MISSING: periodic fact shape is incomplete")
    if "employment_id" in periodic_columns:
        _fail("W1A_VS3_PERIODIC_EMPLOYMENT_FK_FORBIDDEN: periodic status is employment-bound")


def test_vs3_active_uniqueness_and_same_staff_employment_fk() -> None:
    source = _migration_source()
    tables = _mapped_tables()
    onboarding = tables["staff_onboarding_training"]
    periodic = tables["staff_periodic_training_status"]
    onboarding_items = set(onboarding.indexes).union(onboarding.constraints)
    periodic_items = set(periodic.indexes).union(periodic.constraints)
    if not any(
        getattr(item, "unique", False)
        and _constraint_columns(item) == {"staff_id", "employment_id", "course_code"}
        and "invalidated_at_utc" in str(getattr(item, "dialect_options", {}))
        for item in onboarding_items
    ):
        _fail("W1A_VS3_ONBOARDING_ACTIVE_UNIQUE_MISSING: active employment course key is absent")
    if not any(
        getattr(item, "unique", False)
        and _constraint_columns(item) == {"staff_id", "course_code", "period_key"}
        and "invalidated_at_utc" in str(getattr(item, "dialect_options", {}))
        for item in periodic_items
    ):
        _fail("W1A_VS3_PERIODIC_ACTIVE_UNIQUE_MISSING: active period course key is absent")
    if not any(_is_staff_employment_fk(constraint) for constraint in onboarding.constraints):
        _fail("W1A_VS3_ONBOARDING_STAFF_EMPLOYMENT_FK_MISSING: same-staff FK is absent")
    if "DEFERRABLE" not in source.upper() or "INITIALLY DEFERRED" not in source.upper():
        _fail("W1A_VS3_DEFERRED_CONSTRAINT_MISSING: deferred correction contract is absent")


def test_vs3_cycle_period_schema_contract_is_declared() -> None:
    source = _migration_source()
    required_fragments = {
        "ON_HIRE",
        "HALF_YEAR",
        "ANNUAL",
        "period_key",
        "staff_onboarding_training",
        "staff_periodic_training_status",
    }
    missing = sorted(fragment for fragment in required_fragments if fragment not in source)
    source_upper = source.upper()
    half_year_pattern = (
        "H[12]" in source_upper
        or ("H1" in source_upper and "H2" in source_upper)
        or "YYYY-H1" in source_upper
        or "YYYY-H2" in source_upper
    )
    annual_pattern = any(token in source_upper for token in ("YYYY", "[0-9]{4}", r"\d{4}"))
    if missing or not half_year_pattern or not annual_pattern:
        _fail("W1A_VS3_CYCLE_PERIOD_SCHEMA_MISSING: cycle/period schema rules are absent")
