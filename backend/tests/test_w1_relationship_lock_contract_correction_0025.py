from __future__ import annotations

from pathlib import Path
from typing import cast

from sqlalchemy import Table

from app.db.models import Recipient, RecipientGuardian, StaffHealthCheck
from app.domains.recipient.schemas import GuardianCreateRequest, GuardianResponse
from app.domains.staff.schemas import StaffHealthCheckCreateRequest
from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "backend"
    / "alembic"
    / "versions"
    / "20260813_0025_w1_relationship_lock_contract_correction.py"
)


def test_0025_is_a_forward_only_correction_after_0024() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert 'revision: str = "20260813_0025_w1_relationship_lock_contract_correction"' in source
    assert 'down_revision: str | None = "20260813_0024_w2_service_plan_notice_current"' in source
    assert "raise RuntimeError(" in source
    assert "slot_no" in source
    assert 'ondelete="SET NULL (payer_guardian_id)"' in source
    assert "fk_staff_health_check_employment" in source


def test_guardian_slots_and_payer_fallback_exist_in_the_orm_contract() -> None:
    guardian_table = cast(Table, RecipientGuardian.__table__)
    recipient_table = cast(Table, Recipient.__table__)
    guardian_columns = guardian_table.columns
    guardian_constraints = {constraint.name for constraint in guardian_table.constraints}
    payer_constraint = next(
        constraint
        for constraint in recipient_table.foreign_key_constraints
        if constraint.name == "fk_recipient_payer_guardian_same_recipient"
    )

    assert guardian_columns["slot_no"].nullable is False
    assert {
        "ck_recipient_guardian_slot_no",
        "uq_recipient_guardian_recipient_slot",
    } <= guardian_constraints
    assert payer_constraint.ondelete == "SET NULL (payer_guardian_id)"
    assert set(GuardianCreateRequest.model_fields) == {
        "name",
        "phone",
        "email",
        "address",
        "relationship_text",
    }
    assert "slot_no" in GuardianResponse.model_fields


def test_health_check_link_is_internal_nullable_metadata_only() -> None:
    health_table = cast(Table, StaffHealthCheck.__table__)
    health_columns = health_table.columns
    health_constraints = {constraint.name for constraint in health_table.constraints}

    assert health_columns["employment_id"].nullable is True
    assert "fk_staff_health_check_employment" in health_constraints
    assert set(StaffHealthCheckCreateRequest.model_fields) == {"check_date"}


def test_finalized_schedule_month_exposes_http_423() -> None:
    paths = app.openapi()["paths"]

    assert "423" not in paths["/api/v1/schedules"]["get"]["responses"]
    assert "423" in paths["/api/v1/schedules"]["post"]["responses"]
    assert "423" in paths["/api/v1/schedules/{schedule_id}"]["put"]["responses"]
    assert "423" in paths["/api/v1/schedules/{schedule_id}"]["delete"]["responses"]
    assert "423" in paths["/api/v1/schedule-months/{schedule_month}/finalize"]["post"]["responses"]
    assert "423" not in paths["/api/v1/personal-todos"]["post"]["responses"]


def test_http_423_is_documented_only_for_actual_resource_lock_paths() -> None:
    paths = app.openapi()["paths"]
    actual = {
        (method.upper(), path)
        for path, operations in paths.items()
        for method, operation in operations.items()
        if isinstance(operation, dict) and "423" in operation.get("responses", {})
    }

    assert actual == {
        ("POST", "/api/v1/staff/{staff_id}/sensitive-identity/reveal"),
        ("POST", "/api/v1/schedules"),
        ("PUT", "/api/v1/schedules/{schedule_id}"),
        ("DELETE", "/api/v1/schedules/{schedule_id}"),
        ("POST", "/api/v1/schedule-months/{schedule_month}/finalize"),
    }
