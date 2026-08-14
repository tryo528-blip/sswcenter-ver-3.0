from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from app.core.settings import Settings, get_settings
from app.db import session
from app.main import app


class _FakeScalarResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return list(self._values)


class _FakeResult:
    def __init__(self, *, scalar: object | None = None, values: list[object] | None = None) -> None:
        self._scalar = scalar
        self._values = values or []

    def scalar_one(self) -> object:
        return self._scalar

    def scalars(self) -> _FakeScalarResult:
        return _FakeScalarResult(self._values)


class _FakeConnection:
    def __init__(self, revision_values: list[object]) -> None:
        self.revision_values = revision_values

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: Any, _parameters: object | None = None) -> _FakeResult:
        sql = str(statement)
        if "to_regnamespace" in sql:
            return _FakeResult(scalar=True)
        if "version_num" in sql:
            return _FakeResult(values=self.revision_values)
        return _FakeResult(scalar=1)


class _FakeEngine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, revision_values: list[object]) -> None:
        self.connection = _FakeConnection(revision_values)

    def connect(self) -> _FakeConnection:
        return self.connection

    def dispose(self) -> None:
        return None


def test_database_readiness_rejects_stale_or_missing_migration_head(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        session,
        "create_postgres_engine",
        lambda _url: _FakeEngine(["20260813_0024_w2_service_plan_notice_current"]),
    )

    ready, reason = session.database_is_ready("postgresql://example.invalid/sswcenter")

    assert ready is False
    assert reason == "migration_out_of_date"


def test_database_readiness_rejects_missing_or_multiple_migration_heads(
    monkeypatch: Any,
) -> None:
    for revision_values in ([], ["20260813_0025_w1_relationship_lock_contract_correction"] * 2):
        monkeypatch.setattr(
            session,
            "create_postgres_engine",
            lambda _url, values=revision_values: _FakeEngine(values),
        )

        ready, reason = session.database_is_ready("postgresql://example.invalid/sswcenter")

        assert ready is False
        assert reason == "migration_revision_invalid"


def test_application_readiness_requires_runtime_root_and_logs_directory(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(session, "database_is_ready", lambda _url: (True, None))
    settings = Settings(database_url="postgresql://example.invalid/sswcenter")

    ready, reason = session.application_is_ready(settings)
    assert (ready, reason) == (False, "data_root_not_configured")

    settings = Settings(
        database_url="postgresql://example.invalid/sswcenter",
        data_root=tmp_path,
    )
    ready, reason = session.application_is_ready(settings)
    assert (ready, reason) == (False, "logs_path_missing")

    (tmp_path / "logs").mkdir()
    ready, reason = session.application_is_ready(settings)
    assert (ready, reason) == (True, None)


def test_write_requests_are_refused_when_application_is_not_ready(
    monkeypatch: Any,
) -> None:
    from app.api import dependencies

    monkeypatch.setattr(
        dependencies,
        "application_is_ready",
        lambda _settings: (False, "migration_out_of_date"),
    )
    app.dependency_overrides[get_settings] = lambda: Settings(database_url=None)
    try:
        response = TestClient(app).post("/api/auth/logout")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "service_not_ready",
            "reason": "migration_out_of_date",
        }
    }


def test_write_gate_uses_real_application_readiness_reason(monkeypatch: Any) -> None:
    monkeypatch.setattr(session, "database_is_ready", lambda _url: (True, None))
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql://example.invalid/sswcenter",
    )
    try:
        response = TestClient(app).post("/api/auth/logout")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "service_not_ready",
        "reason": "data_root_not_configured",
    }


def test_safe_health_request_is_not_blocked_by_write_gate(monkeypatch: Any) -> None:
    from app.api import dependencies

    monkeypatch.setattr(
        dependencies,
        "application_is_ready",
        lambda _settings: (False, "migration_out_of_date"),
    )
    response = TestClient(app).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
