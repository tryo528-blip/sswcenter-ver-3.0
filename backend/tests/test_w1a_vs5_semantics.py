from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import NoReturn

import pytest
from sqlalchemy import ForeignKeyConstraint, Index, Table

from app.db import models as _models  # noqa: F401
from app.db.base import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "20260728_0007_w1a_staff_quarterly_consultation.py"
)
SERVICE_PATH = REPO_ROOT / "backend" / "app" / "domains" / "staff" / "service.py"
VS5_REVISION = "20260728_0007_w1a_staff_quarterly_consultation"
PARENT_REVISION = "20260728_0006_w1a_staff_health_check"
TABLE_NAME = "staff_quarterly_consultation"
REQUIRED_COLUMNS = {
    "id",
    "staff_id",
    "calendar_year",
    "quarter_no",
    "status",
    "counseling_date",
    "content",
    "incomplete_reason_text",
    "exempt_reason_text",
    "created_by_account_id",
    "created_at_utc",
    "updated_by_account_id",
    "updated_at_utc",
    "row_version",
    "invalidated_at_utc",
    "replacement_staff_quarterly_consultation_id",
}
FORBIDDEN_FIELDS = {
    "care_change_id",
    "care_change_case_id",
    "care_change_consultation_id",
    "file_id",
    "file_key",
    "attachment_id",
    "evidence_file_id",
    "evidence_id",
}
AUDIT_ACTIONS = {
    "STAFF_QUARTERLY_CONSULTATION_CREATE",
    "STAFF_QUARTERLY_CONSULTATION_UPDATE",
    "STAFF_QUARTERLY_CONSULTATION_INVALIDATE",
    "STAFF_QUARTERLY_CONSULTATION_REPLACEMENT_CREATE",
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
        "W1A_VS5_MIGRATION_MISSING: 0007 quarterly-consultation migration is absent",
    )


def _literal_strings(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        _fail("W1A_VS5_MIGRATION_MISSING: 0007 migration is not valid Python")
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _mapped_table() -> Table:
    table = Base.metadata.tables.get(TABLE_NAME) or Base.metadata.tables.get(f"erp.{TABLE_NAME}")
    if table is None:
        _fail("W1A_VS5_MODEL_MISSING: quarterly-consultation table is not mapped")
    return table


def _columns(table: Table) -> set[str]:
    return {column.name for column in table.columns}


def _constraint_text(table: Table) -> str:
    return "\n".join(str(getattr(item, "sqltext", item)) for item in table.constraints)


def _has_staff_fk(table: Table) -> bool:
    for item in table.constraints:
        if not isinstance(item, ForeignKeyConstraint):
            continue
        local = {element.parent.name for element in item.elements}
        target = {str(element.target_fullname) for element in item.elements}
        if local == {"staff_id"} and any(name in {"erp.staff.id", "staff.id"} for name in target):
            return True
    return False


def _active_unique_index(table: Table) -> Index | None:
    for item in table.indexes:
        if not item.unique:
            continue
        if {column.name for column in item.columns} != {
            "staff_id",
            "calendar_year",
            "quarter_no",
        }:
            continue
        postgresql_options = item.dialect_options.get("postgresql")
        where = postgresql_options.get("where") if postgresql_options is not None else None
        if where is not None and "invalidated_at_utc" in str(where).lower():
            return item
    return None


def test_vs5_revision_and_required_contract_fragments() -> None:
    source = _migration_source()
    literals = _literal_strings(source)
    required = {
        VS5_REVISION,
        PARENT_REVISION,
        TABLE_NAME,
        "calendar_year",
        "quarter_no",
        "counseling_date",
        "incomplete_reason_text",
        "exempt_reason_text",
        "replacement_staff_quarterly_consultation_id",
        "COMPLETE",
        "INCOMPLETE",
        "EXEMPT",
    }
    missing = sorted(required - literals)
    if missing:
        _fail(
            "W1A_VS5_MIGRATION_MISSING: revision/table/status contract is incomplete: "
            + ",".join(missing)
        )


def test_vs5_table_shape_and_same_staff_guard() -> None:
    table = _mapped_table()
    missing = sorted(REQUIRED_COLUMNS - _columns(table))
    if missing:
        _fail("W1A_VS5_DB_SCHEMA_MISSING: required columns are absent: " + ",".join(missing))
    for name in (
        "calendar_year",
        "quarter_no",
        "status",
        "row_version",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
    ):
        if table.c[name].nullable:
            _fail(f"W1A_VS5_DB_SCHEMA_MISSING: {name} must be NOT NULL")
    for name in (
        "counseling_date",
        "content",
        "incomplete_reason_text",
        "exempt_reason_text",
        "invalidated_at_utc",
        "replacement_staff_quarterly_consultation_id",
    ):
        if not table.c[name].nullable:
            _fail(f"W1A_VS5_DB_SCHEMA_MISSING: {name} must be nullable")
    if not _has_staff_fk(table):
        _fail("W1A_VS5_SAME_STAFF_FK_MISSING: consultation does not reference staff.id")
    if _columns(table).intersection(FORBIDDEN_FIELDS):
        _fail(
            "W1A_VS5_FORBIDDEN_DB_FIELD_FOUND: "
            + ",".join(sorted(_columns(table).intersection(FORBIDDEN_FIELDS)))
        )


def test_vs5_truth_table_nonblank_active_unique_and_quarter_range() -> None:
    source = _migration_source().upper()
    table = _mapped_table()
    constraint_text = _constraint_text(table).upper()
    required_fragments = (
        "STATUS IN",
        "'COMPLETE'",
        "'INCOMPLETE'",
        "'EXEMPT'",
        "COUNSELING_DATE",
        "CONTENT",
        "INCOMPLETE_REASON_TEXT",
        "EXEMPT_REASON_TEXT",
        "BTRIM",
        "INVALIDATED_AT_UTC IS NULL",
    )
    for fragment in required_fragments:
        if fragment not in source and fragment not in constraint_text:
            _fail("W1A_VS5_TRUTH_TABLE_MISSING: exact status/nonblank contract is absent")
    status_branches = (
        r"STATUS\s*=\s*'COMPLETE'.{0,900}COUNSELING_DATE\s+IS\s+NOT\s+NULL",
        r"STATUS\s*=\s*'INCOMPLETE'.{0,900}INCOMPLETE_REASON_TEXT",
        r"STATUS\s*=\s*'EXEMPT'.{0,900}EXEMPT_REASON_TEXT",
    )
    for pattern in status_branches:
        if not re.search(pattern, source, re.IGNORECASE | re.DOTALL):
            _fail("W1A_VS5_TRUTH_TABLE_MISSING: each status truth branch is not explicit")
    if _active_unique_index(table) is None:
        _fail("W1A_VS5_ACTIVE_UNIQUE_MISSING: active staff/year/quarter unique is absent")
    if "QUARTER_NO" not in source or not re.search(
        r"QUARTER_NO.{0,300}(?:IN\s*\(\s*1\s*,\s*2\s*,\s*3\s*,\s*4\s*\)|BETWEEN\s+1\s+AND\s+4)",
        source,
        re.IGNORECASE | re.DOTALL,
    ):
        _fail("W1A_VS5_QUARTER_CHECK_MISSING: quarter_no 1..4 check is absent")
    if re.search(r"CALENDAR_YEAR\s*(?:>=|<=|>|<|BETWEEN)", source, re.IGNORECASE):
        _fail("W1A_VS5_YEAR_RANGE_FORBIDDEN: calendar_year has an arbitrary range")


def test_vs5_service_audit_actions_are_named_and_separate() -> None:
    source = _read_utf8(
        SERVICE_PATH,
        "W1A_VS5_SERVICE_MISSING: staff quarterly-consultation service is absent",
    )
    missing = sorted(action for action in AUDIT_ACTIONS if action not in source)
    if missing:
        _fail("W1A_VS5_AUDIT_PATH_MISSING: named audit actions are absent: " + ",".join(missing))
    if "STAFF_QUARTERLY_CONSULTATION" not in source:
        _fail("W1A_VS5_SERVICE_MISSING: consultation entity path is absent")
    if "replacement_staff_quarterly_consultation_id" not in source:
        _fail("W1A_VS5_REPLACEMENT_PATH_MISSING: replacement link is not handled")


def test_vs5_previous_migrations_do_not_contain_0007_surface() -> None:
    old_paths = sorted((REPO_ROOT / "backend" / "alembic" / "versions").glob("*.py"))
    old_paths = [path for path in old_paths if path.name < MIGRATION_PATH.name]
    if len(old_paths) < 6:
        _fail("W1A_VS5_MIGRATION_MISSING: existing 0001-0006 migrations are incomplete")
    for path in old_paths:
        source = _read_utf8(path, "W1A_VS5_MIGRATION_MISSING: existing migration is unreadable")
        if VS5_REVISION in source or TABLE_NAME in source:
            _fail("W1A_VS5_OLD_MIGRATION_MODIFIED: 0007 surface leaked into an old migration")
