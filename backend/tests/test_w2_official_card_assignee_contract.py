"""Unit and OpenAPI contract for W2 automatic assignment and admin reassignment."""

from __future__ import annotations

import inspect
from datetime import date
from pathlib import Path
from typing import cast

from fastapi.routing import APIRoute
from sqlalchemy import ForeignKeyConstraint, Table, UniqueConstraint

from app.api.w2 import router
from app.db.models import RecipientContract
from app.db.w2_models import W2ServicePlanNotice
from app.domains.w2.policies import OfficialCardSource, recognition_expiry_source
from app.domains.w2.repository import W2Repository
from app.domains.w2.schemas import (
    OfficialWorkCardDisplay,
    OfficialWorkCardEligibleAssigneeListResponse,
    OfficialWorkCardItem,
    OfficialWorkCardKind,
    OfficialWorkCardReassignRequest,
)
from app.domains.w2.service import W2Service
from app.main import app

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
MIGRATION = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "20260817_0027_w2_official_card_assignee_and_plan_replacement.py"
)
RESTORE_DRILL = REPO_ROOT / "scripts" / "restore-drill.ps1"
W2_LIVE_HARNESS = REPO_ROOT / "scripts" / "test-w2-0027-postgres-linux.ps1"
W2_BROWSER_SEED = BACKEND_ROOT / "app" / "db" / "seed_w2_official_card_browser_test.py"
W2_BROWSER_SPEC = REPO_ROOT / "frontend" / "e2e" / "w2-official-card-reassign-real-pg.spec.ts"
W2_BROWSER_CONFIG = REPO_ROOT / "frontend" / "e2e" / "w2-official-card-real-pg.config.ts"
W2_CURRENT_HTTP_PG_TEST = BACKEND_ROOT / "tests" / "test_w3_0028_w2_current_http_postgres.py"


def test_0027_is_forward_child_of_0026_and_seals_same_recipient_replacement() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert (
        'revision: str = "20260817_0027_w2_official_card_assignee_and_plan_replacement"' in source
    )
    assert (
        'down_revision: str | None = "20260814_0026_w1e_care_assignment_family_relationship_lock"'
    ) in source
    assert "uq_recipient_contract_recipient_id_id" in source
    assert "uq_w2_service_plan_notice_recipient_id_id" in source
    assert "fk_w2_service_plan_notice_contract_same_recipient" in source
    assert "fk_w2_service_plan_notice_replacement_same_recipient" in source
    assert "recipient_id, recipient_contract_id" in source
    assert "recipient_id, replacement_service_plan_notice_id" in source
    assert "DEFERRABLE INITIALLY DEFERRED" in source
    assert "W2_SERVICE_PLAN_NOTICE_RECIPIENT_BACKFILL_INVALID" in source
    assert "fn_w2_service_plan_replacement_same_recipient" in source
    assert "CREATE CONSTRAINT TRIGGER ct_w2_service_plan_replacement" not in source


def test_orm_models_exactly_match_the_0027_composite_recipient_graph() -> None:
    notice = cast(Table, W2ServicePlanNotice.__table__)
    contract = cast(Table, RecipientContract.__table__)
    assert notice.c.recipient_id.nullable is False
    assert {
        "recipient_id",
        "recipient_contract_id",
        "replacement_service_plan_notice_id",
    } <= set(notice.columns.keys())
    contract_unique = next(
        constraint
        for constraint in contract.constraints
        if isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_recipient_contract_recipient_id_id"
    )
    notice_unique = next(
        constraint
        for constraint in notice.constraints
        if isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_w2_service_plan_notice_recipient_id_id"
    )
    assert [column.name for column in contract_unique.columns] == ["recipient_id", "id"]
    assert [column.name for column in notice_unique.columns] == ["recipient_id", "id"]
    foreign_keys = {
        constraint.name: constraint
        for constraint in notice.constraints
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name is not None
    }
    contract_fk = foreign_keys["fk_w2_service_plan_notice_contract_same_recipient"]
    replacement_fk = foreign_keys["fk_w2_service_plan_notice_replacement_same_recipient"]
    assert [column.name for column in contract_fk.columns] == [
        "recipient_id",
        "recipient_contract_id",
    ]
    assert [column.name for column in replacement_fk.columns] == [
        "recipient_id",
        "replacement_service_plan_notice_id",
    ]
    assert replacement_fk.deferrable is True
    assert replacement_fk.initially == "DEFERRED"


def test_official_source_does_not_accept_caller_assignee() -> None:
    source = recognition_expiry_source(
        occurrence_key="recognition:7:2027-12-31",
        renewal_key="recipient:7:renewal:2027-12-31",
        recognition_end_date=date(2027, 12, 31),
        target_name=None,
        detail="세부 업무",
        recipient_id=7,
    )
    assert not hasattr(source, "assignee_staff_id")
    assert "assignee_staff_id" not in OfficialCardSource.__dataclass_fields__
    record_source = inspect.getsource(W2Service.record_official_source)
    assert "_resolve_new_card_assignee" in record_source
    assert "normalized.assignee_staff_id" not in record_source
    bridge_source = inspect.getsource(W2Service.record_service_plan_notice_card_source)
    assert "assignee_staff_id" not in bridge_source


def test_reassignment_mutates_only_assignee_and_row_version() -> None:
    source = inspect.getsource(W2Service.reassign_official_card)
    assert "row.assignee_staff_id = payload.assignee_staff_id" in source
    assert "row.row_version += 1" in source
    assert "updated_by_account_id" not in source
    assert "row.closed_at_utc =" not in source
    assert "W2_OFFICIAL_WORK_CARD_REASSIGNED" in source
    assert "_assignee_snapshot" in source
    assert "CARD_REASSIGN_SAME_ASSIGNEE" in source


def test_display_schema_stays_five_fields_and_assignee_is_item_metadata() -> None:
    assert tuple(OfficialWorkCardDisplay.model_fields) == (
        "work_title",
        "target_name",
        "detail",
        "due_date",
        "d_day",
    )
    assert {
        "assignee_staff_id",
        "assignee_staff_name",
    } <= set(OfficialWorkCardItem.model_fields)
    OfficialWorkCardReassignRequest(expected_row_version=3, assignee_staff_id=11)
    OfficialWorkCardEligibleAssigneeListResponse(as_of_date=date(2026, 8, 17), items=[])


def test_openapi_exposes_admin_reassign_and_eligible_assignees_only() -> None:
    paths = app.openapi()["paths"]
    assert set(paths["/api/v1/official-work-cards/{card_id}/reassign"]) == {"post"}
    assert set(paths["/api/v1/official-work-cards/eligible-assignees"]) == {"get"}
    item_schema = app.openapi()["components"]["schemas"]["OfficialWorkCardItem"]
    assert "assignee_staff_id" in item_schema["properties"]
    assert "assignee_staff_name" in item_schema["properties"]
    display_schema = app.openapi()["components"]["schemas"]["OfficialWorkCardDisplay"]
    assert list(display_schema["properties"]) == [
        "work_title",
        "target_name",
        "detail",
        "due_date",
        "d_day",
    ]


def test_router_reassign_uses_csrf_and_close_stays_forbidden_for_admin() -> None:
    methods_by_path: dict[str, set[str]] = {}
    assert all(isinstance(route, APIRoute) for route in router.routes)
    for route in cast(list[APIRoute], router.routes):
        methods_by_path.setdefault(route.path, set()).update(route.methods or set())
    assert methods_by_path["/api/v1/official-work-cards/{card_id}/reassign"] == {"POST"}
    close_source = inspect.getsource(W2Service.close_official_card)
    assert 'current_account.role_code == "ADMIN"' in close_source
    assert "ADMIN_CARD_MUTATION_FORBIDDEN" in close_source
    reassign_source = inspect.getsource(W2Service.reassign_official_card)
    assert 'current_account.role_code != "ADMIN"' in reassign_source
    assert "CARD_REASSIGN_FORBIDDEN" in reassign_source


def test_repository_assignment_covering_and_eligible_assignees_are_id_ordered() -> None:
    covering = inspect.getsource(W2Repository.current_assignments_covering)
    eligible = inspect.getsource(W2Repository.eligible_card_assignees)
    assert ".order_by(MonthlyProfessionalAssignment.id)" in covering
    assert "ADMIN" in eligible
    assert "SOCIAL_WORKER" in eligible
    assert "NURSE" in eligible
    kind = OfficialWorkCardKind.PLAN_NOTICE
    assert kind.value == "PLAN_NOTICE"


def test_priority_replacement_uses_recorded_manual_assignee_without_later_revalidation() -> None:
    source = inspect.getsource(W2Service._resolve_new_card_assignee)
    assert "return inherited" in source
    assert "staff_is_admin_account(inherited)" not in source
    assert "staff_currently_employed(inherited" not in source
    assert "staff_has_professional_position(inherited" not in source


def test_restore_and_current_head_routes_distinguish_0027_from_historical_heads() -> None:
    """Only a restored 0029 backup may claim the current-head marker."""

    restore_source = RESTORE_DRILL.read_text(encoding="utf-8")
    dispatcher_source = (BACKEND_ROOT / "app" / "db" / "postcheck_dispatch.py").read_text(
        encoding="utf-8"
    )
    harness = W2_LIVE_HARNESS.read_text(encoding="utf-8")
    assert "20260817_0028_w3_source_intake_foundation" in restore_source
    assert "SSWCENTER_CURRENT_0028_DB_POSTCHECK_OK" in restore_source
    assert "20260818_0029_w3_persistent_apply_workspace" in restore_source
    assert "SSWCENTER_CURRENT_0029_DB_POSTCHECK_OK" in restore_source
    assert "20260817_0027_w2_official_card_assignee_and_plan_replacement" in restore_source
    assert "SSWCENTER_CURRENT_0027_DB_POSTCHECK_OK" in restore_source
    assert "20260814_0026_w1e_care_assignment_family_relationship_lock" in restore_source
    assert "SSWCENTER_CURRENT_0026_DB_POSTCHECK_OK" in restore_source
    assert "20260813_0025_w1_relationship_lock_contract_correction" in restore_source
    assert "SSWCENTER_CURRENT_0025_DB_POSTCHECK_OK" in restore_source
    assert "Historical 0027 restore emitted a current-head marker" in restore_source
    assert "Historical 0026 restore emitted a current-head marker" in restore_source
    assert "Historical 0025 restore emitted a current-head marker" in restore_source
    assert (
        """elseif ($ManifestRevision -in @(
        $Historical0025Revision,
        $Historical0026Revision,
        $Historical0027Revision,
        $Historical0028Revision,
        $ActiveRevision
    ))"""
        in restore_source
    )
    assert "$PostcheckOutput | Write-Output" in restore_source
    assert ('ACTIVE_REVISION = "20260818_0029_w3_persistent_apply_workspace"') in dispatcher_source
    assert "verify_current_0025" not in dispatcher_source
    assert "verify_current_0026" not in dispatcher_source
    assert "verify_current_0027" not in dispatcher_source
    assert "app.db.postcheck_current_0027" in harness
    assert "upgrade $ActiveHeadRevision" in harness
    assert "upgrade $CurrentRevision" in harness


def test_w2_historical_database_excludes_current_http_and_runs_it_only_at_0029() -> None:
    harness = W2_LIVE_HARNESS.read_text(encoding="utf-8")
    current_http = W2_CURRENT_HTTP_PG_TEST.read_text(encoding="utf-8")

    assert "$W2HistoricalNodeIds" in harness
    assert "$W2HistoricalCurrentApiNode" in harness
    assert "test_official_card_http_role_csrf_conflict_and_response_contracts" in harness
    assert "--deselect $W2HistoricalCurrentApiNode" in harness
    assert "$W2CurrentHttpNodeIds" in harness
    assert "tests/test_w3_0028_w2_current_http_postgres.py" in harness
    assert "W2_0027_BROWSER_CURRENT_HTTP_GREEN" in harness
    assert "SSWCENTER_W2_CURRENT_HTTP_REAL_PG" in harness
    assert "SSWCENTER_W2_CURRENT_HTTP_DATABASE_URL" in harness
    assert "SSWCENTER_W2_CURRENT_HTTP_APP_DATABASE_URL" in harness
    assert "upgrade $ActiveHeadRevision" in harness
    assert "app.db.postcheck_dispatch" in harness
    assert "SSWCENTER_CURRENT_0029_DB_POSTCHECK_OK" in harness
    assert "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK" in harness
    assert "W2_0027_BROWSER_CURRENT_0029_MARKER_MISSING" in harness
    assert "W2_0027_BROWSER_CURRENT_HEAD_MARKER_MISSING" in harness
    assert "W2_0027_BROWSER_CURRENT_0029_POSTCHECK_GREEN" in harness
    assert "W2_0027_POSTGRES_RESTORE_HISTORICAL_0027_MARKER_MISSING" in harness
    assert "W2_0027_POSTGRES_RESTORE_EMITTED_CURRENT_HEAD_MARKER" in harness
    assert "SSWCENTER_READINESS_BYPASS" not in harness

    assert 'ACTIVE_REVISION = "20260818_0029_w3_persistent_apply_workspace"' in current_http
    assert "SSWCENTER_W2_CURRENT_HTTP_REAL_PG" in current_http
    assert "SSWCENTER_W2_CURRENT_HTTP_DATABASE_URL" in current_http
    assert "SSWCENTER_W2_CURRENT_HTTP_APP_DATABASE_URL" in current_http
    assert "module.seeded.__wrapped__(current_engine)" in current_http
    assert "test_official_card_http_role_csrf_conflict_and_response_contracts" in current_http
    assert 'client.get("/health/ready")' in current_http
    assert "response.status_code == 200" in current_http
    assert "SSWCENTER_READINESS_BYPASS" not in current_http

    restore_source = RESTORE_DRILL.read_text(encoding="utf-8")
    assert "$PostcheckOutput | Write-Output" in restore_source
    assert "Historical 0027 restore emitted a current-head marker" in restore_source


def test_real_browser_gate_owns_database_servers_conflict_and_cleanup() -> None:
    harness = W2_LIVE_HARNESS.read_text(encoding="utf-8")
    seed = W2_BROWSER_SEED.read_text(encoding="utf-8")
    spec = W2_BROWSER_SPEC.read_text(encoding="utf-8")
    config = W2_BROWSER_CONFIG.read_text(encoding="utf-8")

    assert 'BrowserDatabaseName = "sswcenter_w2_0027_browser_test"' in harness
    assert "app.db.seed_w0_w2_workflow_test_data" in harness
    assert "app.db.seed_w2_official_card_browser_test" in harness
    assert "W2_0027_BROWSER_PLAYWRIGHT_TIMEOUT" in harness
    assert "W2_0027_BROWSER_PLAYWRIGHT_STREAM_DRAIN_TIMEOUT" in harness
    assert "W2_0027_BROWSER_PLAYWRIGHT_BOUNDED_STOP_FAILED" in harness
    assert "Stop-W2CapturedProcess" in harness
    assert ".WaitForExit()" not in harness
    assert ".GetAwaiter().GetResult()" not in harness
    assert "--timeout=15" in harness
    assert "$ClusterMayBeRunning = $true\n    & $PgCtlExe `" in harness
    assert harness.count("$BaselinePostgresIds -notcontains $_.Id") >= 1
    assert "W2_0027_POSTGRES_TEMP_DELETE_SKIPPED_CLUSTER_MAY_BE_RUNNING" in harness
    assert "W2_0027_POSTGRES_CLEANUP_FAILURE" in harness
    assert "$CleanupProblems.Count -ne 0" in harness
    assert "W2_0027_BROWSER_DATABASE_EVIDENCE_FAILED" in harness
    assert "W2_0027_BROWSER_REAL_PG_GREEN" in harness
    assert "$RequestedPorts" in harness
    assert "git_delta={3}" in harness

    assert 'endswith("_browser_test")' in seed
    assert "record_official_source" in seed
    assert 'CARD_OCCURRENCE_KEY = "w2-browser-e2e-plan-notice"' in seed
    assert "CARD_DUE_DATE = date(2026, 8, 20)" in seed

    assert "page.route(" not in spec
    assert "login-pin-input" in spec
    assert "W2_BROWSER_STALE_MUST_BE_409" in spec
    assert "W2_BROWSER_CANDIDATE_RELOAD_FAILED" in spec
    assert "W2_BROWSER_CANDIDATE_RELOAD_NOT_SETTLED" in spec
    assert "W2_BROWSER_LATEST_ASSIGNEE_MISMATCH" in spec
    assert "W2_BROWSER_STALE_SELECTION_NOT_CLEARED" in spec
    assert "official-work-card-reassign-confirm" in spec
    assert "getByRole('button', { name: '닫기' })" in spec
    for label in ("업무종류", "대상자", "상세업무", "마감일", "현재 담당자"):
        assert label in spec
    assert "W2_OFFICIAL_CARD_BROWSER_GREEN" in spec

    assert "SSWCENTER_W2_PLAYWRIGHT_OUTPUT_DIR" in config
    assert "must stay outside the repository" in config
    assert "workers: 1" in config
    assert "retries: 0" in config
