from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_current_account, get_db_session
from app.core.auth import CurrentAccount
from app.core.security import (
    csrf_token_signature,
    generate_csrf_token,
    generate_session_token,
)
from app.core.settings import get_settings
from app.db.session import build_session_factory, create_postgres_engine
from app.main import app

DATABASE_URL = os.environ.get("SSWCENTER_DATABASE_URL")
COURSE_PATH = "/api/v1/staff/training-courses"
ONBOARDING_PATH = "/api/v1/staff/{staff_id}/onboarding-trainings"
ONBOARDING_ITEM_PATH = f"{ONBOARDING_PATH}/{{training_id}}"
PERIODIC_PATH = "/api/v1/staff/{staff_id}/periodic-trainings"
PERIODIC_ITEM_PATH = f"{PERIODIC_PATH}/{{training_id}}"

EXPECTED_ROUTE_TEMPLATES = {
    COURSE_PATH,
    ONBOARDING_PATH,
    ONBOARDING_ITEM_PATH,
    PERIODIC_PATH,
    PERIODIC_ITEM_PATH,
    f"{PERIODIC_PATH}/{{training_id}}/invalidate",
}
PERIODIC_PAYLOAD = {
    "course_code": "ELDER_RIGHTS",
    "period_key": "2026-H1",
    "completed": False,
    "expected_row_version": 1,
}


@dataclass(frozen=True)
class AccountCase:
    account: CurrentAccount
    staff_id: int
    permission: str | None


@pytest.fixture(scope="module")
def database_factory() -> Iterator[sessionmaker[Session]]:
    if not DATABASE_URL:
        pytest.skip("W1A_VS3_API_PREREQ_MISSING: SSWCENTER_DATABASE_URL")
    engine = create_postgres_engine(DATABASE_URL)
    factory = build_session_factory(engine)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        yield factory
    except Exception:
        pytest.fail("W1A_VS3_HARNESS_FAILURE: API database setup failed", pytrace=False)
    finally:
        engine.dispose()


def _require_vs3_routes() -> None:
    try:
        paths = set(app.openapi().get("paths", {}))
    except Exception:
        pytest.fail(
            "W1A_VS3_API_MISSING: OpenAPI route surface could not be inspected",
            pytrace=False,
        )
    if not EXPECTED_ROUTE_TEMPLATES.issubset(paths):
        pytest.fail("W1A_VS3_API_MISSING: training routes are absent", pytrace=False)


def _make_account_cases(factory: sessionmaker[Session]) -> dict[str, AccountCase]:
    token = uuid4().hex
    cases: dict[str, AccountCase] = {}
    with factory.begin() as connection:
        for label, role, permission in (
            ("admin", "ADMIN", None),
            ("view", "USER", "STAFF_VIEW"),
            ("manage", "USER", "STAFF_MANAGE"),
            ("user", "USER", None),
        ):
            staff_id = int(
                connection.execute(
                    text(
                        """
                        INSERT INTO erp.staff
                            (name, birth_date, sex_code, phone, phone_normalized,
                             address, display_name, memo)
                        VALUES (:name, DATE '1990-01-01', 'TEST', NULL, NULL,
                                NULL, :display_name, 'VS3 API synthetic fixture')
                        RETURNING id
                        """
                    ),
                    {
                        "name": f"VS3 API synthetic {label} {token}",
                        "display_name": f"VS3 API {label}",
                    },
                ).scalar_one()
            )
            account_id = int(
                connection.execute(
                    text(
                        """
                        INSERT INTO erp.user_account
                            (staff_id, account_code, display_name, role_code,
                             pin_hash, pin_lookup_hmac, pin_key_version)
                        VALUES (:staff_id, :account_code, :display_name, :role_code,
                                'VS3 synthetic hash', :pin_lookup_hmac, 1)
                        RETURNING id
                        """
                    ),
                    {
                        "staff_id": staff_id,
                        "account_code": f"vs3-api-{label}-{token}",
                        "display_name": f"VS3 API {label}",
                        "role_code": role,
                        "pin_lookup_hmac": f"vs3-api-{label}-{token}".encode(),
                    },
                ).scalar_one()
            )
            if permission is not None:
                connection.execute(
                    text(
                        """
                        INSERT INTO erp.permission_definition
                            (permission_code, name, description, active)
                        VALUES (:permission, :permission, 'VS3 synthetic permission', TRUE)
                        ON CONFLICT (permission_code) DO NOTHING
                        """
                    ),
                    {"permission": permission},
                )
            cases[label] = AccountCase(
                account=CurrentAccount(account_id, f"VS3 API {label}", role),
                staff_id=staff_id,
                permission=permission,
            )
        for label in ("view", "manage"):
            case = cases[label]
            assert case.permission is not None
            connection.execute(
                text(
                    """
                    INSERT INTO erp.account_permission
                        (account_id, permission_code, granted_by_account_id)
                    VALUES (:account_id, :permission, :granted_by)
                    """
                ),
                {
                    "account_id": case.account.id,
                    "permission": case.permission,
                    "granted_by": cases["admin"].account.id,
                },
            )
    return cases


def _install_real_dependencies(factory: sessionmaker[Session], account: CurrentAccount) -> None:
    def db_override() -> Iterator[Session]:
        database_session = factory()
        try:
            yield database_session
        finally:
            database_session.rollback()
            database_session.close()

    app.dependency_overrides[get_current_account] = lambda account=account: account
    app.dependency_overrides[get_db_session] = db_override


def _csrf_headers(client: TestClient) -> dict[str, str]:
    settings = get_settings()
    session_token = generate_session_token()
    csrf_token = generate_csrf_token()
    signature = csrf_token_signature(
        session_token,
        csrf_token,
        settings.secret_value("csrf_signing_key"),
    )
    csrf_cookie = f"{csrf_token}.{signature}"
    client.cookies.set(settings.session_cookie_name, session_token)
    client.cookies.set(settings.csrf_cookie_name, csrf_cookie)
    return {settings.csrf_header_name: csrf_cookie}


def _expect_success(response: Any, marker: str) -> dict[str, object]:
    status_code = response.status_code
    if not 200 <= status_code < 300:
        pytest.fail(marker, pytrace=False)
    body = response.json()
    if not isinstance(body, dict):
        pytest.fail(f"{marker}: response body is not an object", pytrace=False)
    return body


@pytest.fixture(autouse=True)
def reset_dependency_overrides() -> Iterator[None]:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_vs3_actual_acl_matrix_for_admin_view_manage_and_user(
    database_factory: sessionmaker[Session],
) -> None:
    _require_vs3_routes()
    cases = _make_account_cases(database_factory)
    client = TestClient(app, raise_server_exceptions=False)

    for label in ("admin", "view", "manage"):
        _install_real_dependencies(database_factory, cases[label].account)
        read_response = client.get(COURSE_PATH)
        if read_response.status_code // 100 != 2:
            pytest.fail(f"W1A_VS3_API_MISSING: {label} GET is not allowed", pytrace=False)

    _install_real_dependencies(database_factory, cases["user"].account)
    denied_get = client.get(COURSE_PATH)
    if denied_get.status_code != 403:
        pytest.fail("W1A_VS3_API_MISSING: ungranted USER GET is not denied", pytrace=False)

    for label, period_key in (("admin", "2026-H1"), ("manage", "2026-H2")):
        _install_real_dependencies(database_factory, cases[label].account)
        headers = _csrf_headers(client)
        payload = {**PERIODIC_PAYLOAD, "period_key": period_key}
        response = client.post(
            PERIODIC_PATH.format(staff_id=cases[label].staff_id),
            json=payload,
            headers=headers,
        )
        if response.status_code // 100 != 2:
            pytest.fail(f"W1A_VS3_API_MISSING: {label} POST is not allowed", pytrace=False)

    _install_real_dependencies(database_factory, cases["view"].account)
    denied_view_write = client.post(
        PERIODIC_PATH.format(staff_id=cases["view"].staff_id),
        json={**PERIODIC_PAYLOAD, "period_key": "2027-H1"},
        headers=_csrf_headers(client),
    )
    if denied_view_write.status_code != 403:
        pytest.fail("W1A_VS3_API_MISSING: STAFF_VIEW write is not denied", pytrace=False)

    _install_real_dependencies(database_factory, cases["user"].account)
    denied_user_write = client.post(
        PERIODIC_PATH.format(staff_id=cases["user"].staff_id),
        json={**PERIODIC_PAYLOAD, "period_key": "2027-H2"},
        headers=_csrf_headers(client),
    )
    if denied_user_write.status_code != 403:
        pytest.fail("W1A_VS3_API_MISSING: ungranted USER write is not denied", pytrace=False)


def test_vs3_real_service_csrf_row_version_and_stable_error_requests(
    database_factory: sessionmaker[Session],
) -> None:
    _require_vs3_routes()
    cases = _make_account_cases(database_factory)
    _install_real_dependencies(database_factory, cases["manage"].account)
    client = TestClient(app, raise_server_exceptions=False)
    headers = _csrf_headers(client)
    staff_id = cases["manage"].staff_id

    created = client.post(
        PERIODIC_PATH.format(staff_id=staff_id),
        json=PERIODIC_PAYLOAD,
        headers=headers,
    )
    body = _expect_success(
        created,
        "W1A_VS3_API_MISSING: real periodic create path is not available",
    )
    training_id = body.get("id")
    if not isinstance(training_id, int):
        pytest.fail("W1A_VS3_API_MISSING: periodic response has no id", pytrace=False)

    completed = client.patch(
        PERIODIC_ITEM_PATH.format(staff_id=staff_id, training_id=training_id),
        json={"completed": True, "expected_row_version": 1},
        headers=headers,
    )
    _expect_success(
        completed,
        "W1A_VS3_API_MISSING: real completion update path is not available",
    )
    stale = client.patch(
        PERIODIC_ITEM_PATH.format(staff_id=staff_id, training_id=training_id),
        json={"completed": False, "expected_row_version": 1},
        headers=headers,
    )
    if stale.status_code != 409 or "ROW_VERSION_CONFLICT" not in stale.text:
        pytest.fail("W1A_VS3_API_MISSING: stale row version is not stable 409", pytrace=False)

    missing_period = client.post(
        PERIODIC_PATH.format(staff_id=staff_id),
        json={key: value for key, value in PERIODIC_PAYLOAD.items() if key != "period_key"},
        headers=headers,
    )
    if missing_period.status_code != 422:
        pytest.fail("W1A_VS3_API_MISSING: missing period is not field-level 422", pytrace=False)

    invalid_cycle = client.post(
        PERIODIC_PATH.format(staff_id=staff_id),
        json={**PERIODIC_PAYLOAD, "course_code": "NEW_HIRE_ORIENTATION", "period_key": "2026"},
        headers=headers,
    )
    if invalid_cycle.status_code not in {409, 422}:
        pytest.fail(
            "W1A_VS3_API_MISSING: invalid cycle/period is not stable 409/422", pytrace=False
        )

    wrong_staff = client.patch(
        PERIODIC_ITEM_PATH.format(staff_id=cases["user"].staff_id, training_id=training_id),
        json={"completed": False, "expected_row_version": 2},
        headers=headers,
    )
    if wrong_staff.status_code not in {409, 422}:
        pytest.fail("W1A_VS3_API_MISSING: other-staff row is not rejected", pytrace=False)


def test_vs3_real_csrf_is_required_for_write_without_override(
    database_factory: sessionmaker[Session],
) -> None:
    _require_vs3_routes()
    cases = _make_account_cases(database_factory)
    _install_real_dependencies(database_factory, cases["manage"].account)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        PERIODIC_PATH.format(staff_id=cases["manage"].staff_id),
        json=PERIODIC_PAYLOAD,
    )
    if response.status_code != 403 or "csrf" not in response.text.lower():
        pytest.fail("W1A_VS3_API_MISSING: missing CSRF is not rejected", pytrace=False)
