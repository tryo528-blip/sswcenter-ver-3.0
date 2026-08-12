from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker


def create_postgres_engine(database_url: str) -> Engine:
    engine = create_engine(database_url, pool_pre_ping=True)
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


def database_is_ready(database_url: str) -> tuple[bool, str | None]:
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
        finally:
            engine.dispose()
    except Exception as exc:
        return False, type(exc).__name__
    return True, None


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
