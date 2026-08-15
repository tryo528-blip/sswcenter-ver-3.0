"""Static and pure-unit contract tests for the isolated W2 core slice."""

from __future__ import annotations

import importlib.util
import inspect
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import ForeignKeyConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.api.w2 import router
from app.db import models as existing_models  # noqa: F401
from app.db.w2_models import (
    MonthlyProfessionalAssignment,
    W2OfficialWorkCard,
    W2PersonalTodo,
    W2Schedule,
    W2ScheduleMonthControl,
    W2ScheduleStaff,
)
from app.domains.w2.policies import (
    OfficialCardSource,
    card_priority,
    contract_expiry_source,
    display_target_name,
    plan_notice_source,
    recognition_expiry_source,
    validate_official_source,
)
from app.domains.w2.repository import W2Repository
from app.domains.w2.schemas import (
    OfficialWorkCardDisplay,
    OfficialWorkCardKind,
    PersonalTodoUpdateRequest,
    ScheduleCreateRequest,
    ScheduleStaffInput,
)
from app.domains.w2.service import W2Service

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    BACKEND_ROOT
    / "alembic"
    / "versions"
    / "20260813_0023_w2_core_ledgers.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location("w2_core_0023", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0023_is_forward_child_and_contains_period_and_schedule_guards() -> None:
    module = _migration_module()
    source = MIGRATION.read_text(encoding="utf-8")

    assert module.revision == "20260813_0023_w2_core_ledgers"
    assert module.down_revision == "20260813_0022_w1_certification_contract_correction"
    assert "monthly_professional_assignment" in source
    assert "w2_professional_assignment" not in source
    assert "ex_monthly_professional_assignment_current_period" in source
    assert "fn_monthly_professional_assignment_fact_guard" in source
    assert "PROFESSIONAL_ASSIGNMENT_OUTSIDE_EMPLOYMENT" in source
    assert "PROFESSIONAL_ASSIGNMENT_POSITION_REQUIRED" in source
    assert "w2_schedule_staff" in source
    assert "fn_w2_schedule_staff_contract_guard" in source
    assert "service_type.code = 'HOME_BATH' THEN 2 ELSE 1" in source
    assert "DEFERRABLE INITIALLY DEFERRED" in source
    assert "SCHEDULE_OUTSIDE_EMPLOYMENT" in source
    assert "SCHEDULE_CARE_WORKER_POSITION_REQUIRED" in source
    assert "SCHEDULE_OUTSIDE_QUALIFICATION" in source
    assert "ex_w2_schedule_recipient_overlap" in source
    assert "ex_w2_schedule_staff_overlap" not in source


def test_monthly_assignment_model_is_period_fact_with_composite_employment_fk() -> None:
    dialect = postgresql.dialect()
    table = MonthlyProfessionalAssignment.__table__
    ddl = str(CreateTable(table).compile(dialect=dialect))
    assert ddl
    assert table.name == "monthly_professional_assignment"
    assert {
        "recipient_id",
        "service_month",
        "staff_id",
        "employment_id",
        "start_date",
        "end_date",
        "assignment_period",
        "invalidated_at_utc",
        "replacement_assignment_id",
        "row_version",
    } <= set(table.columns.keys())
    assert "service_type_id" not in table.columns
    assert "position_code" not in table.columns

    exclusion_names = {
        constraint.name
        for constraint in table.constraints
        if constraint.__class__.__name__ == "ExcludeConstraint"
    }
    assert exclusion_names == {"ex_monthly_professional_assignment_current_period"}
    employment_fks = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_monthly_professional_assignment_employment"
    ]
    assert len(employment_fks) == 1
    assert [column.name for column in employment_fks[0].columns] == [
        "staff_id",
        "employment_id",
    ]


def test_schedule_body_and_staff_join_compile_with_one_shared_schedule_pk() -> None:
    dialect = postgresql.dialect()
    for table in (
        W2ScheduleMonthControl.__table__,
        W2Schedule.__table__,
        W2ScheduleStaff.__table__,
        W2PersonalTodo.__table__,
        W2OfficialWorkCard.__table__,
    ):
        assert str(CreateTable(table).compile(dialect=dialect))

    schedule_columns = set(W2Schedule.__table__.columns.keys())
    assert {"id", "recipient_id", "service_type_id", "schedule_period"} <= schedule_columns
    assert "staff_id" not in schedule_columns
    assert "recipient_projection_id" not in schedule_columns
    assert "staff_projection_id" not in schedule_columns
    assert {"schedule_id", "staff_id", "employment_id"} <= set(
        W2ScheduleStaff.__table__.columns.keys()
    )

    exclusion_names = {
        constraint.name
        for constraint in W2Schedule.__table__.constraints
        if constraint.__class__.__name__ == "ExcludeConstraint"
    }
    assert exclusion_names == {"ex_w2_schedule_recipient_overlap"}


def test_schedule_payload_uses_distinct_assigned_staff_and_timezone() -> None:
    payload = ScheduleCreateRequest(
        schedule_month=date(2027, 1, 1),
        recipient_id=1,
        service_type_id=1,
        assigned_staff=[ScheduleStaffInput(staff_id=1, employment_id=11)],
        starts_at_utc=datetime(2027, 1, 2, 0, tzinfo=UTC),
        ends_at_utc=datetime(2027, 1, 2, 1, tzinfo=UTC),
        expected_month_row_version=1,
    )
    assert payload.assigned_staff[0].employment_id == 11

    with pytest.raises(ValidationError):
        ScheduleCreateRequest(
            schedule_month=date(2027, 1, 1),
            recipient_id=1,
            service_type_id=1,
            assigned_staff=[
                ScheduleStaffInput(staff_id=1, employment_id=11),
                ScheduleStaffInput(staff_id=1, employment_id=12),
            ],
            starts_at_utc=datetime(2027, 1, 2, 0, tzinfo=UTC),
            ends_at_utc=datetime(2027, 1, 2, 1, tzinfo=UTC),
            expected_month_row_version=1,
        )
    with pytest.raises(ValidationError):
        ScheduleCreateRequest(
            schedule_month=date(2027, 1, 2),
            recipient_id=1,
            service_type_id=1,
            assigned_staff=[ScheduleStaffInput(staff_id=1, employment_id=11)],
            starts_at_utc=datetime(2027, 1, 2, 0),
            ends_at_utc=datetime(2027, 1, 2, 1),
            expected_month_row_version=1,
        )


def test_service_seals_home_bath_to_two_and_other_services_to_one() -> None:
    source = inspect.getsource(W2Service._validate_schedule_staff)
    assert 'service_type_code == "HOME_BATH"' in source
    assert "else 1" in source
    assert "SCHEDULE_STAFF_COUNT_INVALID" in source
    assert "employment_fact" in source


def test_personal_todo_has_boolean_only_and_no_status_enum() -> None:
    columns = W2PersonalTodo.__table__.columns
    assert "completed" in columns
    assert "status" not in columns
    assert str(columns.completed.type) == "BOOLEAN"

    valid = PersonalTodoUpdateRequest(
        expected_list_revision=1,
        expected_row_version=1,
        completed=True,
    )
    assert valid.completed is True
    with pytest.raises(ValidationError):
        PersonalTodoUpdateRequest(
            expected_list_revision=1,
            expected_row_version=1,
            completed="true",  # type: ignore[arg-type]
        )


def test_official_card_kind_and_five_display_fields_are_sealed() -> None:
    assert {item.value for item in OfficialWorkCardKind} == {
        "RECOGNITION_EXPIRY",
        "CONTRACT_EXPIRY",
        "PLAN_NOTICE",
        "STAFF_REPLACEMENT_CONSULTATION",
        "NEW_STAFF_WORK",
    }
    assert tuple(OfficialWorkCardDisplay.model_fields) == (
        "work_title",
        "target_name",
        "detail",
        "due_date",
        "d_day",
    )
    assert display_target_name(None) == "미입력"
    assert display_target_name("  ") == "미입력"


def test_renewal_due_dates_priority_and_closed_dominant_history_are_exact() -> None:
    common = {
        "renewal_key": "recipient:7:renewal:2027-12-31",
        "assignee_staff_id": 11,
        "target_name": None,
        "detail": "세부 업무",
        "recipient_id": 7,
    }
    recognition = recognition_expiry_source(
        occurrence_key="recognition:7:2027-12-31",
        recognition_end_date=date(2027, 12, 31),
        **common,
    )
    contract = contract_expiry_source(
        occurrence_key="contract:7:2027-12-31",
        contract_end_date=date(2027, 12, 31),
        **common,
    )
    plan = plan_notice_source(
        occurrence_key="plan:7:2027-12-31",
        writing_deadline=date(2027, 12, 31),
        **common,
    )

    assert recognition.due_date == date(2027, 9, 22)
    assert contract.due_date == date(2027, 11, 16)
    assert plan.due_date == date(2027, 11, 16)
    assert card_priority(recognition.kind) > card_priority(contract.kind) > card_priority(plan.kind)
    assert validate_official_source(recognition).target_name == "미입력"

    repository_source = inspect.getsource(W2Repository.cards_by_renewal_for_update)
    service_source = inspect.getsource(W2Service.record_official_source)
    assert "closed_at_utc" not in repository_source
    assert ".order_by(W2OfficialWorkCard.id)" in repository_source
    assert "dominant = max(" in service_source
    assert "renewal_history" in service_source


def test_nonrenewal_source_interface_does_not_create_a_generator() -> None:
    source = OfficialCardSource(
        kind=OfficialWorkCardKind.STAFF_REPLACEMENT_CONSULTATION,
        occurrence_key="staff-replacement:1",
        renewal_key=None,
        assignee_staff_id=1,
        work_title="직원교체상담",
        target_name="대상자",
        detail="상담 준비",
        due_date=date(2027, 1, 1),
    )
    assert validate_official_source(source) == source
    service_source = inspect.getsource(W2Service)
    assert "record_official_source" in service_source
    assert "generate_staff_replacement" not in service_source
    assert "generate_new_staff" not in service_source


def test_router_has_period_assignment_and_no_unapproved_schedule_commands() -> None:
    methods_by_path: dict[str, set[str]] = {}
    for route in router.routes:
        methods_by_path.setdefault(route.path, set()).update(route.methods or set())

    assert methods_by_path["/api/v1/professional-assignments/staff-options"] == {"GET"}
    assert methods_by_path["/api/v1/professional-assignments/{recipient_id}"] == {"GET"}
    assert methods_by_path[
        "/api/v1/professional-assignments/{recipient_id}/{service_month}"
    ] == {"POST"}
    assert methods_by_path[
        "/api/v1/professional-assignments/{recipient_id}/{service_month}/{assignment_id}"
    ] == {"PUT"}
    assert methods_by_path["/api/v1/official-work-cards"] == {"GET"}
    assert methods_by_path["/api/v1/official-work-cards/{card_id}/close"] == {"POST"}
    assert "/api/v1/schedule-months/{schedule_month}/finalize" in methods_by_path
    assert all("unfinal" not in path and "warning" not in path for path in methods_by_path)
    assert all("bulk" not in path for path in methods_by_path)
    assert all("reopen" not in path for path in methods_by_path)
    assert all(
        not (path.startswith("/api/v1/official-work-cards") and "DELETE" in methods)
        for path, methods in methods_by_path.items()
    )


def test_repository_locks_all_multirow_ledgers_in_id_order() -> None:
    schedule_source = inspect.getsource(W2Repository.schedules)
    schedule_staff_source = inspect.getsource(W2Repository.schedule_staff)
    assignment_source = inspect.getsource(W2Repository.current_assignments_for_update)
    renewal_source = inspect.getsource(W2Repository.cards_by_renewal_for_update)

    assert ".order_by(W2Schedule.id)" in schedule_source
    assert ".order_by(W2ScheduleStaff.id)" in schedule_staff_source
    assert ".order_by(MonthlyProfessionalAssignment.id)" in assignment_source
    assert ".order_by(W2OfficialWorkCard.id)" in renewal_source
    for source in (
        schedule_source,
        schedule_staff_source,
        assignment_source,
        renewal_source,
    ):
        assert ".with_for_update()" in source
