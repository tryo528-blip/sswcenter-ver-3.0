from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_db_session
from app.core.readiness import CURRENT_ALEMBIC_REVISION, evaluate_readiness
from app.core.settings import Environment, Settings, get_settings
from app.db.postcheck_dispatch import ACTIVE_REVISION
from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
READINESS_PATH = REPO_ROOT / "backend" / "app" / "core" / "readiness.py"
DEPENDENCIES_PATH = REPO_ROOT / "backend" / "app" / "api" / "dependencies.py"
HEALTH_PATH = REPO_ROOT / "backend" / "app" / "api" / "health.py"


def _unready_settings() -> Settings:
    return Settings(
        environment=Environment.DEVELOPMENT,
        database_url="postgresql://erp_app:secret@127.0.0.1:1/sswcenter_unready_test",
    )


def test_readiness_contract_binds_current_revision_and_postcheck() -> None:
    readiness_source = READINESS_PATH.read_text(encoding="utf-8")
    health_source = HEALTH_PATH.read_text(encoding="utf-8")
    dependencies_source = DEPENDENCIES_PATH.read_text(encoding="utf-8")

    assert CURRENT_ALEMBIC_REVISION == ACTIVE_REVISION
    assert "alembic_version" in readiness_source
    assert "verify_current_0029" in readiness_source
    assert "verify_current_0028" not in readiness_source
    assert "required_data_paths_ready" in readiness_source
    assert "evaluate_readiness" in health_source
    assert "require_postcheck=True" in health_source
    assert "evaluate_readiness" in dependencies_source
    assert "NOT_READY" in dependencies_source


def test_health_ready_reports_missing_database_configuration() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(database_url=None)
    try:
        response = TestClient(app).get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "reason": "database_not_configured",
    }


def test_health_ready_fails_closed_for_revision_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.health.evaluate_readiness",
        lambda settings, require_postcheck=False: (False, "alembic_revision_mismatch"),
    )
    app.dependency_overrides[get_settings] = _unready_settings
    try:
        response = TestClient(app).get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "reason": "alembic_revision_mismatch",
    }


def test_health_ready_fails_closed_for_postcheck_or_required_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.health.evaluate_readiness",
        lambda settings, require_postcheck=False: (False, "current_postcheck_failed"),
    )
    app.dependency_overrides[get_settings] = _unready_settings
    try:
        response = TestClient(app).get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["reason"] == "current_postcheck_failed"


def test_missing_required_path_is_not_ready(tmp_path: Path) -> None:
    missing = tmp_path / "sswcenter-missing-data-root"
    ready, reason = evaluate_readiness(
        Settings(
            environment=Environment.DEVELOPMENT,
            database_url="postgresql://erp_app:secret@127.0.0.1:1/sswcenter_unready_test",
            data_root=missing,
        ),
        require_postcheck=True,
    )
    assert ready is False
    assert reason == "required_path_missing"


def test_write_gate_rejects_login_before_product_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login_called = {"value": False}
    postcheck_flags: list[bool] = []

    def forbidden_login(*_args: object, **_kwargs: object) -> object:
        login_called["value"] = True
        raise AssertionError("U05_WRITE_GATE_BYPASS: login executed while not ready")

    def reject_failed_postcheck(
        settings: Settings,
        *,
        require_postcheck: bool = False,
    ) -> tuple[bool, str | None]:
        postcheck_flags.append(require_postcheck)
        if require_postcheck:
            return False, "current_postcheck_failed"
        return True, None

    monkeypatch.setattr("app.api.dependencies.evaluate_readiness", reject_failed_postcheck)
    monkeypatch.setattr("app.api.auth.login", forbidden_login)
    app.dependency_overrides[get_settings] = _unready_settings
    try:
        response = TestClient(app).post("/api/auth/login", json={"pin": "123456"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    body = response.json()
    assert "current_postcheck_failed" in str(body)
    assert login_called["value"] is False
    assert postcheck_flags == [True]


def test_write_gate_rejects_bootstrap_mutation_before_session_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_opened = {"value": False}
    postcheck_flags: list[bool] = []

    def forbidden_session(_database_url: str) -> tuple[object, object]:
        session_opened["value"] = True
        raise AssertionError("U05_WRITE_GATE_BYPASS: database session opened while not ready")

    def reject_failed_postcheck(
        settings: Settings,
        *,
        require_postcheck: bool = False,
    ) -> tuple[bool, str | None]:
        postcheck_flags.append(require_postcheck)
        if require_postcheck:
            return False, "current_postcheck_failed"
        return True, None

    monkeypatch.setattr("app.api.dependencies.evaluate_readiness", reject_failed_postcheck)
    monkeypatch.setattr("app.api.dependencies._database_runtime", forbidden_session)
    app.dependency_overrides[get_settings] = _unready_settings
    try:
        response = TestClient(app).post(
            "/api/bootstrap",
            json={
                "center_name": "합성센터",
                "admin_name": "합성관리자",
                "birth_date": "1980-01-01",
                "sex_code": "FEMALE",
                "start_date": "2026-01-01",
                "pin": "123456",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert session_opened["value"] is False
    assert "current_postcheck_failed" in str(response.json())
    assert postcheck_flags == [True]


def test_live_probe_stays_available_when_write_gate_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.api.health.evaluate_readiness",
        lambda settings, require_postcheck=False: (False, "alembic_revision_mismatch"),
    )
    app.dependency_overrides[get_settings] = _unready_settings
    try:
        live = TestClient(app).get("/health/live")
        ready = TestClient(app).get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 503


def test_get_db_session_source_fail_closes_before_runtime() -> None:
    source = inspect.getsource(get_db_session)
    ready_at = source.find("evaluate_readiness")
    runtime_at = source.find("_database_runtime")
    assert ready_at != -1
    assert runtime_at != -1
    assert ready_at < runtime_at
    assert "request.method.upper() not in _READ_ONLY_HTTP_METHODS" in source
    assert get_db_session.__name__ == "get_db_session"
