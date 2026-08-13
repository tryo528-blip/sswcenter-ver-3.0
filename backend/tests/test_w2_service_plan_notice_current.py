from __future__ import annotations

import inspect
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domains.recipient import service_plan_notice
from app.domains.recipient.detail_batch import RecipientDetailBatchRequest
from app.domains.recipient.repository import RecipientRepository
from app.domains.recipient.service import RecipientService
from app.domains.w2.schemas import (
    ServicePlanNoticeCreateRequest,
    ServicePlanNoticeReplaceRequest,
)
from app.domains.w2.service import W2Service
from app.main import app

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "backend" / "alembic" / "versions" / (
    "20260813_0024_w2_service_plan_notice_current.py"
)


def test_default_end_and_writing_deadline_contract() -> None:
    assert service_plan_notice.default_end_date(date(2026, 3, 5)) == date(2026, 12, 31)
    assert service_plan_notice.default_end_date(date(2026, 8, 5)) == date(2027, 6, 30)
    assert service_plan_notice.deadline_date(date(2026, 8, 31)) == date(2027, 2, 28)
    assert service_plan_notice.deadline_date(
        date(2026, 8, 31),
        contract_end_date=date(2026, 12, 31),
        certification_end_date=date(2027, 1, 31),
    ) == date(2026, 12, 31)
    assert service_plan_notice.d45_date(date(2026, 1, 1)) == date(2026, 5, 17)
    assert not hasattr(service_plan_notice, "d100_date")


def test_service_plan_requests_are_narrow_and_date_ordered() -> None:
    request = ServicePlanNoticeCreateRequest(
        recipient_contract_id=4,
        notification_date=date(2026, 8, 13),
        applied_start_date=date(2026, 8, 14),
    )
    assert request.applied_end_date is None

    with pytest.raises(ValidationError):
        ServicePlanNoticeCreateRequest(
            recipient_contract_id=4,
            notification_date=date(2026, 8, 13),
            applied_start_date=date(2026, 9, 1),
            applied_end_date=date(2026, 8, 31),
        )
    with pytest.raises(ValidationError):
        ServicePlanNoticeReplaceRequest(
            recipient_contract_id=4,
            notification_date=date(2026, 8, 13),
            applied_start_date=date(2026, 8, 14),
            expected_row_version=1,
            status="COMPLETE",
        )


def test_0024_is_separate_from_the_read_only_0018_ledger() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'down_revision: str | None = "20260813_0023_w2_core_ledgers"' in source
    assert '"w2_service_plan_notice"' in source
    assert "recipient_service_plan_notice" in source  # historical ledger named in warning
    assert "INSERT INTO erp.w2_service_plan_notice" not in source
    assert "SELECT * FROM erp.recipient_service_plan_notice" not in source
    assert "DEFERRABLE INITIALLY DEFERRED" in source
    assert "W2_SERVICE_PLAN_OUTSIDE_CONTRACT" in source
    assert "W2_SERVICE_PLAN_OUTSIDE_CERTIFICATION" in source
    assert "RECIPIENT_PLAN_NOTIFICATION_READ_ONLY" in source
    assert "tr_recipient_plan_notification_read_only" in source
    assert "BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE" in source
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE" in source
    downgrade = source.split("def downgrade() -> None:", maxsplit=1)[1]
    assert "raise RuntimeError" in downgrade
    assert "restore a verified pre-upgrade backup" in downgrade
    assert "drop_table" not in downgrade
    assert "DELETE FROM" not in downgrade


def test_service_plan_api_is_business_scoped_and_cards_have_no_public_create() -> None:
    document = app.openapi()
    paths = document["paths"]
    collection = "/api/v1/recipients/{recipient_id}/service-plan-notices"
    item = "/api/v1/recipients/{recipient_id}/service-plan-notices/{notice_id}"
    assert set(paths[collection]) >= {"get", "post"}
    assert set(paths[item]) >= {"put"}
    assert not any("/plan-notifications" in path for path in paths)
    assert {
        path for path in paths if "plan-notice" in path or "plan-notification" in path
    } == {collection, item}

    schemas = document["components"]["schemas"]
    assert {
        "PlanNotificationCreateRequest",
        "PlanNotificationResponse",
        "PlanNotificationListResponse",
    }.isdisjoint(schemas)
    detail_properties = schemas["RecipientDetailBatchRequest"]["properties"]
    assert "plan_notification" not in detail_properties

    with pytest.raises(ValidationError):
        RecipientDetailBatchRequest.model_validate(
            {"plan_notification": {"notified_date": "2026-08-13"}}
        )
    for owner in (RecipientService, RecipientRepository):
        assert not hasattr(owner, "create_plan_notification")
        assert not hasattr(owner, "list_plan_notifications")
        assert not hasattr(owner, "invalidate_plan_notification")
    assert set(paths["/api/v1/official-work-cards"]) == {"get"}
    assert set(paths["/api/v1/official-work-cards/{card_id}/close"]) == {"post"}


def test_plan_card_bridge_is_internal_d45_only() -> None:
    source = inspect.getsource(W2Service.record_service_plan_notice_card_source)
    assert "plan_notice_source" in source
    assert "source.due_date > as_of_date" in source
    assert "d100" not in source.lower()
    assert "record_service_plan_notice_card_source" not in str(app.openapi()["paths"])
