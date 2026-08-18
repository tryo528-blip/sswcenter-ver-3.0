from __future__ import annotations

from pathlib import Path

from sqlalchemy import Table

from app.db import models as _models  # noqa: F401
from app.db.base import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_MIGRATION = (
    REPO_ROOT / "backend" / "alembic" / "versions" / "20260728_0006_w1a_staff_health_check.py"
)
CORRECTION_MIGRATION = (
    REPO_ROOT / "backend" / "alembic" / "versions" / "20260813_0020_w1_staff_contract_correction.py"
)


def _table(name: str) -> Table | None:
    return Base.metadata.tables.get(name) or Base.metadata.tables.get(f"erp.{name}")


def test_historical_health_migration_is_preserved_and_0020_is_forward_only() -> None:
    historical = HISTORICAL_MIGRATION.read_text(encoding="utf-8")
    correction = CORRECTION_MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "20260728_0006_w1a_staff_health_check"' in historical
    assert 'revision: str = "20260813_0020_w1_staff_contract_correction"' in correction
    assert 'down_revision: str | None = "20260812_0019_r0_w2_read_only"' in correction
    assert "staff_health_check_requirement" in correction
    assert "op.drop_table" in correction
    assert "forward-only" in correction


def test_current_health_model_is_a_date_fact_without_requirement_ledger() -> None:
    fact = _table("staff_health_check")
    assert fact is not None
    assert _table("staff_health_check_requirement") is None
    assert {column.name for column in fact.columns} == {
        "id",
        "staff_id",
        "employment_id",
        "check_date",
        "invalidated_at_utc",
        "replacement_health_check_id",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    }
    assert fact.c.check_date.nullable is False


def test_current_health_model_has_no_removed_business_fields() -> None:
    fact = _table("staff_health_check")
    assert fact is not None
    assert {
        "check_type_code",
        "result_note",
        "status",
        "target_key",
        "target_rule_version_code",
        "health_check_id",
        "exempt_reason_text",
        "incomplete_reason_text",
    }.isdisjoint({column.name for column in fact.columns})
    assert fact.columns["employment_id"].nullable is True
