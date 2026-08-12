from __future__ import annotations

import sys
from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context
from app.core.settings import assert_migration_database_url, get_settings
from app.db import models as wave0_models  # noqa: F401
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    value = get_settings().database_url
    if value is None:
        raise RuntimeError("SSWCENTER_DATABASE_URL is required for Alembic")
    assert_migration_database_url(value)
    return value


def run_migrations_offline() -> None:
    # Alembic emits its version table before the first revision. Create the
    # dedicated schema first so the generated offline upgrade SQL is executable.
    sys.stdout.write("CREATE SCHEMA IF NOT EXISTS erp;\n")
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        compare_type=True,
        version_table_schema="erp",
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(database_url(), poolclass=pool.NullPool)

    # Own the outer transaction explicitly. Executing CREATE SCHEMA first
    # otherwise starts SQLAlchemy's implicit transaction; Alembic then reuses
    # it and the connection context rolls every migration back on exit.
    with connectable.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS erp")
        connection.exec_driver_sql("SET TIME ZONE 'UTC'")
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            compare_type=True,
            version_table_schema="erp",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
