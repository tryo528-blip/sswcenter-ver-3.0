from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.settings import get_settings
from app.db.session import create_postgres_engine

WAVE0_REVISION = "20260724_0002"
WAVE0_PERMISSION_COUNT = 4

EXPECTED_TABLES = {
    "access_event",
    "account_permission",
    "alembic_version",
    "audit_event",
    "auth_event",
    "auth_rate_limit_bucket",
    "auth_session",
    "business_number_counter",
    "center",
    "installation_state",
    "permission_definition",
    "staff",
    "staff_employment",
    "staff_operational_role_period",
    "staff_position_period",
    "system_run",
    "system_run_event",
    "user_account",
}

EXPECTED_CONSTRAINTS = {
    "ex_staff_employment_period",
    "ex_staff_operational_role_period",
    "ex_staff_position_period",
    "fk_installation_state_first_admin_account_id_user_account",
}

EXPECTED_INDEXES = {
    "uq_account_permission_active",
    "uq_center_single_active",
    "uq_system_run_idempotency",
}


def verify_wave0_invariants(
    connection: Connection,
    *,
    expected_revision: str,
    expected_permission_count: int,
) -> None:
    database_name, server_port, search_path = connection.execute(
        text(
            """
            SELECT
                current_database(),
                inet_server_port(),
                current_setting('search_path')
            """
        )
    ).one()
    tables = set(
        connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'erp'")
        ).scalars()
    )
    missing_tables = sorted(EXPECTED_TABLES - tables)
    if missing_tables:
        raise SystemExit(
            "Missing Wave 0 tables "
            f"(database={database_name}, port={server_port}, "
            f"search_path={search_path}): {missing_tables}"
        )

    revision = connection.execute(text("SELECT version_num FROM erp.alembic_version")).scalar_one()
    if revision != expected_revision:
        raise SystemExit(f"Unexpected Alembic revision: {revision}")

    singleton_count = connection.execute(
        text("SELECT count(*) FROM erp.installation_state")
    ).scalar_one()
    if singleton_count != 1:
        raise SystemExit("installation_state singleton postcheck failed")

    extension_exists = connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'btree_gist')")
    ).scalar_one()
    if not extension_exists:
        raise SystemExit("btree_gist extension is missing")

    constraints = set(
        connection.execute(
            text(
                """
                SELECT conname
                FROM pg_constraint
                WHERE connamespace = 'erp'::regnamespace
                """
            )
        ).scalars()
    )
    missing_constraints = sorted(EXPECTED_CONSTRAINTS - constraints)
    if missing_constraints:
        raise SystemExit(f"Missing Wave 0 constraints: {missing_constraints}")

    indexes = set(
        connection.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = 'erp'")
        ).scalars()
    )
    missing_indexes = sorted(EXPECTED_INDEXES - indexes)
    if missing_indexes:
        raise SystemExit(f"Missing Wave 0 indexes: {missing_indexes}")

    permission_count = connection.execute(
        text("SELECT count(*) FROM erp.permission_definition")
    ).scalar_one()
    if permission_count != expected_permission_count:
        raise SystemExit(
            "Unexpected permission seed count: "
            f"{permission_count} (expected {expected_permission_count})"
        )

    timezone = connection.execute(text("SHOW timezone")).scalar_one()
    if timezone != "UTC":
        raise SystemExit(f"Database session timezone is not UTC: {timezone}")


def run_postcheck(
    *,
    expected_revision: str = WAVE0_REVISION,
    expected_permission_count: int = WAVE0_PERMISSION_COUNT,
    success_marker: str = "WAVE0_DB_POSTCHECK_OK",
) -> None:
    settings = get_settings()
    if settings.database_url is None:
        raise SystemExit("SSWCENTER_DATABASE_URL is required")

    engine = create_postgres_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            verify_wave0_invariants(
                connection,
                expected_revision=expected_revision,
                expected_permission_count=expected_permission_count,
            )
    finally:
        engine.dispose()

    print(success_marker)


def main() -> None:
    run_postcheck()


if __name__ == "__main__":
    main()
