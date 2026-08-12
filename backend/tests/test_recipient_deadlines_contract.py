"""Pure contract tests for recipient deadline rules (no live database)."""

from datetime import date

from app.domains.recipient.schemas import RecipientDeadlineKind
from app.domains.recipient.service import _plan_renewal_due_date
from app.main import app


def test_plan_renewal_due_date_2026_03_02() -> None:
    assert _plan_renewal_due_date(date(2026, 3, 2)) == date(2026, 9, 30)


def test_plan_renewal_due_date_2026_08_31() -> None:
    assert _plan_renewal_due_date(date(2026, 8, 31)) == date(2027, 2, 28)


def test_plan_renewal_due_date_leap_year_target_month() -> None:
    assert _plan_renewal_due_date(date(2023, 8, 31)) == date(2024, 2, 29)


def test_plan_renewal_due_date_from_leap_day() -> None:
    assert _plan_renewal_due_date(date(2024, 2, 29)) == date(2024, 8, 31)


def test_recipient_deadline_kind_enum_values() -> None:
    assert RecipientDeadlineKind.CERTIFICATION_EXPIRY.value == "CERTIFICATION_EXPIRY"
    assert RecipientDeadlineKind.CONTRACT_EXPIRY.value == "CONTRACT_EXPIRY"
    assert RecipientDeadlineKind.PLAN_RENEWAL.value == "PLAN_RENEWAL"
    assert set(RecipientDeadlineKind) == {
        RecipientDeadlineKind.CERTIFICATION_EXPIRY,
        RecipientDeadlineKind.CONTRACT_EXPIRY,
        RecipientDeadlineKind.PLAN_RENEWAL,
    }


def test_app_main_exposes_deadlines_get_route() -> None:
    paths = app.openapi().get("paths", {})
    assert "/api/v1/recipients/deadlines" in paths
    assert "get" in paths["/api/v1/recipients/deadlines"]
