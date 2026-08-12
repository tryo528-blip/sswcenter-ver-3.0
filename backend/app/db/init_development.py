from __future__ import annotations

import os
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

from alembic import command
from app.core.settings import Environment, get_settings
from app.db.postcheck_w1a_vs1 import main as run_postcheck

MAINTENANCE_DATABASE = "postgres"
TARGET_DATABASE = "sswcenter_dev"


def _validate_source_url(database_url: str) -> URL:
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise SystemExit("Development initialization requires PostgreSQL")
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Development initialization requires loopback PostgreSQL")
    if url.database not in {MAINTENANCE_DATABASE, TARGET_DATABASE}:
        raise SystemExit(
            "Development initialization only accepts postgres or sswcenter_dev as the source DB"
        )
    return url


def _maintenance_fingerprint(url: URL) -> tuple[bool, int, str | None]:
    engine = create_engine(url.set(database=MAINTENANCE_DATABASE))
    try:
        with engine.connect() as connection:
            schema_exists = connection.execute(
                text("SELECT to_regnamespace('erp') IS NOT NULL")
            ).scalar_one()
            table_count = connection.execute(
                text("SELECT count(*) FROM pg_tables WHERE schemaname = 'erp'")
            ).scalar_one()
            revision_table = connection.execute(
                text("SELECT to_regclass('erp.alembic_version')::text")
            ).scalar_one_or_none()
            return bool(schema_exists), int(table_count), revision_table
    finally:
        engine.dispose()


def _ensure_development_database(url: URL) -> bool:
    engine = create_engine(
        url.set(database=MAINTENANCE_DATABASE),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = :name)"),
                {"name": TARGET_DATABASE},
            ).scalar_one()
            if exists:
                return False
            connection.exec_driver_sql('CREATE DATABASE "sswcenter_dev"')
            return True
    finally:
        engine.dispose()


def _update_env_file(env_path: Path, target_url: URL) -> None:
    prefix = "SSWCENTER_DATABASE_URL="
    rendered_url = target_url.render_as_string(hide_password=False)
    original_lines = env_path.read_text(encoding="utf-8").splitlines()
    updated_lines: list[str] = []
    replaced = False
    for line in original_lines:
        if line.startswith(prefix):
            if replaced:
                raise SystemExit("backend/.env contains duplicate SSWCENTER_DATABASE_URL entries")
            updated_lines.append(prefix + rendered_url)
            replaced = True
        else:
            updated_lines.append(line)
    if not replaced:
        updated_lines.append(prefix + rendered_url)
    env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def main() -> None:
    settings = get_settings()
    if settings.environment is not Environment.DEVELOPMENT:
        raise SystemExit("This command only runs with SSWCENTER_ENVIRONMENT=development")
    if settings.database_url is None:
        raise SystemExit("SSWCENTER_DATABASE_URL is required")

    source_url = _validate_source_url(settings.database_url)
    maintenance_before = _maintenance_fingerprint(source_url)
    created = _ensure_development_database(source_url)
    target_url = source_url.set(database=TARGET_DATABASE)

    os.environ["SSWCENTER_DATABASE_URL"] = target_url.render_as_string(hide_password=False)
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    run_postcheck()

    maintenance_after = _maintenance_fingerprint(source_url)
    if maintenance_after != maintenance_before:
        raise SystemExit("Default postgres database changed during development initialization")

    env_path = Path.cwd() / ".env"
    if not env_path.is_file():
        raise SystemExit("backend/.env is missing")
    _update_env_file(env_path, target_url)

    print(f"DEVELOPMENT_DATABASE={'created' if created else 'existing'}")
    print("ALEMBIC_TARGET=sswcenter_dev")
    print("DEFAULT_POSTGRES_UNCHANGED")
    print("ENV_DATABASE_UPDATED=sswcenter_dev")


if __name__ == "__main__":
    main()
