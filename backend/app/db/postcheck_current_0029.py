"""Fail-closed current-head catalog check for W3 0029."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import Table, UniqueConstraint, inspect, text
from sqlalchemy.engine import Connection

from app.core.settings import get_settings
from app.db import models as wave0_models  # noqa: F401
from app.db import w2_models as current_w2_models  # noqa: F401
from app.db import w3_models as current_w3_models  # noqa: F401
from app.db.base import Base
from app.db.postcheck_current_0027 import verify_current_0027
from app.db.session import create_postgres_engine

EXPECTED_REVISION = "20260818_0029_w3_persistent_apply_workspace"
W3_0029_REVISION = EXPECTED_REVISION
CURRENT_0029_MARKER = "SSWCENTER_CURRENT_0029_DB_POSTCHECK_OK"
HEAD_MARKER = "SSWCENTER_CURRENT_HEAD_POSTCHECK_OK"

FOUNDATION_TABLES = frozenset(
    {
        "w3_private_content",
        "w3_source_snapshot",
        "w3_source_receipt",
        "w3_import_run",
        "w3_import_attempt",
        "w3_source_row",
    }
)
REQUIRED_0029_TABLES = frozenset(
    {
        "w3_import_run_event",
        "w3_normalized_nhis_row",
        "w3_normalized_rfid_row",
        "w3_nhis_group",
        "w3_nhis_group_member",
        "w3_match_decision",
        "w3_apply_control",
        "w3_actual_work_revision",
        "w3_manual_supplement_event",
        "w3_plan_adjustment_event",
    }
)
REQUIRED_W3_TABLES = FOUNDATION_TABLES | REQUIRED_0029_TABLES
FORBIDDEN_GENERIC_COLUMNS = frozenset({"target_type", "target_id", "public_url", "content_bytes"})

MUTABLE_COLUMNS: Mapping[str, frozenset[str]] = {
    "w3_source_snapshot": frozenset({"status"}),
    "w3_import_run": frozenset({"status", "row_version"}),
    "w3_apply_control": frozenset(
        {
            "active_snapshot_id",
            "active_import_run_id",
            "row_version",
            "updated_by_account_id",
            "updated_at_utc",
        }
    ),
    "w3_actual_work_revision": frozenset({"superseded_at_utc"}),
}


def _fail(code: str, detail: object) -> None:
    raise SystemExit(f"CURRENT_0029_{code}: {detail}")


def _verify_revision(connection: Connection) -> None:
    revisions: Sequence[object] = (
        connection.execute(text("SELECT version_num FROM erp.alembic_version")).scalars().all()
    )
    if revisions != [EXPECTED_REVISION]:
        _fail("REVISION_MISMATCH", f"expected={[EXPECTED_REVISION]} actual={revisions!r}")


def _expected_w3_metadata() -> dict[str, Table]:
    result = {
        table.name: table
        for table in Base.metadata.tables.values()
        if table.schema == "erp" and table.name in REQUIRED_W3_TABLES
    }
    if set(result) != REQUIRED_W3_TABLES:
        _fail(
            "MODEL_TABLE_MISMATCH",
            f"missing={sorted(REQUIRED_W3_TABLES - set(result))} "
            f"extra={sorted(set(result) - REQUIRED_W3_TABLES)}",
        )
    return result


def _verify_table_inventory(connection: Connection) -> None:
    rows = connection.execute(
        text(
            """
            SELECT relation_row.relname, relation_row.relkind,
                   relation_row.relpersistence,
                   owner_role.rolname AS owner_name,
                   relation_row.relrowsecurity,
                   relation_row.relforcerowsecurity
              FROM pg_class AS relation_row
              JOIN pg_namespace AS namespace_row
                ON namespace_row.oid = relation_row.relnamespace
              JOIN pg_roles AS owner_role
                ON owner_role.oid = relation_row.relowner
             WHERE namespace_row.nspname = 'erp'
               AND left(relation_row.relname, 3) = 'w3_'
               AND relation_row.relkind IN ('r', 'p', 'v', 'm', 'f')
             ORDER BY relation_row.relname
            """
        )
    ).mappings()
    actual = {str(row["relname"]): row for row in rows}
    if set(actual) != REQUIRED_W3_TABLES:
        _fail(
            "TABLE_MISMATCH",
            f"missing={sorted(REQUIRED_W3_TABLES - set(actual))} "
            f"extra={sorted(set(actual) - REQUIRED_W3_TABLES)}",
        )
    drift = {
        name: {
            "relkind": row["relkind"],
            "persistence": row["relpersistence"],
            "owner": row["owner_name"],
            "rls": bool(row["relrowsecurity"]),
            "force_rls": bool(row["relforcerowsecurity"]),
        }
        for name, row in actual.items()
        if row["relkind"] != "r"
        or row["relpersistence"] != "p"
        or row["owner_name"] != "erp_owner"
        or bool(row["relrowsecurity"])
        or bool(row["relforcerowsecurity"])
    }
    if drift:
        _fail("RELATION_DRIFT", drift)


def _verify_columns(connection: Connection, expected_tables: Mapping[str, Table]) -> None:
    inspector = inspect(connection)
    for table_name, expected_table in expected_tables.items():
        actual_rows = inspector.get_columns(table_name, schema="erp")
        actual = {str(row["name"]): row for row in actual_rows}
        expected_names = set(expected_table.columns.keys())
        if set(actual) != expected_names:
            _fail(
                "COLUMN_MISMATCH",
                f"table={table_name} missing={sorted(expected_names - set(actual))} "
                f"extra={sorted(set(actual) - expected_names)}",
            )
        for column in expected_table.columns:
            row = actual[column.name]
            if bool(row["nullable"]) != bool(column.nullable):
                _fail(
                    "COLUMN_NULLABILITY_MISMATCH",
                    f"table={table_name} column={column.name} "
                    f"expected={column.nullable} actual={row['nullable']}",
                )
            expected_identity = column.identity is not None
            actual_identity = isinstance(row.get("identity"), dict)
            if expected_identity != actual_identity:
                _fail(
                    "COLUMN_IDENTITY_MISMATCH",
                    f"table={table_name} column={column.name}",
                )

    forbidden = connection.execute(
        text(
            """
            SELECT table_name, column_name
              FROM information_schema.columns
             WHERE table_schema = 'erp'
               AND table_name = ANY(:tables)
               AND (column_name = ANY(:forbidden) OR data_type = 'bytea')
             ORDER BY table_name, ordinal_position
            """
        ),
        {"tables": sorted(REQUIRED_W3_TABLES), "forbidden": sorted(FORBIDDEN_GENERIC_COLUMNS)},
    ).all()
    if forbidden:
        _fail("FORBIDDEN_COLUMN", forbidden)


def _normalize_columns(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def _verify_keys_and_indexes(
    connection: Connection,
    expected_tables: Mapping[str, Table],
) -> None:
    inspector = inspect(connection)
    for table_name, expected_table in expected_tables.items():
        expected_pk = tuple(column.name for column in expected_table.primary_key.columns)
        actual_pk = _normalize_columns(
            inspector.get_pk_constraint(table_name, schema="erp").get("constrained_columns")
        )
        if actual_pk != expected_pk:
            _fail(
                "PRIMARY_KEY_MISMATCH",
                f"table={table_name} expected={expected_pk} actual={actual_pk}",
            )

        expected_uniques = {
            constraint.name: tuple(column.name for column in constraint.columns)
            for constraint in expected_table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        actual_uniques = {
            str(item["name"]): _normalize_columns(item.get("column_names"))
            for item in inspector.get_unique_constraints(table_name, schema="erp")
        }
        if actual_uniques != expected_uniques:
            _fail(
                "UNIQUE_MISMATCH",
                f"table={table_name} expected={expected_uniques} actual={actual_uniques}",
            )

        expected_fks = {
            constraint.name: (
                tuple(column.name for column in constraint.columns),
                constraint.referred_table.name,
                tuple(element.column.name for element in constraint.elements),
                str(constraint.ondelete or "").upper(),
            )
            for constraint in expected_table.foreign_key_constraints
        }
        actual_fks = {
            str(item["name"]): (
                _normalize_columns(item.get("constrained_columns")),
                str(item.get("referred_table")),
                _normalize_columns(item.get("referred_columns")),
                str((item.get("options") or {}).get("ondelete") or "").upper(),
            )
            for item in inspector.get_foreign_keys(table_name, schema="erp")
        }
        if actual_fks != expected_fks:
            _fail(
                "FOREIGN_KEY_MISMATCH",
                f"table={table_name} expected={expected_fks} actual={actual_fks}",
            )
        if any(signature[3] != "RESTRICT" for signature in actual_fks.values()):
            _fail("FOREIGN_KEY_DELETE_ACTION", f"table={table_name} actual={actual_fks}")

        expected_checks = {
            str(constraint.name)
            for constraint in expected_table.constraints
            if constraint.__class__.__name__ == "CheckConstraint"
        }
        actual_checks = {
            str(item["name"])
            for item in inspector.get_check_constraints(table_name, schema="erp")
        }
        if actual_checks != expected_checks:
            _fail(
                "CHECK_MISMATCH",
                f"table={table_name} missing={sorted(expected_checks - actual_checks)} "
                f"extra={sorted(actual_checks - expected_checks)}",
            )

        expected_indexes = {
            index.name: (tuple(column.name for column in index.columns), bool(index.unique))
            for index in expected_table.indexes
        }
        actual_indexes = {
            str(item["name"]): (_normalize_columns(item.get("column_names")), bool(item["unique"]))
            for item in inspector.get_indexes(table_name, schema="erp")
            if not bool(item.get("duplicates_constraint"))
        }
        if actual_indexes != expected_indexes:
            _fail(
                "INDEX_MISMATCH",
                f"table={table_name} expected={expected_indexes} actual={actual_indexes}",
            )

    invalid = connection.execute(
        text(
            """
            SELECT constraint_row.conname
              FROM pg_constraint AS constraint_row
              JOIN pg_class AS relation_row ON relation_row.oid = constraint_row.conrelid
              JOIN pg_namespace AS namespace_row ON namespace_row.oid = relation_row.relnamespace
             WHERE namespace_row.nspname = 'erp'
               AND relation_row.relname = ANY(:tables)
               AND (NOT constraint_row.convalidated
                    OR constraint_row.condeferrable
                    OR constraint_row.condeferred)
            """
        ),
        {"tables": sorted(REQUIRED_W3_TABLES)},
    ).scalars().all()
    if invalid:
        _fail("CONSTRAINT_VALIDATION_MISMATCH", sorted(str(item) for item in invalid))


def _verify_no_trigger_or_policy_bypass(connection: Connection) -> None:
    triggers = connection.execute(
        text(
            """
            SELECT relation_row.relname, trigger_row.tgname, trigger_row.tgenabled
              FROM pg_trigger AS trigger_row
              JOIN pg_class AS relation_row ON relation_row.oid = trigger_row.tgrelid
              JOIN pg_namespace AS namespace_row ON namespace_row.oid = relation_row.relnamespace
             WHERE namespace_row.nspname = 'erp'
               AND relation_row.relname = ANY(:tables)
               AND NOT trigger_row.tgisinternal
            """
        ),
        {"tables": sorted(REQUIRED_W3_TABLES)},
    ).all()
    if triggers:
        _fail("NONINTERNAL_TRIGGER_PRESENT", triggers)

    policies = connection.execute(
        text(
            """
            SELECT relation_row.relname, policy_row.polname
              FROM pg_policy AS policy_row
              JOIN pg_class AS relation_row ON relation_row.oid = policy_row.polrelid
              JOIN pg_namespace AS namespace_row ON namespace_row.oid = relation_row.relnamespace
             WHERE namespace_row.nspname = 'erp'
               AND relation_row.relname = ANY(:tables)
            """
        ),
        {"tables": sorted(REQUIRED_W3_TABLES)},
    ).all()
    if policies:
        _fail("RLS_POLICY_PRESENT", policies)


def _verify_acl(connection: Connection) -> None:
    for table_name in sorted(REQUIRED_W3_TABLES):
        relation = f"erp.{table_name}"
        values = connection.execute(
            text(
                """
                SELECT has_table_privilege('erp_app', :relation, 'SELECT') AS app_select,
                       has_table_privilege('erp_app', :relation, 'INSERT') AS app_insert,
                       has_table_privilege('erp_app', :relation, 'UPDATE') AS app_update,
                       has_table_privilege('erp_app', :relation, 'DELETE') AS app_delete,
                       has_table_privilege('erp_app', :relation, 'TRUNCATE') AS app_truncate,
                       has_table_privilege('erp_backup', :relation, 'SELECT') AS backup_select,
                       has_table_privilege('erp_backup', :relation, 'INSERT') AS backup_insert,
                       has_table_privilege('erp_backup', :relation, 'UPDATE') AS backup_update,
                       has_table_privilege('erp_backup', :relation, 'DELETE') AS backup_delete,
                       has_table_privilege('erp_backup', :relation, 'TRUNCATE') AS backup_truncate
                """
            ),
            {"relation": relation},
        ).mappings().one()
        if not bool(values["app_select"]) or not bool(values["app_insert"]):
            _fail("APP_BASE_ACL_MISMATCH", f"table={table_name} actual={dict(values)}")
        if any(bool(values[key]) for key in ("app_update", "app_delete", "app_truncate")):
            _fail("APP_TABLE_WIDE_MUTATION_GRANT", f"table={table_name} actual={dict(values)}")
        if not bool(values["backup_select"]) or any(
            bool(values[key])
            for key in ("backup_insert", "backup_update", "backup_delete", "backup_truncate")
        ):
            _fail("BACKUP_ACL_MISMATCH", f"table={table_name} actual={dict(values)}")

        columns = {
            str(row["column_name"]): bool(row["can_update"])
            for row in connection.execute(
                text(
                    """
                    SELECT column_name,
                           has_column_privilege(
                               'erp_app', :relation, column_name, 'UPDATE'
                           ) AS can_update
                      FROM information_schema.columns
                     WHERE table_schema = 'erp' AND table_name = :table_name
                    """
                ),
                {"relation": relation, "table_name": table_name},
            ).mappings()
        }
        actual_mutable = {name for name, allowed in columns.items() if allowed}
        expected_mutable = set(MUTABLE_COLUMNS.get(table_name, frozenset()))
        if actual_mutable != expected_mutable:
            _fail(
                "COLUMN_ACL_MISMATCH",
                f"table={table_name} expected={sorted(expected_mutable)} "
                f"actual={sorted(actual_mutable)}",
            )


def _verify_permission_definitions(connection: Connection) -> None:
    rows = [
        (str(row[0]), bool(row[1]))
        for row in connection.execute(
            text(
                """
                SELECT permission_code, active
                  FROM erp.permission_definition
                 WHERE permission_code IN ('W3_VIEW', 'W3_MANAGE')
                 ORDER BY permission_code
                """
            )
        ).all()
    ]
    if rows != [("W3_MANAGE", True), ("W3_VIEW", True)]:
        _fail("PERMISSION_DEFINITION_MISMATCH", rows)


def verify_current_0029(connection: Connection) -> None:
    _verify_revision(connection)
    verify_current_0027(connection, skip_revision=True)
    expected_tables = _expected_w3_metadata()
    _verify_table_inventory(connection)
    _verify_columns(connection, expected_tables)
    _verify_keys_and_indexes(connection, expected_tables)
    _verify_no_trigger_or_policy_bypass(connection)
    _verify_permission_definitions(connection)
    _verify_acl(connection)


def main() -> None:
    database_url = get_settings().database_url
    if not database_url:
        raise SystemExit("CURRENT_0029_DATABASE_URL_MISSING")
    engine = create_postgres_engine(database_url)
    try:
        with engine.connect() as connection:
            verify_current_0029(connection)
    finally:
        engine.dispose()
    print(CURRENT_0029_MARKER)
    print(HEAD_MARKER)


if __name__ == "__main__":
    main()
