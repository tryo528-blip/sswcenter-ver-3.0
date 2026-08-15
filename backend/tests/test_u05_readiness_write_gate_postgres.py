from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.settings import Settings, get_settings
from app.main import app

CURRENT_REVISION = "20260813_0025_w1_relationship_lock_contract_correction"
STALE_REVISION = "20260813_0024_w2_service_plan_notice_current"


def test_current_head_readiness_and_write_refusal_are_postgres_backed() -> None:
    if os.getenv("SSWCENTER_U05_LIVE") != "1":
        pytest.skip("set SSWCENTER_U05_LIVE=1 for the isolated PostgreSQL probe")

    database_url = os.environ["SSWCENTER_DATABASE_URL"]
    data_root = Path(os.environ["SSWCENTER_DATA_ROOT"])
    client = TestClient(app)

    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ok"}

    missing_root = data_root / "sswcenter-u05-missing-runtime-root"
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=database_url,
        data_root=missing_root,
    )
    try:
        blocked = client.post("/api/auth/logout")
        assert blocked.status_code == 503
        assert blocked.json()["detail"] == {
            "code": "service_not_ready",
            "reason": "data_root_missing",
        }
    finally:
        app.dependency_overrides.clear()

    engine = create_engine(database_url)
    stale_revision_applied = False
    try:
        with engine.begin() as connection:
            current_revision = connection.scalar(
                text("SELECT version_num FROM erp.alembic_version")
            )
            assert current_revision == CURRENT_REVISION
            connection.execute(
                text("UPDATE erp.alembic_version SET version_num = :revision"),
                {"revision": STALE_REVISION},
            )
            stale_revision_applied = True

        stale = client.get("/health/ready")
        assert stale.status_code == 503
        assert stale.json() == {
            "status": "not_ready",
            "reason": "migration_out_of_date",
        }
        stale_write = client.post("/api/auth/logout")
        assert stale_write.status_code == 503
        assert stale_write.json()["detail"] == {
            "code": "service_not_ready",
            "reason": "migration_out_of_date",
        }
    finally:
        if stale_revision_applied:
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE erp.alembic_version SET version_num = :revision"),
                    {"revision": CURRENT_REVISION},
                )
        engine.dispose()
