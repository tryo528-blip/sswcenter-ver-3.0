import os
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.script.revision import RevisionError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

DATABASE_URL = os.environ.get("SSWCENTER_DATABASE_URL")
APP_DATABASE_URL = os.environ.get("SSWCENTER_APP_DATABASE_URL")
BACKUP_DATABASE_URL = os.environ.get("SSWCENTER_BACKUP_DATABASE_URL")
W1A_BASE_REVISION = "20260726_0003_w1a_staff"
ALEMBIC_CONFIG_PATH = Path(__file__).resolve().parents[1] / "alembic.ini"


def _is_w1a_revision_or_descendant(revision: str | None) -> bool:
    if not revision:
        return False
    try:
        script_directory = ScriptDirectory.from_config(Config(str(ALEMBIC_CONFIG_PATH)))
        script_directory.get_revision(W1A_BASE_REVISION)
        revision_range = script_directory.revision_map.iterate_revisions(
            revision,
            W1A_BASE_REVISION,
            inclusive=True,
        )
        return any(candidate.revision == W1A_BASE_REVISION for candidate in revision_range)
    except (OSError, RevisionError):
        return False


def require_w1_schema(conn: Connection) -> None:
    """Helper to check schema presence before running queries."""
    has_erp_alembic = conn.execute(
        text("SELECT to_regclass('erp.alembic_version') IS NOT NULL")
    ).scalar()
    has_public_alembic = conn.execute(
        text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
    ).scalar()

    rev = None
    if has_erp_alembic:
        rev = conn.execute(text("SELECT version_num FROM erp.alembic_version")).scalar()
    elif has_public_alembic:
        rev = conn.execute(text("SELECT version_num FROM public.alembic_version")).scalar()
    else:
        pytest.fail("W1A_DB_SCHEMA_MISSING: alembic_version table does not exist")

    if not _is_w1a_revision_or_descendant(rev):
        pytest.fail("W1A_DB_REVISION_MISSING: Alembic revision is not W1A base or descendant")

    has_sensitive_table = conn.execute(
        text("SELECT to_regclass('erp.staff_sensitive_identity') IS NOT NULL")
    ).scalar()
    if not has_sensitive_table:
        pytest.fail("W1A_DB_SCHEMA_MISSING: Table erp.staff_sensitive_identity is missing")


@pytest.mark.skipif(
    not DATABASE_URL,
    reason="SSWCENTER_DATABASE_URL environment variable is required for PostgreSQL test",
)
def test_w1a_postgres_migration_revision_and_tables() -> None:
    """Verify revision 20260726_0003_w1a_staff and staff_sensitive_identity table structure."""
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        require_w1_schema(conn)

        # Check erp.staff_sensitive_identity columns
        columns_query = text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'erp' AND table_name = 'staff_sensitive_identity'
        """)
        cols = {row.column_name: row for row in conn.execute(columns_query)}
        expected_cols = {
            "staff_id",
            "resident_number_ciphertext",
            "resident_number_nonce",
            "resident_number_key_version",
            "resident_number_lookup_hmac",
            "encrypted_at_utc",
            "updated_at_utc",
            "row_version",
        }
        if not expected_cols.issubset(set(cols.keys())):
            missing_columns = expected_cols - set(cols.keys())
            pytest.fail(
                "W1A_DB_COLUMNS_MISSING: Missing columns in "
                f"staff_sensitive_identity: {missing_columns}"
            )

        # Check check constraints
        checks_query = text("""
            SELECT conname FROM pg_constraint
            WHERE connamespace = 'erp'::regnamespace
              AND conrelid = 'erp.staff_sensitive_identity'::regclass
        """)
        constraints = {row.conname for row in conn.execute(checks_query)}
        expected_checks = {
            "ck_staff_sensitive_identity_ciphertext_nonempty",
            "ck_staff_sensitive_identity_nonce_length",
            "ck_staff_sensitive_identity_key_version_positive",
            "ck_staff_sensitive_identity_lookup_hmac_length",
        }
        if not expected_checks.issubset(constraints):
            missing_checks = expected_checks - constraints
            pytest.fail(f"W1A_DB_CONSTRAINTS_MISSING: Missing check constraints: {missing_checks}")

        definitions = {
            row.conname: row.definition
            for row in conn.execute(
                text(
                    """
                    SELECT conname, pg_get_constraintdef(oid) AS definition
                    FROM pg_constraint
                    WHERE connamespace = 'erp'::regnamespace
                      AND conname IN (
                          'ck_staff_sex_code',
                          'ck_staff_operational_role_period_role_code_format'
                      )
                    """
                )
            )
        }
        assert all(
            value in definitions["ck_staff_sex_code"] for value in ("MALE", "FEMALE", "TEST")
        )
        assert (
            "^[A-Z][A-Z0-9_]{0,49}$"
            in definitions["ck_staff_operational_role_period_role_code_format"]
        )


@pytest.mark.skipif(
    not DATABASE_URL,
    reason="SSWCENTER_DATABASE_URL environment variable is required for PostgreSQL test",
)
def test_w1a_postgres_containment_and_reverse_guard_triggers() -> None:
    """Verify deferred containment and reverse-guard triggers."""
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        require_w1_schema(conn)

        triggers_query = text("""
            SELECT tgname, tgdeferrable, tginitdeferred FROM pg_trigger
            WHERE tgrelid IN (
                'erp.staff_position_period'::regclass,
                'erp.staff_operational_role_period'::regclass,
                'erp.staff_employment'::regclass
            )
        """)
        triggers = {row.tgname: row for row in conn.execute(triggers_query)}
        expected_triggers = {
            "ct_staff_position_within_employment",
            "ct_staff_operational_role_within_employment",
            "ct_staff_employment_child_periods_reverse_guard",
        }
        if not expected_triggers.issubset(triggers):
            pytest.fail(
                "W1A_DB_TRIGGERS_MISSING: Missing required constraint triggers: "
                f"{expected_triggers - set(triggers)}"
            )
        for trigger_name in expected_triggers:
            trigger = triggers[trigger_name]
            assert trigger.tgdeferrable is True
            assert trigger.tginitdeferred is True


@pytest.mark.skipif(
    not DATABASE_URL,
    reason="SSWCENTER_DATABASE_URL environment variable is required for PostgreSQL test",
)
def test_w1a_postgres_app_roles_permissions_and_grants() -> None:
    """Verify seeded permissions and erp_app / erp_backup role grants."""
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        require_w1_schema(conn)

        perms = set(
            conn.execute(
                text(
                    """
                    SELECT permission_code
                    FROM erp.permission_definition
                    WHERE permission_code IN ('STAFF_VIEW', 'STAFF_MANAGE')
                    """
                )
            ).scalars()
        )
        if perms != {"STAFF_VIEW", "STAFF_MANAGE"}:
            pytest.fail(
                "W1A_DB_PERMISSIONS_MISSING: STAFF_VIEW and STAFF_MANAGE "
                "must be seeded in erp.permission_definition"
            )

    assert APP_DATABASE_URL is not None
    app_engine = create_engine(APP_DATABASE_URL)
    with app_engine.connect() as app_conn:
        app_privileges = app_conn.execute(
            text(
                """
                SELECT
                    has_schema_privilege(current_user, 'erp', 'USAGE') AS schema_usage,
                    has_schema_privilege(current_user, 'erp', 'CREATE') AS schema_create,
                    has_table_privilege(
                        current_user,
                        'erp.staff_sensitive_identity',
                        'SELECT'
                    ) AS sensitive_select,
                    has_table_privilege(
                        current_user,
                        'erp.staff_sensitive_identity',
                        'INSERT'
                    ) AS sensitive_insert,
                    has_table_privilege(
                        current_user,
                        'erp.staff_sensitive_identity',
                        'UPDATE'
                    ) AS sensitive_update,
                    has_table_privilege(
                        current_user,
                        'erp.staff_sensitive_identity',
                        'DELETE'
                    ) AS sensitive_delete,
                    has_table_privilege(
                        current_user,
                        'erp.access_event',
                        'DELETE'
                    ) AS access_delete,
                    has_table_privilege(
                        current_user,
                        'erp.audit_event',
                        'DELETE'
                    ) AS audit_delete
                """
            )
        ).one()
        assert app_privileges.schema_usage is True
        assert app_privileges.schema_create is False
        assert app_privileges.sensitive_select is True
        assert app_privileges.sensitive_insert is True
        assert app_privileges.sensitive_update is True
        assert app_privileges.sensitive_delete is False
        assert app_privileges.access_delete is False
        assert app_privileges.audit_delete is False

        sensitive_acl = app_conn.execute(
            text(
                """
                SELECT
                    has_schema_privilege(current_user, 'erp', 'USAGE') AS schema_usage,
                    has_schema_privilege(current_user, 'erp', 'CREATE') AS schema_create,
                    has_table_privilege(
                        current_user, 'erp.staff_sensitive_identity', 'SELECT'
                    ) AS can_select,
                    has_table_privilege(
                        current_user, 'erp.staff_sensitive_identity', 'INSERT'
                    ) AS can_insert,
                    has_table_privilege(
                        current_user, 'erp.staff_sensitive_identity', 'UPDATE'
                    ) AS can_update,
                    has_table_privilege(
                        current_user, 'erp.staff_sensitive_identity', 'DELETE'
                    ) AS can_delete,
                    has_table_privilege(
                        current_user, 'erp.staff_sensitive_identity', 'TRUNCATE'
                    ) AS can_truncate
                """
            )
        ).one()
        assert tuple(sensitive_acl) == (True, False, True, True, True, False, False)

        sequence_acl = app_conn.execute(
            text(
                """
                SELECT
                    c.relname,
                    has_sequence_privilege(
                        current_user, format('erp.%I', c.relname), 'USAGE'
                    ) AS can_use,
                    has_sequence_privilege(
                        current_user, format('erp.%I', c.relname), 'SELECT'
                    ) AS can_select,
                    has_sequence_privilege(
                        current_user, format('erp.%I', c.relname), 'UPDATE'
                    ) AS can_update
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'erp' AND c.relkind = 'S'
                ORDER BY c.relname
                """
            )
        ).all()
        assert sequence_acl
        assert all(row.can_use and row.can_select and not row.can_update for row in sequence_acl)

    assert BACKUP_DATABASE_URL is not None
    backup_engine = create_engine(BACKUP_DATABASE_URL)
    with backup_engine.connect() as backup_conn:
        backup_privileges = backup_conn.execute(
            text(
                """
                SELECT
                    has_table_privilege(
                        current_user,
                        'erp.staff_sensitive_identity',
                        'SELECT'
                    ) AS sensitive_select,
                    has_table_privilege(
                        current_user,
                        'erp.staff_sensitive_identity',
                        'INSERT'
                    ) AS sensitive_insert,
                    has_table_privilege(
                        current_user,
                        'erp.staff',
                        'UPDATE'
                    ) AS staff_update
                """
            )
        ).one()
        assert backup_privileges.sensitive_select is True
        assert backup_privileges.sensitive_insert is False
        assert backup_privileges.staff_update is False

        backup_sequence_acl = backup_conn.execute(
            text(
                """
                SELECT
                    bool_and(
                        has_sequence_privilege(
                            current_user, format('erp.%I', c.relname), 'SELECT'
                        )
                    ) AS all_select,
                    bool_and(
                        NOT has_sequence_privilege(
                            current_user, format('erp.%I', c.relname), 'USAGE'
                        )
                    ) AS no_usage
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'erp' AND c.relkind = 'S'
                """
            )
        ).one()
        assert backup_sequence_acl.all_select is True
        assert backup_sequence_acl.no_usage is True


@pytest.mark.skipif(
    not DATABASE_URL,
    reason="SSWCENTER_DATABASE_URL environment variable is required for PostgreSQL test",
)
def test_w1a_postgres_no_plaintext_rrn_columns() -> None:
    """Verify zero plaintext RRN columns exist across all tables in erp schema."""
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        query = text("""
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'erp'
              AND (
                  column_name LIKE '%rrn%'
                  OR column_name LIKE '%resident_number%'
                  OR column_name LIKE '%jumin%'
              )
              AND column_name NOT IN (
                  'resident_number_ciphertext',
                  'resident_number_nonce',
                  'resident_number_key_version',
                  'resident_number_lookup_hmac'
              )
        """)
        rows = conn.execute(query).fetchall()
        if len(rows) > 0:
            pytest.fail(
                "W1A_DB_PLAINTEXT_RRN_COLUMN_FOUND: "
                f"Plaintext RRN column detected in erp schema: {rows}"
            )
