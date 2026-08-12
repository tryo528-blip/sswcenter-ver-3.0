from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_current_account, get_db_session
from app.core.auth import CurrentAccount
from app.core.security import csrf_token_signature, generate_csrf_token, generate_session_token
from app.core.settings import get_settings
from app.db.session import build_session_factory, create_postgres_engine
from app.main import app

DATABASE_URL = os.environ.get("SSWCENTER_DATABASE_URL")
FACT_PATH = "/api/v1/staff/{staff_id}/health-checks"
FACT_ITEM_PATH = f"{FACT_PATH}/{{health_check_id}}"
REQUIREMENT_PATH = "/api/v1/staff/{staff_id}/health-check-requirements"
REQUIREMENT_ITEM_PATH = f"{REQUIREMENT_PATH}/{{requirement_id}}"
REQUIRED_PATHS = {
    FACT_PATH,
    FACT_ITEM_PATH,
    REQUIREMENT_PATH,
    REQUIREMENT_ITEM_PATH,
    f"{FACT_ITEM_PATH}/invalidate",
    f"{REQUIREMENT_ITEM_PATH}/invalidate",
}


@dataclass(frozen=True)
class AccountCase:
    account: CurrentAccount
    staff_id: int
    permission: str | None


@pytest.fixture(scope="module")
def database_factory() -> Iterator[sessionmaker[Session]]:
    if not DATABASE_URL:
        pytest.skip("isolated PostgreSQL harness is required")
    engine = create_postgres_engine(DATABASE_URL)
    factory = build_session_factory(engine)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        yield factory
    except Exception:
        pytest.fail("W1A_VS4_HARNESS_FAILURE: API database setup failed", pytrace=False)
    finally:
        engine.dispose()


def _require_routes() -> None:
    try:
        paths = set(app.openapi().get("paths", {}))
    except Exception:
        pytest.fail("W1A_VS4_API_HARNESS_FAILURE: route inspection failed", pytrace=False)
    if not REQUIRED_PATHS.issubset(paths):
        pytest.fail("W1A_VS4_API_MISSING: health fact/requirement routes are absent", pytrace=False)


def _make_cases(factory: sessionmaker[Session]) -> dict[str, AccountCase]:
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
                                NULL, :display_name, 'VS4 API synthetic fixture')
                        RETURNING id
                        """
                    ),
                    {
                        "name": f"VS4 API synthetic {label} {token}",
                        "display_name": f"VS4 API {label}",
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
                                'VS4 synthetic hash', :pin_lookup_hmac, 1)
                        RETURNING id
                        """
                    ),
                    {
                        "staff_id": staff_id,
                        "account_code": f"vs4-api-{label}-{token}",
                        "display_name": f"VS4 API {label}",
                        "role_code": role,
                        "pin_lookup_hmac": f"vs4-api-{label}-{token}".encode(),
                    },
                ).scalar_one()
            )
            if permission is not None:
                connection.execute(
                    text(
                        """
                        INSERT INTO erp.permission_definition
                            (permission_code, name, description, active)
                        VALUES (:permission, :permission, 'VS4 synthetic permission', TRUE)
                        ON CONFLICT (permission_code) DO NOTHING
                        """
                    ),
                    {"permission": permission},
                )
            cases[label] = AccountCase(
                CurrentAccount(account_id, f"VS4 {label}", role), staff_id, permission
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


def _install(factory: sessionmaker[Session], account: CurrentAccount) -> None:
    def db_override() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        finally:
            session.rollback()
            session.close()

    app.dependency_overrides[get_current_account] = lambda account=account: account
    app.dependency_overrides[get_db_session] = db_override


def _csrf_headers(client: TestClient) -> dict[str, str]:
    settings = get_settings()
    session_token = generate_session_token()
    csrf_token = generate_csrf_token()
    signature = csrf_token_signature(
        session_token, csrf_token, settings.secret_value("csrf_signing_key")
    )
    cookie = f"{csrf_token}.{signature}"
    client.cookies.set(settings.session_cookie_name, session_token)
    client.cookies.set(settings.csrf_cookie_name, cookie)
    return {settings.csrf_header_name: cookie}


@pytest.fixture(autouse=True)
def reset_overrides() -> Iterator[None]:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_vs4_actual_acl_matrix_csrf_and_separate_routes(
    database_factory: sessionmaker[Session],
) -> None:
    _require_routes()
    cases = _make_cases(database_factory)
    client = TestClient(app, raise_server_exceptions=False)
    for label in ("admin", "view", "manage"):
        _install(database_factory, cases[label].account)
        for path in (FACT_PATH, REQUIREMENT_PATH):
            response = client.get(path.format(staff_id=cases[label].staff_id))
            if response.status_code // 100 != 2:
                pytest.fail(f"W1A_VS4_API_MISSING: {label} read is not allowed", pytrace=False)
    _install(database_factory, cases["user"].account)
    for path in (FACT_PATH, REQUIREMENT_PATH):
        if client.get(path.format(staff_id=cases["user"].staff_id)).status_code != 403:
            pytest.fail("W1A_VS4_API_MISSING: ungranted USER read is not denied", pytrace=False)
    payload = {"check_date": "2026-07-28", "check_type_code": "GENERAL", "result_note": "synthetic"}
    for label in ("admin", "manage"):
        _install(database_factory, cases[label].account)
        response = client.post(
            FACT_PATH.format(staff_id=cases[label].staff_id),
            json=payload,
            headers=_csrf_headers(client),
        )
        if response.status_code // 100 != 2:
            pytest.fail(f"W1A_VS4_API_MISSING: {label} fact write is not allowed", pytrace=False)
    _install(database_factory, cases["view"].account)
    if (
        client.post(
            FACT_PATH.format(staff_id=cases["view"].staff_id),
            json=payload,
            headers=_csrf_headers(client),
        ).status_code
        != 403
    ):
        pytest.fail("W1A_VS4_API_MISSING: STAFF_VIEW write is not denied", pytrace=False)
    _install(database_factory, cases["user"].account)
    if (
        client.post(
            FACT_PATH.format(staff_id=cases["user"].staff_id),
            json=payload,
            headers=_csrf_headers(client),
        ).status_code
        != 403
    ):
        pytest.fail("W1A_VS4_API_MISSING: ungranted USER write is not denied", pytrace=False)
    _install(database_factory, cases["manage"].account)
    if (
        client.post(FACT_PATH.format(staff_id=cases["manage"].staff_id), json=payload).status_code
        != 403
    ):
        pytest.fail("W1A_VS4_API_MISSING: missing CSRF is not denied", pytrace=False)


def test_vs4_actual_validation_stale_row_and_other_staff_contract(
    database_factory: sessionmaker[Session],
) -> None:
    _require_routes()
    cases = _make_cases(database_factory)
    client = TestClient(app, raise_server_exceptions=False)
    _install(database_factory, cases["manage"].account)
    response = client.post(
        FACT_PATH.format(staff_id=cases["manage"].staff_id),
        json={"check_date": "2026-07-28", "check_type_code": "GENERAL"},
        headers=_csrf_headers(client),
    )
    if response.status_code // 100 != 2 or not isinstance(response.json().get("id"), int):
        pytest.fail("W1A_VS4_API_MISSING: real health fact create path is absent", pytrace=False)
    fact_id = response.json()["id"]
    item_path = FACT_ITEM_PATH.format(staff_id=cases["manage"].staff_id, health_check_id=fact_id)
    updated = client.patch(
        item_path,
        json={"check_date": "2026-07-28", "expected_row_version": 1},
        headers=_csrf_headers(client),
    )
    if updated.status_code // 100 != 2:
        pytest.fail("W1A_VS4_API_MISSING: health fact update path is absent", pytrace=False)
    stale = client.patch(
        item_path,
        json={"check_date": "2026-07-29", "expected_row_version": 1},
        headers=_csrf_headers(client),
    )
    if stale.status_code != 409 or "ROW_VERSION_CONFLICT" not in stale.text:
        pytest.fail("W1A_VS4_API_MISSING: stale health fact is not stable 409", pytrace=False)
    invalid = client.post(
        FACT_PATH.format(staff_id=cases["manage"].staff_id),
        json={"check_type_code": "GENERAL"},
        headers=_csrf_headers(client),
    )
    if invalid.status_code != 422:
        pytest.fail(
            "W1A_VS4_API_MISSING: invalid health fact is not field-level 422", pytrace=False
        )
    other_staff = client.patch(
        FACT_ITEM_PATH.format(staff_id=cases["user"].staff_id, health_check_id=fact_id),
        json={"check_date": "2026-07-30", "expected_row_version": 2},
        headers=_csrf_headers(client),
    )
    if other_staff.status_code not in {409, 422}:
        pytest.fail("W1A_VS4_API_MISSING: other-staff fact is not 409/422", pytrace=False)
