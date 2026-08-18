"""Fail-closed current-head postcheck for 0027's composite W2 graph."""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.settings import get_settings
from app.db.postcheck_current_0026 import (
    ERP_APP_READ_ONLY_PRIVILEGES,
    ERP_APP_WRITE_PRIVILEGES,
    _privileges,
    verify_current_0026,
)
from app.db.session import create_postgres_engine

EXPECTED_REVISION = "20260817_0027_w2_official_card_assignee_and_plan_replacement"

COMPOSITE_FOREIGN_KEYS = {
    "fk_w2_service_plan_notice_contract_same_recipient": {
        "columns": ("recipient_id", "recipient_contract_id"),
        "referenced_table": "erp.recipient_contract",
        "referenced_columns": ("recipient_id", "id"),
        "deferrable": False,
        "deferred": False,
    },
    "fk_w2_service_plan_notice_replacement_same_recipient": {
        "columns": ("recipient_id", "replacement_service_plan_notice_id"),
        "referenced_table": "erp.w2_service_plan_notice",
        "referenced_columns": ("recipient_id", "id"),
        "deferrable": True,
        "deferred": True,
    },
}

COMPOSITE_UNIQUES = {
    "uq_recipient_contract_recipient_id_id": (
        "erp.recipient_contract",
        ("recipient_id", "id"),
    ),
    "uq_w2_service_plan_notice_recipient_id_id": (
        "erp.w2_service_plan_notice",
        ("recipient_id", "id"),
    ),
}

OBSOLETE_TRIGGER_NAMES = frozenset(
    {
        "ct_w2_service_plan_replacement_same_recipient",
        "ct_w2_service_plan_replacement_contract_reverse",
    }
)
OBSOLETE_FUNCTION_NAMES = frozenset(
    {
        "fn_w2_service_plan_replacement_same_recipient",
        "fn_w2_service_plan_replacement_contract_reverse",
    }
)
OBSOLETE_SIMPLE_FOREIGN_KEYS = frozenset(
    {
        "fk_w2_service_plan_notice_contract",
        "fk_w2_service_plan_notice_replacement",
    }
)


def _as_names(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(str(value) for value in values)


def _verify_recipient_column(connection: Connection) -> None:
    row = connection.execute(
        text(
            """
            SELECT data_type, is_nullable
              FROM information_schema.columns
             WHERE table_schema = 'erp'
               AND table_name = 'w2_service_plan_notice'
               AND column_name = 'recipient_id'
            """
        )
    ).one_or_none()
    if row is None or tuple(row) != ("bigint", "NO"):
        raise SystemExit(f"CURRENT_0027_RECIPIENT_COLUMN_MISMATCH: {row!r}")


def _foreign_key_rows(connection: Connection) -> dict[str, dict[str, object]]:
    rows = connection.execute(
        text(
            """
            SELECT constraint_row.conname,
                   referenced_namespace.nspname || '.' || referenced_relation.relname
                       AS referenced_table,
                   constraint_row.condeferrable,
                   constraint_row.condeferred,
                   constraint_row.convalidated,
                   constraint_row.confdeltype,
                   constraint_row.confupdtype,
                   array_agg(local_column.attname ORDER BY local_key.ordinality)
                       AS local_columns,
                   array_agg(referenced_column.attname ORDER BY local_key.ordinality)
                       AS referenced_columns
              FROM pg_constraint AS constraint_row
              JOIN LATERAL unnest(constraint_row.conkey)
                   WITH ORDINALITY AS local_key(attnum, ordinality) ON true
              JOIN pg_attribute AS local_column
                ON local_column.attrelid = constraint_row.conrelid
               AND local_column.attnum = local_key.attnum
              JOIN LATERAL unnest(constraint_row.confkey)
                   WITH ORDINALITY AS referenced_key(attnum, ordinality)
                ON referenced_key.ordinality = local_key.ordinality
              JOIN pg_attribute AS referenced_column
                ON referenced_column.attrelid = constraint_row.confrelid
               AND referenced_column.attnum = referenced_key.attnum
              JOIN pg_class AS referenced_relation
                ON referenced_relation.oid = constraint_row.confrelid
              JOIN pg_namespace AS referenced_namespace
                ON referenced_namespace.oid = referenced_relation.relnamespace
             WHERE constraint_row.conrelid = 'erp.w2_service_plan_notice'::regclass
               AND constraint_row.contype = 'f'
             GROUP BY constraint_row.oid,
                      referenced_namespace.nspname,
                      referenced_relation.relname
            """
        )
    ).mappings()
    return {str(row["conname"]): dict(row) for row in rows}


def _verify_composite_foreign_keys(connection: Connection) -> None:
    rows = _foreign_key_rows(connection)
    stale = sorted(OBSOLETE_SIMPLE_FOREIGN_KEYS & rows.keys())
    if stale:
        raise SystemExit(f"CURRENT_0027_SIMPLE_FOREIGN_KEY_PRESENT: {stale}")

    failures: dict[str, dict[str, object]] = {}
    for name, expected in COMPOSITE_FOREIGN_KEYS.items():
        actual = rows.get(name)
        if actual is None:
            failures[name] = {"missing": True}
            continue
        observed = {
            "columns": _as_names(cast(Iterable[object], actual["local_columns"])),
            "referenced_table": str(actual["referenced_table"]),
            "referenced_columns": _as_names(cast(Iterable[object], actual["referenced_columns"])),
            "deferrable": bool(actual["condeferrable"]),
            "deferred": bool(actual["condeferred"]),
            "validated": bool(actual["convalidated"]),
            "delete_action": str(actual["confdeltype"]),
            "update_action": str(actual["confupdtype"]),
        }
        if (
            observed["columns"] != expected["columns"]
            or observed["referenced_table"] != expected["referenced_table"]
            or observed["referenced_columns"] != expected["referenced_columns"]
            or observed["deferrable"] != expected["deferrable"]
            or observed["deferred"] != expected["deferred"]
            or not observed["validated"]
            or observed["delete_action"] != "r"  # RESTRICT
            or observed["update_action"] != "a"  # NO ACTION
        ):
            failures[name] = observed
    if failures:
        raise SystemExit(f"CURRENT_0027_COMPOSITE_FOREIGN_KEY_MISMATCH: {failures}")


def _verify_composite_uniques(connection: Connection) -> None:
    rows = connection.execute(
        text(
            """
            SELECT con.conname,
                   relation_namespace.nspname || '.' || relation_row.relname
                       AS table_name,
                   con.condeferrable,
                   con.condeferred,
                   con.convalidated,
                   pg_get_expr(index_row.indpred, index_row.indrelid) AS predicate,
                   array_agg(attribute_row.attname ORDER BY key.ordinality) AS columns
              FROM pg_constraint AS con
              JOIN pg_index AS index_row ON index_row.indexrelid = con.conindid
              JOIN pg_class AS relation_row ON relation_row.oid = con.conrelid
              JOIN pg_namespace AS relation_namespace
                ON relation_namespace.oid = relation_row.relnamespace
              JOIN LATERAL unnest(con.conkey)
                   WITH ORDINALITY AS key(attnum, ordinality) ON true
              JOIN pg_attribute AS attribute_row
                ON attribute_row.attrelid = con.conrelid
               AND attribute_row.attnum = key.attnum
             WHERE con.contype = 'u'
               AND con.conname = ANY(:names)
             GROUP BY con.oid,
                      index_row.indpred,
                      index_row.indrelid,
                      relation_namespace.nspname,
                      relation_row.relname
            """
        ),
        {"names": list(COMPOSITE_UNIQUES)},
    ).mappings()
    actual = {str(row["conname"]): dict(row) for row in rows}
    failures: dict[str, dict[str, object]] = {}
    for name, (table_name, columns) in COMPOSITE_UNIQUES.items():
        row = actual.get(name)
        if row is None:
            failures[name] = {"missing": True}
            continue
        observed = {
            "table_name": str(row["table_name"]),
            "columns": _as_names(row["columns"]),
            "deferrable": bool(row["condeferrable"]),
            "deferred": bool(row["condeferred"]),
            "validated": bool(row["convalidated"]),
            "predicate": row["predicate"],
        }
        if (
            observed["table_name"] != table_name
            or observed["columns"] != columns
            or observed["deferrable"]
            or observed["deferred"]
            or not observed["validated"]
            or observed["predicate"] is not None
        ):
            failures[name] = observed
    if failures:
        raise SystemExit(f"CURRENT_0027_COMPOSITE_UNIQUE_MISMATCH: {failures}")


def _verify_no_obsolete_procedural_guard(connection: Connection) -> None:
    triggers = {
        str(value)
        for value in connection.scalars(
            text(
                """
                SELECT trigger_row.tgname
                  FROM pg_trigger AS trigger_row
                  JOIN pg_class AS relation_row ON relation_row.oid = trigger_row.tgrelid
                  JOIN pg_namespace AS namespace_row
                    ON namespace_row.oid = relation_row.relnamespace
                 WHERE namespace_row.nspname = 'erp'
                   AND NOT trigger_row.tgisinternal
                   AND trigger_row.tgname = ANY(:names)
                """
            ),
            {"names": list(OBSOLETE_TRIGGER_NAMES)},
        )
    }
    functions = {
        str(value)
        for value in connection.scalars(
            text(
                """
                SELECT procedure_row.proname
                  FROM pg_proc AS procedure_row
                  JOIN pg_namespace AS namespace_row
                    ON namespace_row.oid = procedure_row.pronamespace
                 WHERE namespace_row.nspname = 'erp'
                   AND procedure_row.proname = ANY(:names)
                """
            ),
            {"names": list(OBSOLETE_FUNCTION_NAMES)},
        )
    }
    if triggers or functions:
        raise SystemExit(
            "CURRENT_0027_OBSOLETE_PROCEDURAL_GUARD_PRESENT: "
            f"triggers={sorted(triggers)} functions={sorted(functions)}"
        )


def _verify_acl(connection: Connection) -> None:
    if _privileges(connection, "erp_app", "w2_service_plan_notice") != ERP_APP_WRITE_PRIVILEGES:
        raise SystemExit("CURRENT_0027_SERVICE_PLAN_APP_ACL_MISMATCH")
    if (
        _privileges(connection, "erp_backup", "w2_service_plan_notice")
        != ERP_APP_READ_ONLY_PRIVILEGES
    ):
        raise SystemExit("CURRENT_0027_SERVICE_PLAN_BACKUP_ACL_MISMATCH")


def _verify_revision(connection: Connection) -> None:
    """Require the sole historical 0027 Alembic head, never a scalar lookalike."""

    revisions = [
        str(value)
        for value in connection.execute(text("SELECT version_num FROM erp.alembic_version"))
        .scalars()
        .all()
    ]
    if revisions != [EXPECTED_REVISION]:
        raise SystemExit(
            f"CURRENT_0027_REVISION_MISMATCH: expected={[EXPECTED_REVISION]} actual={revisions}"
        )


def verify_current_0027(connection: Connection, *, skip_revision: bool = False) -> None:
    if not skip_revision:
        _verify_revision(connection)

    # 0027 adds to, rather than weakens, every 0026 postcheck boundary.
    verify_current_0026(connection, skip_revision=True)
    _verify_recipient_column(connection)
    _verify_composite_foreign_keys(connection)
    _verify_composite_uniques(connection)
    _verify_no_obsolete_procedural_guard(connection)
    _verify_acl(connection)


def main() -> None:
    database_url = get_settings().database_url
    if not database_url:
        raise SystemExit("CURRENT_0027_DATABASE_URL_MISSING")
    engine = create_postgres_engine(database_url)
    try:
        with engine.connect() as connection:
            verify_current_0027(connection)
    finally:
        engine.dispose()
    print("SSWCENTER_CURRENT_0027_DB_POSTCHECK_OK")


if __name__ == "__main__":
    main()
