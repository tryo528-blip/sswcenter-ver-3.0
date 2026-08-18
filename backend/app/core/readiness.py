from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import text

from app.core.settings import Settings
from app.db.postcheck_current_0029 import verify_current_0029
from app.db.postcheck_dispatch import ACTIVE_REVISION
from app.db.session import create_postgres_engine

CURRENT_ALEMBIC_REVISION = ACTIVE_REVISION


def required_data_paths_ready(data_root: Path | None) -> tuple[bool, str | None]:
    if data_root is None:
        return True, None
    resolved = data_root.expanduser()
    if not resolved.exists() or not resolved.is_dir():
        return False, "required_path_missing"
    if not os.access(resolved, os.R_OK | os.W_OK | os.X_OK):
        return False, "required_path_unusable"
    return True, None


def database_catalog_is_ready(
    database_url: str,
    *,
    require_postcheck: bool = False,
) -> tuple[bool, str | None]:
    try:
        engine = create_postgres_engine(database_url)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                schema_exists = connection.execute(
                    text("SELECT to_regnamespace('erp') IS NOT NULL")
                ).scalar_one()
                if not schema_exists:
                    return False, "erp_schema_missing"

                version_table = connection.execute(
                    text("SELECT to_regclass('erp.alembic_version') IS NOT NULL")
                ).scalar_one()
                if not version_table:
                    return False, "alembic_revision_missing"

                revisions = (
                    connection.execute(text("SELECT version_num FROM erp.alembic_version"))
                    .scalars()
                    .all()
                )
                if len(revisions) != 1:
                    return False, "alembic_revision_cardinality"
                revision = revisions[0]
                if not isinstance(revision, str) or revision != CURRENT_ALEMBIC_REVISION:
                    return False, "alembic_revision_mismatch"

                if require_postcheck:
                    try:
                        verify_current_0029(connection)
                    except SystemExit:
                        return False, "current_postcheck_failed"
        finally:
            engine.dispose()
    except Exception as exc:
        return False, type(exc).__name__
    return True, None


def evaluate_readiness(
    settings: Settings,
    *,
    require_postcheck: bool = False,
) -> tuple[bool, str | None]:
    if settings.database_url is None:
        return False, "database_not_configured"

    path_ready, path_reason = required_data_paths_ready(settings.data_root)
    if not path_ready:
        return False, path_reason

    return database_catalog_is_ready(
        settings.database_url,
        require_postcheck=require_postcheck,
    )
