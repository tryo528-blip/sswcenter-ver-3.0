"""Pure contract tests for the current recipient deadline read API."""

import inspect

from app.domains.recipient.schemas import RecipientDeadlineKind
from app.domains.recipient.service import RecipientService
from app.main import app


def test_plan_deadline_uses_current_w2_notice_and_parent_caps() -> None:
    source = inspect.getsource(RecipientService.list_recipient_deadlines)
    assert "W2ServicePlanNotice" in source
    assert "deadline_date" in source
    assert "contract_end_date" in source
    assert "certification.end_date" in source
    assert "RecipientPlanNotification" not in source
    assert "_plan_renewal_due_date" not in source


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
