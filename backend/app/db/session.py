from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings

_READINESS_ENGINE_LOCK = Lock()
_READINESS_ENGINES: dict[str, Engine] = {}
_READINESS_PROBE_LOCK = Lock()
_CONFIGURED_LOG_FILES = ("app.log", "error.log", "access.log", "install-update.log")


def create_postgres_engine(
    database_url: str,
    *,
    pool_size: int | None = None,
    max_overflow: int | None = None,
) -> Engine:
    engine_options: dict[str, object] = {"pool_pre_ping": True}
    if pool_size is not None:
        engine_options["pool_size"] = pool_size
        engine_options["max_overflow"] = 0 if max_overflow is None else max_overflow
    engine = create_engine(database_url, **engine_options)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        raise ValueError("SSWCenter requires PostgreSQL")

    @event.listens_for(engine, "connect")
    def configure_connection(dbapi_connection: object, _: object) -> None:
        original_autocommit = dbapi_connection.autocommit  # type: ignore[attr-defined]
        cursor = None
        try:
            dbapi_connection.autocommit = True  # type: ignore[attr-defined]
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("SET TIME ZONE 'UTC'")
            cursor.execute("SET statement_timeout = '30s'")
            cursor.execute("SET lock_timeout = '5s'")
            cursor.execute("SET idle_in_transaction_session_timeout = '30s'")
            cursor.execute("SET search_path TO erp, pg_catalog")
        finally:
            try:
                if cursor is not None:
                    cursor.close()
            finally:
                dbapi_connection.autocommit = original_autocommit  # type: ignore[attr-defined]

    return engine


def _readiness_engine(database_url: str) -> Engine:
    """Return one shared, bounded-pool engine for readiness probes."""

    with _READINESS_ENGINE_LOCK:
        engine = _READINESS_ENGINES.get(database_url)
        if engine is None:
            engine = create_postgres_engine(database_url, pool_size=1, max_overflow=0)
            _READINESS_ENGINES[database_url] = engine
        return engine


def database_is_ready(database_url: str) -> tuple[bool, str | None]:
    try:
        with _readiness_engine(database_url).connect() as connection:
            connection.execute(text("SELECT 1"))
            schema_exists = connection.execute(
                text("SELECT to_regnamespace('erp') IS NOT NULL")
            ).scalar_one()
            if not schema_exists:
                return False, "erp_schema_missing"
            from app.db.postcheck_current_0025 import EXPECTED_REVISION

            revisions = connection.execute(
                text("SELECT version_num FROM erp.alembic_version")
            ).scalars().all()
            if len(revisions) != 1:
                return False, "migration_revision_invalid"
            if revisions[0] != EXPECTED_REVISION:
                return False, "migration_out_of_date"
    except Exception as exc:
        return False, type(exc).__name__
    return True, None


def _probe_directory_write(directory: Path) -> bool:
    """Exercise the service account's directory ACL with a bounded probe."""

    # A stable per-process name plus a process lock means a denied cleanup
    # leaves at most one marker instead of one orphan per health poll.
    probe = directory / f".sswcenter-readiness-{os.getpid()}.tmp"
    with _READINESS_PROBE_LOCK:
        try:
            with probe.open("x", encoding="utf-8") as handle:
                handle.write("ready")
            probe.unlink()
            return True
        except OSError:
            try:
                probe.unlink()
            except OSError:
                pass
            return False


def _probe_log_append(logs_root: Path) -> bool:
    """Verify append access for every file used by ``configure_logging``."""

    with _READINESS_PROBE_LOCK:
        for name in _CONFIGURED_LOG_FILES:
            path = logs_root / name
            # Missing files have no file-specific ACL to verify; the directory
            # probe above already proves the handler can create them. Skipping
            # them also avoids deleting a file created concurrently by a logger.
            if not path.exists():
                continue
            try:
                # Rollover reads the active file before creating its archive;
                # append permission alone is not enough for that path.
                with path.open("rb"):
                    pass
                with path.open("a", encoding="utf-8"):
                    pass
            except OSError:
                return False
    return True


def runtime_paths_are_ready(data_root: Path | None) -> tuple[bool, str | None]:
    """Check the non-database paths required before accepting a write."""

    if data_root is None:
        return False, "data_root_not_configured"
    if not data_root.is_dir():
        return False, "data_root_missing"
    if not os.access(data_root, os.R_OK | os.X_OK) or not _probe_directory_write(data_root):
        return False, "data_root_not_writable"

    logs_root = data_root / "logs"
    if not logs_root.is_dir():
        return False, "logs_path_missing"
    if (
        not os.access(logs_root, os.R_OK | os.X_OK)
        or not _probe_directory_write(logs_root)
        or not _probe_log_append(logs_root)
    ):
        return False, "logs_path_not_writable"
    return True, None


def application_is_ready(settings: Settings) -> tuple[bool, str | None]:
    """Return the shared readiness result used by health and write gates."""

    if settings.database_url is None:
        return False, "database_not_configured"

    database_ready, database_reason = database_is_ready(settings.database_url)
    if not database_ready:
        return False, database_reason or "database_unavailable"

    return runtime_paths_are_ready(settings.data_root)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        with session.begin():
            yield session
    finally:
        session.close()
