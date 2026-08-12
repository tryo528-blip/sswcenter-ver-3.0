from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any, NoReturn

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_staff_service,
    require_staff_manage,
    require_staff_view,
)
from app.core.auth import CurrentAccount
from app.domains.staff.schemas import (
    EmploymentStatus,
    SexCode,
    StaffCreateResponse,
    StaffDetailResponse,
    StaffEmploymentResponse,
    StaffListResponse,
    StaffResponse,
)
from app.main import app


def build_synthetic_payload() -> dict[str, object]:
    birth_prefix = "90010" + "1"
    gender_digit = "1"
    sequence = "1234" + "56"
    return {
        "name": "홍길동",
        "birth_date": "1990-01-01",
        "sex_code": "MALE",
        "resident_number": f"{birth_prefix}-{gender_digit}{sequence}",
        "phone": "010-1234-5678",
        "address": "서울특별시 강남구 테헤란로 123",
        "display_name": "홍길동 요양보호사",
        "memo": "최초 생성 테스트",
        "initial_employment": {"start_date": "2026-01-01"},
    }


def _employment() -> StaffEmploymentResponse:
    return StaffEmploymentResponse(
        id=11,
        staff_id=7,
        employment_no=1,
        staff_no="2026-001",
        start_date=date(2026, 1, 1),
        end_date=None,
        end_reason_code=None,
        status=EmploymentStatus.ACTIVE,
        row_version=1,
    )


def _staff_detail() -> StaffDetailResponse:
    return StaffDetailResponse(
        id=7,
        name="홍길동",
        birth_date=date(1990, 1, 1),
        sex_code=SexCode.MALE,
        phone="010-1234-5678",
        address="서울특별시 강남구 테헤란로 123",
        display_name="홍길동 요양보호사",
        memo="최초 생성 테스트",
        resident_number_masked="900101-*******",
        row_version=1,
        current_employment=_employment(),
        current_positions=[],
        current_operational_roles=[],
        employments=[_employment()],
        positions=[],
        operational_roles=[],
    )


class FakeStaffService:
    def __init__(self) -> None:
        self.replacement_payload: Any = None

    def create_staff(
        self,
        payload: object,
        current_account: CurrentAccount,
    ) -> StaffCreateResponse:
        del payload, current_account
        return StaffCreateResponse(**_staff_detail().model_dump())

    def list_staff(
        self,
        *,
        search: str | None,
        page: int,
        page_size: int,
    ) -> StaffListResponse:
        del search
        detail = _staff_detail()
        item = StaffResponse(
            **detail.model_dump(exclude={"employments", "positions", "operational_roles"})
        )
        return StaffListResponse(items=[item], total=1, page=page, page_size=page_size)

    def get_staff_detail(self, staff_id: int) -> StaffDetailResponse:
        assert staff_id == 7
        return _staff_detail()

    def replace_employment(
        self,
        staff_id: int,
        employment_id: int,
        payload: Any,
        current_account: CurrentAccount,
    ) -> StaffEmploymentResponse:
        assert staff_id == 7
        assert employment_id == 11
        assert current_account.id == 2
        self.replacement_payload = payload
        return _employment()


class BrokenStaffService:
    def list_staff(self, *, search: str | None, page: int, page_size: int) -> StaffListResponse:
        del search, page, page_size
        raise RuntimeError("unexpected synthetic service failure")

    def reveal_sensitive_identity(
        self,
        staff_id: int,
        current_pin: str,
        current_account: CurrentAccount,
    ) -> NoReturn:
        del staff_id, current_pin, current_account
        raise RuntimeError("unexpected synthetic reveal failure")


def _raise_http(status_code: int, code: str) -> NoReturn:
    raise HTTPException(status_code=status_code, detail={"code": code})


@pytest.fixture(autouse=True)
def reset_dependency_overrides() -> Iterator[None]:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_w1a_staff_api_route_surface() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/staff" in paths, "W1A_API_ROUTE_MISSING: /api/v1/staff route is not registered"


def test_w1a_staff_api_service_seam() -> None:
    import app.api.dependencies as dependencies

    assert hasattr(dependencies, "get_staff_service"), (
        "W1A_API_SERVICE_SEAM_MISSING: get_staff_service dependency seam is missing"
    )


def test_staff_create_permissions_and_contract() -> None:
    client = TestClient(app)
    payload = build_synthetic_payload()
    app.dependency_overrides[get_staff_service] = lambda: FakeStaffService()

    app.dependency_overrides[require_staff_manage] = lambda: _raise_http(
        401,
        "session_required",
    )
    unauthenticated = client.post("/api/v1/staff", json=payload)
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "SESSION_REQUIRED"

    app.dependency_overrides[require_staff_manage] = lambda: _raise_http(
        403,
        "PERMISSION_REQUIRED",
    )
    viewer = client.post("/api/v1/staff", json=payload)
    assert viewer.status_code == 403
    assert viewer.json()["error"]["code"] == "PERMISSION_REQUIRED"

    app.dependency_overrides[require_staff_manage] = lambda: CurrentAccount(
        id=2,
        display_name="Manager",
        role_code="USER",
    )
    manager = client.post("/api/v1/staff", json=payload)
    assert manager.status_code == 201
    assert manager.json()["resident_number_masked"] == "900101-*******"
    assert "resident_number" not in manager.json()


def test_staff_create_rejects_test_sex_code() -> None:
    client = TestClient(app)
    payload = build_synthetic_payload()
    payload["sex_code"] = "TEST"
    app.dependency_overrides[get_staff_service] = lambda: FakeStaffService()
    app.dependency_overrides[require_staff_manage] = lambda: CurrentAccount(
        id=2,
        display_name="Manager",
        role_code="USER",
    )

    response = client.post("/api/v1/staff", json=payload)

    assert response.status_code == 422, "I1_CREATE_TEST_SEX_CODE_ACCEPTED"


def test_staff_list_and_detail_permissions_and_contract() -> None:
    client = TestClient(app)
    app.dependency_overrides[get_staff_service] = lambda: FakeStaffService()

    app.dependency_overrides[require_staff_view] = lambda: _raise_http(
        401,
        "session_required",
    )
    unauthenticated = client.get("/api/v1/staff")
    assert unauthenticated.status_code == 401

    app.dependency_overrides[require_staff_view] = lambda: CurrentAccount(
        id=3,
        display_name="Viewer",
        role_code="USER",
    )
    listed = client.get("/api/v1/staff")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["resident_number_masked"] == "900101-*******"

    detail = client.get("/api/v1/staff/7")
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == 7
    assert "resident_number" not in body
    assert "phone_normalized" not in body


def test_staff_replacement_omission_is_422_and_null_is_explicit_removal() -> None:
    client = TestClient(app)
    fake_service = FakeStaffService()
    app.dependency_overrides[get_staff_service] = lambda: fake_service
    app.dependency_overrides[require_staff_manage] = lambda: CurrentAccount(
        id=2,
        display_name="Manager",
        role_code="USER",
    )
    path = "/api/v1/staff/7/employments/11/replacements"
    common = {
        "expected_employment_row_version": 1,
        "start_date": "2026-01-01",
        "operational_role_replacements": [],
    }

    omitted = client.post(
        path,
        json={
            **common,
            "position_replacements": [{"old_period_id": 21, "expected_row_version": 1}],
        },
    )
    assert omitted.status_code == 422
    assert omitted.json()["error"]["code"] == "VALIDATION_ERROR"
    assert fake_service.replacement_payload is None

    explicit_null = client.post(
        path,
        json={
            **common,
            "position_replacements": [
                {
                    "old_period_id": 21,
                    "expected_row_version": 1,
                    "replacement": None,
                }
            ],
        },
    )
    assert explicit_null.status_code == 201, explicit_null.json()
    assert fake_service.replacement_payload is not None
    assert fake_service.replacement_payload.position_replacements[0].replacement is None


def test_unexpected_api_error_is_safe_envelope_and_reveal_is_no_store() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_staff_service] = lambda: BrokenStaffService()
    app.dependency_overrides[require_staff_view] = lambda: CurrentAccount(
        id=3,
        display_name="Viewer",
        role_code="USER",
    )
    app.dependency_overrides[require_staff_manage] = lambda: CurrentAccount(
        id=3,
        display_name="Manager",
        role_code="USER",
    )

    listed = client.get("/api/v1/staff", headers={"X-Request-ID": "not-a-uuid"})
    assert listed.status_code == 500
    assert listed.json()["error"]["code"] == "UNEXPECTED_SERVER_ERROR"
    assert listed.json()["request_id"]
    assert "synthetic service failure" not in listed.text

    revealed = client.post(
        "/api/v1/staff/7/sensitive-identity/reveal",
        json={"current_pin": "123456"},
    )
    assert revealed.status_code == 500
    assert revealed.headers["Cache-Control"] == "no-store"
    assert revealed.json()["error"]["code"] == "UNEXPECTED_SERVER_ERROR"
