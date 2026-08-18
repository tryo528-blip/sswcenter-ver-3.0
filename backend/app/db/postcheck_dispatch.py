"""Fail-closed dispatch for the exact active Alembic head postcheck.

Historical revision verifiers remain executable as their own modules.  This
entrypoint is deliberately not a compatibility router: a non-0028 database
must never look current merely because it still has a valid historical catalog.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.settings import get_settings
from app.db.postcheck_current_0028 import verify_current_0028
from app.db.session import create_postgres_engine

ACTIVE_REVISION = "20260817_0028_w3_source_intake_foundation"
CURRENT_0028_MARKER = "SSWCENTER_CURRENT_0028_DB_POSTCHECK_OK"
HEAD_MARKER = "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK"


def _read_single_revision(connection: Connection) -> str:
    values: Sequence[object] = (
        connection.execute(text("SELECT version_num FROM erp.alembic_version")).scalars().all()
    )
    if len(values) != 1:
        raise SystemExit(f"FOUNDATION_0028_REVISION_CARDINALITY: expected=1 actual={len(values)}")
    revision = values[0]
    if not isinstance(revision, str) or revision != ACTIVE_REVISION:
        raise SystemExit(
            f"FOUNDATION_0028_UNSUPPORTED_REVISION: expected={ACTIVE_REVISION} actual={revision!r}"
        )
    return revision


def dispatch_current_head(connection: Connection) -> str:
    """Verify only the active 0028 catalog and emit the sole head marker."""

    revision = _read_single_revision(connection)
    verify_current_0028(connection)
    print(CURRENT_0028_MARKER)
    print(HEAD_MARKER)
    return revision


def main() -> None:
    database_url = get_settings().database_url
    if not database_url:
        raise SystemExit("FOUNDATION_0028_DATABASE_URL_MISSING")
    engine = create_postgres_engine(database_url)
    try:
        with engine.connect() as connection:
            dispatch_current_head(connection)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
