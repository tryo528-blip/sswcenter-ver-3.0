"""Fail-closed dispatch for the current Alembic head postcheck."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.settings import get_settings
from app.db.postcheck_current_0025 import verify_current_0025
from app.db.session import create_postgres_engine

CURRENT_REVISION = "20260813_0025_w1_relationship_lock_contract_correction"
CURRENT_MARKER = "SSWCENTER_CURRENT_0025_DB_POSTCHECK_OK"
HEAD_MARKER = "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK"


def _read_single_revision(connection: Connection) -> str:
    values: Sequence[object] = connection.execute(
        text("SELECT version_num FROM erp.alembic_version")
    ).scalars().all()
    if len(values) != 1:
        raise SystemExit(
            "FOUNDATION_0025_REVISION_CARDINALITY: "
            f"expected=1 actual={len(values)}"
        )
    revision = values[0]
    if not isinstance(revision, str) or revision != CURRENT_REVISION:
        raise SystemExit(
            "FOUNDATION_0025_UNSUPPORTED_REVISION: "
            f"expected={CURRENT_REVISION} actual={revision!r}"
        )
    return revision


def dispatch_current_head(connection: Connection) -> str:
    """Verify the exact current head and emit both success markers."""

    revision = _read_single_revision(connection)
    verify_current_0025(connection)
    print(CURRENT_MARKER)
    print(HEAD_MARKER)
    return revision


def main() -> None:
    database_url = get_settings().database_url
    if not database_url:
        raise SystemExit("FOUNDATION_0025_DATABASE_URL_MISSING")
    engine = create_postgres_engine(database_url)
    try:
        with engine.connect() as connection:
            dispatch_current_head(connection)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
