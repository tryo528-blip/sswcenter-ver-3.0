from __future__ import annotations

import inspect
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_staff_service,
    require_staff_manage,
    require_staff_view,
)
from app.core.auth import CurrentAccount
from app.domains.staff.schemas import (
    StaffQuarterlyConsultationListResponse,
    StaffQuarterlyConsultationResponse,
)
from app.main import app

COLLECTION_PATH = "/api/v1/staff/{staff_id}/quarterly-consultations"
ITEM_PATH = f"{COLLECTION_PATH}/{{consultation_id}}"


class FakeStaffService:
    def __init__(self) -> None:
        self.created: tuple[int, object, CurrentAccount] | None = None
        self.updated: tuple[int, int, object, CurrentAccount] | None = None

    @staticmethod
    def _response(*, completed: bool, row_version: int) -> StaffQuarterlyConsultationResponse:
        now = datetime(2026, 8, 13, tzinfo=UTC)
        return StaffQuarterlyConsultationResponse(
            id=17,
            staff_id=3,
            calendar_year=2026,
            quarter_no=3,
            completed=completed,
            created_by_account_id=1,
            created_at_utc=now,
            updated_by_account_id=1,
            updated_at_utc=now,
            row_version=row_version,
        )

    def list_quarterly_consultations(self, staff_id: int) -> StaffQuarterlyConsultationListResponse:
        assert staff_id == 3
        return StaffQuarterlyConsultationListResponse(
            items=[self._response(completed=False, row_version=1)]
        )

    def create_quarterly_consultation(
        self, staff_id: int, payload: object, current_account: CurrentAccount
    ) -> StaffQuarterlyConsultationResponse:
        self.created = (staff_id, payload, current_account)
        return self._response(completed=False, row_version=1)

    def update_quarterly_consultation(
        self,
        staff_id: int,
        consultation_id: int,
        payload: object,
        current_account: CurrentAccount,
    ) -> StaffQuarterlyConsultationResponse:
        self.updated = (staff_id, consultation_id, payload, current_account)
        return self._response(completed=True, row_version=2)


@pytest.fixture()
def client_and_service() -> Iterator[tuple[TestClient, FakeStaffService]]:
    account = CurrentAccount(1, "W1 staff test", "ADMIN")
    service = FakeStaffService()
    app.dependency_overrides[require_staff_view] = lambda: account
    app.dependency_overrides[require_staff_manage] = lambda: account
    app.dependency_overrides[get_staff_service] = lambda: service
    try:
        yield TestClient(app), service
    finally:
        app.dependency_overrides.clear()


def test_quarterly_routes_accept_boolean_toggle_contract(
    client_and_service: tuple[TestClient, FakeStaffService],
) -> None:
    client, service = client_and_service
    listed = client.get(COLLECTION_PATH.format(staff_id=3))
    assert listed.status_code == 200
    assert listed.json()["items"][0]["completed"] is False

    created = client.post(
        COLLECTION_PATH.format(staff_id=3),
        json={"calendar_year": 2026, "quarter_no": 3, "completed": False},
    )
    assert created.status_code == 201
    assert service.created is not None

    updated = client.patch(
        ITEM_PATH.format(staff_id=3, consultation_id=17),
        json={"completed": True, "expected_row_version": 1},
    )
    assert updated.status_code == 200
    assert updated.json()["completed"] is True
    assert updated.json()["row_version"] == 2
    assert service.updated is not None


def test_quarterly_routes_reject_removed_status_and_detail_fields(
    client_and_service: tuple[TestClient, FakeStaffService],
) -> None:
    client, _service = client_and_service
    response = client.post(
        COLLECTION_PATH.format(staff_id=3),
        json={
            "calendar_year": 2026,
            "quarter_no": 3,
            "completed": True,
            "status": "COMPLETE",
            "counseling_date": "2026-08-13",
            "content": "removed",
            "incomplete_reason_text": "removed",
            "exempt_reason_text": "removed",
        },
    )
    assert response.status_code == 422


def test_staff_manage_dependency_still_requires_csrf() -> None:
    source = inspect.getsource(require_staff_manage)
    assert "CsrfAccountDependency" in source
