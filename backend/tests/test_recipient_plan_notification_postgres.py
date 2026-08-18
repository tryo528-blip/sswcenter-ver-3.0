"""Live PostgreSQL contract for the 0014 recipient plan-notification boundary.

This module is intentionally inert outside the dedicated current-head wrapper.
It uses the disposable database URLs exported by that wrapper and never falls
back to a developer or production database.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.core.security import PinProtector
from app.core.settings import get_settings
from app.db.models import Staff, UserAccount
from app.db.postcheck_w1a_vs1 import _verify_recipient_plan_notification_contract
from app.main import app

pytestmark = pytest.mark.skipif(
    os.getenv("SSWCENTER_0014_REAL_PG") != "1",
    reason="requires the dedicated 0014 private PostgreSQL wrapper",
)

EXPECTED_REVISION = "20260803_0014_recipient_plan_notification"
EXPECTED_TABLE = "erp.recipient_plan_notification"
ADMIN_PIN = "314159"
NO_PERMISSION_PIN = "271828"


def _required_url(name: str) -> str:
    value = os.getenv(name)
    assert value, f"{name} must be exported by the 0014 wrapper"
    assert value.startswith("postgresql+psycopg://"), f"{name} must use psycopg"
    assert value.rsplit("/", 1)[-1].endswith(("_test", "_review")), (
        f"{name} must point to a disposable test/review database"
    )
    return value


@pytest.fixture(scope="module")
def owner_engine() -> Iterator[Engine]:
    engine = create_engine(_required_url("SSWCENTER_0014_OWNER_DATABASE_URL"), pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def admin_client() -> Iterator[TestClient]:
    settings = get_settings()
    assert settings.environment.value == "test"
    assert settings.dev_login_bypass is False
    assert settings.database_url == _required_url("SSWCENTER_0014_APP_DATABASE_URL")

    with TestClient(app) as client:
        bootstrap_status = client.get("/api/bootstrap/status")
        assert bootstrap_status.status_code == 200
        if bootstrap_status.json() == {"bootstrap_required": True}:
            bootstrap = client.post(
                "/api/bootstrap",
                json={
                    "center_name": "0014 synthetic integration center",
                    "admin_name": "0014 synthetic administrator",
                    "birth_date": "1980-01-01",
                    "sex_code": "TEST",
                    "start_date": "2026-01-01",
                    "pin": ADMIN_PIN,
                },
            )
            assert bootstrap.status_code == 201, bootstrap.text

        login = client.post("/api/auth/login", json={"pin": ADMIN_PIN})
        assert login.status_code == 200, login.text
        assert login.json()["account"]["role_code"] == "ADMIN"
        assert client.cookies.get(settings.session_cookie_name)
        assert client.cookies.get(settings.csrf_cookie_name)
        yield client


def _csrf_headers(client: TestClient) -> dict[str, str]:
    settings = get_settings()
    csrf = client.cookies.get(settings.csrf_cookie_name)
    assert csrf, "authenticated mutating requests require the real CSRF cookie"
    return {settings.csrf_header_name: csrf}


def _post(client: TestClient, path: str, payload: dict[str, object]) -> Response:
    return cast(Response, client.post(path, json=payload, headers=_csrf_headers(client)))


def _assert_error_envelope(
    response: Response,
    *,
    status: int,
    code: str,
) -> dict[str, object]:
    assert response.status_code == status, response.text
    payload = cast(dict[str, Any], response.json())
    assert set(payload) == {"error", "field_errors", "details", "request_id"}
    assert payload["error"]["code"] == code
    assert isinstance(payload["error"]["message"], str) and payload["error"]["message"]
    assert isinstance(payload["field_errors"], list)
    assert isinstance(payload["details"], dict)
    request_id = str(UUID(payload["request_id"]))
    assert response.headers["x-request-id"] == request_id
    assert "traceback" not in response.text.lower()
    assert "sqlalchemy" not in response.text.lower()
    return cast(dict[str, object], payload)


def test_0014_catalog_roles_acl_constraints_and_trigger_contract(owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        identity = (
            connection.execute(
                text(
                    """
                SELECT current_user AS current_user,
                       current_database() AS current_database,
                       (SELECT pg_get_userbyid(datdba)
                          FROM pg_database
                         WHERE datname = current_database()) AS database_owner,
                       (SELECT version_num FROM erp.alembic_version) AS revision
                """
                )
            )
            .mappings()
            .one()
        )
        assert identity["current_user"] == "erp_owner"
        assert identity["database_owner"] == "erp_owner"
        assert str(identity["current_database"]).endswith(("_test", "_review"))
        assert identity["revision"] == EXPECTED_REVISION

        roles = {
            row["rolname"]: bool(row["rolcanlogin"])
            for row in connection.execute(
                text(
                    """
                    SELECT rolname, rolcanlogin
                      FROM pg_roles
                     WHERE rolname IN ('erp_owner', 'erp_app', 'erp_backup')
                    """
                )
            ).mappings()
        }
        assert roles == {"erp_app": True, "erp_backup": True, "erp_owner": True}

        table_owner = connection.execute(
            text(
                """
                SELECT pg_get_userbyid(c.relowner)
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'erp'
                   AND c.relname = 'recipient_plan_notification'
                   AND c.relkind = 'r'
                """
            )
        ).scalar_one()
        assert table_owner == "erp_owner"

        sequence_owner = connection.execute(
            text(
                """
                SELECT pg_get_userbyid(c.relowner)
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'erp'
                   AND c.relname = 'recipient_plan_notification_id_seq'
                   AND c.relkind = 'S'
                """
            )
        ).scalar_one()
        assert sequence_owner == "erp_owner"

        columns = (
            connection.execute(
                text(
                    """
                SELECT column_name, is_nullable, is_identity, identity_generation,
                       column_default
                  FROM information_schema.columns
                 WHERE table_schema = 'erp'
                   AND table_name = 'recipient_plan_notification'
                 ORDER BY ordinal_position
                """
                )
            )
            .mappings()
            .all()
        )
        assert [row["column_name"] for row in columns] == [
            "id",
            "recipient_id",
            "notified_date",
            "invalidated_at_utc",
            "created_by_account_id",
            "created_at_utc",
            "updated_by_account_id",
            "updated_at_utc",
            "row_version",
        ]
        by_column = {row["column_name"]: row for row in columns}
        assert by_column["id"]["is_identity"] == "YES"
        assert by_column["id"]["identity_generation"] == "BY DEFAULT"
        assert by_column["invalidated_at_utc"]["is_nullable"] == "YES"
        assert all(
            row["is_nullable"] == "NO"
            for name, row in by_column.items()
            if name != "invalidated_at_utc"
        )
        assert "1" in str(by_column["row_version"]["column_default"])

        constraint_rows = (
            connection.execute(
                text(
                    """
                SELECT conname, contype, pg_get_constraintdef(oid, true) AS definition,
                       confdeltype, confupdtype, confmatchtype,
                       condeferrable, condeferred, convalidated
                  FROM pg_constraint
                 WHERE conrelid = 'erp.recipient_plan_notification'::regclass
                 ORDER BY conname
                """
                )
            )
            .mappings()
            .all()
        )
        constraints = {
            row["conname"]: {
                "contype": row["contype"],
                "definition": row["definition"],
                "confdeltype": row["confdeltype"],
                "confupdtype": row["confupdtype"],
                "confmatchtype": row["confmatchtype"],
                "condeferrable": row["condeferrable"],
                "condeferred": row["condeferred"],
                "convalidated": row["convalidated"],
            }
            for row in constraint_rows
        }
        assert set(constraints) == {
            "ck_recipient_plan_notification_row_version_positive",
            "fk_recipient_plan_notification_created_by_account",
            "fk_recipient_plan_notification_recipient",
            "fk_recipient_plan_notification_updated_by_account",
            "pk_recipient_plan_notification",
        }
        assert constraints["ck_recipient_plan_notification_row_version_positive"]["contype"] == "c"
        assert (
            "row_version > 0"
            in constraints["ck_recipient_plan_notification_row_version_positive"]["definition"]
        )
        assert constraints["pk_recipient_plan_notification"]["contype"] == "p"
        for name in (
            "fk_recipient_plan_notification_created_by_account",
            "fk_recipient_plan_notification_recipient",
            "fk_recipient_plan_notification_updated_by_account",
        ):
            fk = constraints[name]
            assert fk["contype"] == "f"
            assert "ON DELETE RESTRICT" in fk["definition"]
            assert fk["confdeltype"] == "r", f"{name} confdeltype expected 'r'"
            assert fk["confupdtype"] == "a", f"{name} confupdtype expected 'a'"
            assert fk["confmatchtype"] == "s", f"{name} confmatchtype expected 's'"
            assert fk["condeferrable"] is False, f"{name} must not be deferrable"
            assert fk["condeferred"] is False, f"{name} must not be initially deferred"
            assert fk["convalidated"] is True, f"{name} must be validated"

        indexes = {
            row["indexname"]
            for row in connection.execute(
                text(
                    """
                    SELECT indexname
                      FROM pg_indexes
                     WHERE schemaname = 'erp'
                       AND tablename = 'recipient_plan_notification'
                    """
                )
            ).mappings()
        }
        assert indexes == {
            "ix_recipient_plan_notification_notified_date",
            "ix_recipient_plan_notification_recipient_id",
            "pk_recipient_plan_notification",
        }

        user_triggers = (
            connection.execute(
                text(
                    """
                SELECT tgname
                  FROM pg_trigger
                 WHERE tgrelid = 'erp.recipient_plan_notification'::regclass
                   AND NOT tgisinternal
                 ORDER BY tgname
                """
                )
            )
            .scalars()
            .all()
        )
        assert user_triggers == []

        privileges = (
            connection.execute(
                text(
                    """
                SELECT
                    has_schema_privilege('erp_app', 'erp', 'USAGE') AS app_schema_usage,
                    has_table_privilege('erp_app', :table_name, 'SELECT') AS app_select,
                    has_table_privilege('erp_app', :table_name, 'INSERT') AS app_insert,
                    has_table_privilege('erp_app', :table_name, 'UPDATE') AS app_update,
                    has_table_privilege('erp_app', :table_name, 'DELETE') AS app_delete,
                    has_table_privilege('erp_app', :table_name, 'TRUNCATE') AS app_truncate,
                    has_sequence_privilege(
                        'erp_app', 'erp.recipient_plan_notification_id_seq', 'USAGE'
                    ) AS app_sequence_usage,
                    has_sequence_privilege(
                        'erp_app', 'erp.recipient_plan_notification_id_seq', 'SELECT'
                    ) AS app_sequence_select,
                    has_schema_privilege('erp_backup', 'erp', 'USAGE')
                        AS backup_schema_usage,
                    has_table_privilege('erp_backup', :table_name, 'SELECT') AS backup_select,
                    has_table_privilege('erp_backup', :table_name, 'INSERT') AS backup_insert,
                    has_table_privilege('erp_backup', :table_name, 'UPDATE') AS backup_update,
                    has_table_privilege('erp_backup', :table_name, 'DELETE') AS backup_delete,
                    has_table_privilege('erp_backup', :table_name, 'TRUNCATE')
                        AS backup_truncate,
                    has_sequence_privilege(
                        'erp_backup', 'erp.recipient_plan_notification_id_seq', 'USAGE'
                    ) AS backup_sequence_usage,
                    has_sequence_privilege(
                        'erp_backup', 'erp.recipient_plan_notification_id_seq', 'SELECT'
                    ) AS backup_sequence_select
                """
                ),
                {"table_name": EXPECTED_TABLE},
            )
            .mappings()
            .one()
        )
        assert dict(privileges) == {
            "app_schema_usage": True,
            "app_select": True,
            "app_insert": True,
            "app_update": True,
            "app_delete": False,
            "app_truncate": False,
            "app_sequence_usage": True,
            "app_sequence_select": True,
            "backup_schema_usage": True,
            "backup_select": True,
            "backup_insert": False,
            "backup_update": False,
            "backup_delete": False,
            "backup_truncate": False,
            "backup_sequence_usage": False,
            "backup_sequence_select": True,
        }

        # Prove the repaired postcheck verifier does not false-reject the
        # pristine migrated schema when search_path is set to erp, pg_catalog.
        connection.execute(text("SET LOCAL search_path TO erp, pg_catalog"))
        _verify_recipient_plan_notification_contract(connection)

    app_engine = create_engine(_required_url("SSWCENTER_0014_APP_DATABASE_URL"))
    try:
        with app_engine.connect() as connection:
            assert connection.execute(text("SELECT current_user")).scalar_one() == "erp_app"
            assert (
                connection.execute(
                    text("SELECT count(*) FROM erp.recipient_plan_notification")
                ).scalar_one()
                == 0
            )
    finally:
        app_engine.dispose()

    print("SSWCENTER_0014_CATALOG_ACL_GREEN")


def test_0014_real_api_deadlines_cumulative_history_and_row_version(
    admin_client: TestClient,
) -> None:
    recipient_response = _post(
        admin_client,
        "/api/v1/recipients",
        {
            "name": "0014 synthetic recipient",
            "birth_date": "1940-01-01",
            "sex_code": "FEMALE",
            "memo": "synthetic integration data only",
        },
    )
    assert recipient_response.status_code == 201, recipient_response.text
    recipient_id = int(recipient_response.json()["id"])

    identity = _post(
        admin_client,
        f"/api/v1/recipients/{recipient_id}/certification-identity",
        {"certification_number": "L1234567890"},
    )
    assert identity.status_code == 201, identity.text
    certification = _post(
        admin_client,
        f"/api/v1/recipients/{recipient_id}/certification-periods",
        {"start_date": "2026-01-01", "end_date": "2026-12-31"},
    )
    assert certification.status_code == 201, certification.text
    contract = _post(
        admin_client,
        f"/api/v1/recipients/{recipient_id}/contracts",
        {
            "service_type_code": "HOME_CARE",
            "start_date": "2026-01-01",
            "end_date": "2027-01-31",
            "service_start_date": "2026-01-01",
        },
    )
    assert contract.status_code == 201, contract.text

    notification_path = f"/api/v1/recipients/{recipient_id}/plan-notifications"
    first = _post(admin_client, notification_path, {"notified_date": "2026-03-02"})
    duplicate = _post(admin_client, notification_path, {"notified_date": "2026-03-02"})
    latest = _post(admin_client, notification_path, {"notified_date": "2026-04-15"})
    for response in (first, duplicate, latest):
        assert response.status_code == 201, response.text
        assert response.json()["row_version"] == 1
        assert response.json()["invalidated_at_utc"] is None

    first_body = first.json()
    duplicate_body = duplicate.json()
    latest_body = latest.json()
    assert len({first_body["id"], duplicate_body["id"], latest_body["id"]}) == 3

    listed = admin_client.get(notification_path)
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["items"]] == [
        latest_body["id"],
        duplicate_body["id"],
        first_body["id"],
    ]
    assert [item["notified_date"] for item in listed.json()["items"]] == [
        "2026-04-15",
        "2026-03-02",
        "2026-03-02",
    ]

    deadlines = admin_client.get("/api/v1/recipients/deadlines")
    assert deadlines.status_code == 200, deadlines.text
    recipient_deadlines = [
        item for item in deadlines.json()["items"] if item["recipient_id"] == recipient_id
    ]
    by_kind = {item["kind"]: item for item in recipient_deadlines}
    assert by_kind["CERTIFICATION_EXPIRY"]["source_date"] == "2026-12-31"
    assert by_kind["CERTIFICATION_EXPIRY"]["due_date"] == "2026-12-31"
    assert by_kind["CONTRACT_EXPIRY"]["source_date"] == "2027-01-31"
    assert by_kind["CONTRACT_EXPIRY"]["due_date"] == "2027-01-31"
    assert by_kind["PLAN_RENEWAL"] == {
        "recipient_id": recipient_id,
        "recipient_name": "0014 synthetic recipient",
        "kind": "PLAN_RENEWAL",
        "source_id": latest_body["id"],
        "source_date": "2026-04-15",
        "due_date": "2026-10-31",
    }

    invalidate_path = f"{notification_path}/{latest_body['id']}/invalidate"
    stale = _post(admin_client, invalidate_path, {"expected_row_version": 99})
    stale_body = _assert_error_envelope(stale, status=409, code="ROW_VERSION_CONFLICT")
    assert stale_body["details"] == {
        "current_row_version": 1,
        "entity": "plan_notification",
    }

    invalidated = _post(admin_client, invalidate_path, {"expected_row_version": 1})
    assert invalidated.status_code == 200, invalidated.text
    assert invalidated.json()["row_version"] == 2
    assert invalidated.json()["invalidated_at_utc"] is not None

    repeated = _post(admin_client, invalidate_path, {"expected_row_version": 1})
    repeated_body = _assert_error_envelope(repeated, status=409, code="ROW_VERSION_CONFLICT")
    assert repeated_body["details"] == {
        "current_row_version": 2,
        "entity": "plan_notification",
    }

    history = admin_client.get(notification_path)
    assert history.status_code == 200, history.text
    assert len(history.json()["items"]) == 3
    history_by_id = {item["id"]: item for item in history.json()["items"]}
    assert history_by_id[latest_body["id"]]["row_version"] == 2
    assert history_by_id[latest_body["id"]]["invalidated_at_utc"] is not None
    assert history_by_id[duplicate_body["id"]]["invalidated_at_utc"] is None
    assert history_by_id[first_body["id"]]["invalidated_at_utc"] is None

    fallback_deadlines = admin_client.get("/api/v1/recipients/deadlines")
    assert fallback_deadlines.status_code == 200, fallback_deadlines.text
    fallback_plan = next(
        item
        for item in fallback_deadlines.json()["items"]
        if item["recipient_id"] == recipient_id and item["kind"] == "PLAN_RENEWAL"
    )
    assert fallback_plan["source_id"] == duplicate_body["id"]
    assert fallback_plan["source_date"] == "2026-03-02"
    assert fallback_plan["due_date"] == "2026-09-30"

    replacement = _post(
        admin_client,
        notification_path,
        {"notified_date": "2026-05-20"},
    )
    assert replacement.status_code == 201, replacement.text
    replacement_body = replacement.json()
    assert replacement_body["row_version"] == 1
    assert replacement_body["invalidated_at_utc"] is None
    assert replacement_body["id"] not in {
        first_body["id"],
        duplicate_body["id"],
        latest_body["id"],
    }

    replacement_history = admin_client.get(notification_path)
    assert replacement_history.status_code == 200, replacement_history.text
    replacement_items = replacement_history.json()["items"]
    assert len(replacement_items) == 4
    assert replacement_items[0]["id"] == replacement_body["id"]
    replacement_by_id = {item["id"]: item for item in replacement_items}
    assert replacement_by_id[latest_body["id"]]["row_version"] == 2
    assert replacement_by_id[latest_body["id"]]["invalidated_at_utc"] is not None
    assert replacement_by_id[duplicate_body["id"]]["invalidated_at_utc"] is None
    assert replacement_by_id[first_body["id"]]["invalidated_at_utc"] is None

    replacement_deadlines = admin_client.get("/api/v1/recipients/deadlines")
    assert replacement_deadlines.status_code == 200, replacement_deadlines.text
    replacement_plan = next(
        item
        for item in replacement_deadlines.json()["items"]
        if item["recipient_id"] == recipient_id and item["kind"] == "PLAN_RENEWAL"
    )
    assert replacement_plan["source_id"] == replacement_body["id"]
    assert replacement_plan["source_date"] == "2026-05-20"
    assert replacement_plan["due_date"] == "2026-11-30"

    print("SSWCENTER_0014_BACKEND_API_GREEN")


def test_0014_authorization_csrf_validation_and_error_envelopes(
    admin_client: TestClient,
    owner_engine: Engine,
) -> None:
    with TestClient(app) as unauthenticated:
        unauthenticated_error = unauthenticated.get("/api/v1/recipients/deadlines")
        _assert_error_envelope(
            unauthenticated_error,
            status=401,
            code="AUTHENTICATION_REQUIRED",
        )

    settings = get_settings()
    protector = PinProtector(
        settings.secret_value("pin_pepper"),
        settings.secret_value("pin_lookup_key"),
    )
    with Session(owner_engine) as owner_session, owner_session.begin():
        staff = Staff(
            name="0014 no-permission synthetic user",
            birth_date=date(1991, 1, 1),
            sex_code="TEST",
            phone=None,
            phone_normalized=None,
            address=None,
            display_name="0014 no-permission user",
            memo="synthetic integration data only",
        )
        owner_session.add(staff)
        owner_session.flush()
        owner_session.add(
            UserAccount(
                staff_id=staff.id,
                account_code="0014_NO_PERMISSION_USER",
                display_name="0014 no-permission user",
                role_code="USER",
                pin_hash=protector.hash_pin(NO_PERMISSION_PIN),
                pin_lookup_hmac=protector.lookup_hmac(NO_PERMISSION_PIN),
                pin_key_version=1,
                active=True,
                login_allowed=True,
                failed_count=0,
                session_version=1,
                row_version=1,
            )
        )

    with TestClient(app) as no_permission_client:
        login = no_permission_client.post("/api/auth/login", json={"pin": NO_PERMISSION_PIN})
        assert login.status_code == 200, login.text
        denied = no_permission_client.get("/api/v1/recipients/deadlines")
        denied_body = _assert_error_envelope(denied, status=403, code="PERMISSION_REQUIRED")
        assert denied_body["details"] == {"permission": "RECIPIENT_VIEW"}

    recipient = _post(
        admin_client,
        "/api/v1/recipients",
        {
            "name": "0014 authorization synthetic recipient",
            "birth_date": "1945-05-05",
            "sex_code": "MALE",
        },
    )
    assert recipient.status_code == 201, recipient.text
    recipient_id = int(recipient.json()["id"])
    path = f"/api/v1/recipients/{recipient_id}/plan-notifications"

    missing_csrf = admin_client.post(path, json={"notified_date": "2026-03-02"})
    _assert_error_envelope(missing_csrf, status=403, code="CSRF_REQUIRED")

    validation = _post(admin_client, path, {"notified_date": "not-a-date"})
    validation_body = _assert_error_envelope(validation, status=422, code="VALIDATION_ERROR")
    field_errors = validation_body["field_errors"]
    assert isinstance(field_errors, list) and field_errors
    first_field_error = field_errors[0]
    assert isinstance(first_field_error, dict)
    assert first_field_error["field"] == "notified_date"

    missing_recipient = admin_client.get(
        "/api/v1/recipients/9223372036854775807/plan-notifications"
    )
    _assert_error_envelope(missing_recipient, status=404, code="RECIPIENT_NOT_FOUND")

    print("SSWCENTER_0014_AUTH_ERROR_GREEN")


_FK_RECIPIENT = "fk_recipient_plan_notification_recipient"
_FK_RECIPIENT_DDL = (
    "ALTER TABLE erp.recipient_plan_notification "
    "ADD CONSTRAINT fk_recipient_plan_notification_recipient "
    "FOREIGN KEY (recipient_id) REFERENCES erp.recipient(id) "
    "ON DELETE RESTRICT"
)


@pytest.mark.parametrize(
    "drift_label, alter_suffix, expected_message",
    [
        (
            "update_action",
            " ON UPDATE CASCADE",
            "update action",
        ),
        (
            "deferrable",
            " DEFERRABLE INITIALLY IMMEDIATE",
            "deferrable",
        ),
        (
            "validated",
            " NOT VALID",
            "validated",
        ),
    ],
)
def test_0014_recipient_fk_drift_detection(
    owner_engine: Engine,
    drift_label: str,
    alter_suffix: str,
    expected_message: str,
) -> None:
    with owner_engine.connect() as connection:
        tx = connection.begin()
        try:
            connection.execute(text("SET LOCAL search_path TO erp, pg_catalog"))
            connection.execute(
                text(
                    "ALTER TABLE erp.recipient_plan_notification "
                    "DROP CONSTRAINT fk_recipient_plan_notification_recipient"
                )
            )
            connection.execute(text(_FK_RECIPIENT_DDL + alter_suffix))
            with pytest.raises(SystemExit, match=expected_message):
                _verify_recipient_plan_notification_contract(connection)
        finally:
            tx.rollback()
