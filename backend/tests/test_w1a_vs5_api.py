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
from app.core.security import csrf_token_signature, generate_csrf_token, generate_session_token
from app.core.settings import get_settings
from app.db.session import build_session_factory, create_postgres_engine
from app.main import app

DATABASE_URL = os.environ.get("SSWCENTER_DATABASE_URL")
COLLECTION_PATH = "/api/v1/staff/{staff_id}/quarterly-consultations"
ITEM_PATH = f"{COLLECTION_PATH}/{{consultation_id}}"
INVALIDATE_PATH = f"{ITEM_PATH}/invalidate"
REQUIRED_OPERATIONS = {
    COLLECTION_PATH: {"get", "post"},
    ITEM_PATH: {"patch"},
    INVALIDATE_PATH: {"post"},
}
UNSAFE_RESPONSE_WORDS = (
    "integrityerror",
    "sqlalchemy",
    "psycopg",
    "constraint",
    "traceback",
    "select ",
    "insert ",
    "update ",
)


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
        pytest.fail("W1A_VS5_API_HARNESS_FAILURE: API database setup failed", pytrace=False)
    finally:
        engine.dispose()


def _require_routes() -> None:
    try:
        paths = app.openapi().get("paths", {})
    except Exception:
        pytest.fail("W1A_VS5_API_HARNESS_FAILURE: route inspection failed", pytrace=False)
    if not isinstance(paths, dict):
        pytest.fail("W1A_VS5_API_HARNESS_FAILURE: OpenAPI paths are not an object", pytrace=False)
    for path, methods in REQUIRED_OPERATIONS.items():
        operations = paths.get(path)
        if not isinstance(operations, dict) or not methods.issubset(operations):
            pytest.fail(
                "W1A_VS5_API_MISSING: quarterly-consultation route is absent", pytrace=False
            )


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
                                NULL, :display_name, 'VS5 API synthetic fixture')
                        RETURNING id
                        """
                    ),
                    {
                        "name": f"VS5 API synthetic {label} {token}",
                        "display_name": f"VS5 API {label}",
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
                                'VS5 synthetic hash', :pin_lookup_hmac, 1)
                        RETURNING id
                        """
                    ),
                    {
                        "staff_id": staff_id,
                        "account_code": f"vs5-api-{label}-{token}",
                        "display_name": f"VS5 API {label}",
                        "role_code": role,
                        "pin_lookup_hmac": f"vs5-api-{label}-{token}".encode(),
                    },
                ).scalar_one()
            )
            if permission is not None:
                connection.execute(
                    text(
                        """
                        INSERT INTO erp.permission_definition
                            (permission_code, name, description, active)
                        VALUES (:permission, :permission, 'VS5 synthetic permission', TRUE)
                        ON CONFLICT (permission_code) DO NOTHING
                        """
                    ),
                    {"permission": permission},
                )
            cases[label] = AccountCase(
                CurrentAccount(account_id, f"VS5 {label}", role), staff_id, permission
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


def _assert_safe_error(response: Any, marker: str) -> None:
    lowered = response.text.lower()
    if any(word in lowered for word in UNSAFE_RESPONSE_WORDS):
        pytest.fail(marker + ": raw SQL or internal diagnostic leaked", pytrace=False)
    try:
        payload = response.json()
    except ValueError:
        pytest.fail(marker + ": error response is not structured JSON", pytrace=False)
    if not isinstance(payload, (dict, list)):
        pytest.fail(marker + ": error response is not structured", pytrace=False)


@pytest.fixture(autouse=True)
def reset_overrides() -> Iterator[None]:
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_vs5_fastapi_routes_are_real_and_separate() -> None:
    _require_routes()


def test_vs5_actual_acl_matrix_csrf_and_duplicate_contract(
    database_factory: sessionmaker[Session],
) -> None:
    _require_routes()
    cases = _make_cases(database_factory)
    client = TestClient(app, raise_server_exceptions=False)
    for label in ("admin", "view", "manage"):
        _install(database_factory, cases[label].account)
        response = client.get(COLLECTION_PATH.format(staff_id=cases[label].staff_id))
        if response.status_code // 100 != 2:
            pytest.fail(f"W1A_VS5_API_ACL_MISSING: {label} read is not allowed", pytrace=False)
    _install(database_factory, cases["user"].account)
    denied_read = client.get(COLLECTION_PATH.format(staff_id=cases["user"].staff_id))
    if denied_read.status_code != 403:
        pytest.fail("W1A_VS5_API_ACL_MISSING: ungranted USER read is not denied", pytrace=False)

    payload = {
        "calendar_year": 2035,
        "quarter_no": 1,
        "status": "COMPLETE",
        "counseling_date": "2026-07-28",
        "content": "VS5 API synthetic consultation",
        "incomplete_reason_text": None,
        "exempt_reason_text": None,
    }
    for label in ("admin", "manage"):
        _install(database_factory, cases[label].account)
        response = client.post(
            COLLECTION_PATH.format(staff_id=cases[label].staff_id),
            json=payload,
            headers=_csrf_headers(client),
        )
        if response.status_code // 100 != 2:
            pytest.fail(f"W1A_VS5_API_ACL_MISSING: {label} write is not allowed", pytrace=False)
    _install(database_factory, cases["view"].account)
    view_write = client.post(
        COLLECTION_PATH.format(staff_id=cases["view"].staff_id),
        json={**payload, "calendar_year": 2035, "quarter_no": 2},
        headers=_csrf_headers(client),
    )
    if view_write.status_code != 403:
        pytest.fail("W1A_VS5_API_ACL_MISSING: STAFF_VIEW write is not denied", pytrace=False)
    _install(database_factory, cases["user"].account)
    user_write = client.post(
        COLLECTION_PATH.format(staff_id=cases["user"].staff_id),
        json={**payload, "calendar_year": 2035, "quarter_no": 2},
        headers=_csrf_headers(client),
    )
    if user_write.status_code != 403:
        pytest.fail("W1A_VS5_API_ACL_MISSING: ungranted USER write is not denied", pytrace=False)
    _install(database_factory, cases["manage"].account)
    no_csrf = client.post(COLLECTION_PATH.format(staff_id=cases["manage"].staff_id), json=payload)
    if no_csrf.status_code != 403:
        pytest.fail("W1A_VS5_API_ACL_MISSING: missing CSRF is not denied", pytrace=False)

    duplicate = client.post(
        COLLECTION_PATH.format(staff_id=cases["manage"].staff_id),
        json=payload,
        headers=_csrf_headers(client),
    )
    if duplicate.status_code != 409:
        _assert_safe_error(duplicate, "W1A_VS5_API_DUPLICATE_MISSING")
        pytest.fail(
            "W1A_VS5_API_DUPLICATE_MISSING: active duplicate is not stable 409", pytrace=False
        )
    _assert_safe_error(duplicate, "W1A_VS5_API_DUPLICATE_MISSING")


def test_vs5_actual_truth_validation_stale_wrong_staff_and_immutable_key(
    database_factory: sessionmaker[Session],
) -> None:
    _require_routes()
    cases = _make_cases(database_factory)
    _install(database_factory, cases["manage"].account)
    client = TestClient(app, raise_server_exceptions=False)
    base_payload = {
        "calendar_year": 2036,
        "quarter_no": 1,
        "status": "COMPLETE",
        "counseling_date": "2026-07-28",
        "content": "VS5 stale synthetic content",
        "incomplete_reason_text": None,
        "exempt_reason_text": None,
    }
    created = client.post(
        COLLECTION_PATH.format(staff_id=cases["manage"].staff_id),
        json=base_payload,
        headers=_csrf_headers(client),
    )
    if created.status_code // 100 != 2 or not isinstance(created.json().get("id"), int):
        pytest.fail("W1A_VS5_API_MISSING: consultation create path is absent", pytrace=False)
    consultation_id = created.json()["id"]
    row_version = created.json().get("row_version", 1)
    item_path = ITEM_PATH.format(staff_id=cases["manage"].staff_id, consultation_id=consultation_id)
    updated = client.patch(
        item_path,
        json={
            "status": "INCOMPLETE",
            "counseling_date": None,
            "content": None,
            "incomplete_reason_text": "VS5 synthetic incomplete reason",
            "exempt_reason_text": None,
            "expected_row_version": row_version,
        },
        headers=_csrf_headers(client),
    )
    if updated.status_code // 100 != 2:
        pytest.fail("W1A_VS5_API_MISSING: consultation update path is absent", pytrace=False)
    stale = client.patch(
        item_path,
        json={
            "status": "EXEMPT",
            "counseling_date": None,
            "content": None,
            "incomplete_reason_text": None,
            "exempt_reason_text": "VS5 stale synthetic reason",
            "expected_row_version": row_version,
        },
        headers=_csrf_headers(client),
    )
    if stale.status_code != 409:
        _assert_safe_error(stale, "W1A_VS5_API_STALE_MISSING")
        pytest.fail("W1A_VS5_API_STALE_MISSING: stale version is not stable 409", pytrace=False)
    _assert_safe_error(stale, "W1A_VS5_API_STALE_MISSING")

    other_staff = client.patch(
        ITEM_PATH.format(staff_id=cases["user"].staff_id, consultation_id=consultation_id),
        json={
            "status": "INCOMPLETE",
            "counseling_date": None,
            "content": None,
            "incomplete_reason_text": "VS5 wrong staff synthetic reason",
            "exempt_reason_text": None,
            "expected_row_version": 2,
        },
        headers=_csrf_headers(client),
    )
    if other_staff.status_code != 409:
        _assert_safe_error(other_staff, "W1A_VS5_API_WRONG_STAFF_MISSING")
        pytest.fail("W1A_VS5_API_WRONG_STAFF_MISSING: wrong-staff row is not 409", pytrace=False)
    _assert_safe_error(other_staff, "W1A_VS5_API_WRONG_STAFF_MISSING")

    invalid_truth = client.post(
        COLLECTION_PATH.format(staff_id=cases["manage"].staff_id),
        json={
            "calendar_year": 2036,
            "quarter_no": 2,
            "status": "COMPLETE",
            "counseling_date": None,
            "content": "   ",
            "incomplete_reason_text": None,
            "exempt_reason_text": None,
        },
        headers=_csrf_headers(client),
    )
    if invalid_truth.status_code != 422 or not any(
        field in invalid_truth.text for field in ("counseling_date", "content", "status")
    ):
        _assert_safe_error(invalid_truth, "W1A_VS5_API_FIELD_422_MISSING")
        pytest.fail(
            "W1A_VS5_API_FIELD_422_MISSING: truth validation is not field-level 422", pytrace=False
        )
    _assert_safe_error(invalid_truth, "W1A_VS5_API_FIELD_422_MISSING")
    invalid_quarter = client.post(
        COLLECTION_PATH.format(staff_id=cases["manage"].staff_id),
        json={**base_payload, "calendar_year": 2037, "quarter_no": 5},
        headers=_csrf_headers(client),
    )
    if invalid_quarter.status_code != 422:
        _assert_safe_error(invalid_quarter, "W1A_VS5_API_FIELD_422_MISSING")
        pytest.fail("W1A_VS5_API_FIELD_422_MISSING: quarter validation is not 422", pytrace=False)
    invalid_length = client.post(
        COLLECTION_PATH.format(staff_id=cases["manage"].staff_id),
        json={**base_payload, "calendar_year": 2038, "content": "x" * 4001},
        headers=_csrf_headers(client),
    )
    if invalid_length.status_code != 422:
        _assert_safe_error(invalid_length, "W1A_VS5_API_FIELD_422_MISSING")
        pytest.fail("W1A_VS5_API_FIELD_422_MISSING: content length is not 422", pytrace=False)

    immutable = client.patch(
        item_path,
        json={
            "calendar_year": 2099,
            "quarter_no": 4,
            "status": "INCOMPLETE",
            "counseling_date": None,
            "content": None,
            "incomplete_reason_text": "VS5 immutable-key probe",
            "exempt_reason_text": None,
            "expected_row_version": 2,
        },
        headers=_csrf_headers(client),
    )
    if immutable.status_code != 422:
        _assert_safe_error(immutable, "W1A_VS5_API_IMMUTABLE_KEY_MISSING")
        pytest.fail("W1A_VS5_API_IMMUTABLE_KEY_MISSING: update accepts year/quarter", pytrace=False)
    _assert_safe_error(immutable, "W1A_VS5_API_IMMUTABLE_KEY_MISSING")

    missing_row = client.patch(
        ITEM_PATH.format(staff_id=cases["manage"].staff_id, consultation_id=2147483647),
        json={
            "status": "INCOMPLETE",
            "counseling_date": None,
            "content": None,
            "incomplete_reason_text": "VS5 missing-row synthetic reason",
            "exempt_reason_text": None,
            "expected_row_version": 1,
        },
        headers=_csrf_headers(client),
    )
    if missing_row.status_code != 404:
        _assert_safe_error(missing_row, "W1A_VS5_API_NOT_FOUND_MISSING")
        pytest.fail("W1A_VS5_API_NOT_FOUND_MISSING: missing row is not 404", pytrace=False)
