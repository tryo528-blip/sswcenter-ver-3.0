"""RED-first contract for the exact W3 0029 persistence and workspace slice."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Table
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import readiness
from app.core.settings import Settings
from app.db import postcheck_dispatch
from app.db.postcheck_current_0029 import (
    CURRENT_0029_MARKER,
    EXPECTED_REVISION,
    HEAD_MARKER,
    REQUIRED_0029_TABLES,
)
from app.db.w3_models import (
    PERSISTENCE_HAS_TYPED_LINK,
    W3ActualWorkRevision,
    W3ApplyControl,
    W3ImportRun,
    W3ImportRunEvent,
    W3ManualSupplementEvent,
    W3MatchDecision,
    W3NhisGroup,
    W3NhisGroupMember,
    W3NormalizedNhisRow,
    W3NormalizedRfidRow,
    W3PlanAdjustmentEvent,
)
from app.domains.recipient.errors import RecipientDomainError
from app.domains.w3.schemas import W3PlanAdjustmentRequest
from app.domains.w3.service import W3Service
from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
MIGRATION = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "20260818_0029_w3_persistent_apply_workspace.py"
)
GRANT_SCRIPT = REPO_ROOT / "infra" / "postgres" / "grant-application-access.sql"
FRONTEND_IO = REPO_ROOT / "frontend" / "src" / "pages" / "IOPage.tsx"
FRONTEND_API = REPO_ROOT / "frontend" / "src" / "services" / "w3Api.ts"
SERVICE = BACKEND_ROOT / "app" / "domains" / "w3" / "service.py"
SCHEMAS = BACKEND_ROOT / "app" / "domains" / "w3" / "schemas.py"
MATCHING_REPOSITORY = (
    BACKEND_ROOT / "app" / "domains" / "w3" / "matching_repository.py"
)
POSTGRES_HARNESS = REPO_ROOT / "scripts" / "test-w3-0029-postgres-linux.ps1"

PARENT_REVISION = "20260817_0028_w3_source_intake_foundation"
ACTIVE_REVISION = "20260818_0029_w3_persistent_apply_workspace"

EXPECTED_NEW_TABLES = {
    "w3_import_run_event",
    "w3_normalized_nhis_row",
    "w3_normalized_rfid_row",
    "w3_nhis_group",
    "w3_nhis_group_member",
    "w3_match_decision",
    "w3_apply_control",
    "w3_actual_work_revision",
    "w3_manual_supplement_event",
    "w3_plan_adjustment_event",
}


def test_0029_migration_is_exact_child_and_opens_only_approved_objects() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert f'revision: str = "{ACTIVE_REVISION}"' in source
    assert f'down_revision: str | None = "{PARENT_REVISION}"' in source
    assert 'op.add_column(\n        "w3_import_run"' in source
    assert 'sa.Column("row_version"' in source
    assert "target_type" not in source
    assert "target_id" not in source
    assert "BYTEA" not in source.upper()
    for table_name in sorted(EXPECTED_NEW_TABLES):
        assert f'"{table_name}"' in source
        assert f"ALTER TABLE erp.{table_name} OWNER TO erp_owner" in source
    assert source.count('ondelete="RESTRICT"') >= 25
    assert "FOR UPDATE" not in source  # runtime lock belongs to repository/service
    assert "W3_VIEW" in source
    assert "W3_MANAGE" in source
    assert "INSERT INTO erp.w3_apply_control" in source
    assert "snapshot.status = 'ACTIVE'" in source
    assert "run.status = 'APPLIED'" in source


def test_0029_orm_has_typed_links_and_no_generic_target_pair() -> None:
    assert PERSISTENCE_HAS_TYPED_LINK is True
    assert W3ImportRun.__table__.c.row_version.nullable is False

    classes = (
        W3ImportRunEvent,
        W3NormalizedNhisRow,
        W3NormalizedRfidRow,
        W3NhisGroup,
        W3NhisGroupMember,
        W3MatchDecision,
        W3ApplyControl,
        W3ActualWorkRevision,
        W3ManualSupplementEvent,
        W3PlanAdjustmentEvent,
    )
    assert {item.__tablename__ for item in classes} == EXPECTED_NEW_TABLES
    for mapped_class in classes:
        columns = set(cast(Table, mapped_class.__table__).columns.keys())
        assert "target_type" not in columns
        assert "target_id" not in columns

    decision_columns = set(cast(Table, W3MatchDecision.__table__).columns.keys())
    assert {
        "recipient_id",
        "certification_period_id",
        "staff_id",
        "employment_id",
        "staff_legacy_mapping_id",
        "service_type_id",
        "recipient_contract_id",
        "care_assignment_id",
        "w2_schedule_id",
    } <= decision_columns
    actual_columns = set(cast(Table, W3ActualWorkRevision.__table__).columns.keys())
    assert {
        "snapshot_id",
        "normalized_rfid_row_id",
        "match_decision_id",
        "recipient_id",
        "staff_id",
        "employment_id",
        "recipient_contract_id",
        "care_assignment_id",
        "w2_schedule_id",
        "actual_start",
        "actual_end",
        "actual_seconds",
        "superseded_at_utc",
    } <= actual_columns
    event_columns = set(cast(Table, W3ImportRunEvent.__table__).columns.keys())
    assert {"command_idempotency_key", "command_digest"} <= event_columns
    plan_columns = set(cast(Table, W3PlanAdjustmentEvent.__table__).columns.keys())
    assert {
        "expected_schedule_row_version",
        "adopted_schedule_row_version",
        "expected_month_row_version",
        "adopted_month_row_version",
    } <= plan_columns


def test_0029_current_head_dispatch_readiness_and_postcheck_are_exact() -> None:
    assert EXPECTED_REVISION == ACTIVE_REVISION
    assert postcheck_dispatch.ACTIVE_REVISION == ACTIVE_REVISION
    assert readiness.CURRENT_ALEMBIC_REVISION == ACTIVE_REVISION
    assert set(REQUIRED_0029_TABLES) == EXPECTED_NEW_TABLES
    assert CURRENT_0029_MARKER == "SSWCENTER_CURRENT_0029_DB_POSTCHECK_OK"
    assert HEAD_MARKER == "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK"
    assert "verify_current_0029" in inspect.getsource(readiness.database_catalog_is_ready)
    assert "verify_current_0028" not in inspect.getsource(readiness.database_catalog_is_ready)


def test_0029_acl_keeps_history_append_only_and_backup_select_only() -> None:
    source = GRANT_SCRIPT.read_text(encoding="utf-8")
    for table_name in sorted(EXPECTED_NEW_TABLES):
        assert f"erp.{table_name}" in source
    immutable = EXPECTED_NEW_TABLES - {"w3_apply_control"}
    revoke = source.split("W3 0029", maxsplit=1)[1]
    for table_name in sorted(immutable):
        assert f"erp.{table_name}" in revoke
    assert "GRANT UPDATE (status, row_version) ON TABLE erp.w3_import_run" in source
    assert "GRANT UPDATE (active_snapshot_id, active_import_run_id, row_version)" in source
    assert "erp_backup" in revoke


def test_0029_file_only_api_surface_and_single_workspace_are_wired() -> None:
    openapi = app.openapi()
    paths = set(openapi["paths"])
    expected_paths = {
        "/api/v1/w3/workspace",
        "/api/v1/w3/import-runs",
        "/api/v1/w3/import-runs/{run_id}/confirm",
        "/api/v1/w3/import-runs/{run_id}/apply",
        "/api/v1/w3/import-runs/{run_id}/decisions/{decision_id}/resolve",
        "/api/v1/w3/actual-work/{revision_id}/supplements",
        "/api/v1/w3/actual-work/{revision_id}/plan-adjustments",
    }
    assert expected_paths <= paths
    import_operation = openapi["paths"]["/api/v1/w3/import-runs"]["post"]
    assert "multipart/form-data" in import_operation["requestBody"]["content"]
    assert all("internal" not in path.casefold() for path in paths if "/w3/" in path)

    io_source = FRONTEND_IO.read_text(encoding="utf-8")
    api_source = FRONTEND_API.read_text(encoding="utf-8")
    assert "SINGLE_STATEFUL_WORKSPACE" in io_source
    assert "OCR 문서" not in io_source
    assert "uploadW3Workbook" in io_source
    assert "confirmW3ImportRun" in io_source
    assert "applyW3ImportRun" in io_source
    assert "FormData" in api_source
    assert "target_type" not in io_source
    assert "storage_locator" not in io_source


def test_0029_reviewer_regressions_are_closed_by_contract() -> None:
    service_source = SERVICE.read_text(encoding="utf-8")
    schema_source = SCHEMAS.read_text(encoding="utf-8")
    matching_source = MATCHING_REPOSITORY.read_text(encoding="utf-8")
    harness_source = POSTGRES_HARNESS.read_text(encoding="utf-8")

    assert 'getattr(error, "code"' not in service_source
    assert "MAX_PUBLIC_DECISIONS" not in service_source
    assert "_revalidate_typed_decisions(decisions)" in service_source
    assert "pg_advisory_xact_lock" in service_source
    assert '"manual-supplement"' in service_source
    assert '"plan-adjustment"' in service_source
    assert "INVALID_SUPPLEMENT_TRANSITION" in service_source
    assert "INVALID_PLAN_ADJUSTMENT_INPUT" in service_source
    assert 'Literal["w3-rfid-adjustment-v1"]' in schema_source
    assert "W2Schedule.schedule_month == schedule_month" in matching_source
    assert "W2Schedule.starts_at_utc >= service_day_start_utc" in matching_source
    assert "W2Schedule.starts_at_utc < service_day_end_utc" in matching_source
    assert "W3_0029_POSTGRES_DATAFUL_REUPGRADE_GREEN" in harness_source


def test_0029_integrity_error_is_mapped_even_when_sqlalchemy_code_is_truthy() -> None:
    session = MagicMock(spec=Session)
    service = W3Service(cast(Session, session), Settings())
    error = IntegrityError("INSERT", {}, Exception("duplicate"))

    with pytest.raises(RecipientDomainError) as caught:
        service._rollback_and_raise(error)

    session.rollback.assert_called_once_with()
    assert caught.value.code == "W3_TYPED_LINK_INVALID"
    assert caught.value.status_code == 422


def test_0029_plan_adjustment_rule_version_is_closed() -> None:
    valid = W3PlanAdjustmentRequest(
        expected_schedule_row_version=1,
        expected_month_row_version=1,
        rule_version="w3-rfid-adjustment-v1",
        reason="가명 자료 검증",
        command_idempotency_key="w3-rule-valid",
    )
    assert valid.rule_version == "w3-rfid-adjustment-v1"
    with pytest.raises(ValueError):
        W3PlanAdjustmentRequest(
            expected_schedule_row_version=1,
            expected_month_row_version=1,
            rule_version="unknown-rule",  # type: ignore[arg-type]
            reason="가명 자료 검증",
            command_idempotency_key="w3-rule-invalid",
        )
