from __future__ import annotations

import inspect
import os
import re
from datetime import date
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult

from app.core.auth import CurrentAccount
from app.core.settings import Environment, get_settings
from app.db.models import (
    Recipient,
    RecipientGuardian,
    Staff,
    StaffSensitiveIdentity,
)
from app.db.seed_w0_w2_workflow_test_data import (
    ASSIGNMENT_SPECS,
    BENEFIT_START_TEXT,
    BOUNDARY_EXCLUSIONS,
    EXPECTED_INVENTORY,
    GRAPH_INTEGRITY_DIMENSIONS,
    RECIPIENT_SCENARIOS,
    SEED_MARKER,
    SEED_VERSION,
    SERVICE_MONTH,
    STAFF_SCENARIOS,
    MeasuredInventory,
    ObservedRecipient,
    ObservedStaff,
    _apply_benefit,
    _compose_address,
    _local_database_guard,
    _memo,
    _phone,
    _seoul_slot,
    _staff_create_request,
    _synthetic_rrn,
    classify_measured_inventory,
    evaluate_workflow_graph,
    recipient_integrity_errors,
    seed_w0_w2_workflow_test_data,
    staff_integrity_errors,
)
from app.db.session import build_session_factory, create_postgres_engine
from app.domains.recipient.schemas import RecipientStatus
from app.domains.staff.policies import validate_resident_number
from app.domains.w1c.schemas import (
    BenefitCode,
    BenefitPeriodListResponse,
    BenefitPeriodReplacementRequest,
    BenefitPeriodResponse,
    GradeCode,
)
from app.domains.w1c.service import W1CService
from app.domains.w1d.schemas import ServiceTypeCode

LIVE_ENABLED = os.environ.get("SSWCENTER_SEED_LIVE_PG") == "1"


def _zero_measured(**overrides: object) -> MeasuredInventory:
    payload: dict[str, object] = {
        "staff": 0,
        "active_staff": 0,
        "ended_staff": 0,
        "recipients": 0,
        "active_recipients": 0,
        "waiting_recipients": 0,
        "ended_recipients": 0,
        "guardians": 0,
        "payer_guardians": 0,
        "certification_identities": 0,
        "active_certification_periods": 0,
        "active_benefits": 0,
        "staff_sensitive_identities": 0,
        "staff_licenses": 0,
        "staff_qualifications": 0,
        "contracts": 0,
        "care_assignments": 0,
        "monthly_professional_assignments": 0,
        "schedules": 0,
        "schedule_staff": 0,
        "home_bath_two_worker_schedules": 0,
        "official_work_cards": 0,
        "service_plan_notices": 0,
        "personal_todos_seed_created": 0,
        "replacement_lineage": 0,
        "integrity_errors": (),
    }
    payload.update(overrides)
    return MeasuredInventory(**payload)  # type: ignore[arg-type]


def _complete_measured(**overrides: object) -> MeasuredInventory:
    expected = EXPECTED_INVENTORY
    return _zero_measured(
        staff=expected.staff,
        active_staff=expected.active_staff,
        ended_staff=expected.ended_staff,
        recipients=expected.recipients,
        active_recipients=expected.active_recipients,
        waiting_recipients=expected.waiting_recipients,
        ended_recipients=expected.ended_recipients,
        guardians=expected.guardians,
        payer_guardians=expected.payer_guardians,
        certification_identities=expected.certification_identities,
        active_certification_periods=expected.active_certification_periods,
        active_benefits=expected.active_benefits,
        staff_sensitive_identities=expected.staff_sensitive_identities,
        staff_licenses=expected.staff_licenses,
        staff_qualifications=expected.staff_qualifications,
        contracts=expected.contracts,
        care_assignments=expected.care_assignments,
        monthly_professional_assignments=expected.monthly_professional_assignments,
        schedules=expected.schedules,
        schedule_staff=expected.schedule_staff,
        home_bath_two_worker_schedules=expected.home_bath_two_worker_schedules,
        **overrides,
    )


def test_workflow_inventory_is_small_and_complete() -> None:
    assert EXPECTED_INVENTORY.staff == 10
    assert EXPECTED_INVENTORY.active_staff == 6
    assert EXPECTED_INVENTORY.ended_staff == 4
    assert EXPECTED_INVENTORY.recipients == 6
    assert EXPECTED_INVENTORY.active_recipients == 4
    assert EXPECTED_INVENTORY.waiting_recipients == 1
    assert EXPECTED_INVENTORY.ended_recipients == 1
    assert EXPECTED_INVENTORY.guardians == 4
    assert EXPECTED_INVENTORY.payer_guardians == 3
    assert EXPECTED_INVENTORY.certification_identities == 6
    assert EXPECTED_INVENTORY.active_benefits == 6
    assert EXPECTED_INVENTORY.staff_sensitive_identities == 10
    assert EXPECTED_INVENTORY.contracts == 6
    assert EXPECTED_INVENTORY.care_assignments == 7
    assert EXPECTED_INVENTORY.monthly_professional_assignments == 2
    assert EXPECTED_INVENTORY.schedules == 4
    assert EXPECTED_INVENTORY.schedule_staff == 5
    assert EXPECTED_INVENTORY.home_bath_two_worker_schedules == 1
    assert EXPECTED_INVENTORY.official_work_cards == 0
    assert EXPECTED_INVENTORY.service_plan_notices == 0
    assert EXPECTED_INVENTORY.personal_todos == 0
    assert EXPECTED_INVENTORY.replacement_lineage == 0
    assert len(ASSIGNMENT_SPECS) == 7
    assert SEED_VERSION == 1
    assert SEED_MARKER.endswith("_V1")
    assert SERVICE_MONTH == date(2026, 8, 1)
    assert set(GRAPH_INTEGRITY_DIMENSIONS) >= {
        "staff_marker_keys",
        "staff_sensitive_identity",
        "guardians_relationship",
        "current_benefit_code_start_text",
        "w2_schedules_month_service_time_staff",
        "no_marked_recipient_official_cards",
    }


def test_workflow_scenarios_cover_current_codes_and_statuses() -> None:
    assert {item.status for item in RECIPIENT_SCENARIOS} == {
        RecipientStatus.ACTIVE,
        RecipientStatus.WAITING,
        RecipientStatus.ENDED,
    }
    assert {item.grade_code for item in RECIPIENT_SCENARIOS} == set(GradeCode)
    assert {item.benefit_code for item in RECIPIENT_SCENARIOS} == set(BenefitCode)
    contract_codes = {code for item in RECIPIENT_SCENARIOS for code in item.service_type_codes}
    assert contract_codes == set(ServiceTypeCode)
    assert any(item.self_payer for item in RECIPIENT_SCENARIOS)
    assert any(not item.self_payer for item in RECIPIENT_SCENARIOS)
    assert any(item.guardian_name is not None for item in RECIPIENT_SCENARIOS)
    waiting = next(item for item in RECIPIENT_SCENARIOS if item.status is RecipientStatus.WAITING)
    assert waiting.service_type_codes == ()
    positions = {item.position_code.value for item in STAFF_SCENARIOS}
    assert positions == {"CARE_WORKER", "SOCIAL_WORKER", "NURSE", "MANAGER"}
    assert any(item.ended for item in STAFF_SCENARIOS)
    assert any(not item.ended for item in STAFF_SCENARIOS)
    ended = next(item for item in RECIPIENT_SCENARIOS if item.status is RecipientStatus.ENDED)
    assert ended.grade_code is GradeCode.GRADE_5
    assert ended.benefit_code is BenefitCode.MEDICAL_6


def test_workflow_marker_state_is_fail_closed() -> None:
    assert classify_measured_inventory(_zero_measured()) == "empty"
    assert classify_measured_inventory(_complete_measured()) == "complete"
    assert classify_measured_inventory(_zero_measured(staff=1)) == "partial"
    assert (
        classify_measured_inventory(
            _complete_measured(integrity_errors=("missing_guardian:R_ACTIVE_BARO",))
        )
        == "partial"
    )


def test_workflow_synthetic_identity_formats() -> None:
    phone = re.compile(r"^010-0700-\d{4}$")
    korean_name = re.compile(r"^[가-힣]{2,4}$")
    role_coded = re.compile(r"(요양|사회|간호|관리|퇴사)$")
    for staff_scenario in STAFF_SCENARIOS:
        request = _staff_create_request(staff_scenario)
        assert korean_name.fullmatch(staff_scenario.name)
        assert role_coded.search(staff_scenario.name) is None
        assert request.memo == _memo(staff_scenario.key)
        assert request.memo == f"{SEED_MARKER}|{staff_scenario.key}"
        assert phone.fullmatch(request.phone or "")
        assert "시드센터" in (request.address or "")
        assert "합성" in (request.address or "")
        cleaned = validate_resident_number(
            rrn_input=request.resident_number,
            expected_birth_date=staff_scenario.birth_date,
            expected_sex_code=staff_scenario.sex_code.value,
        )
        assert cleaned.startswith(staff_scenario.birth_date.strftime("%y%m%d"))
        assert request.resident_number.split("-")[1][1:].startswith("70")
    for recipient_scenario in RECIPIENT_SCENARIOS:
        assert korean_name.fullmatch(recipient_scenario.name)
        assert phone.fullmatch(_phone(recipient_scenario.phone_index))
        address = _compose_address(
            recipient_scenario.road_address,
            recipient_scenario.unit_detail,
        )
        assert address.startswith(recipient_scenario.road_address)
        assert "시드센터" in address
        assert "합성" in address
        assert recipient_scenario.postal_code.isdigit()
        assert len(recipient_scenario.postal_code) == 5
        assert _memo(recipient_scenario.key) == f"{SEED_MARKER}|{recipient_scenario.key}"


def test_workflow_staff_request_wires_current_employment_constructor() -> None:
    ended = next(item for item in STAFF_SCENARIOS if item.key == "CW_ENDED")
    request = _staff_create_request(ended)
    position_end = request.initial_employment.initial_positions[0].end_date
    assert position_end is not None
    assert request.initial_employment.start_date < position_end
    assert request.initial_employment.initial_positions[0].position_code.value == "CARE_WORKER"
    assert request.initial_employment.initial_operational_roles[0].role_code == "CARE_SERVICE"
    synthetic = _synthetic_rrn(ended.birth_date, ended.sex_code, 700007)
    assert request.resident_number == synthetic


def test_workflow_schedule_slots_are_timezone_aware_and_inside_month() -> None:
    start, end = _seoul_slot(11, 10, 11)
    assert start.tzinfo is not None
    assert end.tzinfo is not None
    assert start < end
    assert start.date() == date(2026, 8, 11)
    assert end.date() == date(2026, 8, 11)


def test_workflow_excludes_d01_d02_and_account_owned_rows() -> None:
    import app.db.seed_w0_w2_workflow_test_data as workflow

    source = inspect.getsource(workflow)
    assert "create_service_plan_notice" not in source
    assert "record_official_source" not in source
    assert "W2OfficialWorkCard" in source
    assert "replace_assignment" not in source
    assert "replace_professional_assignment" not in source
    assert "replace_schedule" not in source
    assert "create_personal_todo" not in source
    assert "W2-D01" in " ".join(BOUNDARY_EXCLUSIONS)
    assert "W2-D02" in " ".join(BOUNDARY_EXCLUSIONS)


def test_workflow_uses_service_layer_and_exact_markers() -> None:
    import app.db.seed_w0_w2_workflow_test_data as workflow

    source = inspect.getsource(workflow)
    assert "StaffService" in source
    assert "RecipientService" in source
    assert "W1CService" in source
    assert "W1DService" in source
    assert "W1EService" in source
    assert "W2Service" in source
    assert "create_staff" in source
    assert "create_assignment" in source
    assert "create_schedule" in source
    assert "create_professional_assignment" in source
    assert "staff_id=1" not in source
    assert "recipient_id=1" not in source
    assert "ALREADY_COMPLETE" in source
    assert "SEED_W0_W2_WORKFLOW_UNEXPECTED_PARTIAL_STATE" in source
    assert "recipient_detail_batch_defer_commit" in source
    assert "session.flush" in source
    assert "Staff.memo.like" not in source
    assert "Recipient.memo.like" not in source
    assert "func.strpos" in source
    assert "evaluate_workflow_graph" in source


def test_workflow_local_database_guard() -> None:
    _local_database_guard("postgresql://ssw:ssw@127.0.0.1:5432/sswcenter_dev")
    with pytest.raises(RuntimeError, match="loopback"):
        _local_database_guard("postgresql://ssw:ssw@8.8.8.8:5432/sswcenter_test")
    with pytest.raises(RuntimeError, match="development/test"):
        _local_database_guard("postgresql://ssw:ssw@127.0.0.1:5432/sswcenter")


def test_workflow_seed_refuses_production_and_missing_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.db.seed_w0_w2_workflow_test_data.get_settings",
        lambda: SimpleNamespace(
            environment=Environment.PRODUCTION,
            database_url="postgresql://ssw:ssw@127.0.0.1:5432/sswcenter_test",
        ),
    )
    with pytest.raises(RuntimeError, match="production"):
        seed_w0_w2_workflow_test_data()
    monkeypatch.setattr(
        "app.db.seed_w0_w2_workflow_test_data.get_settings",
        lambda: SimpleNamespace(environment=Environment.TEST, database_url=None),
    )
    with pytest.raises(RuntimeError, match="SSWCENTER_DATABASE_URL"):
        seed_w0_w2_workflow_test_data()


def test_workflow_graph_rejects_missing_guardian() -> None:
    scenario = next(item for item in RECIPIENT_SCENARIOS if item.key == "R_ACTIVE_BARO")
    observed = ObservedRecipient(
        key=scenario.key,
        name=scenario.name,
        sex_code=scenario.sex_code.value,
        birth_date=scenario.birth_date,
        status=scenario.status.value,
        phone=_phone(scenario.phone_index),
        address=_compose_address(scenario.road_address, scenario.unit_detail),
        self_payer=True,
        guardians=(),
        certification_number="L9000000006",
        grade_code=scenario.grade_code.value,
        cert_start=date(2025, 6, 1),
        cert_end=date(2027, 5, 31),
        benefit_code=scenario.benefit_code.value,
        benefit_start_text=BENEFIT_START_TEXT,
        contract_codes=("BARO_CARE",),
        contract_dates=(("BARO_CARE", date(2026, 1, 5), None),),
    )
    errors = recipient_integrity_errors(scenario, observed)
    assert "missing_guardian:R_ACTIVE_BARO" in errors


def test_workflow_graph_rejects_staff_identity_and_qualification_corruption() -> None:
    scenario = next(item for item in STAFF_SCENARIOS if item.key == "CW_HOME_A")
    observed = ObservedStaff(
        key=scenario.key,
        name=scenario.name,
        sex_code=scenario.sex_code.value,
        birth_date=scenario.birth_date,
        phone=_phone(scenario.phone_index),
        address=scenario.address,
        has_sensitive_identity=False,
        employment_start=date(2025, 1, 2),
        employment_end=None,
        end_reason_code=None,
        position_code=scenario.position_code.value,
        position_start=date(2025, 1, 2),
        position_end=None,
        role_code="CARE_SERVICE",
        role_start=date(2025, 1, 2),
        role_end=None,
        license_type_code="CARE_WORKER",
        qualification_codes=("HOME_CARE",),
    )
    errors = staff_integrity_errors(scenario, observed)
    assert "missing_staff_sensitive_identity:CW_HOME_A" in errors
    assert "staff_qualifications:CW_HOME_A" in errors


def test_workflow_graph_rejects_blank_general_start_text() -> None:
    scenario = next(item for item in RECIPIENT_SCENARIOS if item.key == "R_ACTIVE_HOME_CARE")
    observed = ObservedRecipient(
        key=scenario.key,
        name=scenario.name,
        sex_code=scenario.sex_code.value,
        birth_date=scenario.birth_date,
        status=scenario.status.value,
        phone=_phone(scenario.phone_index),
        address=_compose_address(scenario.road_address, scenario.unit_detail),
        self_payer=True,
        guardians=(),
        certification_number="L9000000001",
        grade_code=scenario.grade_code.value,
        cert_start=date(2025, 6, 1),
        cert_end=date(2027, 5, 31),
        benefit_code=BenefitCode.GENERAL.value,
        benefit_start_text="",
        contract_codes=("HOME_CARE",),
        contract_dates=(("HOME_CARE", date(2026, 1, 5), None),),
    )
    errors = recipient_integrity_errors(scenario, observed)
    assert "benefit_start_text:R_ACTIVE_HOME_CARE" in errors


class _RecordingW1CService:
    def __init__(self, start_text: str = "") -> None:
        self.replaced: tuple[int, int, BenefitPeriodReplacementRequest] | None = None
        self.start_text = start_text

    def list_benefit_periods(self, recipient_id: int) -> BenefitPeriodListResponse:
        return BenefitPeriodListResponse(
            items=[
                BenefitPeriodResponse(
                    id=11,
                    recipient_id=recipient_id,
                    benefit_code=BenefitCode.GENERAL,
                    start_text=self.start_text,
                    invalidated_at_utc=None,
                    replacement_benefit_period_id=None,
                    row_version=1,
                )
            ]
        )

    def replace_benefit_period(
        self,
        recipient_id: int,
        period_id: int,
        payload: BenefitPeriodReplacementRequest,
        account: CurrentAccount,
    ) -> None:
        self.replaced = (recipient_id, period_id, payload)


def test_workflow_general_benefit_replaces_blank_start_text() -> None:
    recorder = _RecordingW1CService(start_text="")
    account = CurrentAccount(id=1, display_name="관리자", role_code="ADMIN")
    _apply_benefit(
        w1c_service=cast(W1CService, recorder),
        recipient_id=77,
        benefit_code=BenefitCode.GENERAL,
        start_text=BENEFIT_START_TEXT,
        account=account,
    )
    assert recorder.replaced is not None
    _recipient_id, period_id, payload = recorder.replaced
    assert period_id == 11
    assert payload.benefit_code is BenefitCode.GENERAL
    assert payload.start_text == BENEFIT_START_TEXT


def test_workflow_spouse_name_is_not_forced_to_recipient_surname() -> None:
    temp = next(item for item in RECIPIENT_SCENARIOS if item.key == "R_ACTIVE_TEMP")
    assert temp.guardian_relationship == "배우자"
    assert temp.guardian_name is not None
    assert temp.guardian_name[0] != temp.name[0]


@pytest.mark.skipif(not LIVE_ENABLED, reason="requires isolated seed live PostgreSQL")
def test_workflow_live_complete_rerun_and_subordinate_deletion_fail_closed() -> None:
    get_settings.cache_clear()
    first = seed_w0_w2_workflow_test_data()
    assert first["status"] == "COMPLETE"
    assert first["staff"] == 10
    assert first["recipients"] == 6
    assert first["guardians"] == 4
    assert first["payer_guardians"] == 3
    assert first["active_staff"] == 6
    assert first["ended_staff"] == 4
    assert first["official_work_cards"] == 0
    assert first["service_plan_notices"] == 0
    assert first["personal_todos"] == 0
    assert first["integrity_error_count"] == 0

    second = seed_w0_w2_workflow_test_data()
    assert second["status"] == "ALREADY_COMPLETE"
    assert second["created"] == 0

    settings = get_settings()
    assert settings.database_url is not None
    engine = create_postgres_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as session:
            recipient = session.scalar(
                select(Recipient).where(Recipient.memo == _memo("R_ACTIVE_BARO"))
            )
            assert recipient is not None
            deleted = cast(
                CursorResult[Any],
                session.execute(
                    delete(RecipientGuardian).where(RecipientGuardian.recipient_id == recipient.id)
                ),
            )
            assert deleted.rowcount == 1
            session.commit()
            measured = evaluate_workflow_graph(session)
            assert "missing_guardian:R_ACTIVE_BARO" in measured.integrity_errors
            assert classify_measured_inventory(measured) == "partial"
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="PARTIAL"):
        seed_w0_w2_workflow_test_data()

    engine = create_postgres_engine(settings.database_url)
    factory = build_session_factory(engine)
    try:
        with factory() as session:
            staff = session.scalar(select(Staff).where(Staff.memo == _memo("CW_HOME_A")))
            assert staff is not None
            session.execute(
                delete(StaffSensitiveIdentity).where(StaffSensitiveIdentity.staff_id == staff.id)
            )
            session.commit()
            measured = evaluate_workflow_graph(session)
            assert any(
                item.startswith("missing_staff_sensitive_identity:CW_HOME_A")
                for item in measured.integrity_errors
            )
    finally:
        engine.dispose()
