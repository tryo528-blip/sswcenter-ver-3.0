from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.core.readiness import CURRENT_ALEMBIC_REVISION, evaluate_readiness
from app.core.settings import Environment, Settings, get_settings
from app.main import app

LIVE_ENABLED = os.environ.get("SSWCENTER_W0_POSTGRES_LIVE") == "1"
OWNER_DATABASE_URL = os.environ.get("SSWCENTER_DATABASE_URL")
APP_DATABASE_URL = os.environ.get("SSWCENTER_APP_DATABASE_URL")
DATA_ROOT = os.environ.get("SSWCENTER_DATA_ROOT")

pytestmark = pytest.mark.skipif(
    not (LIVE_ENABLED and OWNER_DATABASE_URL and APP_DATABASE_URL and DATA_ROOT),
    reason="isolated W0 PostgreSQL harness is required",
)

APPEND_ONLY_EVENT_TABLES = (
    "audit_event",
    "access_event",
    "auth_event",
    "system_run_event",
)


def _runtime_settings() -> Settings:
    assert APP_DATABASE_URL is not None
    assert DATA_ROOT is not None
    return Settings(
        environment=Environment.TEST,
        database_url=APP_DATABASE_URL,
        data_root=Path(DATA_ROOT),
    )


def test_current_catalog_is_ready_for_application_role() -> None:
    ready, reason = evaluate_readiness(_runtime_settings(), require_postcheck=True)
    assert (ready, reason) == (True, None)


def test_write_gate_fails_closed_on_live_revision_drift() -> None:
    assert OWNER_DATABASE_URL is not None
    owner_engine = create_engine(OWNER_DATABASE_URL)
    try:
        with owner_engine.begin() as connection:
            event_count_before = connection.scalar(text("SELECT count(*) FROM erp.auth_event"))
            connection.execute(text("UPDATE erp.alembic_version SET version_num = 'w0_live_drift'"))

        app.dependency_overrides[get_settings] = _runtime_settings
        try:
            client = TestClient(app)
            ready_response = client.get("/health/ready")
            write_response = client.post("/api/auth/login", json={"pin": "123456"})
        finally:
            app.dependency_overrides.clear()

        assert ready_response.status_code == 503
        assert ready_response.json()["reason"] == "alembic_revision_mismatch"
        assert write_response.status_code == 503
        assert write_response.json()["detail"] == {
            "code": "NOT_READY",
            "reason": "alembic_revision_mismatch",
        }

        with owner_engine.connect() as connection:
            event_count_after = connection.scalar(text("SELECT count(*) FROM erp.auth_event"))
        assert event_count_after == event_count_before
    finally:
        with owner_engine.begin() as connection:
            connection.execute(
                text("UPDATE erp.alembic_version SET version_num = :revision"),
                {"revision": CURRENT_ALEMBIC_REVISION},
            )
        owner_engine.dispose()

    ready, reason = evaluate_readiness(_runtime_settings(), require_postcheck=True)
    assert (ready, reason) == (True, None)


def test_application_role_cannot_rewrite_or_delete_event_ledgers() -> None:
    assert OWNER_DATABASE_URL is not None
    assert APP_DATABASE_URL is not None
    owner_engine = create_engine(OWNER_DATABASE_URL)
    app_engine = create_engine(APP_DATABASE_URL)
    try:
        with app_engine.connect() as connection:
            assert connection.scalar(text("SELECT current_user")) == "erp_app"

        with owner_engine.connect() as connection:
            for table_name in APPEND_ONLY_EVENT_TABLES:
                privileges = connection.execute(
                    text(
                        "SELECT has_table_privilege('erp_app', :table_name, 'SELECT'), "
                        "has_table_privilege('erp_app', :table_name, 'INSERT'), "
                        "has_table_privilege('erp_app', :table_name, 'UPDATE'), "
                        "has_table_privilege('erp_app', :table_name, 'DELETE'), "
                        "has_table_privilege('erp_app', :table_name, 'TRUNCATE')"
                    ),
                    {"table_name": f"erp.{table_name}"},
                ).one()
                assert tuple(bool(value) for value in privileges) == (
                    True,
                    True,
                    False,
                    False,
                    False,
                )

        for table_name in APPEND_ONLY_EVENT_TABLES:
            statements = (
                f"UPDATE erp.{table_name} SET id = id WHERE false",
                f"DELETE FROM erp.{table_name} WHERE false",
                f"TRUNCATE TABLE erp.{table_name}",
            )
            for statement in statements:
                with pytest.raises(DBAPIError, match="permission denied"):
                    with app_engine.begin() as connection:
                        connection.execute(text(statement))
    finally:
        app_engine.dispose()
        owner_engine.dispose()
