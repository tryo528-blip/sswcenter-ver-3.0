from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domains.staff.policies import (
    has_annual_health_check,
    has_entry_health_check,
    health_check_entry_window,
    is_annual_health_check_date,
    is_entry_health_check_date,
    requires_annual_health_check,
)
from app.domains.staff.repository import _TRAINING_COURSE_ORDER
from app.domains.staff.schemas import (
    StaffHealthCheckCreateRequest,
    StaffQuarterlyConsultationCreateRequest,
    StaffQuarterlyConsultationUpdateRequest,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT / "backend" / "alembic" / "versions" / "20260813_0020_w1_staff_contract_correction.py"
)


def test_0020_revision_and_forward_only_contract() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "20260813_0020_w1_staff_contract_correction"' in source
    assert 'down_revision: str | None = "20260812_0019_r0_w2_read_only"' in source
    assert "staff_health_check_requirement" in source
    assert "op.drop_table" in source
    assert "SET completed = (status = 'COMPLETE')" in source
    assert "raise RuntimeError" in source


def test_new_hire_and_reentry_window_is_inclusive_at_exact_boundaries() -> None:
    employment_start = date(2026, 8, 15)
    assert health_check_entry_window(employment_start) == (
        date(2025, 8, 16),
        date(2027, 8, 15),
    )
    assert not is_entry_health_check_date(employment_start, date(2025, 8, 15))
    assert is_entry_health_check_date(employment_start, date(2025, 8, 16))
    assert is_entry_health_check_date(employment_start, date(2027, 8, 15))
    assert not is_entry_health_check_date(employment_start, date(2027, 8, 16))
    assert has_entry_health_check(employment_start, [date(2025, 8, 16)])


def test_entry_window_handles_february_29_deterministically() -> None:
    assert health_check_entry_window(date(2024, 2, 29)) == (
        date(2023, 3, 1),
        date(2025, 2, 28),
    )


@pytest.mark.parametrize(
    ("employment_start", "employment_end", "calendar_year", "expected"),
    [
        (date(2025, 1, 1), None, 2026, True),
        (date(2025, 1, 1), date(2026, 12, 29), 2026, False),
        (date(2025, 1, 1), date(2026, 12, 30), 2026, False),
        (date(2025, 1, 1), date(2026, 12, 31), 2026, True),
        (date(2026, 8, 15), None, 2026, False),
        (date(2026, 8, 15), date(2026, 11, 1), 2026, False),
    ],
)
def test_existing_employee_annual_target_rule(
    employment_start: date,
    employment_end: date | None,
    calendar_year: int,
    expected: bool,
) -> None:
    assert (
        requires_annual_health_check(
            employment_start=employment_start,
            employment_end=employment_end,
            calendar_year=calendar_year,
        )
        is expected
    )


def test_annual_check_uses_calendar_year_only() -> None:
    assert is_annual_health_check_date(2026, date(2026, 1, 1))
    assert is_annual_health_check_date(2026, date(2026, 12, 31))
    assert not is_annual_health_check_date(2026, date(2025, 12, 31))
    assert has_annual_health_check(2026, [date(2026, 7, 1)])


def test_health_and_quarterly_payloads_reject_removed_fields() -> None:
    with pytest.raises(ValidationError):
        StaffHealthCheckCreateRequest.model_validate(
            {"check_date": "2026-08-13", "status": "COMPLETE"}
        )
    with pytest.raises(ValidationError):
        StaffQuarterlyConsultationCreateRequest.model_validate(
            {
                "calendar_year": 2026,
                "quarter_no": 3,
                "completed": True,
                "content": "removed",
            }
        )
    toggle = StaffQuarterlyConsultationUpdateRequest(
        completed=True,
        expected_row_version=4,
    )
    assert toggle.completed is True
    assert toggle.expected_row_version == 4


def test_training_catalog_remains_exactly_eight_courses() -> None:
    assert _TRAINING_COURSE_ORDER == (
        "NEW_HIRE_ORIENTATION",
        "ELDER_RIGHTS",
        "DISABLED_ABUSE",
        "ELDER_ABUSE",
        "SEXUAL_HARASSMENT",
        "WORKPLACE_BULLYING",
        "PRIVACY",
        "CONTINUING_EDUCATION",
    )


def test_quarterly_constraint_drops_use_frozen_database_names() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    for constraint_name in (
        "ck_staff_quarterly_consultation_status_truth",
        "ck_staff_quarterly_consultation_text_length",
        "ck_staff_quarterly_consultation_status",
    ):
        assert f'op.f("{constraint_name}")' in source
