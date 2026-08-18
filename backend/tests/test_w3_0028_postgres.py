"""Isolated PostgreSQL proofs for the 0028 W3 source-intake foundation."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from typing import NoReturn

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.core.readiness import database_catalog_is_ready
from app.db.postcheck_current_0028 import (
    ACTIVE_PARTIAL_UNIQUE,
    CURRENT_0028_MARKER,
    EXPECTED_OWNER,
    EXPECTED_REVISION,
    HEAD_MARKER,
    PG16_COLUMN_OWNER_PRIVILEGES,
    PG16_SCHEMA_OWNER_PRIVILEGES,
    PG16_SEQUENCE_OWNER_PRIVILEGES,
    PG16_TABLE_OWNER_PRIVILEGES,
    is_expected_active_partial_unique_conflict,
    verify_current_0028,
)
from app.db.postcheck_dispatch import dispatch_current_head

CURRENT_REVISION = "20260817_0028_w3_source_intake_foundation"
DIGEST_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
DIGEST_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
DIGEST_C = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
DIGEST_D = "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _sqlstate_of(error: BaseException) -> str | None:
    original = getattr(error, "orig", None)
    if original is None:
        return None
    diagnostic = getattr(original, "diag", None)
    sqlstate = getattr(original, "sqlstate", None)
    if sqlstate is None:
        sqlstate = getattr(diagnostic, "sqlstate", None)
    if sqlstate is None:
        sqlstate = getattr(original, "pgcode", None)
    return str(sqlstate) if sqlstate is not None else None


def _exploded_class_acl(connection: Connection, relname: str) -> set[tuple[str, str, str, bool]]:
    rows = connection.execute(
        text(
            """
            SELECT CASE
                     WHEN acl.grantee = 0 THEN 'PUBLIC'
                     ELSE grantee.rolname
                   END AS grantee,
                   CASE
                     WHEN acl.grantor = 0 THEN 'PUBLIC'
                     ELSE grantor.rolname
                   END AS grantor,
                   acl.privilege_type,
                   acl.is_grantable
              FROM pg_class AS relation_row
              JOIN pg_namespace AS namespace_row
                ON namespace_row.oid = relation_row.relnamespace
              LEFT JOIN LATERAL aclexplode(relation_row.relacl) AS acl ON true
              LEFT JOIN pg_roles AS grantee
                ON grantee.oid = acl.grantee
              LEFT JOIN pg_roles AS grantor
                ON grantor.oid = acl.grantor
             WHERE namespace_row.nspname = 'erp'
               AND relation_row.relname = :relname
               AND acl.privilege_type IS NOT NULL
            """
        ),
        {"relname": relname},
    ).mappings()
    return {
        (
            str(row["grantee"] or "PUBLIC"),
            str(row["grantor"] or "UNKNOWN"),
            str(row["privilege_type"]),
            bool(row["is_grantable"]),
        )
        for row in rows
    }


def _exploded_schema_acl(connection: Connection) -> set[tuple[str, str, str, bool]]:
    rows = connection.execute(
        text(
            """
            SELECT CASE
                     WHEN acl.grantee = 0 THEN 'PUBLIC'
                     ELSE grantee.rolname
                   END AS grantee,
                   CASE
                     WHEN acl.grantor = 0 THEN 'PUBLIC'
                     ELSE grantor.rolname
                   END AS grantor,
                   acl.privilege_type,
                   acl.is_grantable
              FROM pg_namespace AS namespace_row
              LEFT JOIN LATERAL aclexplode(namespace_row.nspacl) AS acl ON true
              LEFT JOIN pg_roles AS grantee
                ON grantee.oid = acl.grantee
              LEFT JOIN pg_roles AS grantor
                ON grantor.oid = acl.grantor
             WHERE namespace_row.nspname = 'erp'
               AND acl.privilege_type IS NOT NULL
            """
        )
    ).mappings()
    return {
        (
            str(row["grantee"] or "PUBLIC"),
            str(row["grantor"] or "UNKNOWN"),
            str(row["privilege_type"]),
            bool(row["is_grantable"]),
        )
        for row in rows
    }


def _exploded_column_acl(
    connection: Connection, table_name: str, column_name: str
) -> set[tuple[str, str, str, bool]]:
    rows = connection.execute(
        text(
            """
            SELECT CASE
                     WHEN acl.grantee = 0 THEN 'PUBLIC'
                     ELSE grantee.rolname
                   END AS grantee,
                   CASE
                     WHEN acl.grantor = 0 THEN 'PUBLIC'
                     ELSE grantor.rolname
                   END AS grantor,
                   acl.privilege_type,
                   acl.is_grantable
              FROM pg_attribute AS attribute_row
              JOIN pg_class AS relation_row
                ON relation_row.oid = attribute_row.attrelid
              JOIN pg_namespace AS namespace_row
                ON namespace_row.oid = relation_row.relnamespace
              LEFT JOIN LATERAL aclexplode(attribute_row.attacl) AS acl ON true
              LEFT JOIN pg_roles AS grantee
                ON grantee.oid = acl.grantee
              LEFT JOIN pg_roles AS grantor
                ON grantor.oid = acl.grantor
             WHERE namespace_row.nspname = 'erp'
               AND relation_row.relname = :table_name
               AND attribute_row.attname = :column_name
               AND attribute_row.attnum > 0
               AND NOT attribute_row.attisdropped
               AND acl.privilege_type IS NOT NULL
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).mappings()
    return {
        (
            str(row["grantee"] or "PUBLIC"),
            str(row["grantor"] or "UNKNOWN"),
            str(row["privilege_type"]),
            bool(row["is_grantable"]),
        )
        for row in rows
    }


def _owner_privileges(entries: set[tuple[str, str, str, bool]]) -> set[str]:
    return {
        privilege
        for grantee, grantor, privilege, grantable in entries
        if grantee == EXPECTED_OWNER and grantor == EXPECTED_OWNER and not grantable
    }


def _assert_dispatch_markers_absent(
    connection: Connection,
    capsys: pytest.CaptureFixture[str],
    match: str,
) -> None:
    # Historical helper name retained for stable test-node history.  Once 0029
    # became current, catalog-drift assertions must call the 0028 verifier
    # directly; the dispatcher correctly rejects 0028 before catalog checks.
    capsys.readouterr()
    with pytest.raises(SystemExit, match=match):
        verify_current_0028(connection)
    output = capsys.readouterr().out
    assert CURRENT_0028_MARKER not in output
    assert HEAD_MARKER not in output


def _assert_dispatch_markers_present(
    connection: Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    capsys.readouterr()
    verify_current_0028(connection)
    output = capsys.readouterr().out
    assert CURRENT_0028_MARKER not in output
    assert HEAD_MARKER not in output


def _restore_active_partial_unique(connection: Connection) -> None:
    name, _table, columns, predicate = ACTIVE_PARTIAL_UNIQUE
    connection.execute(text(f"DROP INDEX IF EXISTS erp.{name}"))
    column_sql = ", ".join(columns)
    connection.execute(
        text(
            f"CREATE UNIQUE INDEX {name} ON erp.w3_source_snapshot ({column_sql}) WHERE {predicate}"
        )
    )


@pytest.fixture(scope="session")
def database_engine() -> Iterator[Engine]:
    if os.environ.get("SSWCENTER_W3_0028_REAL_PG") != "1":
        pytest.skip("requires the isolated W3 0028 PostgreSQL harness")
    database_url = os.environ.get("SSWCENTER_DATABASE_URL")
    if not database_url:
        _fail("W3_0028_HARNESS_DATABASE_URL_MISSING")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def app_engine() -> Iterator[Engine]:
    if os.environ.get("SSWCENTER_W3_0028_REAL_PG") != "1":
        pytest.skip("requires the isolated W3 0028 PostgreSQL harness")
    database_url = os.environ.get("SSWCENTER_APP_DATABASE_URL")
    if not database_url:
        _fail("W3_0028_HARNESS_APP_DATABASE_URL_MISSING")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def superuser_engine() -> Iterator[Engine]:
    if os.environ.get("SSWCENTER_W3_0028_REAL_PG") != "1":
        pytest.skip("requires the isolated W3 0028 PostgreSQL harness")
    database_url = os.environ.get("SSWCENTER_DATABASE_URL")
    if not database_url:
        _fail("W3_0028_HARNESS_DATABASE_URL_MISSING")
    superuser_url = make_url(database_url).set(username="postgres")
    engine = create_engine(superuser_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def database_connection(database_engine: Engine) -> Iterator[Connection]:
    connection = database_engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def _insert_content(connection: Connection, digest: str, locator_suffix: str) -> int:
    value = connection.execute(
        text(
            """
            INSERT INTO erp.w3_private_content (
                content_digest, byte_size, media_type, storage_locator,
                quarantine_state, legal_hold_state, automatic_gc_enabled
            ) VALUES (
                :digest, 12, 'application/octet-stream',
                :locator, 'NONE', 'NONE', FALSE
            )
            RETURNING id
            """
        ),
        {"digest": digest, "locator": f"w3-private:{locator_suffix}"},
    ).scalar_one()
    return int(value)


def _insert_snapshot(
    connection: Connection,
    content_id: int,
    digest: str,
    *,
    target_date: str = "2026-08-17",
    status: str = "CANDIDATE",
) -> int:
    value = connection.execute(
        text(
            """
            INSERT INTO erp.w3_source_snapshot (
                content_id, source_type, target_date, content_digest, status
            ) VALUES (
                :content_id, 'RFID', CAST(:target_date AS date), :digest, :status
            )
            RETURNING id
            """
        ),
        {
            "content_id": content_id,
            "target_date": target_date,
            "digest": digest,
            "status": status,
        },
    ).scalar_one()
    return int(value)


def _insert_receipt(
    connection: Connection,
    snapshot_id: int,
    content_id: int,
    digest: str,
    filename: str,
) -> int:
    value = connection.execute(
        text(
            """
            INSERT INTO erp.w3_source_receipt (
                snapshot_id, content_id, content_digest, original_filename,
                actor_type, actor_account_id, source_context_type
            ) VALUES (
                :snapshot_id, :content_id, :digest, :filename,
                'SYSTEM_RUN', NULL, 'RFID_FILE'
            )
            RETURNING id
            """
        ),
        {
            "snapshot_id": snapshot_id,
            "content_id": content_id,
            "digest": digest,
            "filename": filename,
        },
    ).scalar_one()
    return int(value)


def _insert_run(
    connection: Connection,
    receipt_id: int,
    snapshot_id: int,
    content_id: int,
    digest: str,
    *,
    profile: str = "rfid-v0",
    key: str = "w3-test-key-a",
) -> int:
    value = connection.execute(
        text(
            """
            INSERT INTO erp.w3_import_run (
                receipt_id, snapshot_id, content_id, content_digest,
                parser_profile_version, status, apply_idempotency_key
            ) VALUES (
                :receipt_id, :snapshot_id, :content_id, :digest,
                :profile, 'RECEIVED', :key
            )
            RETURNING id
            """
        ),
        {
            "receipt_id": receipt_id,
            "snapshot_id": snapshot_id,
            "content_id": content_id,
            "digest": digest,
            "profile": profile,
            "key": key,
        },
    ).scalar_one()
    return int(value)


def _insert_attempt(
    connection: Connection,
    receipt_id: int,
    run_id: int,
    snapshot_id: int,
    content_id: int,
    digest: str,
    ordinal: int,
    status: str,
) -> int:
    value = connection.execute(
        text(
            """
            INSERT INTO erp.w3_import_attempt (
                receipt_id, import_run_id, snapshot_id, content_id, content_digest,
                attempt_ordinal, status
            ) VALUES (
                :receipt_id, :run_id, :snapshot_id, :content_id, :digest,
                :ordinal, :status
            )
            RETURNING id
            """
        ),
        {
            "receipt_id": receipt_id,
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "content_id": content_id,
            "digest": digest,
            "ordinal": ordinal,
            "status": status,
        },
    ).scalar_one()
    return int(value)


def test_w3_0028_pg_current_revision_and_postcheck(database_connection: Connection) -> None:
    revision = database_connection.execute(
        text("SELECT version_num FROM erp.alembic_version")
    ).scalar_one()
    assert revision == CURRENT_REVISION == EXPECTED_REVISION
    verify_current_0028(database_connection)


def test_w3_0028_pg_duplicate_snapshot_identity_rejected(database_connection: Connection) -> None:
    content_id = _insert_content(database_connection, DIGEST_A, "aa" * 16)
    _insert_snapshot(database_connection, content_id, DIGEST_A)
    with pytest.raises(IntegrityError):
        _insert_snapshot(database_connection, content_id, DIGEST_A)


def test_w3_0028_pg_one_active_per_source_date(database_connection: Connection) -> None:
    content_a = _insert_content(database_connection, DIGEST_A, "aa" * 16)
    content_b = _insert_content(database_connection, DIGEST_B, "bb" * 16)
    _insert_snapshot(database_connection, content_a, DIGEST_A, status="ACTIVE")
    with pytest.raises(IntegrityError):
        _insert_snapshot(database_connection, content_b, DIGEST_B, status="ACTIVE")


def test_w3_0028_pg_append_only_same_digest_receipts(database_connection: Connection) -> None:
    content_id = _insert_content(database_connection, DIGEST_A, "aa" * 16)
    snapshot_id = _insert_snapshot(database_connection, content_id, DIGEST_A)
    first = _insert_receipt(database_connection, snapshot_id, content_id, DIGEST_A, "rfid.xlsx")
    second = _insert_receipt(
        database_connection, snapshot_id, content_id, DIGEST_A, "rfid (1).xlsx"
    )
    assert first != second
    count = database_connection.execute(
        text("SELECT count(*) FROM erp.w3_source_receipt WHERE content_id = :id"),
        {"id": content_id},
    ).scalar_one()
    assert int(count) == 2


def test_w3_0028_pg_duplicate_retry_and_blocked_receipts_link_one_existing_run(
    database_connection: Connection,
) -> None:
    content_id = _insert_content(database_connection, DIGEST_A, "aa" * 16)
    snapshot_id = _insert_snapshot(database_connection, content_id, DIGEST_A)
    initial_receipt = _insert_receipt(
        database_connection, snapshot_id, content_id, DIGEST_A, "initial.xlsx"
    )
    run_id = _insert_run(
        database_connection,
        initial_receipt,
        snapshot_id,
        content_id,
        DIGEST_A,
        key="w3-lineage-key",
    )
    _insert_attempt(
        database_connection,
        initial_receipt,
        run_id,
        snapshot_id,
        content_id,
        DIGEST_A,
        1,
        "SUCCEEDED",
    )
    duplicate_receipt = _insert_receipt(
        database_connection, snapshot_id, content_id, DIGEST_A, "duplicate.xlsx"
    )
    retry_receipt = _insert_receipt(
        database_connection, snapshot_id, content_id, DIGEST_A, "retry.xlsx"
    )
    blocked_receipt = _insert_receipt(
        database_connection, snapshot_id, content_id, DIGEST_A, "blocked.xlsx"
    )
    _insert_attempt(
        database_connection,
        duplicate_receipt,
        run_id,
        snapshot_id,
        content_id,
        DIGEST_A,
        2,
        "SUCCEEDED",
    )
    _insert_attempt(
        database_connection,
        retry_receipt,
        run_id,
        snapshot_id,
        content_id,
        DIGEST_A,
        3,
        "FAILED_RETRYABLE",
    )
    _insert_attempt(
        database_connection,
        blocked_receipt,
        run_id,
        snapshot_id,
        content_id,
        DIGEST_A,
        4,
        "BLOCKED",
    )
    attempts = (
        database_connection.execute(
            text(
                """
            SELECT receipt_id, status
              FROM erp.w3_import_attempt
             WHERE import_run_id = :run_id
             ORDER BY attempt_ordinal
            """
            ),
            {"run_id": run_id},
        )
        .tuples()
        .all()
    )
    assert attempts == [
        (initial_receipt, "SUCCEEDED"),
        (duplicate_receipt, "SUCCEEDED"),
        (retry_receipt, "FAILED_RETRYABLE"),
        (blocked_receipt, "BLOCKED"),
    ]
    with pytest.raises(IntegrityError):
        _insert_run(
            database_connection,
            duplicate_receipt,
            snapshot_id,
            content_id,
            DIGEST_A,
            key="w3-lineage-key-duplicate-run",
        )


def test_w3_0028_pg_composite_lineage_rejects_direct_sql_mismatch(
    database_connection: Connection,
) -> None:
    content_a = _insert_content(database_connection, DIGEST_A, "aa" * 16)
    content_b = _insert_content(database_connection, DIGEST_B, "bb" * 16)
    snapshot_a = _insert_snapshot(database_connection, content_a, DIGEST_A)
    snapshot_b = _insert_snapshot(database_connection, content_b, DIGEST_B)
    receipt_a = _insert_receipt(database_connection, snapshot_a, content_a, DIGEST_A, "a.xlsx")
    receipt_b = _insert_receipt(database_connection, snapshot_b, content_b, DIGEST_B, "b.xlsx")
    run_a = _insert_run(
        database_connection,
        receipt_a,
        snapshot_a,
        content_a,
        DIGEST_A,
        key="w3-mismatch-run-a",
    )
    nested = database_connection.begin_nested()
    with pytest.raises(IntegrityError):
        _insert_run(
            database_connection,
            receipt_a,
            snapshot_b,
            content_b,
            DIGEST_B,
            key="w3-mismatch-run-b",
        )
    nested.rollback()
    nested = database_connection.begin_nested()
    with pytest.raises(IntegrityError):
        _insert_attempt(
            database_connection,
            receipt_b,
            run_a,
            snapshot_a,
            content_a,
            DIGEST_A,
            1,
            "BLOCKED",
        )
    nested.rollback()


def test_w3_0028_pg_receipt_row_and_attempt_are_append_only_for_erp_app(
    app_engine: Engine,
) -> None:
    with app_engine.begin() as connection:
        content_id = _insert_content(connection, DIGEST_C, "cc" * 16)
        snapshot_id = _insert_snapshot(connection, content_id, DIGEST_C)
        receipt_id = _insert_receipt(connection, snapshot_id, content_id, DIGEST_C, "keep.xlsx")
        run_id = _insert_run(
            connection,
            receipt_id,
            snapshot_id,
            content_id,
            DIGEST_C,
            key="w3-app-attempt-key",
        )
        _insert_attempt(
            connection,
            receipt_id,
            run_id,
            snapshot_id,
            content_id,
            DIGEST_C,
            1,
            "SUCCEEDED",
        )
        connection.execute(
            text(
                """
                INSERT INTO erp.w3_source_row (receipt_id, sheet_ref, source_row_number)
                VALUES (:receipt_id, 'opaque-sheet-1', 1)
                """
            ),
            {"receipt_id": receipt_id},
        )
    with app_engine.connect() as connection:
        for statement in (
            "UPDATE erp.w3_source_receipt SET original_filename = 'changed.xlsx'",
            "DELETE FROM erp.w3_source_receipt",
            "UPDATE erp.w3_source_row SET source_row_number = 99",
            "UPDATE erp.w3_import_attempt SET status = 'BLOCKED'",
            "DELETE FROM erp.w3_import_attempt",
            "TRUNCATE erp.w3_import_attempt",
        ):
            with pytest.raises(ProgrammingError) as caught:
                connection.execute(text(statement))
                connection.commit()
            assert _sqlstate_of(caught.value) == "42501"
            connection.rollback()


def test_w3_0028_pg_fk_restrict_and_closed_status(database_connection: Connection) -> None:
    content_id = _insert_content(database_connection, DIGEST_A, "aa" * 16)
    snapshot_id = _insert_snapshot(database_connection, content_id, DIGEST_A)
    receipt_id = _insert_receipt(
        database_connection, snapshot_id, content_id, DIGEST_A, "keep.xlsx"
    )
    run_id = _insert_run(
        database_connection,
        receipt_id,
        snapshot_id,
        content_id,
        DIGEST_A,
        key="w3-closed-status-key",
    )
    nested = database_connection.begin_nested()
    with pytest.raises(IntegrityError):
        database_connection.execute(
            text("DELETE FROM erp.w3_private_content WHERE id = :id"),
            {"id": content_id},
        )
    nested.rollback()
    nested = database_connection.begin_nested()
    with pytest.raises(IntegrityError):
        _insert_attempt(
            database_connection,
            receipt_id,
            run_id,
            snapshot_id,
            content_id,
            DIGEST_A,
            1,
            "IN_PROGRESS",
        )
    nested.rollback()
    nested = database_connection.begin_nested()
    with pytest.raises(IntegrityError):
        database_connection.execute(
            text(
                """
                INSERT INTO erp.w3_private_content (
                    content_digest, byte_size, media_type, storage_locator,
                    quarantine_state, legal_hold_state, automatic_gc_enabled
                ) VALUES (
                    :digest, 1, 'text/plain', 'https://example.invalid/file',
                    'NONE', 'NONE', FALSE
                )
                """
            ),
            {"digest": DIGEST_B},
        )
    nested.rollback()


def test_w3_0028_pg_direct_sql_hostile_generic_columns(
    database_connection: Connection,
) -> None:
    for statement in (
        "SELECT target_type, target_id FROM erp.w3_import_run",
        "SELECT content_bytes FROM erp.w3_private_content",
        "SELECT public_url FROM erp.w3_private_content",
        "SELECT parser_profile_version FROM erp.w3_source_snapshot",
    ):
        with pytest.raises(ProgrammingError):
            database_connection.execute(text(statement))
        database_connection.rollback()


def test_w3_0028_pg_postcheck_rejects_weakened_or_moved_check(
    database_connection: Connection,
) -> None:
    database_connection.execute(
        text("ALTER TABLE erp.w3_source_receipt DROP CONSTRAINT ck_w3_source_receipt_actor_pair")
    )
    database_connection.execute(
        text(
            """
            ALTER TABLE erp.w3_source_receipt
            ADD CONSTRAINT ck_w3_source_receipt_actor_pair CHECK (true)
            """
        )
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_CHECK_MISMATCH"):
        verify_current_0028(database_connection)
    database_connection.rollback()

    nested = database_connection.begin_nested()
    database_connection.execute(
        text("ALTER TABLE erp.w3_source_receipt DROP CONSTRAINT ck_w3_source_receipt_actor_pair")
    )
    database_connection.execute(
        text(
            """
            ALTER TABLE erp.w3_source_row
            ADD CONSTRAINT ck_w3_source_receipt_actor_pair CHECK (source_row_number > 0)
            """
        )
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_CHECK_NAME_MISMATCH"):
        verify_current_0028(database_connection)
    nested.rollback()


def test_w3_0028_pg_postcheck_rejects_missing_or_extra_catalog(
    database_connection: Connection,
) -> None:
    database_connection.execute(
        text("ALTER TABLE erp.w3_source_snapshot DROP CONSTRAINT uq_w3_source_snapshot_identity")
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_UNIQUE_MISMATCH"):
        verify_current_0028(database_connection)
    database_connection.rollback()

    nested = database_connection.begin_nested()
    database_connection.execute(
        text("ALTER TABLE erp.w3_source_row ADD COLUMN unreviewed_metadata text")
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_COLUMN_SET_MISMATCH"):
        verify_current_0028(database_connection)
    nested.rollback()

    nested = database_connection.begin_nested()
    database_connection.execute(
        text("CREATE UNIQUE INDEX ux_w3_source_row_unreviewed ON erp.w3_source_row (id)")
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_UNIQUE_MISMATCH"):
        verify_current_0028(database_connection)
    nested.rollback()

    nested = database_connection.begin_nested()
    database_connection.execute(
        text("ALTER TABLE erp.w3_source_row DROP CONSTRAINT pk_w3_source_row")
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_PRIMARY_KEY_MISMATCH"):
        verify_current_0028(database_connection)
    nested.rollback()

    nested = database_connection.begin_nested()
    database_connection.execute(
        text("ALTER TABLE erp.w3_source_row ALTER COLUMN created_at_utc DROP DEFAULT")
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_COLUMN_SET_MISMATCH"):
        verify_current_0028(database_connection)
    nested.rollback()

    nested = database_connection.begin_nested()
    database_connection.execute(
        text("ALTER TABLE erp.w3_source_row ALTER COLUMN sheet_ref TYPE character varying(64)")
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_COLUMN_SET_MISMATCH"):
        verify_current_0028(database_connection)
    nested.rollback()

    nested = database_connection.begin_nested()
    database_connection.execute(
        text("ALTER TABLE erp.w3_source_row ALTER COLUMN id DROP IDENTITY IF EXISTS")
    )
    database_connection.execute(text("CREATE SEQUENCE erp.w3_source_row_id_seq"))
    with pytest.raises(SystemExit, match="CURRENT_0028_COLUMN_SET_MISMATCH"):
        verify_current_0028(database_connection)
    nested.rollback()

    nested = database_connection.begin_nested()
    database_connection.execute(text("DROP INDEX erp.ix_w3_source_row_receipt_id"))
    with pytest.raises(SystemExit, match="CURRENT_0028_EXPLICIT_INDEX_MISMATCH"):
        verify_current_0028(database_connection)
    nested.rollback()


def test_w3_0028_pg_postcheck_rejects_lowercase_active_predicate(
    database_connection: Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    name, _table, columns, _predicate = ACTIVE_PARTIAL_UNIQUE
    column_sql = ", ".join(columns)
    database_connection.execute(text(f"DROP INDEX erp.{name}"))
    database_connection.execute(
        text(
            f"CREATE UNIQUE INDEX {name} ON erp.w3_source_snapshot ({column_sql}) "
            "WHERE status = 'active'"
        )
    )
    with pytest.raises(SystemExit, match="CURRENT_0028_ACTIVE_PARTIAL_UNIQUE_MISMATCH"):
        verify_current_0028(database_connection)
    with pytest.raises(SystemExit):
        dispatch_current_head(database_connection)
    output = capsys.readouterr().out
    assert CURRENT_0028_MARKER not in output
    assert HEAD_MARKER not in output
    _restore_active_partial_unique(database_connection)
    verify_current_0028(database_connection)


def test_w3_0028_pg_app_status_update_only_other_columns_are_42501(app_engine: Engine) -> None:
    with app_engine.begin() as connection:
        content_id = _insert_content(connection, DIGEST_D, "dd" * 16)
        snapshot_id = _insert_snapshot(connection, content_id, DIGEST_D)
        receipt_id = _insert_receipt(connection, snapshot_id, content_id, DIGEST_D, "keep.xlsx")
        run_id = _insert_run(
            connection,
            receipt_id,
            snapshot_id,
            content_id,
            DIGEST_D,
            key="w3-app-status-key",
        )
        _insert_attempt(
            connection,
            receipt_id,
            run_id,
            snapshot_id,
            content_id,
            DIGEST_D,
            1,
            "SUCCEEDED",
        )

    with app_engine.connect() as connection:
        connection.execute(
            text("UPDATE erp.w3_source_snapshot SET status = 'CANDIDATE' WHERE id = :id"),
            {"id": snapshot_id},
        )
        connection.execute(
            text("UPDATE erp.w3_import_run SET status = 'PARSING' WHERE id = :id"),
            {"id": run_id},
        )
        connection.commit()

        denied = (
            (
                "UPDATE erp.w3_import_run SET parser_profile_version = 'hostile' "
                "WHERE id = :run_id",
                {"run_id": run_id},
            ),
            (
                "UPDATE erp.w3_import_run SET apply_idempotency_key = 'hostile-key' "
                "WHERE id = :run_id",
                {"run_id": run_id},
            ),
            (
                "UPDATE erp.w3_import_run SET receipt_id = :receipt_id WHERE id = :run_id",
                {"run_id": run_id, "receipt_id": receipt_id},
            ),
            (
                "UPDATE erp.w3_import_run SET snapshot_id = :snapshot_id WHERE id = :run_id",
                {"run_id": run_id, "snapshot_id": snapshot_id},
            ),
            (
                "UPDATE erp.w3_import_run SET created_at_utc = now() WHERE id = :run_id",
                {"run_id": run_id},
            ),
            (
                "UPDATE erp.w3_source_snapshot SET source_type = 'RFID' WHERE id = :snapshot_id",
                {"snapshot_id": snapshot_id},
            ),
            (
                "UPDATE erp.w3_source_snapshot SET target_date = DATE '2026-08-17' "
                "WHERE id = :snapshot_id",
                {"snapshot_id": snapshot_id},
            ),
            (
                "UPDATE erp.w3_source_snapshot SET content_digest = :digest "
                "WHERE id = :snapshot_id",
                {"snapshot_id": snapshot_id, "digest": DIGEST_D},
            ),
            (
                "UPDATE erp.w3_source_snapshot SET created_at_utc = now() WHERE id = :snapshot_id",
                {"snapshot_id": snapshot_id},
            ),
            (
                "UPDATE erp.w3_source_receipt SET original_filename = 'changed.xlsx' "
                "WHERE id = :receipt_id",
                {"receipt_id": receipt_id},
            ),
        )
        for statement, parameters in denied:
            with pytest.raises(ProgrammingError) as caught:
                connection.execute(text(statement), parameters)
                connection.commit()
            assert _sqlstate_of(caught.value) == "42501"
            connection.rollback()


def test_w3_0028_pg_postcheck_rejects_hostile_filename_update_grant(
    database_connection: Connection,
) -> None:
    database_connection.execute(
        text("GRANT UPDATE (original_filename) ON erp.w3_source_receipt TO erp_app")
    )
    with pytest.raises(
        SystemExit,
        match="CURRENT_0028_(APP_COLUMN_UPDATE_ACL_MISMATCH|UNEXPECTED_COLUMN_GRANT)",
    ):
        verify_current_0028(database_connection)
    database_connection.execute(
        text("REVOKE UPDATE (original_filename) ON erp.w3_source_receipt FROM erp_app")
    )
    verify_current_0028(database_connection)


def test_w3_0028_pg_rogue_second_head_fails_direct_dispatcher_and_readiness(
    database_engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rogue = "w3_0028_rogue_second_head"
    with database_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO erp.alembic_version (version_num) VALUES (:rev)"),
            {"rev": rogue},
        )
    try:
        with database_engine.connect() as connection:
            with pytest.raises(SystemExit, match="CURRENT_0028_REVISION_MISMATCH"):
                verify_current_0028(connection)
            with pytest.raises(SystemExit, match="W3_0029_REVISION_CARDINALITY"):
                dispatch_current_head(connection)
        output = capsys.readouterr().out
        assert CURRENT_0028_MARKER not in output
        assert HEAD_MARKER not in output
        ready, reason = database_catalog_is_ready(
            os.environ["SSWCENTER_DATABASE_URL"],
            require_postcheck=True,
        )
        assert ready is False
        assert reason in {"alembic_revision_cardinality", "current_postcheck_failed"}
    finally:
        with database_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM erp.alembic_version WHERE version_num = :rev"),
                {"rev": rogue},
            )
    with database_engine.connect() as connection:
        verify_current_0028(connection)


def test_w3_0028_pg_two_connection_active_partial_unique_race(
    database_engine: Engine,
) -> None:
    with database_engine.begin() as setup:
        content_a = _insert_content(setup, DIGEST_A, "aa" * 16)
        content_b = _insert_content(setup, DIGEST_B, "bb" * 16)

    barrier = threading.Barrier(2, timeout=10)
    outcomes: list[str] = []
    unexpected: list[BaseException] = []
    lock = threading.Lock()

    def _attempt(content_id: int, digest: str) -> None:
        with database_engine.connect() as connection:
            transaction = connection.begin()
            try:
                barrier.wait()
                _insert_snapshot(
                    connection,
                    content_id,
                    digest,
                    target_date="2026-08-18",
                    status="ACTIVE",
                )
                transaction.commit()
                with lock:
                    outcomes.append("commit")
            except BaseException as error:
                if transaction.is_active:
                    transaction.rollback()
                if is_expected_active_partial_unique_conflict(error):
                    with lock:
                        outcomes.append("reject")
                    return
                with lock:
                    unexpected.append(error)

    first = threading.Thread(target=_attempt, args=(content_a, DIGEST_A))
    second = threading.Thread(target=_attempt, args=(content_b, DIGEST_B))
    first.start()
    second.start()
    first.join(timeout=15)
    second.join(timeout=15)
    assert not first.is_alive()
    assert not second.is_alive()
    if unexpected:
        raise unexpected[0]
    assert outcomes.count("commit") == 1
    assert outcomes.count("reject") == 1
    assert len(outcomes) == 2
    with database_engine.connect() as connection:
        count = connection.execute(
            text(
                """
                SELECT count(*)
                  FROM erp.w3_source_snapshot
                 WHERE source_type = 'RFID'
                   AND target_date = DATE '2026-08-18'
                   AND status = 'ACTIVE'
                """
            )
        ).scalar_one()
    assert int(count) == 1


def test_w3_0028_pg_dispatcher_rejects_historical_revision_without_head_marker(
    database_engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with database_engine.connect() as connection:
        with pytest.raises(SystemExit, match="W3_0029_UNSUPPORTED_REVISION"):
            dispatch_current_head(connection)
    output = capsys.readouterr().out
    assert CURRENT_0028_MARKER not in output
    assert HEAD_MARKER not in output


def test_w3_0028_pg_app_direct_verifier_rejects_hidden_no_privilege_w3_relation(
    superuser_engine: Engine,
    app_engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hidden_relation = "w3_hidden_no_privilege"
    qualified_relation = f"erp.{hidden_relation}"
    with superuser_engine.begin() as super_connection:
        super_connection.execute(text(f"CREATE TABLE {qualified_relation} (id bigint)"))
        super_connection.execute(
            text(f"REVOKE ALL PRIVILEGES ON TABLE {qualified_relation} FROM PUBLIC, erp_app")
        )

    try:
        with app_engine.connect() as app_connection:
            with pytest.raises(ProgrammingError) as caught:
                app_connection.execute(text(f"SELECT * FROM {qualified_relation}"))
            assert _sqlstate_of(caught.value) == "42501"
            app_connection.rollback()

            with pytest.raises(SystemExit, match="CURRENT_0028_TABLE_MISMATCH"):
                verify_current_0028(app_connection)

        output = capsys.readouterr().out
        assert CURRENT_0028_MARKER not in output
        assert HEAD_MARKER not in output
    finally:
        with superuser_engine.begin() as super_connection:
            super_connection.execute(text(f"DROP TABLE IF EXISTS {qualified_relation}"))


def test_w3_0028_pg_app_url_is_not_superuser(app_engine: Engine) -> None:
    url = make_url(str(app_engine.url))
    assert url.username == "erp_app"


def test_w3_0028_pg_postcheck_rejects_unexpected_owner(
    superuser_engine: Engine,
    database_connection: Connection,
) -> None:
    verify_current_0028(database_connection)
    with superuser_engine.connect() as super_connection:
        transaction = super_connection.begin()
        try:
            super_connection.execute(text("ALTER TABLE erp.w3_source_row OWNER TO erp_app"))
            with pytest.raises(SystemExit, match="CURRENT_0028_RELATION_OWNER_MISMATCH"):
                verify_current_0028(super_connection)
        finally:
            if transaction.is_active:
                transaction.rollback()
    verify_current_0028(database_connection)


def test_w3_0028_pg_postcheck_rejects_sequence_and_schema_acl_drift(
    superuser_engine: Engine,
    database_connection: Connection,
) -> None:
    verify_current_0028(database_connection)

    owner_mutations = (
        (
            "GRANT SELECT ON SEQUENCE erp.w3_source_row_id_seq TO PUBLIC",
            "CURRENT_0028_SEQUENCE_ACL_MISMATCH",
        ),
        (
            "GRANT USAGE ON SEQUENCE erp.w3_source_row_id_seq TO erp_app WITH GRANT OPTION",
            "CURRENT_0028_(SEQUENCE_ACL|APP_SEQUENCE_ACL)_MISMATCH",
        ),
        (
            "GRANT SELECT ON SEQUENCE erp.w3_source_row_id_seq TO erp_owner WITH GRANT OPTION",
            "CURRENT_0028_SEQUENCE_ACL_MISMATCH",
        ),
        (
            "GRANT USAGE ON SCHEMA erp TO PUBLIC",
            "CURRENT_0028_SCHEMA_ACL_MISMATCH",
        ),
        (
            "GRANT CREATE ON SCHEMA erp TO erp_app",
            "CURRENT_0028_SCHEMA_ACL_MISMATCH",
        ),
        (
            "GRANT USAGE ON SCHEMA erp TO erp_app WITH GRANT OPTION",
            "CURRENT_0028_SCHEMA_ACL_MISMATCH",
        ),
    )
    for mutation, expected in owner_mutations:
        savepoint = database_connection.begin_nested()
        try:
            database_connection.execute(text(mutation))
            with pytest.raises(SystemExit, match=expected):
                verify_current_0028(database_connection)
        finally:
            if savepoint.is_active:
                savepoint.rollback()
        verify_current_0028(database_connection)

    sequence_revoke = database_connection.begin_nested()
    try:
        before = _exploded_class_acl(database_connection, "w3_source_row_id_seq")
        owner_before = _owner_privileges(before)
        database_connection.execute(
            text("REVOKE UPDATE ON SEQUENCE erp.w3_source_row_id_seq FROM erp_owner")
        )
        after = _exploded_class_acl(database_connection, "w3_source_row_id_seq")
        owner_after = _owner_privileges(after)
        assert after != before
        assert "UPDATE" not in owner_after
        assert owner_after != PG16_SEQUENCE_OWNER_PRIVILEGES
        if owner_before:
            assert "UPDATE" in owner_before
        with pytest.raises(SystemExit, match="CURRENT_0028_SEQUENCE_ACL_MISMATCH"):
            verify_current_0028(database_connection)
    finally:
        if sequence_revoke.is_active:
            sequence_revoke.rollback()
    verify_current_0028(database_connection)

    schema_revoke = database_connection.begin_nested()
    try:
        before = _exploded_schema_acl(database_connection)
        owner_before = _owner_privileges(before)
        database_connection.execute(text("REVOKE CREATE ON SCHEMA erp FROM erp_owner"))
        after = _exploded_schema_acl(database_connection)
        owner_after = _owner_privileges(after)
        assert after != before
        assert "CREATE" not in owner_after
        assert owner_after != PG16_SCHEMA_OWNER_PRIVILEGES
        if owner_before:
            assert "CREATE" in owner_before
        with pytest.raises(SystemExit, match="CURRENT_0028_SCHEMA_ACL_MISMATCH"):
            verify_current_0028(database_connection)
    finally:
        if schema_revoke.is_active:
            schema_revoke.rollback()
    verify_current_0028(database_connection)

    with superuser_engine.connect() as super_connection:
        transaction = super_connection.begin()
        try:
            super_connection.execute(text("CREATE ROLE w3_0028_acl_third LOGIN"))
            third_mutations = (
                (
                    "GRANT SELECT ON SEQUENCE erp.w3_source_row_id_seq TO w3_0028_acl_third",
                    "CURRENT_0028_SEQUENCE_ACL_MISMATCH",
                ),
                (
                    "GRANT USAGE ON SCHEMA erp TO w3_0028_acl_third",
                    "CURRENT_0028_SCHEMA_ACL_MISMATCH",
                ),
            )
            for mutation, expected in third_mutations:
                savepoint = super_connection.begin_nested()
                try:
                    super_connection.execute(text(mutation))
                    with pytest.raises(SystemExit, match=expected):
                        verify_current_0028(super_connection)
                finally:
                    if savepoint.is_active:
                        savepoint.rollback()
                verify_current_0028(super_connection)

            granter_savepoint = super_connection.begin_nested()
            try:
                super_connection.execute(text("CREATE ROLE w3_0028_acl_granter LOGIN"))
                super_connection.execute(text("GRANT USAGE ON SCHEMA erp TO w3_0028_acl_granter"))
                super_connection.execute(
                    text(
                        "GRANT SELECT, USAGE ON SEQUENCE erp.w3_source_row_id_seq "
                        "TO w3_0028_acl_granter WITH GRANT OPTION"
                    )
                )
                super_connection.execute(text("SET ROLE w3_0028_acl_granter"))
                try:
                    super_connection.execute(
                        text("GRANT SELECT ON SEQUENCE erp.w3_source_row_id_seq TO erp_owner")
                    )
                finally:
                    super_connection.execute(text("RESET ROLE"))
                with pytest.raises(SystemExit, match="CURRENT_0028_SEQUENCE_ACL_MISMATCH"):
                    verify_current_0028(super_connection)
            finally:
                if granter_savepoint.is_active:
                    granter_savepoint.rollback()
            verify_current_0028(super_connection)
        finally:
            if transaction.is_active:
                transaction.rollback()
    verify_current_0028(database_connection)


def test_w3_0028_pg_postcheck_rejects_table_and_column_acl_provenance(
    superuser_engine: Engine,
    database_connection: Connection,
) -> None:
    verify_current_0028(database_connection)

    table_revoke = database_connection.begin_nested()
    try:
        before = _exploded_class_acl(database_connection, "w3_source_row")
        owner_before = _owner_privileges(before)
        database_connection.execute(
            text("REVOKE TRIGGER ON TABLE erp.w3_source_row FROM erp_owner")
        )
        after = _exploded_class_acl(database_connection, "w3_source_row")
        owner_after = _owner_privileges(after)
        assert after != before
        assert "TRIGGER" not in owner_after
        assert owner_after != PG16_TABLE_OWNER_PRIVILEGES
        if owner_before:
            assert "TRIGGER" in owner_before
        with pytest.raises(SystemExit, match="CURRENT_0028_TABLE_RELACL_MISMATCH"):
            verify_current_0028(database_connection)
    finally:
        if table_revoke.is_active:
            table_revoke.rollback()
    verify_current_0028(database_connection)

    column_revoke = database_connection.begin_nested()
    try:
        before = _exploded_column_acl(database_connection, "w3_source_snapshot", "status")
        database_connection.execute(
            text(
                "GRANT SELECT (status), INSERT (status), UPDATE (status), "
                "REFERENCES (status) ON TABLE erp.w3_source_snapshot TO erp_owner"
            )
        )
        database_connection.execute(
            text("REVOKE REFERENCES (status) ON TABLE erp.w3_source_snapshot FROM erp_owner")
        )
        after = _exploded_column_acl(database_connection, "w3_source_snapshot", "status")
        owner_after = _owner_privileges(after)
        assert after != before
        assert "REFERENCES" not in owner_after
        assert owner_after != PG16_COLUMN_OWNER_PRIVILEGES
        with pytest.raises(SystemExit, match="CURRENT_0028_UNEXPECTED_COLUMN_GRANT"):
            verify_current_0028(database_connection)
    finally:
        if column_revoke.is_active:
            column_revoke.rollback()
    verify_current_0028(database_connection)

    with superuser_engine.connect() as super_connection:
        transaction = super_connection.begin()
        try:
            super_connection.execute(text("CREATE ROLE w3_0028_table_granter LOGIN"))
            super_connection.execute(text("GRANT USAGE ON SCHEMA erp TO w3_0028_table_granter"))
            super_connection.execute(
                text(
                    "GRANT SELECT ON TABLE erp.w3_source_row "
                    "TO w3_0028_table_granter WITH GRANT OPTION"
                )
            )
            super_connection.execute(text("SET ROLE w3_0028_table_granter"))
            try:
                super_connection.execute(text("GRANT SELECT ON TABLE erp.w3_source_row TO erp_app"))
            finally:
                super_connection.execute(text("RESET ROLE"))
            table_acl = _exploded_class_acl(super_connection, "w3_source_row")
            assert (
                "erp_app",
                "w3_0028_table_granter",
                "SELECT",
                False,
            ) in table_acl
            assert not any(
                grantee == "erp_app" and privilege == "SELECT" and grantor == "postgres"
                for grantee, grantor, privilege, _grantable in table_acl
            )
            with pytest.raises(SystemExit, match="CURRENT_0028_TABLE_RELACL_MISMATCH"):
                verify_current_0028(super_connection)
        finally:
            if transaction.is_active:
                transaction.rollback()
    verify_current_0028(database_connection)

    with superuser_engine.connect() as super_connection:
        transaction = super_connection.begin()
        try:
            super_connection.execute(text("CREATE ROLE w3_0028_column_granter LOGIN"))
            super_connection.execute(text("GRANT USAGE ON SCHEMA erp TO w3_0028_column_granter"))
            super_connection.execute(
                text(
                    "GRANT UPDATE (status) ON TABLE erp.w3_source_snapshot "
                    "TO w3_0028_column_granter WITH GRANT OPTION"
                )
            )
            super_connection.execute(text("SET ROLE w3_0028_column_granter"))
            try:
                super_connection.execute(
                    text("GRANT UPDATE (status) ON TABLE erp.w3_source_snapshot TO erp_app")
                )
            finally:
                super_connection.execute(text("RESET ROLE"))
            column_acl = _exploded_column_acl(super_connection, "w3_source_snapshot", "status")
            assert (
                "erp_app",
                "w3_0028_column_granter",
                "UPDATE",
                False,
            ) in column_acl
            assert not any(
                grantee == "erp_app" and privilege == "UPDATE" and grantor == "postgres"
                for grantee, grantor, privilege, _grantable in column_acl
            )
            with pytest.raises(SystemExit, match="CURRENT_0028_UNEXPECTED_COLUMN_GRANT"):
                verify_current_0028(super_connection)
        finally:
            if transaction.is_active:
                transaction.rollback()
    verify_current_0028(database_connection)


def test_w3_0028_pg_postcheck_rejects_deferrable_pk_hash_and_extra_indexes(
    database_connection: Connection,
) -> None:
    verify_current_0028(database_connection)

    savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text("ALTER TABLE erp.w3_source_row DROP CONSTRAINT pk_w3_source_row")
        )
        database_connection.execute(
            text(
                "ALTER TABLE erp.w3_source_row "
                "ADD CONSTRAINT pk_w3_source_row PRIMARY KEY (id) DEFERRABLE"
            )
        )
        with pytest.raises(SystemExit, match="CURRENT_0028_PRIMARY_KEY_MISMATCH"):
            verify_current_0028(database_connection)
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    verify_current_0028(database_connection)

    savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(text("DROP INDEX erp.ix_w3_source_row_receipt_id"))
        database_connection.execute(
            text(
                "CREATE INDEX ix_w3_source_row_receipt_id "
                "ON erp.w3_source_row USING hash (receipt_id)"
            )
        )
        with pytest.raises(SystemExit, match="CURRENT_0028_EXPLICIT_INDEX_MISMATCH"):
            verify_current_0028(database_connection)
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    verify_current_0028(database_connection)

    savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                "CREATE INDEX ix_w3_source_row_partial_hostile "
                "ON erp.w3_source_row (receipt_id) WHERE source_row_number > 0"
            )
        )
        with pytest.raises(SystemExit, match="CURRENT_0028_EXPLICIT_INDEX_MISMATCH"):
            verify_current_0028(database_connection)
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    verify_current_0028(database_connection)

    savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                "CREATE INDEX ix_w3_source_row_expr_hostile ON erp.w3_source_row (lower(sheet_ref))"
            )
        )
        with pytest.raises(SystemExit, match="CURRENT_0028_EXPLICIT_INDEX_MISMATCH"):
            verify_current_0028(database_connection)
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    verify_current_0028(database_connection)


def test_w3_0028_pg_postcheck_rejects_set_role_membership_bypass(
    superuser_engine: Engine,
    app_engine: Engine,
    database_connection: Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verify_current_0028(database_connection)
    with superuser_engine.begin() as super_connection:
        super_connection.execute(text("GRANT erp_owner TO erp_app WITH INHERIT FALSE, SET TRUE"))
    try:
        with app_engine.connect() as app_connection:
            with pytest.raises(ProgrammingError) as caught:
                app_connection.execute(
                    text("UPDATE erp.w3_source_receipt SET original_filename = 'set-role.xlsx'")
                )
                app_connection.commit()
            assert _sqlstate_of(caught.value) == "42501"
            app_connection.rollback()
            app_connection.execute(text("SET ROLE erp_owner"))
            current_role = app_connection.execute(text("SELECT current_user")).scalar_one()
            assert str(current_role) == "erp_owner"
            app_connection.execute(text("RESET ROLE"))
            set_possible = app_connection.execute(
                text("SELECT pg_has_role('erp_app', 'erp_owner', 'SET')")
            ).scalar_one()
            assert bool(set_possible) is True
            _assert_dispatch_markers_absent(app_connection, capsys, "CURRENT_0028_SET_ROLE_PATH")
    finally:
        with superuser_engine.begin() as super_connection:
            super_connection.execute(text("REVOKE erp_owner FROM erp_app"))
    _assert_dispatch_markers_present(database_connection, capsys)


def test_w3_0028_pg_postcheck_rejects_fk_trigger_and_replication_bypass(
    superuser_engine: Engine,
    database_connection: Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verify_current_0028(database_connection)

    with superuser_engine.connect() as super_connection:
        transaction = super_connection.begin()
        try:
            super_connection.execute(text("ALTER TABLE erp.w3_import_attempt DISABLE TRIGGER ALL"))
            disabled = super_connection.execute(
                text(
                    """
                    SELECT count(*)
                      FROM pg_trigger AS trigger_row
                      JOIN pg_class AS relation_row
                        ON relation_row.oid = trigger_row.tgrelid
                      JOIN pg_namespace AS namespace_row
                        ON namespace_row.oid = relation_row.relnamespace
                     WHERE namespace_row.nspname = 'erp'
                       AND relation_row.relname = 'w3_import_attempt'
                       AND trigger_row.tgenabled = 'D'
                    """
                )
            ).scalar_one()
            assert int(disabled) > 0
            super_connection.execute(
                text(
                    """
                    INSERT INTO erp.w3_import_attempt (
                        receipt_id, import_run_id, snapshot_id, content_id, content_digest,
                        attempt_ordinal, status
                    ) VALUES (
                        999001, 999002, 999003, 999004, :digest, 1, 'SUCCEEDED'
                    )
                    """
                ),
                {"digest": DIGEST_A},
            )
            orphan = super_connection.execute(
                text("SELECT count(*) FROM erp.w3_import_attempt WHERE receipt_id = 999001")
            ).scalar_one()
            assert int(orphan) == 1
            _assert_dispatch_markers_absent(
                super_connection, capsys, "CURRENT_0028_FK_TRIGGER_MISMATCH"
            )
        finally:
            if transaction.is_active:
                transaction.rollback()
    _assert_dispatch_markers_present(database_connection, capsys)

    savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                """
                CREATE FUNCTION erp.w3_0028_noop() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$
                """
            )
        )
        database_connection.execute(
            text(
                """
                CREATE TRIGGER w3_0028_hostile_audit
                    BEFORE INSERT ON erp.w3_source_row
                    FOR EACH ROW EXECUTE FUNCTION erp.w3_0028_noop()
                """
            )
        )
        _assert_dispatch_markers_absent(
            database_connection, capsys, "CURRENT_0028_NONINTERNAL_TRIGGER_PRESENT"
        )
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    _assert_dispatch_markers_present(database_connection, capsys)

    with superuser_engine.connect() as super_connection:
        transaction = super_connection.begin()
        try:
            super_connection.execute(text("SET LOCAL session_replication_role = 'replica'"))
            shown = super_connection.execute(text("SHOW session_replication_role")).scalar_one()
            assert str(shown) == "replica"
            super_connection.execute(
                text(
                    """
                    INSERT INTO erp.w3_import_attempt (
                        receipt_id, import_run_id, snapshot_id, content_id, content_digest,
                        attempt_ordinal, status
                    ) VALUES (
                        999011, 999012, 999013, 999014, :digest, 1, 'SUCCEEDED'
                    )
                    """
                ),
                {"digest": DIGEST_A},
            )
            replica_orphan = super_connection.execute(
                text("SELECT count(*) FROM erp.w3_import_attempt WHERE receipt_id = 999011")
            ).scalar_one()
            assert int(replica_orphan) == 1
            _assert_dispatch_markers_absent(
                super_connection, capsys, "CURRENT_0028_REPLICATION_ROLE_MISMATCH"
            )
        finally:
            if transaction.is_active:
                transaction.rollback()

    with superuser_engine.connect() as super_connection:
        transaction = super_connection.begin()
        try:
            super_connection.execute(
                text("GRANT SET ON PARAMETER session_replication_role TO erp_app")
            )
            _assert_dispatch_markers_absent(
                super_connection, capsys, "CURRENT_0028_REPLICATION_PARAMETER_SET"
            )
        finally:
            if transaction.is_active:
                transaction.rollback()

    try:
        with superuser_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as super_connection:
            super_connection.execute(
                text("ALTER ROLE erp_app SET session_replication_role = replica")
            )
        with superuser_engine.connect() as super_connection:
            _assert_dispatch_markers_absent(
                super_connection, capsys, "CURRENT_0028_REPLICATION_DEFAULT"
            )
    finally:
        with superuser_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as super_connection:
            super_connection.execute(text("ALTER ROLE erp_app RESET session_replication_role"))
    _assert_dispatch_markers_present(database_connection, capsys)


def test_w3_0028_pg_postcheck_rejects_fk_inventory_collision_and_metadata_drift(
    database_connection: Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verify_current_0028(database_connection)

    savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                """
                ALTER TABLE erp.w3_source_row
                ADD CONSTRAINT fk_w3_source_snapshot_content_identity
                FOREIGN KEY (receipt_id) REFERENCES erp.w3_source_receipt(id)
                ON DELETE RESTRICT
                """
            )
        )
        _assert_dispatch_markers_absent(
            database_connection, capsys, "CURRENT_0028_FOREIGN_KEY_MISMATCH"
        )
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    _assert_dispatch_markers_present(database_connection, capsys)

    savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text("ALTER TABLE erp.w3_source_row DROP CONSTRAINT fk_w3_source_row_receipt")
        )
        database_connection.execute(
            text(
                """
                ALTER TABLE erp.w3_source_row
                ADD CONSTRAINT fk_w3_source_row_receipt
                FOREIGN KEY (receipt_id) REFERENCES erp.w3_source_receipt(id)
                MATCH FULL ON DELETE RESTRICT
                """
            )
        )
        _assert_dispatch_markers_absent(
            database_connection, capsys, "CURRENT_0028_FOREIGN_KEY_MISMATCH"
        )
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    _assert_dispatch_markers_present(database_connection, capsys)

    savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text("ALTER TABLE erp.w3_source_row DROP CONSTRAINT fk_w3_source_row_receipt")
        )
        database_connection.execute(
            text(
                """
                ALTER TABLE erp.w3_source_row
                ADD CONSTRAINT fk_w3_source_row_receipt
                FOREIGN KEY (receipt_id) REFERENCES erp.w3_private_content(id)
                ON DELETE RESTRICT
                NOT VALID
                """
            )
        )
        _assert_dispatch_markers_absent(
            database_connection, capsys, "CURRENT_0028_FOREIGN_KEY_MISMATCH"
        )
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    _assert_dispatch_markers_present(database_connection, capsys)


def test_w3_0028_pg_postcheck_rejects_hidden_matview_and_standalone_sequence(
    database_connection: Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verify_current_0028(database_connection)

    savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text("CREATE MATERIALIZED VIEW erp.w3_hidden_matview AS SELECT 1 AS id")
        )
        _assert_dispatch_markers_absent(database_connection, capsys, "CURRENT_0028_TABLE_MISMATCH")
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    _assert_dispatch_markers_present(database_connection, capsys)

    savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(text("CREATE SEQUENCE erp.w3_hidden_seq"))
        _assert_dispatch_markers_absent(database_connection, capsys, "CURRENT_0028_TABLE_MISMATCH")
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    _assert_dispatch_markers_present(database_connection, capsys)


def test_w3_0028_pg_postcheck_rejects_unlogged_persistence(
    database_connection: Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verify_current_0028(database_connection)
    savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(text("ALTER TABLE erp.w3_import_attempt SET UNLOGGED"))
        persistence = database_connection.execute(
            text(
                """
                SELECT relpersistence
                  FROM pg_class AS relation_row
                  JOIN pg_namespace AS namespace_row
                    ON namespace_row.oid = relation_row.relnamespace
                 WHERE namespace_row.nspname = 'erp'
                   AND relation_row.relname = 'w3_import_attempt'
                """
            )
        ).scalar_one()
        assert str(persistence) == "u"
        _assert_dispatch_markers_absent(
            database_connection, capsys, "CURRENT_0028_PERSISTENCE_MISMATCH"
        )
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    _assert_dispatch_markers_present(database_connection, capsys)


def test_w3_0028_pg_postcheck_rejects_identity_sequence_option_drift(
    database_connection: Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verify_current_0028(database_connection)
    savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text("ALTER SEQUENCE erp.w3_import_attempt_id_seq INCREMENT BY 2 CYCLE")
        )
        _assert_dispatch_markers_absent(
            database_connection, capsys, "CURRENT_0028_SEQUENCE_OPTION_MISMATCH"
        )
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    _assert_dispatch_markers_present(database_connection, capsys)


def test_w3_0028_pg_postcheck_rejects_rls_policy(
    database_connection: Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verify_current_0028(database_connection)
    savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(text("ALTER TABLE erp.w3_source_row ENABLE ROW LEVEL SECURITY"))
        database_connection.execute(text("ALTER TABLE erp.w3_source_row FORCE ROW LEVEL SECURITY"))
        database_connection.execute(
            text(
                """
                CREATE POLICY w3_0028_deny_all ON erp.w3_source_row
                    FOR ALL TO PUBLIC USING (false)
                """
            )
        )
        _assert_dispatch_markers_absent(database_connection, capsys, "CURRENT_0028_RLS_PRESENT")
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    _assert_dispatch_markers_present(database_connection, capsys)


def _raw_membership_rows(connection: Connection) -> list[tuple[str, str, bool, bool, bool]]:
    return [
        (
            str(row["granted_role"]),
            str(row["member_role"]),
            bool(row["admin_option"]),
            bool(row["inherit_option"]),
            bool(row["set_option"]),
        )
        for row in connection.execute(
            text(
                """
                SELECT granted_role.rolname AS granted_role,
                       member_role.rolname AS member_role,
                       raw_membership_row.admin_option,
                       raw_membership_row.inherit_option,
                       raw_membership_row.set_option
                  FROM pg_auth_members AS raw_membership_row
                  JOIN pg_roles AS granted_role
                    ON granted_role.oid = raw_membership_row.roleid
                  JOIN pg_roles AS member_role
                    ON member_role.oid = raw_membership_row.member
                 WHERE granted_role.rolname = ANY(:roles)
                    OR member_role.rolname = ANY(:roles)
                """
            ),
            {"roles": ["erp_owner", "erp_app", "erp_backup"]},
        ).mappings()
    ]


def test_w3_0028_pg_postcheck_rejects_raw_admin_option_set_false_membership(
    superuser_engine: Engine,
    app_engine: Engine,
    database_connection: Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verify_current_0028(database_connection)
    with superuser_engine.begin() as super_connection:
        super_connection.execute(
            text("GRANT erp_owner TO erp_app WITH ADMIN OPTION, INHERIT FALSE, SET FALSE")
        )
    try:
        with superuser_engine.connect() as catalog_connection:
            edges = _raw_membership_rows(catalog_connection)
        assert ("erp_owner", "erp_app", True, False, False) in edges
        with app_engine.connect() as app_connection:
            with pytest.raises(ProgrammingError) as denied:
                app_connection.execute(
                    text(
                        "UPDATE erp.w3_source_receipt "
                        "SET original_filename = 'admin-set-false.xlsx' WHERE id = -1"
                    )
                )
                app_connection.commit()
            assert _sqlstate_of(denied.value) == "42501"
            app_connection.rollback()
            with pytest.raises(ProgrammingError) as set_denied:
                app_connection.execute(text("SET ROLE erp_owner"))
            assert _sqlstate_of(set_denied.value) == "42501"
            app_connection.rollback()
            _assert_dispatch_markers_absent(
                app_connection, capsys, "CURRENT_0028_RAW_ROLE_MEMBERSHIP"
            )
            app_connection.execute(text("GRANT erp_owner TO erp_app WITH SET TRUE, INHERIT FALSE"))
            app_connection.commit()
        with app_engine.connect() as escalated:
            escalated.execute(text("SET ROLE erp_owner"))
            current_role = escalated.execute(text("SELECT current_user")).scalar_one()
            assert str(current_role) == "erp_owner"
            escalated.execute(
                text(
                    "UPDATE erp.w3_source_receipt "
                    "SET original_filename = 'self-escalated.xlsx' WHERE id = -1"
                )
            )
            escalated.execute(text("RESET ROLE"))
    finally:
        with superuser_engine.begin() as super_connection:
            super_connection.execute(text("REVOKE erp_owner FROM erp_app CASCADE"))
    _assert_dispatch_markers_present(database_connection, capsys)
    with superuser_engine.connect() as catalog_connection:
        assert _raw_membership_rows(catalog_connection) == []


def test_w3_0028_pg_postcheck_rejects_raw_inherit_true_set_false_membership(
    superuser_engine: Engine,
    app_engine: Engine,
    database_connection: Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verify_current_0028(database_connection)
    with superuser_engine.begin() as super_connection:
        super_connection.execute(
            text("GRANT erp_owner TO erp_app WITH INHERIT TRUE, SET FALSE, ADMIN FALSE")
        )
    try:
        with superuser_engine.connect() as catalog_connection:
            edges = _raw_membership_rows(catalog_connection)
        assert ("erp_owner", "erp_app", False, True, False) in edges
        with app_engine.connect() as app_connection:
            app_connection.execute(
                text(
                    "UPDATE erp.w3_source_receipt "
                    "SET original_filename = 'inherited.xlsx' WHERE id = -1"
                )
            )
            app_connection.commit()
            with pytest.raises(ProgrammingError) as set_denied:
                app_connection.execute(text("SET ROLE erp_owner"))
            assert _sqlstate_of(set_denied.value) == "42501"
            app_connection.rollback()
            current_role = app_connection.execute(text("SELECT current_user")).scalar_one()
            assert str(current_role) == "erp_app"
            _assert_dispatch_markers_absent(
                app_connection, capsys, "CURRENT_0028_RAW_ROLE_MEMBERSHIP"
            )
    finally:
        with superuser_engine.begin() as super_connection:
            super_connection.execute(text("REVOKE erp_owner FROM erp_app CASCADE"))
    _assert_dispatch_markers_present(database_connection, capsys)
    with superuser_engine.connect() as catalog_connection:
        assert _raw_membership_rows(catalog_connection) == []


def test_w3_0028_pg_postcheck_rejects_rolinherit_false(
    superuser_engine: Engine,
    database_connection: Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verify_current_0028(database_connection)
    try:
        with superuser_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as super_connection:
            super_connection.execute(text("ALTER ROLE erp_app NOINHERIT"))
        with superuser_engine.connect() as super_connection:
            inherit_flag = super_connection.execute(
                text("SELECT rolinherit FROM pg_roles WHERE rolname = 'erp_app'")
            ).scalar_one()
            assert bool(inherit_flag) is False
            _assert_dispatch_markers_absent(
                super_connection, capsys, "CURRENT_0028_ROLE_ATTRIBUTE_MISMATCH"
            )
    finally:
        with superuser_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as super_connection:
            super_connection.execute(text("ALTER ROLE erp_app INHERIT"))
    _assert_dispatch_markers_present(database_connection, capsys)


def test_w3_0028_pg_postcheck_accepts_unrelated_w3x_namespace_object(
    database_connection: Connection,
    capsys: pytest.CaptureFixture[str],
) -> None:
    verify_current_0028(database_connection)
    savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                """
                CREATE TABLE erp.w3x_unrelated_probe (
                    id integer PRIMARY KEY,
                    payload bytea
                )
                """
            )
        )
        present = database_connection.execute(
            text(
                """
                SELECT relation_row.relname
                  FROM pg_class AS relation_row
                  JOIN pg_namespace AS namespace_row
                    ON namespace_row.oid = relation_row.relnamespace
                 WHERE namespace_row.nspname = 'erp'
                   AND relation_row.relname = 'w3x_unrelated_probe'
                """
            )
        ).scalar_one()
        assert str(present) == "w3x_unrelated_probe"
        _assert_dispatch_markers_present(database_connection, capsys)
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    _assert_dispatch_markers_present(database_connection, capsys)
