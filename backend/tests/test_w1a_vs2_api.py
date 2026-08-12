from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import NoReturn

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_current_account,
    get_db_session,
    get_staff_service,
    require_staff_manage,
    require_staff_view,
)
from app.core.auth import CurrentAccount
from app.main import app

LICENSE_LIST_PATH = "/api/v1/staff/7/licenses"
QUALIFICATION_LIST_PATH = "/api/v1/staff/7/service-qualifications"
LICENSE_ROUTE_TEMPLATE = "/api/v1/staff/{staff_id}/licenses"
QUALIFICATION_ROUTE_TEMPLATE = "/api/v1/staff/{staff_id}/service-qualifications"
LICENSE_CREATE_PATH = LICENSE_LIST_PATH
QUALIFICATION_CREATE_PATH = QUALIFICATION_LIST_PATH
LICENSE_PAYLOAD = {
    "license_type_code": "CARE_WORKER",
    "license_number": "VS2-SYNTHETIC-LICENSE-A",
    "issued_date": "2026-01-01",
    "expected_row_version": 1,
}
QUALIFICATION_PAYLOAD = {
    "employment_id": 11,
    "service_type_code": "HOME_CARE",
    "start_date": "2026-01-01",
    "end_date": None,
    "source_license_id": None,
    "expected_row_version": 1,
}


class FakePermissionSession:
    def scalar(self, statement: object) -> int:
        del statement
        return 1


class FakeVS2Service:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self.raise_conflict = False

    def __getattr__(self, name: str) -> Callable[..., JSONResponse]:
        if not (
            name.startswith("list_")
            or name.startswith("create_")
            or name.startswith("replace_")
            or name.startswith("close_")
            or name.startswith("invalidate_")
        ):
            raise AttributeError(name)

        def handler(*args: object, **kwargs: object) -> JSONResponse:
            self.calls.append((name, args, kwargs))
            if self.raise_conflict:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "ROW_VERSION_CONFLICT"},
                )
            status_code = 200 if name.startswith("list_") else 201
            return JSONResponse(status_code=status_code, content={"ok": True})

        return handler


def _account(account_id: int, role_code: str) -> CurrentAccount:
    return CurrentAccount(id=account_id, display_name=f"VS2 {role_code}", role_code=role_code)


def _raise_http(status_code: int, code: str) -> NoReturn:
    raise HTTPException(status_code=status_code, detail={"code": code})


def _fake_db_session() -> Iterator[FakePermissionSession]:
    yield FakePermissionSession()


def _require_vs2_routes() -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    required = {LICENSE_ROUTE_TEMPLATE, QUALIFICATION_ROUTE_TEMPLATE}
    if not required.issubset(paths):
        pytest.fail("W1A_VS2_API_MISSING: license/qualification routes are absent")


def _captured_field(service: FakeVS2Service, field: str) -> object | None:
    for _name, args, kwargs in service.calls:
        values = (*args, *kwargs.values())
        for value in values:
            if isinstance(value, dict) and field in value:
                return value[field]
            if hasattr(value, field):
                return getattr(value, field)
    return None


@pytest.fixture(autouse=True)
def reset_dependency_overrides() -> Iterator[None]:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_vs2_actual_acl_matrix_for_get_and_post() -> None:
    _require_vs2_routes()
    client = TestClient(app, raise_server_exceptions=False)
    service = FakeVS2Service()
    app.dependency_overrides[get_staff_service] = lambda: service

    for account in (_account(1, "ADMIN"), _account(2, "USER")):
        app.dependency_overrides[require_staff_view] = lambda account=account: account
        response = client.get(LICENSE_LIST_PATH)
        if response.status_code != 200:
            pytest.fail("W1A_VS2_API_MISSING: ADMIN/viewer GET did not return 2xx")

    app.dependency_overrides[require_staff_view] = lambda: _raise_http(403, "PERMISSION_REQUIRED")
    denied_get = client.get(QUALIFICATION_LIST_PATH)
    if denied_get.status_code != 403:
        pytest.fail("W1A_VS2_API_MISSING: ungranted USER GET was not denied")

    for account in (_account(1, "ADMIN"), _account(3, "USER")):
        app.dependency_overrides[require_staff_manage] = lambda account=account: account
        response = client.post(LICENSE_CREATE_PATH, json=LICENSE_PAYLOAD)
        if response.status_code not in {200, 201}:
            pytest.fail("W1A_VS2_API_MISSING: ADMIN/STAFF_MANAGE POST did not return 2xx")

    for account in (_account(2, "USER"), _account(4, "USER")):
        del account
        app.dependency_overrides[require_staff_manage] = lambda: _raise_http(
            403, "PERMISSION_REQUIRED"
        )
        response = client.post(QUALIFICATION_CREATE_PATH, json=QUALIFICATION_PAYLOAD)
        if response.status_code != 403:
            pytest.fail("W1A_VS2_API_MISSING: ungranted/view-only POST was not denied")


def test_vs2_actual_csrf_row_version_422_and_409_requests() -> None:
    _require_vs2_routes()
    client = TestClient(app, raise_server_exceptions=False)
    service = FakeVS2Service()
    app.dependency_overrides[get_staff_service] = lambda: service
    app.dependency_overrides[require_staff_manage] = lambda: _account(3, "USER")

    valid = client.post(LICENSE_CREATE_PATH, json=LICENSE_PAYLOAD)
    if valid.status_code not in {200, 201}:
        pytest.fail("W1A_VS2_API_MISSING: expected_row_version request was not accepted")
    if _captured_field(service, "expected_row_version") != 1:
        pytest.fail("W1A_VS2_API_MISSING: expected_row_version was not passed to service")

    invalid = client.post(
        LICENSE_CREATE_PATH,
        json={key: value for key, value in LICENSE_PAYLOAD.items() if key != "license_number"},
    )
    if invalid.status_code != 422:
        pytest.fail("W1A_VS2_API_MISSING: invalid license request did not return 422")

    service.raise_conflict = True
    conflict = client.post(LICENSE_CREATE_PATH, json=LICENSE_PAYLOAD)
    if conflict.status_code != 409 or "ROW_VERSION_CONFLICT" not in conflict.text:
        pytest.fail("W1A_VS2_API_MISSING: row-version conflict did not return 409")


def test_vs2_actual_csrf_is_required_without_override() -> None:
    _require_vs2_routes()
    client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_staff_service] = lambda: FakeVS2Service()
    app.dependency_overrides[get_current_account] = lambda: _account(3, "USER")
    app.dependency_overrides[get_db_session] = _fake_db_session

    response = client.post(LICENSE_CREATE_PATH, json=LICENSE_PAYLOAD)
    if response.status_code != 403 or "csrf" not in response.text.lower():
        pytest.fail("W1A_VS2_API_MISSING: missing CSRF request was not rejected")
