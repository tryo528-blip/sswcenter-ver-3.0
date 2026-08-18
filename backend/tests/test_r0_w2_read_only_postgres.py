"""R0-A W2 read-only retirement integration contract.

This module is intentionally opt-in.  The paired PowerShell wrapper creates a
fresh PostgreSQL 17 cluster, supplies two disposable databases, and enables
``SSWCENTER_R0_W2_REAL_PG``.  No connection is opened during collection.

The test keeps the two migration paths separate:

* current path: empty -> 0018, minimal connected seed, preservation snapshot,
  then 0018 -> 0019;
* fresh path: empty -> 0019, no business rows.

All catalog and ACL assertions are read-only after the seed.  The only writes
performed by the test are the disposable migration/fixture operations inside
the owned cluster.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import DBAPIError

from alembic import command

CURRENT_REVISION = "20260809_0018_w2_service_plan_notice"
READ_ONLY_REVISION = "20260812_0019_r0_w2_read_only"
SERVICE_PLAN_TABLE = "erp.recipient_service_plan_notice"
SERVICE_PLAN_SEQUENCE = "erp.recipient_service_plan_notice_id_seq"

ACCOUNT_ID = 910010
ACCOUNT_STAFF_ID = 910000
RECIPIENT_ID = 910020
CONTRACT_ID = 910030
CERTIFICATION_PERIOD_ID = 910040
HISTORY_INVALIDATED_ID = 910001
HISTORY_ACTIVE_ID = 910002

W2_FUNCTIONS = frozenset(
    {
        "fn_service_plan_notice_before_contract_start",
        "fn_service_plan_notice_within_contract",
        "fn_service_plan_notice_within_certification",
        "fn_recipient_contract_service_plan_reverse_guard",
        "fn_recipient_certification_period_service_plan_reverse_guard",
        "fn_recipient_contract_recipient_id_immutable",
        "fn_recipient_certification_period_recipient_id_immutable",
    }
)
W2_GUARD_TRIGGERS = {
    "ct_service_plan_notice_before_contract_start": "recipient_service_plan_notice",
    "ct_service_plan_notice_within_contract": "recipient_service_plan_notice",
    "ct_service_plan_notice_within_certification": "recipient_service_plan_notice",
    "ct_recipient_contract_service_plan_reverse_guard": "recipient_contract",
    "ct_recipient_certification_period_service_plan_reverse_guard": (
        "recipient_certification_period"
    ),
}
W2_IMMUTABLE_TRIGGERS = {
    "ct_recipient_contract_recipient_id_immutable": "recipient_contract",
    "ct_recipient_certification_period_recipient_id_immutable": ("recipient_certification_period"),
}
W2_CONSTRAINTS = frozenset(
    {
        "pk_recipient_service_plan_notice",
        "fk_service_plan_notice_recipient_contract",
        "fk_service_plan_notice_replacement",
        "fk_service_plan_notice_created_by_account",
        "fk_service_plan_notice_updated_by_account",
        "ck_service_plan_notice_date_order",
        "ck_service_plan_notice_row_version_positive",
    }
)
TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
ALL_TABLE_PRIVILEGES = TABLE_PRIVILEGES + ("REFERENCES", "TRIGGER", "MAINTAIN")
SEQUENCE_PRIVILEGES = ("USAGE", "SELECT", "UPDATE")
EXPECTED_COLUMNS = (
    ("id", "bigint", "NO", "BY DEFAULT"),
    ("recipient_contract_id", "bigint", "NO", ""),
    ("notification_date", "date", "NO", ""),
    ("applied_start_date", "date", "NO", ""),
    ("applied_end_date", "date", "NO", ""),
    ("invalidated_at_utc", "timestamp with time zone", "YES", ""),
    ("replacement_service_plan_notice_id", "bigint", "YES", ""),
    ("created_by_account_id", "bigint", "NO", ""),
    ("created_at_utc", "timestamp with time zone", "NO", ""),
    ("updated_by_account_id", "bigint", "NO", ""),
    ("updated_at_utc", "timestamp with time zone", "NO", ""),
    ("row_version", "integer", "NO", ""),
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class DataSnapshot:
    count: int
    ids: tuple[int, ...]
    canonical_json: str
    canonical_sha256: str
    all_utc: bool


@dataclass(frozen=True)
class Scenario:
    current_before: dict[str, Any]
    current_after: dict[str, Any]
    fresh_after: dict[str, Any]
    current_data_before: DataSnapshot
    current_data_after: DataSnapshot
    fresh_data_after: DataSnapshot
    markers: tuple[str, ...]
    postcheck_failures: tuple[str, ...]


def _require_live_harness() -> None:
    if os.environ.get("SSWCENTER_R0_W2_REAL_PG") != "1":
        pytest.skip("requires the isolated R0 W2 PostgreSQL wrapper")


def _env_value(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"R0_ROOM2_HARNESS_ENV_MISSING: {name}", pytrace=False)
    return value


def _database_urls() -> dict[str, dict[str, str]]:
    urls = {
        "current": {
            "owner": _env_value("SSWCENTER_R0_W2_CURRENT_OWNER_URL"),
            "app": _env_value("SSWCENTER_R0_W2_CURRENT_APP_URL"),
            "backup": _env_value("SSWCENTER_R0_W2_CURRENT_BACKUP_URL"),
        },
        "fresh": {
            "owner": _env_value("SSWCENTER_R0_W2_FRESH_OWNER_URL"),
            "app": _env_value("SSWCENTER_R0_W2_FRESH_APP_URL"),
            "backup": _env_value("SSWCENTER_R0_W2_FRESH_BACKUP_URL"),
        },
    }
    expected_databases = {
        "current": "sswcenter_r0_current_test",
        "fresh": "sswcenter_r0_fresh_test",
    }
    for path_name, role_urls in urls.items():
        for role_name, database_url in role_urls.items():
            parsed = make_url(database_url)
            if parsed.get_backend_name() != "postgresql":
                pytest.fail(f"R0_ROOM2_NON_POSTGRES_URL: {path_name}/{role_name}")
            if parsed.host != "127.0.0.1" or parsed.port != 55447:
                pytest.fail(
                    f"R0_ROOM2_TARGET_MISMATCH: {path_name}/{role_name} "
                    f"host={parsed.host!r} port={parsed.port!r}"
                )
            if parsed.database != expected_databases[path_name]:
                pytest.fail(
                    f"R0_ROOM2_DATABASE_MISMATCH: {path_name}/{role_name} "
                    f"database={parsed.database!r}"
                )
            expected_user = {
                "owner": "erp_owner",
                "app": "erp_app",
                "backup": "erp_backup",
            }[role_name]
            if parsed.username != expected_user:
                pytest.fail(
                    f"R0_ROOM2_ROLE_MISMATCH: {path_name}/{role_name} role={parsed.username!r}"
                )
    if urls["current"]["owner"] == urls["fresh"]["owner"]:
        pytest.fail("R0_ROOM2_CURRENT_FRESH_TARGET_COLLISION")
    return urls


@contextlib.contextmanager
def _database_environment(database_url: str) -> Iterator[None]:
    from app.core.settings import get_settings

    previous = {
        key: os.environ.get(key) for key in ("SSWCENTER_DATABASE_URL", "SSWCENTER_ENVIRONMENT")
    }
    os.environ["SSWCENTER_DATABASE_URL"] = database_url
    os.environ["SSWCENTER_ENVIRONMENT"] = "test"
    get_settings.cache_clear()
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


def _upgrade(database_url: str, target: str) -> None:
    from app.core.settings import get_settings

    old_cwd = Path.cwd()
    with _database_environment(database_url):
        try:
            os.chdir(BACKEND_ROOT)
            get_settings.cache_clear()
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            command.upgrade(config, target)
        finally:
            os.chdir(old_cwd)


def _assert_empty_database(engine: Engine, label: str) -> None:
    with engine.connect() as connection:
        revision_table = connection.execute(
            text("SELECT to_regclass('erp.alembic_version')")
        ).scalar_one_or_none()
        if revision_table is not None:
            pytest.fail(f"R0_ROOM2_{label.upper()}_DATABASE_NOT_EMPTY: {revision_table}")


def _seed_current_path(engine: Engine) -> None:
    created_at = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    invalidated_at = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        service_type_id = connection.execute(
            text("SELECT id FROM erp.service_type WHERE code = 'HOME_CARE'")
        ).scalar_one()
        connection.execute(
            text(
                """
                INSERT INTO erp.staff (id, name, birth_date, sex_code, display_name, row_version)
                VALUES (:id, 'R0 ROOM2 ACCOUNT STAFF', DATE '1990-01-01', 'TEST',
                        'R0 ROOM2 ACCOUNT STAFF', 1)
                """
            ),
            {"id": ACCOUNT_STAFF_ID},
        )
        connection.execute(
            text(
                """
                INSERT INTO erp.user_account (
                    id, staff_id, account_code, display_name, role_code,
                    pin_hash, pin_lookup_hmac, pin_key_version, row_version
                )
                VALUES (
                    :id, :staff_id, 'R0_ROOM2_ACCOUNT', 'R0 ROOM2 ACCOUNT', 'ADMIN',
                    'r0-room2-test-pin-hash', :pin_lookup_hmac, 1, 1
                )
                """
            ),
            {
                "id": ACCOUNT_ID,
                "staff_id": ACCOUNT_STAFF_ID,
                "pin_lookup_hmac": bytes.fromhex("91" * 32),
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO erp.recipient (
                    id, name, birth_date, sex_code,
                    created_by_account_id, updated_by_account_id
                )
                VALUES (
                    :id, 'R0 ROOM2 RECIPIENT', DATE '1980-06-15', 'TEST',
                    :account_id, :account_id
                )
                """
            ),
            {"id": RECIPIENT_ID, "account_id": ACCOUNT_ID},
        )
        connection.execute(
            text(
                """
                INSERT INTO erp.recipient_contract (
                    id, recipient_id, service_type_id, start_date, end_date,
                    created_by_account_id, updated_by_account_id
                )
                VALUES (
                    :id, :recipient_id, :service_type_id,
                    DATE '2026-01-01', DATE '2026-12-31', :account_id, :account_id
                )
                """
            ),
            {
                "id": CONTRACT_ID,
                "recipient_id": RECIPIENT_ID,
                "service_type_id": service_type_id,
                "account_id": ACCOUNT_ID,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO erp.recipient_certification_identity (
                    recipient_id, certification_number,
                    created_by_account_id, updated_by_account_id
                )
                VALUES (
                    :recipient_id, 'L9100000001', :account_id, :account_id
                )
                """
            ),
            {"recipient_id": RECIPIENT_ID, "account_id": ACCOUNT_ID},
        )
        connection.execute(
            text(
                """
                INSERT INTO erp.recipient_certification_period (
                    id, recipient_id, start_date, end_date,
                    created_by_account_id, updated_by_account_id
                )
                VALUES (
                    :id, :recipient_id, DATE '2026-01-01', DATE '2026-12-31',
                    :account_id, :account_id
                )
                """
            ),
            {
                "id": CERTIFICATION_PERIOD_ID,
                "recipient_id": RECIPIENT_ID,
                "account_id": ACCOUNT_ID,
            },
        )
        connection.execute(
            text(
                f"""
                INSERT INTO {SERVICE_PLAN_TABLE} (
                    id, recipient_contract_id, notification_date,
                    applied_start_date, applied_end_date,
                    invalidated_at_utc, replacement_service_plan_notice_id,
                    created_by_account_id, created_at_utc,
                    updated_by_account_id, updated_at_utc, row_version
                )
                VALUES (
                    :invalidated_id, :contract_id, DATE '2026-01-15',
                    DATE '2026-01-01', DATE '2026-06-30', :invalidated_at,
                    :active_id, :account_id, :created_at,
                    :account_id, :created_at, 1
                ), (
                    :active_id, :contract_id, DATE '2026-07-01',
                    DATE '2026-07-01', DATE '2026-12-31', NULL, NULL,
                    :account_id, :created_at, :account_id, :created_at, 1
                )
                """
            ),
            {
                "invalidated_id": HISTORY_INVALIDATED_ID,
                "active_id": HISTORY_ACTIVE_ID,
                "contract_id": CONTRACT_ID,
                "account_id": ACCOUNT_ID,
                "invalidated_at": invalidated_at,
                "created_at": created_at,
            },
        )
        connection.execute(
            text(f"SELECT setval('{SERVICE_PLAN_SEQUENCE}', :value, true)"),
            {"value": HISTORY_ACTIVE_ID},
        )
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def _capture_data(engine: Engine) -> DataSnapshot:
    with engine.connect() as connection:
        connection.execute(text("SET TIME ZONE 'UTC'"))
        row = connection.execute(
            text(
                f"""
                SELECT
                    count(*)::integer AS row_count,
                    COALESCE(array_agg(id ORDER BY id), ARRAY[]::bigint[]) AS ids,
                    COALESCE(
                        jsonb_agg(to_jsonb(ordered) ORDER BY id),
                        '[]'::jsonb
                    )::text AS canonical_json,
                    COALESCE(
                        bool_and(
                            EXTRACT(TIMEZONE FROM created_at_utc) = 0
                            AND EXTRACT(TIMEZONE FROM updated_at_utc) = 0
                            AND (
                                invalidated_at_utc IS NULL
                                OR EXTRACT(TIMEZONE FROM invalidated_at_utc) = 0
                            )
                        ),
                        true
                    ) AS all_utc
                FROM (
                    SELECT *
                    FROM {SERVICE_PLAN_TABLE}
                    ORDER BY id
                ) AS ordered
                """
            )
        ).one()
    canonical_json = str(row.canonical_json)
    return DataSnapshot(
        count=int(row.row_count),
        ids=tuple(int(value) for value in (row.ids or [])),
        canonical_json=canonical_json,
        canonical_sha256=hashlib.sha256(canonical_json.encode("utf-8")).hexdigest().upper(),
        all_utc=bool(row.all_utc),
    )


def _capture_rows(
    connection: Connection,
    statement: str,
    parameters: dict[str, Any] | None = None,
) -> tuple[tuple[Any, ...], ...]:
    rows = connection.execute(text(statement), parameters or {}).all()
    return tuple(tuple(_normalize_value(value) for value in row) for row in rows)


def _normalize_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return tuple(_normalize_value(item) for item in value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def _capture_catalog(engine: Engine) -> dict[str, Any]:
    with engine.connect() as connection:
        columns = _capture_rows(
            connection,
            """
            SELECT ordinal_position, column_name, data_type,
                   is_nullable, COALESCE(identity_generation, '')
            FROM information_schema.columns
            WHERE table_schema = 'erp' AND table_name = 'recipient_service_plan_notice'
            ORDER BY ordinal_position
            """,
        )
        constraints = _capture_rows(
            connection,
            """
            SELECT c.conname, c.contype,
                   COALESCE(pg_get_constraintdef(c.oid, true), ''),
                   COALESCE(c.confdeltype::text, ''),
                   COALESCE(c.confupdtype::text, ''),
                   COALESCE(c.confmatchtype::text, ''),
                   c.condeferrable, c.condeferred, c.convalidated,
                   COALESCE(array_to_string(c.conkey, ','), ''),
                   COALESCE(array_to_string(c.confkey, ','), '')
            FROM pg_constraint c
            WHERE c.conrelid = 'erp.recipient_service_plan_notice'::regclass
              AND c.contype IN ('p', 'f', 'c')
            ORDER BY c.conname
            """,
        )
        pk_index = _capture_rows(
            connection,
            """
            SELECT index_class.relname, index_info.indisprimary,
                   index_info.indisunique, index_info.indisvalid,
                   index_info.indisready, pg_get_indexdef(index_class.oid)
            FROM pg_index index_info
            JOIN pg_class index_class ON index_class.oid = index_info.indexrelid
            WHERE index_info.indrelid = 'erp.recipient_service_plan_notice'::regclass
              AND index_info.indisprimary
            """,
        )
        identity_dependency = _capture_rows(
            connection,
            """
            SELECT dependency.deptype::text, sequence_class.relname,
                   table_class.relname, dependency.refobjsubid,
                   dependency.objsubid, attribute.attname
            FROM pg_depend dependency
            JOIN pg_class sequence_class
              ON sequence_class.oid = dependency.objid
             AND sequence_class.relkind = 'S'
            JOIN pg_namespace sequence_namespace
              ON sequence_namespace.oid = sequence_class.relnamespace
            JOIN pg_class table_class ON table_class.oid = dependency.refobjid
            JOIN pg_attribute attribute
              ON attribute.attrelid = table_class.oid
             AND attribute.attnum = dependency.refobjsubid
            WHERE dependency.refobjid = 'erp.recipient_service_plan_notice'::regclass
              AND sequence_namespace.nspname = 'erp'
              AND sequence_class.relname = 'recipient_service_plan_notice_id_seq'
            ORDER BY dependency.deptype, dependency.refobjsubid
            """,
        )
        pg_sequence = _capture_rows(
            connection,
            """
            SELECT sequence_info.seqstart::text, sequence_info.seqincrement::text,
                   sequence_info.seqmax::text, sequence_info.seqmin::text,
                   sequence_info.seqcache::text, sequence_info.seqcycle
            FROM pg_sequence sequence_info
            JOIN pg_class sequence_class ON sequence_class.oid = sequence_info.seqrelid
            JOIN pg_namespace sequence_namespace
              ON sequence_namespace.oid = sequence_class.relnamespace
            WHERE sequence_namespace.nspname = 'erp'
              AND sequence_class.relname = 'recipient_service_plan_notice_id_seq'
            """,
        )
        sequence_state = _capture_rows(
            connection,
            f"SELECT last_value::text, is_called FROM {SERVICE_PLAN_SEQUENCE}",
        )
        functions = _capture_rows(
            connection,
            """
            SELECT procedure.proname,
                   pg_get_function_identity_arguments(procedure.oid),
                   procedure.provolatile::text, procedure.prosecdef,
                   procedure.prokind, pg_get_functiondef(procedure.oid)
            FROM pg_proc procedure
            WHERE procedure.pronamespace = 'erp'::regnamespace
              AND procedure.proname = ANY(:names)
            ORDER BY procedure.proname,
                     pg_get_function_identity_arguments(procedure.oid)
            """,
            {"names": sorted(W2_FUNCTIONS)},
        )
        trigger_names = sorted(set(W2_GUARD_TRIGGERS) | set(W2_IMMUTABLE_TRIGGERS))
        triggers = _capture_rows(
            connection,
            """
            SELECT trigger_info.tgname, table_class.relname, trigger_info.tgenabled,
                   trigger_info.tgdeferrable, trigger_info.tginitdeferred,
                   pg_get_triggerdef(trigger_info.oid, true)
            FROM pg_trigger trigger_info
            JOIN pg_class table_class ON table_class.oid = trigger_info.tgrelid
            JOIN pg_namespace table_namespace
              ON table_namespace.oid = table_class.relnamespace
            WHERE table_namespace.nspname = 'erp'
              AND NOT trigger_info.tgisinternal
              AND trigger_info.tgname = ANY(:names)
            ORDER BY trigger_info.tgname, table_class.relname
            """,
            {"names": trigger_names},
        )
        guard_trigger_count = int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM pg_trigger trigger_info
                    JOIN pg_namespace table_namespace
                      ON table_namespace.oid = (
                          SELECT relnamespace FROM pg_class WHERE oid = trigger_info.tgrelid
                      )
                    WHERE table_namespace.nspname = 'erp'
                      AND NOT trigger_info.tgisinternal
                      AND trigger_info.tgname = ANY(:names)
                    """
                ),
                {"names": sorted(W2_GUARD_TRIGGERS)},
            ).scalar_one()
        )
        owners = _capture_rows(
            connection,
            """
            SELECT pg_get_userbyid(table_class.relowner),
                   pg_get_userbyid(sequence_class.relowner),
                   pg_get_serial_sequence(
                       'erp.recipient_service_plan_notice', 'id'
                   )
            FROM pg_class table_class
            JOIN pg_namespace table_namespace
              ON table_namespace.oid = table_class.relnamespace
            JOIN pg_class sequence_class
              ON sequence_class.relname = 'recipient_service_plan_notice_id_seq'
             AND sequence_class.relnamespace = table_namespace.oid
             AND sequence_class.relkind = 'S'
            WHERE table_namespace.nspname = 'erp'
              AND table_class.relname = 'recipient_service_plan_notice'
              AND table_class.relkind = 'r'
            """,
        )
        raw_acl = {
            "schema": _capture_rows(
                connection,
                "SELECT nspacl::text FROM pg_namespace WHERE nspname = 'erp'",
            ),
            "table": _capture_rows(
                connection,
                """
                SELECT relacl::text
                FROM pg_class
                WHERE oid = 'erp.recipient_service_plan_notice'::regclass
                """,
            ),
            "sequence": _capture_rows(
                connection,
                (
                    "SELECT relacl::text FROM pg_class "
                    f"WHERE oid = '{SERVICE_PLAN_SEQUENCE}'::regclass"
                ),
            ),
            "columns": _capture_rows(
                connection,
                """
                SELECT attname, attacl::text
                FROM pg_attribute
                WHERE attrelid = 'erp.recipient_service_plan_notice'::regclass
                  AND attnum > 0 AND NOT attisdropped
                ORDER BY attnum
                """,
            ),
        }
        effective_acl: dict[str, Any] = {
            "schema": {},
            "table": {},
            "sequence": {},
        }
        for role_name in ("erp_app", "erp_backup"):
            effective_acl["schema"][role_name] = tuple(
                bool(
                    connection.execute(
                        text("SELECT has_schema_privilege(:role_name, 'erp', :privilege)"),
                        {"role_name": role_name, "privilege": privilege},
                    ).scalar_one()
                )
                for privilege in ("USAGE", "CREATE")
            )
            effective_acl["table"][role_name] = tuple(
                bool(
                    connection.execute(
                        text("SELECT has_table_privilege(:role_name, :table_name, :privilege)"),
                        {
                            "role_name": role_name,
                            "table_name": SERVICE_PLAN_TABLE,
                            "privilege": privilege,
                        },
                    ).scalar_one()
                )
                for privilege in ALL_TABLE_PRIVILEGES
            )
            effective_acl["sequence"][role_name] = tuple(
                bool(
                    connection.execute(
                        text(
                            "SELECT has_sequence_privilege(:role_name, :sequence_name, :privilege)"
                        ),
                        {
                            "role_name": role_name,
                            "sequence_name": SERVICE_PLAN_SEQUENCE,
                            "privilege": privilege,
                        },
                    ).scalar_one()
                )
                for privilege in SEQUENCE_PRIVILEGES
            )

    return {
        "owners": owners,
        "columns": columns,
        "constraints": constraints,
        "pk_index": pk_index,
        "identity_dependency": identity_dependency,
        "pg_sequence": pg_sequence,
        "sequence_state": sequence_state,
        "functions": functions,
        "triggers": triggers,
        "guard_trigger_count": guard_trigger_count,
        "raw_acl": raw_acl,
        "effective_acl": effective_acl,
    }


def _assert_catalog_contract(snapshot: dict[str, Any], *, read_only: bool) -> None:
    columns = tuple(
        (str(row[1]), str(row[2]), str(row[3]), str(row[4])) for row in snapshot["columns"]
    )
    assert columns == EXPECTED_COLUMNS
    assert len(snapshot["columns"]) == 12

    constraint_names = {str(row[0]) for row in snapshot["constraints"]}
    assert len(snapshot["constraints"]) == 7
    assert constraint_names == set(W2_CONSTRAINTS)
    constraint_by_name = {str(row[0]): row for row in snapshot["constraints"]}
    assert constraint_by_name["pk_recipient_service_plan_notice"][1] == "p"
    assert constraint_by_name["fk_service_plan_notice_replacement"][6:9] == (
        True,
        True,
        True,
    )
    assert all(row[8] is True for row in snapshot["constraints"])

    assert len(snapshot["owners"]) == 1
    assert snapshot["owners"][0] == ("erp_owner", "erp_owner", SERVICE_PLAN_SEQUENCE)
    assert len(snapshot["pk_index"]) == 1
    assert snapshot["pk_index"][0][0] == "pk_recipient_service_plan_notice"
    assert snapshot["pk_index"][0][1:5] == (True, True, True, True)
    assert snapshot["identity_dependency"] == (
        ("i", "recipient_service_plan_notice_id_seq", "recipient_service_plan_notice", 1, 0, "id"),
    )
    assert len(snapshot["pg_sequence"]) == 1
    assert len(snapshot["sequence_state"]) == 1

    function_names = {str(row[0]) for row in snapshot["functions"]}
    assert function_names == set(W2_FUNCTIONS)
    assert len(snapshot["functions"]) == 7
    assert all(str(row[5]).strip() for row in snapshot["functions"])

    trigger_pairs = {(str(row[0]), str(row[1])) for row in snapshot["triggers"]}
    immutable_pairs = set(W2_IMMUTABLE_TRIGGERS.items())
    guard_pairs = set(W2_GUARD_TRIGGERS.items())
    if read_only:
        assert snapshot["guard_trigger_count"] == 0
        assert trigger_pairs == immutable_pairs
    else:
        assert snapshot["guard_trigger_count"] == len(W2_GUARD_TRIGGERS)
        assert trigger_pairs == immutable_pairs | guard_pairs

    expected_app_table = (
        (True, False, False, False, False, False, False, False)
        if read_only
        else (True, True, True, False, False, False, False, False)
    )
    expected_backup_table = (True, False, False, False, False, False, False, False)
    expected_app_sequence = (False, True, False) if read_only else (True, True, False)
    assert snapshot["effective_acl"]["table"]["erp_app"] == expected_app_table
    assert snapshot["effective_acl"]["table"]["erp_backup"] == expected_backup_table
    assert snapshot["effective_acl"]["sequence"]["erp_app"] == expected_app_sequence
    assert snapshot["effective_acl"]["sequence"]["erp_backup"] == (False, True, False)
    assert snapshot["effective_acl"]["schema"]["erp_app"] == (True, False)
    assert snapshot["effective_acl"]["schema"]["erp_backup"] == (True, False)


def _run_postcheck(database_url: str, expected_marker: str) -> str | None:
    from app.db import postcheck_w1a_vs1

    output = io.StringIO()
    with _database_environment(database_url):
        try:
            with contextlib.redirect_stdout(output):
                postcheck_w1a_vs1.main()
        except SystemExit as exc:
            evidence_engine = create_engine(database_url, pool_pre_ping=True)
            try:
                with evidence_engine.connect() as evidence_connection:
                    w1c_trigger_rows = _capture_rows(
                        evidence_connection,
                        """
                        SELECT trigger_info.tgname, table_class.relname,
                               trigger_info.tgdeferrable,
                               trigger_info.tginitdeferred
                        FROM pg_trigger trigger_info
                        JOIN pg_class table_class
                          ON table_class.oid = trigger_info.tgrelid
                        WHERE trigger_info.tgrelid IN (
                            'erp.recipient_certification_period'::regclass,
                            'erp.recipient_grade_period'::regclass
                        )
                          AND NOT trigger_info.tgisinternal
                        ORDER BY trigger_info.tgname
                        """,
                    )
            finally:
                evidence_engine.dispose()
            failure = (
                "R0_ROOM2_POSTCHECK_FAILED: "
                f"marker={expected_marker} exit={exc.code}; "
                "W1C_TRIGGER_CATALOG="
                f"{w1c_trigger_rows!r}"
            )
            print(failure)
            return failure
    captured = output.getvalue()
    assert captured.count(expected_marker) == 1
    print(expected_marker)
    return expected_marker


def _sqlstate(error: DBAPIError) -> str | None:
    original = getattr(error, "orig", error)
    sqlstate = getattr(original, "sqlstate", None)
    if sqlstate:
        return str(sqlstate)
    pgcode = getattr(original, "pgcode", None)
    if pgcode:
        return str(pgcode)
    diagnostics = getattr(original, "diag", None)
    diagnostic_state = getattr(diagnostics, "sqlstate", None)
    return str(diagnostic_state) if diagnostic_state else None


def _expect_permission_denied(engine: Engine, label: str, statement: str) -> None:
    try:
        with engine.connect() as connection:
            with connection.begin():
                connection.execute(text(statement))
    except DBAPIError as exc:
        state = _sqlstate(exc)
        assert state == "42501", f"{label}: expected SQLSTATE 42501, got {state!r}"
    else:
        pytest.fail(f"{label}: mutation unexpectedly succeeded", pytrace=False)


def _assert_runtime_role(
    database_url: str,
    role_name: str,
    expected_count: int,
    expected_sequence_value: int,
) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            identity = connection.execute(
                text(f"SELECT current_user, count(*)::integer FROM {SERVICE_PLAN_TABLE}")
            ).one()
            assert identity[0] == role_name
            assert int(identity[1]) == expected_count
            sequence_value = connection.execute(
                text(f"SELECT last_value FROM {SERVICE_PLAN_SEQUENCE}")
            ).scalar_one()
            assert int(sequence_value) == expected_sequence_value

        statements = {
            "INSERT": f"""
                INSERT INTO {SERVICE_PLAN_TABLE} (
                    recipient_contract_id, notification_date,
                    applied_start_date, applied_end_date,
                    created_by_account_id, updated_by_account_id
                ) VALUES (
                    {CONTRACT_ID}, DATE '2026-01-01', DATE '2026-01-01',
                    DATE '2026-01-01', {ACCOUNT_ID}, {ACCOUNT_ID}
                )
            """,
            "UPDATE": f"UPDATE {SERVICE_PLAN_TABLE} SET row_version = row_version + 1",
            "DELETE": f"DELETE FROM {SERVICE_PLAN_TABLE}",
            "TRUNCATE": f"TRUNCATE TABLE {SERVICE_PLAN_TABLE}",
            "nextval": f"SELECT nextval('{SERVICE_PLAN_SEQUENCE}')",
            "setval": f"SELECT setval('{SERVICE_PLAN_SEQUENCE}', 1, true)",
        }
        for operation, statement in statements.items():
            _expect_permission_denied(
                engine,
                f"{role_name} {operation}",
                statement,
            )
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def scenario() -> Scenario:
    _require_live_harness()
    urls = _database_urls()
    current_engine = create_engine(urls["current"]["owner"], pool_pre_ping=True)
    fresh_engine = create_engine(urls["fresh"]["owner"], pool_pre_ping=True)
    postcheck_failures: list[str] = []
    try:
        _assert_empty_database(current_engine, "current")
        _assert_empty_database(fresh_engine, "fresh")

        _upgrade(urls["current"]["owner"], CURRENT_REVISION)
        _seed_current_path(current_engine)
        current_marker_0018 = _run_postcheck(
            urls["current"]["owner"],
            "W2_SERVICE_PLAN_NOTICE_DB_POSTCHECK_OK",
        )
        if current_marker_0018 is not None and current_marker_0018.startswith(
            "R0_ROOM2_POSTCHECK_FAILED:"
        ):
            postcheck_failures.append(current_marker_0018)
        current_data_before = _capture_data(current_engine)
        current_catalog_before = _capture_catalog(current_engine)
        _assert_catalog_contract(current_catalog_before, read_only=False)
        assert current_data_before.count == 2
        assert current_data_before.ids == (HISTORY_INVALIDATED_ID, HISTORY_ACTIVE_ID)
        assert current_data_before.all_utc is True

        _upgrade(urls["current"]["owner"], READ_ONLY_REVISION)
        current_data_after = _capture_data(current_engine)
        current_catalog_after = _capture_catalog(current_engine)
        current_marker_0019 = _run_postcheck(
            urls["current"]["owner"],
            "R0_W2_READ_ONLY_DB_POSTCHECK_OK",
        )
        if current_marker_0019 is not None and current_marker_0019.startswith(
            "R0_ROOM2_POSTCHECK_FAILED:"
        ):
            postcheck_failures.append(current_marker_0019)
        _assert_catalog_contract(current_catalog_after, read_only=True)
        assert current_data_after == current_data_before

        _upgrade(urls["fresh"]["owner"], READ_ONLY_REVISION)
        fresh_data_after = _capture_data(fresh_engine)
        fresh_catalog_after = _capture_catalog(fresh_engine)
        fresh_marker_0019 = _run_postcheck(
            urls["fresh"]["owner"],
            "R0_W2_READ_ONLY_DB_POSTCHECK_OK",
        )
        if fresh_marker_0019 is not None and fresh_marker_0019.startswith(
            "R0_ROOM2_POSTCHECK_FAILED:"
        ):
            postcheck_failures.append(fresh_marker_0019)
        _assert_catalog_contract(fresh_catalog_after, read_only=True)
        assert fresh_data_after.count == 0
        assert fresh_data_after.ids == ()
        assert fresh_data_after.all_utc is True

        structural_keys = (
            "owners",
            "columns",
            "constraints",
            "pk_index",
            "identity_dependency",
            "pg_sequence",
            "functions",
            "triggers",
            "guard_trigger_count",
            "raw_acl",
            "effective_acl",
        )
        for key in structural_keys:
            assert current_catalog_after[key] == fresh_catalog_after[key], key
        assert current_catalog_before["owners"] == current_catalog_after["owners"]
        assert current_catalog_before["columns"] == current_catalog_after["columns"]
        assert current_catalog_before["constraints"] == current_catalog_after["constraints"]
        assert current_catalog_before["pk_index"] == current_catalog_after["pk_index"]
        assert (
            current_catalog_before["identity_dependency"]
            == current_catalog_after["identity_dependency"]
        )
        assert current_catalog_before["pg_sequence"] == current_catalog_after["pg_sequence"]
        assert current_catalog_before["sequence_state"] == current_catalog_after["sequence_state"]
        assert current_catalog_before["functions"] == current_catalog_after["functions"]
        assert (
            current_catalog_before["raw_acl"]["schema"]
            == current_catalog_after["raw_acl"]["schema"]
        )
        assert (
            current_catalog_before["raw_acl"]["columns"]
            == current_catalog_after["raw_acl"]["columns"]
        )

        markers = tuple(
            marker
            for marker in (current_marker_0018, current_marker_0019, fresh_marker_0019)
            if marker is not None
        )
        print(
            "R0_ROOM2_DATA "
            f"current_count={current_data_after.count} "
            f"current_ids={','.join(str(value) for value in current_data_after.ids)} "
            f"current_sha={current_data_after.canonical_sha256} "
            f"fresh_count={fresh_data_after.count}"
        )
        return Scenario(
            current_before=current_catalog_before,
            current_after=current_catalog_after,
            fresh_after=fresh_catalog_after,
            current_data_before=current_data_before,
            current_data_after=current_data_after,
            fresh_data_after=fresh_data_after,
            markers=markers,
            postcheck_failures=tuple(postcheck_failures),
        )
    finally:
        current_engine.dispose()
        fresh_engine.dispose()


def test_current_path_preserves_rows_and_runs_postchecks(scenario: Scenario) -> None:
    assert not scenario.postcheck_failures, (
        "official postcheck did not produce the required exact marker: "
        + " | ".join(scenario.postcheck_failures)
    )
    assert scenario.current_data_before.count == 2
    assert scenario.current_data_after.count == 2
    assert scenario.current_data_after.ids == (HISTORY_INVALIDATED_ID, HISTORY_ACTIVE_ID)
    assert scenario.current_data_after == scenario.current_data_before
    assert (
        scenario.current_data_after.canonical_sha256
        == scenario.current_data_before.canonical_sha256
    )
    assert scenario.markers == (
        "W2_SERVICE_PLAN_NOTICE_DB_POSTCHECK_OK",
        "R0_W2_READ_ONLY_DB_POSTCHECK_OK",
        "R0_W2_READ_ONLY_DB_POSTCHECK_OK",
    )


def test_fresh_path_is_empty_and_catalog_acl_matches_current(scenario: Scenario) -> None:
    assert scenario.fresh_data_after.count == 0
    assert scenario.fresh_data_after.ids == ()
    current_after = dict(scenario.current_after)
    fresh_after = dict(scenario.fresh_after)
    current_after.pop("sequence_state")
    fresh_after.pop("sequence_state")
    assert current_after == fresh_after
    assert scenario.current_after["sequence_state"] == ((str(HISTORY_ACTIVE_ID), True),)
    assert scenario.fresh_after["sequence_state"] == (("1", False),)


def test_current_path_exact_preservation_contract(scenario: Scenario) -> None:
    for key in (
        "owners",
        "columns",
        "constraints",
        "pk_index",
        "identity_dependency",
        "pg_sequence",
        "sequence_state",
        "functions",
    ):
        assert scenario.current_before[key] == scenario.current_after[key], key
    assert (
        scenario.current_before["raw_acl"]["schema"] == scenario.current_after["raw_acl"]["schema"]
    )
    assert (
        scenario.current_before["raw_acl"]["columns"]
        == scenario.current_after["raw_acl"]["columns"]
    )


def test_real_app_and_backup_logins_are_read_only(scenario: Scenario) -> None:
    del scenario
    urls = _database_urls()
    for path_name, expected_count in (("current", 2), ("fresh", 0)):
        expected_sequence_value = HISTORY_ACTIVE_ID if path_name == "current" else 1
        _assert_runtime_role(
            urls[path_name]["app"],
            "erp_app",
            expected_count,
            expected_sequence_value,
        )
        _assert_runtime_role(
            urls[path_name]["backup"],
            "erp_backup",
            expected_count,
            expected_sequence_value,
        )
