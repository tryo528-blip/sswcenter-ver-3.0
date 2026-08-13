from __future__ import annotations

from pathlib import Path

from sqlalchemy import ForeignKeyConstraint, Table, UniqueConstraint

from app.db import models as _models  # noqa: F401
from app.db.base import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_MIGRATION = (
    REPO_ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "20260728_0007_w1a_staff_quarterly_consultation.py"
)
CORRECTION_MIGRATION = (
    REPO_ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "20260813_0020_w1_staff_contract_correction.py"
)
SERVICE_PATH = REPO_ROOT / "backend" / "app" / "domains" / "staff" / "service.py"


def _table() -> Table:
    table = Base.metadata.tables.get("staff_quarterly_consultation")
    if table is None:
        table = Base.metadata.tables["erp.staff_quarterly_consultation"]
    return table


def test_historical_quarterly_migration_is_preserved_and_0020_converts_deterministically() -> None:
    historical = HISTORICAL_MIGRATION.read_text(encoding="utf-8")
    correction = CORRECTION_MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "20260728_0007_w1a_staff_quarterly_consultation"' in historical
    assert "SET completed = (status = 'COMPLETE')" in correction
    assert "row_number() OVER" in correction
    assert "(invalidated_at_utc IS NULL) DESC" in correction
    assert "updated_at_utc DESC" in correction
    assert "row_rank > 1" in correction


def test_current_quarterly_model_is_one_boolean_per_staff_year_quarter() -> None:
    table = _table()
    assert {column.name for column in table.columns} == {
        "id",
        "staff_id",
        "calendar_year",
        "quarter_no",
        "completed",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    }
    assert table.c.completed.nullable is False
    assert any(
        isinstance(constraint, UniqueConstraint)
        and {column.name for column in constraint.columns}
        == {"staff_id", "calendar_year", "quarter_no"}
        for constraint in table.constraints
    )
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        and {column.name for column in constraint.columns} == {"staff_id"}
        for constraint in table.constraints
    )


def test_current_quarterly_model_and_service_have_no_removed_contract() -> None:
    table = _table()
    service = SERVICE_PATH.read_text(encoding="utf-8")
    removed_columns = {
        "status",
        "counseling_date",
        "content",
        "incomplete_reason_text",
        "exempt_reason_text",
        "invalidated_at_utc",
        "replacement_staff_quarterly_consultation_id",
    }
    assert removed_columns.isdisjoint({column.name for column in table.columns})
    assert "STAFF_QUARTERLY_CONSULTATION_CREATE" in service
    assert "STAFF_QUARTERLY_CONSULTATION_UPDATE" in service
    assert "STAFF_QUARTERLY_CONSULTATION_INVALIDATE" not in service
    assert "STAFF_QUARTERLY_CONSULTATION_REPLACEMENT_CREATE" not in service
