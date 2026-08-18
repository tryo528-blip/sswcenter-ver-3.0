"""Run the full W2 HTTP contract against the active 0029 browser database.

The W2 0027 lifecycle database remains deliberately historical.  This test
does not duplicate or dilute its HTTP assertions: it loads and invokes the
original W2 HTTP contract with an independently seeded active 0029 database.
That keeps FastAPI -> W2 service -> PostgreSQL coverage complete without
allowing a historical catalog to masquerade as the current head.

The filename is retained so historical W2 harness references remain stable.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.settings import assert_safe_test_database_url

ACTIVE_REVISION = "20260818_0029_w3_persistent_apply_workspace"
W2_CORE_POSTGRES_TEST = Path(__file__).with_name("test_w2_core_postgres.py")

pytestmark = pytest.mark.skipif(
    os.getenv("SSWCENTER_W2_CURRENT_HTTP_REAL_PG") != "1",
    reason="requires the active 0029 W2 browser/current PostgreSQL harness",
)


def _required_url(name: str) -> str:
    value = os.getenv(name)
    assert value, f"{name} must be explicitly exported"
    assert_safe_test_database_url(value)
    return value


@pytest.fixture(scope="module")
def current_engine() -> Iterator[Engine]:
    engine = create_engine(
        _required_url("SSWCENTER_W2_CURRENT_HTTP_DATABASE_URL"),
        pool_pre_ping=True,
    )
    try:
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM erp.alembic_version"))
            assert revision == ACTIVE_REVISION
        yield engine
    finally:
        engine.dispose()


def _load_original_w2_http_contract() -> ModuleType:
    """Load the unmodified historical source without making it a pytest item.

    Its fixture generator supplies the same real owner-side seed used by the
    original node, while this module independently proves the active revision.
    """

    spec = spec_from_file_location("w3_current_http_w2_core_contract", W2_CORE_POSTGRES_TEST)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_current_application_ready(app_database_url: str) -> None:
    """Exercise the normal readiness endpoint before the write-capable contract."""

    from fastapi.testclient import TestClient

    from app.api import dependencies as api_dependencies
    from app.core.settings import get_settings
    from app.main import create_app

    previous_database_url = os.environ.get("SSWCENTER_DATABASE_URL")
    previous_environment = os.environ.get("SSWCENTER_ENVIRONMENT")
    os.environ["SSWCENTER_DATABASE_URL"] = app_database_url
    os.environ["SSWCENTER_ENVIRONMENT"] = "test"
    get_settings.cache_clear()
    api_dependencies._database_runtime.cache_clear()
    try:
        with TestClient(create_app(), raise_server_exceptions=False) as client:
            response = client.get("/health/ready")
        assert response.status_code == 200, response.text
        assert response.json() == {"status": "ok"}
    finally:
        if previous_database_url is None:
            os.environ.pop("SSWCENTER_DATABASE_URL", None)
        else:
            os.environ["SSWCENTER_DATABASE_URL"] = previous_database_url
        if previous_environment is None:
            os.environ.pop("SSWCENTER_ENVIRONMENT", None)
        else:
            os.environ["SSWCENTER_ENVIRONMENT"] = previous_environment
        get_settings.cache_clear()
        api_dependencies._database_runtime.cache_clear()


def test_current_0029_runs_full_original_w2_http_contract(
    current_engine: Engine,
) -> None:
    """Keep every original HTTP assertion on the separately active catalog."""

    module = _load_original_w2_http_contract()
    app_database_url = _required_url("SSWCENTER_W2_CURRENT_HTTP_APP_DATABASE_URL")
    original_seed = module.seeded.__wrapped__(current_engine)
    seeded = next(original_seed)
    try:
        _assert_current_application_ready(app_database_url)
        module.test_official_card_http_role_csrf_conflict_and_response_contracts(
            current_engine,
            seeded,
        )
    finally:
        try:
            next(original_seed)
        except StopIteration:
            pass
        else:  # pragma: no cover - the historical fixture must yield once.
            raise AssertionError("historical W2 seed fixture yielded more than once")
