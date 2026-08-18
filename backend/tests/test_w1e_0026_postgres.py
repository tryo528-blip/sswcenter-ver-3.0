"""Isolated PostgreSQL mutation tests for the W1E 0026 forward constraint.

Execution is explicitly gated by SSWCENTER_W1E_0026_REAL_PG=1 and expects an
isolated PostgreSQL database migrated to the current 0026 head.  The mutation
tests seed real parent rows and exercise the actual CHECK/EXCLUSION constraints
and forward guards; they do not use ``session_replication_role = replica`` and
do not claim trigger coverage from disabled triggers.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from datetime import date
from types import SimpleNamespace
from typing import NoReturn
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.db.postcheck_current_0026 import (
    EXACT_CARE_ASSIGNMENT_EXCLUSION,
    EXACT_CARE_ASSIGNMENT_FAMILY_CHECK,
    EXACT_CARE_ASSIGNMENT_KIND_CHECK,
    W1E_TRIGGER_EXPECTATIONS,
    _compact_constraint,
    _migration_0026_function_bodies,
    verify_current_0026,
)

CURRENT_REVISION = "20260814_0026_w1e_care_assignment_family_relationship_lock"
ASSIGNMENT_TABLE = "erp.care_assignment"
CONTRACT_SERVICE_CODE = "HOME_CARE"
OTHER_SERVICE_CODE = "HOME_BATH"


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


class _TransientProofFailure(Exception):
    """Scenario failure that must not skip lock-function restoration."""


def _proof_fail(marker: str) -> NoReturn:
    raise _TransientProofFailure(marker)


def _assert_trusted_function_name(function_name: str) -> None:
    if re.fullmatch(r"[a-z_][a-z0-9_]*", function_name) is None:
        _fail("W1E_0026_UNTRUSTED_FUNCTION_NAME:" + function_name)


def _dead_code_trigger_function_sql(function_name: str, expected_body: str) -> str:
    """Return a CREATE OR REPLACE FUNCTION that wraps the exact 0012 guard
    body in an unreachable ``IF FALSE`` branch.

    The mutated body still contains every marker, so only the fail-closed
    exact-body comparison can reject it.  Function names come from the static
    W1E trigger expectation table and are validated before interpolation.
    """

    _assert_trusted_function_name(function_name)
    stripped = expected_body.strip()
    if not stripped.startswith("BEGIN"):
        _fail("W1E_0026_DEAD_CODE_BODY_WRAP_UNEXPECTED_START:" + function_name)
    if not stripped.endswith("END"):
        _fail("W1E_0026_DEAD_CODE_BODY_WRAP_UNEXPECTED_END:" + function_name)
    inner = stripped[len("BEGIN") :].strip()
    inner = inner[: -len("END")].strip()
    dead_body = f"BEGIN\n    IF FALSE THEN\n{inner}\n    END IF;\n    RETURN NEW;\nEND\n"
    return (
        "CREATE OR REPLACE FUNCTION erp." + function_name + "()\n"
        "RETURNS trigger\n"
        "LANGUAGE plpgsql\n"
        "AS $$\n" + dead_body + "$$\n"
        ";\n"
    )


@pytest.fixture(scope="session")
def database_engine() -> Iterator[Engine]:
    if os.environ.get("SSWCENTER_W1E_0026_REAL_PG") != "1":
        pytest.skip("requires the isolated W1E 0026 PostgreSQL harness")
    database_url = os.environ.get("SSWCENTER_DATABASE_URL")
    if not database_url:
        _fail("W1E_0026_HARNESS_DATABASE_URL_MISSING")
    engine = create_engine(database_url, pool_pre_ping=True)
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


@pytest.fixture(scope="session")
def superuser_engine() -> Iterator[Engine]:
    if os.environ.get("SSWCENTER_W1E_0026_REAL_PG") != "1":
        pytest.skip("requires the isolated W1E 0026 PostgreSQL harness")
    database_url = os.environ.get("SSWCENTER_DATABASE_URL")
    if not database_url:
        _fail("W1E_0026_HARNESS_DATABASE_URL_MISSING")
    superuser_url = make_url(database_url).set(username="postgres")
    engine = create_engine(superuser_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


def _insert_id(
    connection: Connection,
    statement: str,
    parameters: dict[str, object],
    marker: str,
) -> int:
    value = connection.execute(text(statement), parameters).scalar_one_or_none()
    if value is None:
        _fail(marker)
    return int(value)


def _service_id(connection: Connection, code: str, marker: str) -> int:
    value = connection.execute(
        text("SELECT id FROM erp.service_type WHERE code = :code AND active IS TRUE"),
        {"code": code},
    ).scalar_one_or_none()
    if value is None:
        _fail(marker)
    return int(value)


def _flush_constraints(connection: Connection) -> None:
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def _run_two_connection_barrier(
    engine: Engine,
    *,
    assignment_action: Callable[[Connection], None],
    parent_action: Callable[[Connection], None],
) -> list[tuple[str, object]]:
    """Run two independent PostgreSQL transactions into the same constraint check.

    Both callables receive an open SQLAlchemy ``Connection`` and are responsible
    for the DML inside a transaction.  The helper sets deferred constraints on
    both transactions, runs the callables, then releases both transactions into
    ``SET CONSTRAINTS ALL IMMEDIATE`` from a ``threading.Barrier`` so the
    assignment-side and parent-side deferred triggers overlap.
    """

    results: list[tuple[str, object]] = [("", None), ("", None)]
    barrier = threading.Barrier(2)

    def _worker(index: int, action: Callable[[Connection], None]) -> None:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
                action(connection)
                barrier.wait(timeout=20)
                connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                transaction.commit()
                results[index] = ("success", None)
            except Exception as exc:  # noqa: BLE001 - barrier exceptions must be recorded
                if transaction.is_active:
                    transaction.rollback()
                results[index] = ("error", exc)

    assignment_thread = threading.Thread(
        target=_worker,
        args=(0, assignment_action),
        name="w1e-0026-assignment",
    )
    parent_thread = threading.Thread(
        target=_worker,
        args=(1, parent_action),
        name="w1e-0026-parent",
    )
    assignment_thread.start()
    parent_thread.start()
    assignment_thread.join(timeout=30)
    parent_thread.join(timeout=30)
    if assignment_thread.is_alive() or parent_thread.is_alive():
        raise AssertionError("W1E_0026_CONCURRENT_THREADS_STILL_ALIVE")
    return results


def _connection_backend_pid(connection: Connection) -> int:
    pid = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
    connection.rollback()
    return int(pid)


def _run_connection_transaction_thread(
    connection: Connection,
    action: Callable[[Connection], None],
    *,
    thread_name: str,
) -> tuple[threading.Thread, list[tuple[str, object]]]:
    result: list[tuple[str, object]] = [("", None)]

    def _worker() -> None:
        try:
            transaction = connection.begin()
            try:
                action(connection)
                transaction.commit()
                result[0] = ("success", None)
            except Exception as exc:  # noqa: BLE001 - thread exceptions recorded
                if transaction.is_active:
                    transaction.rollback()
                result[0] = ("error", exc)
        except Exception as exc:  # noqa: BLE001 - thread setup failures recorded
            result[0] = ("error", exc)

    thread = threading.Thread(target=_worker, name=thread_name)
    thread.start()
    return thread, result


def _advisory_lock_held(
    engine: Engine,
    backend_pid: int,
    *,
    domain: str,
    key: int,
    granted: bool,
) -> bool:
    """Observe one exact W1E advisory lock key for ``backend_pid``.

    Matching is ``hashtextextended(domain, key)`` against the advisory
    ``classid/objid`` pair.  A generic granted/ungranted wait is not enough
    to prove the helper holds C1/E/global or is waiting on C2.
    """

    with engine.connect() as poll_connection:
        return bool(
            poll_connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                          FROM pg_locks
                         WHERE pid = :pid
                           AND granted IS NOT DISTINCT FROM CAST(:granted AS boolean)
                           AND locktype = 'advisory'
                           AND objsubid = 1
                           AND ((classid::bigint << 32) | objid::bigint)
                               = hashtextextended(:domain, :key)
                    )
                    """
                ),
                {
                    "pid": backend_pid,
                    "domain": domain,
                    "key": key,
                    "granted": granted,
                },
            ).scalar_one()
        )


def _assert_backend_holds_advisory(
    engine: Engine,
    backend_pid: int,
    *,
    domain: str,
    key: int,
    marker: str,
) -> None:
    if not _advisory_lock_held(
        engine,
        backend_pid,
        domain=domain,
        key=key,
        granted=True,
    ):
        _fail(marker)


def _assert_backend_does_not_hold_advisory(
    engine: Engine,
    backend_pid: int,
    *,
    domain: str,
    key: int,
    marker: str,
) -> None:
    if _advisory_lock_held(
        engine,
        backend_pid,
        domain=domain,
        key=key,
        granted=True,
    ):
        _fail(marker)


def _backend_has_ungranted_advisory(engine: Engine, backend_pid: int) -> bool:
    with engine.connect() as poll_connection:
        return bool(
            poll_connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                          FROM pg_locks
                         WHERE pid = :pid
                           AND granted IS FALSE
                           AND locktype = 'advisory'
                    )
                    """
                ),
                {"pid": backend_pid},
            ).scalar_one()
        )


def _hold_w1e_advisory_xact_lock(
    connection: Connection,
    domain: str,
    key: int,
) -> None:
    connection.execute(
        text(
            """
            SELECT pg_advisory_xact_lock(
                hashtextextended(:domain, :key)
            )
            """
        ),
        {"domain": domain, "key": key},
    )


def _wait_for_exact_advisory_lock(
    engine: Engine,
    backend_pid: int,
    *,
    domain: str,
    key: int,
    granted: bool,
    timeout_seconds: float,
) -> bool:
    """Poll only the exact ``pg_locks`` predicate, with bounded backoff sleep."""

    deadline = time.monotonic() + timeout_seconds
    delay = 0.005
    while True:
        if _advisory_lock_held(
            engine,
            backend_pid,
            domain=domain,
            key=key,
            granted=granted,
        ):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(delay, remaining))
        delay = min(delay * 2, 0.05)


def _advisory_holder_pids(
    engine: Engine,
    *,
    domain: str,
    key: int,
    granted: bool,
) -> set[int]:
    with engine.connect() as poll_connection:
        rows = (
            poll_connection.execute(
                text(
                    """
                SELECT pid
                  FROM pg_locks
                 WHERE locktype = 'advisory'
                   AND objsubid = 1
                   AND granted IS NOT DISTINCT FROM CAST(:granted AS boolean)
                   AND ((classid::bigint << 32) | objid::bigint)
                       = hashtextextended(:domain, :key)
                """
                ),
                {"domain": domain, "key": key, "granted": granted},
            )
            .scalars()
            .all()
        )
    return {int(pid) for pid in rows if pid is not None}


def _assert_distinct_advisory_hashes(
    engine: Engine,
    pairs: list[tuple[str, int]],
    marker: str,
) -> None:
    hashes: list[int] = []
    with engine.connect() as connection:
        for domain, key in pairs:
            hashes.append(
                int(
                    connection.execute(
                        text("SELECT hashtextextended(:domain, :key)"),
                        {"domain": domain, "key": key},
                    ).scalar_one()
                )
            )
    if len(set(hashes)) != len(hashes):
        _proof_fail(marker + ":" + repr(list(zip(pairs, hashes, strict=True))))


def _committed_assignment_count(engine: Engine, assignment_id: int) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    """
                    SELECT count(*)
                      FROM erp.care_assignment
                     WHERE id = :assignment_id
                    """
                ),
                {"assignment_id": assignment_id},
            ).scalar_one()
        )


_ISOLATED_W1E_DATA_DIRECTORY = re.compile(r"^/tmp/sswcenter-w1e-0026-pg-[0-9a-f]{32}/data$")


def _is_isolated_ephemeral_w1e_postgres(engine: Engine) -> bool:
    if os.environ.get("SSWCENTER_W1E_0026_REAL_PG") != "1":
        return False
    database_url = os.environ.get("SSWCENTER_DATABASE_URL")
    if not database_url:
        return False
    url = make_url(database_url)
    if url.host not in {"127.0.0.1", "localhost"}:
        return False
    if url.database != "sswcenter_w1e_0026_test":
        return False
    with engine.connect() as connection:
        data_directory = str(connection.execute(text("SHOW data_directory")).scalar_one())
    return _ISOLATED_W1E_DATA_DIRECTORY.fullmatch(data_directory) is not None


def _signal_backend(engine: Engine, backend_pid: int, *, terminate: bool) -> bool:
    statement = (
        "SELECT pg_terminate_backend(CAST(:pid AS integer))"
        if terminate
        else "SELECT pg_cancel_backend(CAST(:pid AS integer))"
    )
    with engine.connect() as connection:
        signaled = bool(connection.execute(text(statement), {"pid": backend_pid}).scalar_one())
        connection.commit()
    return signaled


def _backend_advisory_lock_count(engine: Engine, backend_pid: int) -> int:
    with engine.connect() as poll_connection:
        return int(
            poll_connection.execute(
                text(
                    """
                    SELECT count(*)
                      FROM pg_locks
                     WHERE pid = :pid
                       AND locktype = 'advisory'
                    """
                ),
                {"pid": backend_pid},
            ).scalar_one()
        )


def _backend_is_alive(engine: Engine, backend_pid: int) -> bool:
    with engine.connect() as poll_connection:
        return bool(
            poll_connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                          FROM pg_stat_activity
                         WHERE pid = :pid
                    )
                    """
                ),
                {"pid": backend_pid},
            ).scalar_one()
        )


_TRANSIENT_CONTRACT_GATE_DOMAIN = "erp.w1e.test.contract_gate"

_TRANSIENT_CONTRACT_PATH_GATE_SQL = """
CREATE OR REPLACE FUNCTION erp.fn_w1e_lock_contract_path(
    p_contract_id bigint
)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended('erp.w1e.test.contract_gate', p_contract_id)
    );
    IF NOT pg_try_advisory_xact_lock(
        hashtextextended('erp.w1e.contract', p_contract_id)
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '55P03',
            MESSAGE = 'CARE_ASSIGNMENT_CONCURRENT_CONFLICT';
    END IF;
END
$$;
"""


def _capture_lock_function_catalog(
    engine: Engine,
    function_name: str,
    identity_arguments: str,
) -> dict[str, str]:
    """Capture exact DDL plus the whole ``pg_proc`` identity row.

    ``to_jsonb(pg_proc)`` includes OID, owner, ACL, cost, rows, support,
    arguments, defaults, body, config, and flags.  MVCC system columns are
    not part of ``to_jsonb(pg_proc)``.
    """

    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    """
                SELECT pg_get_functiondef(pg_proc.oid) AS definition,
                       to_jsonb(pg_proc)::text AS proc_identity,
                       pg_get_function_identity_arguments(pg_proc.oid)
                           AS identity_arguments,
                       pg_get_function_arguments(pg_proc.oid) AS argument_arguments
                  FROM pg_proc
                  JOIN pg_namespace
                    ON pg_namespace.oid = pg_proc.pronamespace
                 WHERE pg_namespace.nspname = 'erp'
                   AND pg_proc.proname = :function_name
                """
                ),
                {"function_name": function_name},
            )
            .mappings()
            .one()
        )
    captured = {
        "definition": str(row["definition"]),
        "proc_identity": str(row["proc_identity"]),
        "identity_arguments": str(row["identity_arguments"] or ""),
        "argument_arguments": str(row["argument_arguments"] or ""),
    }
    if captured["identity_arguments"] != identity_arguments:
        raise RuntimeError(
            "W1E_0026_TRANSIENT_IDENTITY_ARGUMENTS_MISMATCH:" + repr(captured["identity_arguments"])
        )
    return captured


def _lock_function_catalog_mismatch(
    before: dict[str, str],
    after: dict[str, str],
) -> str | None:
    mismatches: list[str] = []
    for key in (
        "definition",
        "proc_identity",
        "identity_arguments",
        "argument_arguments",
    ):
        if before[key] != after[key]:
            mismatches.append(key + ":" + repr(before[key]) + "!=" + repr(after[key]))
    if not mismatches:
        return None
    return "W1E_0026_TRANSIENT_FUNCTION_NOT_RESTORED: " + "; ".join(mismatches)


def _assert_lock_function_catalog_restored(
    before: dict[str, str],
    after: dict[str, str],
) -> None:
    mismatch = _lock_function_catalog_mismatch(before, after)
    if mismatch is not None:
        _fail(mismatch)


def _call_w1e_lock_employment_assignment_edges(
    connection: Connection,
    employment_id: int,
    staff_id: int,
) -> None:
    connection.execute(
        text(
            """
            SELECT erp.fn_w1e_lock_employment_assignment_edges(
                :employment_id,
                :staff_id
            )
            """
        ),
        {"employment_id": employment_id, "staff_id": staff_id},
    )


def _call_w1e_lock_assignment_path(
    connection: Connection,
    contract_id: int,
    employment_id: int,
) -> None:
    connection.execute(
        text(
            """
            SELECT erp.fn_w1e_lock_assignment_path(
                :contract_id,
                :employment_id
            )
            """
        ),
        {"contract_id": contract_id, "employment_id": employment_id},
    )


def _sqlstate_of_error(error: BaseException) -> str | None:
    original = getattr(error, "orig", None)
    sqlstate = getattr(original, "sqlstate", None)
    if sqlstate is None:
        diagnostic = getattr(original, "diag", None)
        sqlstate = getattr(diagnostic, "sqlstate", None)
    if sqlstate is None:
        return None
    return str(sqlstate)


def _message_primary_of_error(error: BaseException) -> str | None:
    original = getattr(error, "orig", None)
    diagnostic = getattr(original, "diag", None)
    message = getattr(diagnostic, "message_primary", None)
    if message is None:
        return None
    return str(message)


def _assert_one_success_one_concurrent_conflict(
    results: list[tuple[str, object]],
    *,
    marker: str,
    allowed_messages: set[str],
) -> None:
    outcomes = sorted(outcome for outcome, _error in results)
    if outcomes != ["error", "success"]:
        _fail(marker + "_OUTCOME_MISMATCH:" + repr(results))

    errors = [error for outcome, error in results if outcome == "error"]
    if len(errors) != 1:
        _fail(marker + "_ERROR_COUNT_MISMATCH")
    error = errors[0]
    if not isinstance(error, BaseException):
        _fail(marker + "_ERROR_TYPE_MISMATCH")
    sqlstate = _sqlstate_of_error(error)
    message = _message_primary_of_error(error)

    if isinstance(error, OperationalError):
        # Lost the non-waiting advisory-lock race: stable 55P03 conflict.
        if sqlstate != "55P03" or message != "CARE_ASSIGNMENT_CONCURRENT_CONFLICT":
            _fail(
                marker
                + "_LOCK_CONFLICT_MISMATCH: sqlstate="
                + repr(sqlstate)
                + " message="
                + repr(message)
            )
        return

    if isinstance(error, IntegrityError):
        # The winner committed first and released the domain lock, so the loser
        # acquired the lock and its final validation found the now-committed
        # invalid state.
        if sqlstate != "23514" or message not in allowed_messages:
            _fail(
                marker
                + "_VALIDATION_MISMATCH: sqlstate="
                + repr(sqlstate)
                + " message="
                + repr(message)
                + " allowed="
                + repr(sorted(allowed_messages))
            )
        return

    _fail(
        marker
        + "_ERROR_TYPE_MISMATCH:"
        + repr(type(error))
        + " sqlstate="
        + repr(sqlstate)
        + " message="
        + repr(message)
    )


def _assert_multi_edge_employment_parent_outcome(
    results: list[tuple[str, object]],
) -> None:
    """Accept only the two safe serializations of the multi-edge race.

    The parent update is already invalid against the seeded January and
    February assignments.  If the assignment transaction loses the non-waiting
    employment-path lock, both transactions can therefore be rejected without
    a deadlock or persisted orphan.  When the assignment transaction wins, the
    existing strict one-success/one-error contract still applies.
    """

    outcomes = sorted(outcome for outcome, _error in results)
    if outcomes == ["error", "success"]:
        _assert_one_success_one_concurrent_conflict(
            results,
            marker="W1E_0026_MULTI_EDGE_DEADLOCK",
            allowed_messages={
                "CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD",
                "STAFF_PERIOD_OUTSIDE_EMPLOYMENT",
            },
        )
        return

    if outcomes != ["error", "error"]:
        _fail("W1E_0026_MULTI_EDGE_DEADLOCK_OUTCOME_MISMATCH:" + repr(results))

    assignment_outcome, assignment_error = results[0]
    parent_outcome, parent_error = results[1]
    if assignment_outcome != "error" or not isinstance(assignment_error, OperationalError):
        _fail("W1E_0026_MULTI_EDGE_DEADLOCK_ASSIGNMENT_ERROR_MISMATCH:" + repr(results[0]))
    assert isinstance(assignment_error, OperationalError)
    if (
        _sqlstate_of_error(assignment_error) != "55P03"
        or _message_primary_of_error(assignment_error) != "CARE_ASSIGNMENT_CONCURRENT_CONFLICT"
    ):
        _fail("W1E_0026_MULTI_EDGE_DEADLOCK_ASSIGNMENT_CONFLICT_MISMATCH:" + repr(results[0]))

    if parent_outcome != "error" or not isinstance(parent_error, IntegrityError):
        _fail("W1E_0026_MULTI_EDGE_DEADLOCK_PARENT_ERROR_MISMATCH:" + repr(results[1]))
    assert isinstance(parent_error, IntegrityError)
    if (
        _sqlstate_of_error(parent_error) != "23514"
        or _message_primary_of_error(parent_error) != "STAFF_PERIOD_OUTSIDE_EMPLOYMENT"
    ):
        _fail("W1E_0026_MULTI_EDGE_DEADLOCK_PARENT_VALIDATION_MISMATCH:" + repr(results[1]))


def _seed_case(
    connection: Connection,
    *,
    contract_end: date = date(2030, 12, 31),
    employment_end: date = date(2030, 12, 31),
    position_a_end: date = date(2030, 12, 31),
    qualification_a_end: date = date(2030, 12, 31),
    qualification_a_service_code: str = CONTRACT_SERVICE_CODE,
) -> SimpleNamespace:
    label = uuid4().hex
    account_staff_id = _insert_id(
        connection,
        """
        INSERT INTO erp.staff
            (name, birth_date, sex_code, display_name, row_version)
        VALUES
            (:name, DATE '1990-01-01', 'TEST', :display_name, 1)
        RETURNING id
        """,
        {
            "name": "W1E 0026 ACCOUNT STAFF " + label,
            "display_name": "W1E 0026 ACCOUNT " + label,
        },
        "W1E_0026_HARNESS_ACCOUNT_STAFF_SEED_FAILED",
    )
    account_id = _insert_id(
        connection,
        """
        INSERT INTO erp.user_account
            (staff_id, account_code, display_name, role_code,
             pin_hash, pin_lookup_hmac, pin_key_version, row_version)
        VALUES
            (:staff_id, :account_code, :display_name, 'ADMIN',
             :pin_hash, :pin_lookup_hmac, 1, 1)
        RETURNING id
        """,
        {
            "staff_id": account_staff_id,
            "account_code": "W1E_0026_" + label,
            "display_name": "W1E 0026 ACCOUNT " + label,
            "pin_hash": "w1e-0026-test-pin-hash-" + label,
            "pin_lookup_hmac": uuid4().bytes,
        },
        "W1E_0026_HARNESS_ACCOUNT_SEED_FAILED",
    )
    contract_service_type_id = _service_id(
        connection,
        CONTRACT_SERVICE_CODE,
        "W1E_0026_HARNESS_HOME_CARE_SEED_MISSING",
    )
    other_service_type_id = _service_id(
        connection,
        OTHER_SERVICE_CODE,
        "W1E_0026_HARNESS_HOME_BATH_SEED_MISSING",
    )

    def staff_id(suffix: str) -> int:
        return _insert_id(
            connection,
            """
            INSERT INTO erp.staff
                (name, birth_date, sex_code, display_name, row_version)
            VALUES
                (:name, DATE '1990-01-01', 'TEST', :display_name, 1)
            RETURNING id
            """,
            {
                "name": "W1E 0026 " + label + suffix,
                "display_name": "W1E 0026 " + label + suffix,
            },
            "W1E_0026_HARNESS_STAFF_INSERT_FAILED",
        )

    def employment_id(staff: int, suffix: str, end_date: date) -> int:
        sequence = _insert_id(
            connection,
            """
            SELECT COALESCE(MAX(staff_no_sequence), 0) + 1
              FROM erp.staff_employment
            """,
            {},
            "W1E_0026_HARNESS_EMPLOYMENT_SEQUENCE_INVALID",
        )
        return _insert_id(
            connection,
            """
            INSERT INTO erp.staff_employment
                (staff_id, employment_no, staff_no, staff_no_year, staff_no_sequence,
                 start_date, end_date, created_by_account_id, updated_by_account_id, row_version)
            VALUES
                (:staff_id, 1, :staff_no, 2099, :staff_no_sequence,
                 DATE '2030-01-01', :end_date, :account_id, :account_id, 1)
            RETURNING id
            """,
            {
                "staff_id": staff,
                "staff_no": "W1E_0026_" + label + suffix,
                "staff_no_sequence": sequence,
                "end_date": end_date,
                "account_id": account_id,
            },
            "W1E_0026_HARNESS_EMPLOYMENT_INSERT_FAILED",
        )

    def position_id(staff: int, employment: int, end_date: date) -> int:
        return _insert_id(
            connection,
            """
            INSERT INTO erp.staff_position_period
                (staff_id, employment_id, position_code, start_date, end_date,
                 invalidated_at_utc, replacement_id, created_by_account_id,
                 updated_by_account_id, row_version)
            VALUES
                (:staff_id, :employment_id, 'CARE_WORKER', DATE '2030-01-01',
                 :end_date, NULL, NULL, :account_id, :account_id, 1)
            RETURNING id
            """,
            {
                "staff_id": staff,
                "employment_id": employment,
                "end_date": end_date,
                "account_id": account_id,
            },
            "W1E_0026_HARNESS_POSITION_INSERT_FAILED",
        )

    def qualification_id(
        staff: int,
        employment: int,
        service_code: str,
        end_date: date,
    ) -> int:
        service_type_id = _service_id(
            connection,
            service_code,
            "W1E_0026_HARNESS_QUALIFICATION_SERVICE_MISSING",
        )
        return _insert_id(
            connection,
            """
            INSERT INTO erp.staff_service_qualification_period
                (staff_id, employment_id, service_type_id, start_date, end_date,
                 source_license_id, created_by_account_id, updated_by_account_id, row_version)
            VALUES
                (:staff_id, :employment_id, :service_type_id, DATE '2030-01-01',
                 :end_date, NULL, :account_id, :account_id, 1)
            RETURNING id
            """,
            {
                "staff_id": staff,
                "employment_id": employment,
                "service_type_id": service_type_id,
                "end_date": end_date,
                "account_id": account_id,
            },
            "W1E_0026_HARNESS_QUALIFICATION_INSERT_FAILED",
        )

    staff_a = staff_id("_A")
    employment_a = employment_id(staff_a, "_A", employment_end)
    position_a = position_id(staff_a, employment_a, position_a_end)
    qualification_a = qualification_id(
        staff_a,
        employment_a,
        qualification_a_service_code,
        qualification_a_end,
    )
    staff_b = staff_id("_B")
    employment_b = employment_id(staff_b, "_B", date(2030, 12, 31))
    position_b = position_id(staff_b, employment_b, date(2030, 12, 31))
    qualification_b = qualification_id(
        staff_b,
        employment_b,
        CONTRACT_SERVICE_CODE,
        date(2030, 12, 31),
    )
    recipient_id = _insert_id(
        connection,
        """
        INSERT INTO erp.recipient
            (name, birth_date, sex_code, mobile_phone, created_by_account_id,
             updated_by_account_id, row_version)
        VALUES
            (:name, DATE '1950-01-01', 'TEST', :mobile_phone,
             :account_id, :account_id, 1)
        RETURNING id
        """,
        {
            "name": "W1E 0026 RECIPIENT " + label,
            "mobile_phone": "010-0000-0000",
            "account_id": account_id,
        },
        "W1E_0026_HARNESS_RECIPIENT_INSERT_FAILED",
    )
    contract_id = _insert_id(
        connection,
        """
        INSERT INTO erp.recipient_contract
            (recipient_id, service_type_id, start_date, end_date,
             invalidated_at_utc, replacement_contract_id,
             created_by_account_id, updated_by_account_id, row_version)
        VALUES
            (:recipient_id, :service_type_id, DATE '2030-01-01', :end_date,
             NULL, NULL, :account_id, :account_id, 1)
        RETURNING id
        """,
        {
            "recipient_id": recipient_id,
            "service_type_id": contract_service_type_id,
            "end_date": contract_end,
            "account_id": account_id,
        },
        "W1E_0026_HARNESS_CONTRACT_INSERT_FAILED",
    )
    _flush_constraints(connection)
    return SimpleNamespace(
        account_id=account_id,
        recipient_id=recipient_id,
        contract_id=contract_id,
        contract_service_type_id=contract_service_type_id,
        other_service_type_id=other_service_type_id,
        staff_a_id=staff_a,
        employment_a_id=employment_a,
        position_a_id=position_a,
        qualification_a_id=qualification_a,
        staff_b_id=staff_b,
        employment_b_id=employment_b,
        position_b_id=position_b,
        qualification_b_id=qualification_b,
    )


def _insert_assignment(
    connection: Connection,
    case: SimpleNamespace,
    *,
    staff_id: int,
    employment_id: int,
    assignment_kind: str,
    family_relationship_text: str | None,
    start_date: date,
    end_date: date | None,
    contract_id: int | None = None,
) -> int:
    return _insert_id(
        connection,
        """
        INSERT INTO erp.care_assignment
            (recipient_contract_id, staff_id, employment_id, assignment_kind,
             family_relationship_text, start_date, end_date, invalidated_at_utc,
             replacement_assignment_id, created_by_account_id, updated_by_account_id,
             row_version)
        VALUES
            (:contract_id, :staff_id, :employment_id, :assignment_kind,
             :family_relationship_text, :start_date, :end_date, NULL, NULL,
             :account_id, :account_id, 1)
        RETURNING id
        """,
        {
            "contract_id": case.contract_id if contract_id is None else contract_id,
            "staff_id": staff_id,
            "employment_id": employment_id,
            "assignment_kind": assignment_kind,
            "family_relationship_text": family_relationship_text,
            "start_date": start_date,
            "end_date": end_date,
            "account_id": case.account_id,
        },
        "W1E_0026_ASSIGNMENT_INSERT_FAILED",
    )


def _insert_contract(
    connection: Connection,
    case: SimpleNamespace,
    *,
    end_date: date,
    service_type_id: int | None = None,
) -> int:
    return _insert_id(
        connection,
        """
        INSERT INTO erp.recipient_contract
            (recipient_id, service_type_id, start_date, end_date,
             invalidated_at_utc, replacement_contract_id,
             created_by_account_id, updated_by_account_id, row_version)
        VALUES
            (:recipient_id, :service_type_id, DATE '2030-01-01', :end_date,
             NULL, NULL, :account_id, :account_id, 1)
        RETURNING id
        """,
        {
            "recipient_id": case.recipient_id,
            "service_type_id": (
                case.contract_service_type_id if service_type_id is None else service_type_id
            ),
            "end_date": end_date,
            "account_id": case.account_id,
        },
        "W1E_0026_HARNESS_SECOND_CONTRACT_INSERT_FAILED",
    )


def _assert_db_violation(
    error: IntegrityError,
    marker: str,
    *,
    expected_constraint: str | None,
    expected_sqlstate: str | None,
    expected_message: str | None,
) -> None:
    original = error.orig
    diagnostic = getattr(original, "diag", None)
    sqlstate = getattr(original, "sqlstate", None)
    if sqlstate is None and diagnostic is not None:
        sqlstate = getattr(diagnostic, "sqlstate", None)
    if expected_sqlstate is not None and str(sqlstate) != expected_sqlstate:
        _fail(
            marker
            + "_SQLSTATE_MISMATCH: expected="
            + expected_sqlstate
            + " actual="
            + repr(sqlstate)
        )
    constraint = getattr(diagnostic, "constraint_name", None)
    if expected_constraint is not None and str(constraint) != expected_constraint:
        _fail(
            marker
            + "_CONSTRAINT_MISMATCH: expected="
            + expected_constraint
            + " actual="
            + repr(constraint)
        )
    message = getattr(diagnostic, "message_primary", None)
    if expected_message is not None and str(message) != expected_message:
        _fail(
            marker + "_MESSAGE_MISMATCH: expected=" + expected_message + " actual=" + repr(message)
        )


def _expect_statement_violation(
    connection: Connection,
    statement: str,
    parameters: dict[str, object],
    marker: str,
    *,
    expected_constraint: str | None = None,
    expected_sqlstate: str | None = None,
    expected_message: str | None = None,
) -> None:
    savepoint = connection.begin_nested()
    try:
        connection.execute(text(statement), parameters)
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    except IntegrityError as error:
        savepoint.rollback()
        _assert_db_violation(
            error,
            marker,
            expected_constraint=expected_constraint,
            expected_sqlstate=expected_sqlstate,
            expected_message=expected_message,
        )
        connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        return
    savepoint.rollback()
    connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    _fail(marker + "_ACCEPTED")


def _expect_violation(
    connection: Connection,
    case: SimpleNamespace,
    *,
    staff_id: int,
    employment_id: int,
    assignment_kind: str,
    family_relationship_text: str | None,
    start_date: date,
    end_date: date | None,
    expected_constraint: str | None = None,
    expected_sqlstate: str | None = None,
    expected_message: str | None = None,
) -> None:
    savepoint = connection.begin_nested()
    try:
        _insert_assignment(
            connection,
            case,
            staff_id=staff_id,
            employment_id=employment_id,
            assignment_kind=assignment_kind,
            family_relationship_text=family_relationship_text,
            start_date=start_date,
            end_date=end_date,
        )
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    except IntegrityError as error:
        savepoint.rollback()
        _assert_db_violation(
            error,
            "W1E_0026_VIOLATION",
            expected_constraint=expected_constraint,
            expected_sqlstate=expected_sqlstate,
            expected_message=expected_message,
        )
        connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        return
    savepoint.rollback()
    connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    _fail("W1E_0026_VIOLATION_ACCEPTED")


def test_w1e_0026_pg_current_head_and_constraints_exist(
    database_connection: Connection,
) -> None:
    revision = database_connection.execute(
        text("SELECT version_num FROM erp.alembic_version")
    ).scalar_one()
    assert revision == CURRENT_REVISION

    check = database_connection.execute(
        text(
            """
            SELECT pg_get_constraintdef(oid, true)
              FROM pg_constraint
             WHERE conrelid = 'erp.care_assignment'::regclass
               AND conname = 'ck_care_assignment_family_relationship_present'
            """
        )
    ).scalar_one_or_none()
    assert check is not None
    assert _compact_constraint(str(check)) == _compact_constraint(
        EXACT_CARE_ASSIGNMENT_FAMILY_CHECK
    )

    kind_check = database_connection.execute(
        text(
            """
            SELECT pg_get_constraintdef(oid, true)
              FROM pg_constraint
             WHERE conrelid = 'erp.care_assignment'::regclass
               AND conname = 'ck_care_assignment_kind'
            """
        )
    ).scalar_one_or_none()
    assert kind_check is not None
    assert _compact_constraint(str(kind_check)) == _compact_constraint(
        EXACT_CARE_ASSIGNMENT_KIND_CHECK
    )

    exclusion = database_connection.execute(
        text(
            """
            SELECT pg_get_constraintdef(oid, true), condeferrable, condeferred
              FROM pg_constraint
             WHERE conrelid = 'erp.care_assignment'::regclass
               AND conname = 'ex_care_assignment_same_contract_staff_period'
            """
        )
    ).one_or_none()
    assert exclusion is not None
    exclusion_definition, exclusion_deferrable, exclusion_deferred = exclusion

    assert (
        _compact_constraint(str(exclusion_definition)).lower()
        == _compact_constraint(EXACT_CARE_ASSIGNMENT_EXCLUSION).lower()
    )
    assert exclusion_deferrable is False
    assert exclusion_deferred is False


def test_w1e_0026_pg_family_check_success_and_rejections(
    database_connection: Connection,
) -> None:
    case = _seed_case(database_connection)

    family_id = _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        assignment_kind="FAMILY",
        family_relationship_text="자녀",
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
    )
    assert family_id > 0
    _flush_constraints(database_connection)

    _expect_violation(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        assignment_kind="FAMILY",
        family_relationship_text=None,
        start_date=date(2030, 2, 1),
        end_date=date(2030, 2, 28),
        expected_constraint="ck_care_assignment_family_relationship_present",
        expected_sqlstate="23514",
    )
    blank_cases = (
        ("   ", date(2030, 3, 1), date(2030, 3, 28)),
        ("\t", date(2030, 4, 1), date(2030, 4, 28)),
        ("\n", date(2030, 5, 1), date(2030, 5, 28)),
        ("\r", date(2030, 6, 1), date(2030, 6, 28)),
        (" \t\n\r", date(2030, 7, 1), date(2030, 7, 28)),
        ("\f", date(2030, 8, 1), date(2030, 8, 14)),
        ("\v", date(2030, 8, 15), date(2030, 8, 28)),
        (" \t\n\r\f\v", date(2030, 9, 1), date(2030, 9, 28)),
    )
    for family_relationship_text, start_date, end_date in blank_cases:
        _expect_violation(
            database_connection,
            case,
            staff_id=case.staff_a_id,
            employment_id=case.employment_a_id,
            assignment_kind="FAMILY",
            family_relationship_text=family_relationship_text,
            start_date=start_date,
            end_date=end_date,
            expected_constraint="ck_care_assignment_family_relationship_present",
            expected_sqlstate="23514",
        )

    _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        assignment_kind="FAMILY",
        family_relationship_text="\t자녀\n",
        start_date=date(2030, 10, 1),
        end_date=date(2030, 10, 15),
    )
    _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        assignment_kind="FAMILY",
        family_relationship_text="\f자녀\v",
        start_date=date(2030, 10, 16),
        end_date=date(2030, 10, 31),
    )
    nbsp_id = _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        assignment_kind="FAMILY",
        family_relationship_text="\u00a0",
        start_date=date(2030, 11, 1),
        end_date=date(2030, 11, 30),
    )
    assert nbsp_id > 0
    letter_v_id = _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        assignment_kind="FAMILY",
        family_relationship_text="v",
        start_date=date(2030, 12, 1),
        end_date=date(2030, 12, 15),
    )
    assert letter_v_id > 0
    _flush_constraints(database_connection)


def test_w1e_0026_pg_general_null_relationship_and_multiple_staff_allowed(
    database_connection: Connection,
) -> None:
    case = _seed_case(database_connection)

    _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        assignment_kind="GENERAL",
        family_relationship_text=None,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 12, 31),
    )
    _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_b_id,
        employment_id=case.employment_b_id,
        assignment_kind="GENERAL",
        family_relationship_text=None,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 12, 31),
    )
    _flush_constraints(database_connection)


def test_w1e_0026_pg_same_contract_staff_overlap_rejected(
    database_connection: Connection,
) -> None:
    case = _seed_case(database_connection)

    _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        assignment_kind="GENERAL",
        family_relationship_text=None,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 12, 31),
    )
    _flush_constraints(database_connection)
    _expect_violation(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        assignment_kind="GENERAL",
        family_relationship_text=None,
        start_date=date(2030, 6, 1),
        end_date=date(2030, 6, 30),
        expected_constraint="ex_care_assignment_same_contract_staff_period",
        expected_sqlstate="23P01",
    )


def test_w1e_0026_pg_forward_guards_accept_and_reject_exact_boundaries(
    database_connection: Connection,
) -> None:
    # Full coverage accepts both FAMILY and GENERAL rows on distinct staff keys.
    accepted_case = _seed_case(database_connection)
    family_id = _insert_assignment(
        database_connection,
        accepted_case,
        staff_id=accepted_case.staff_a_id,
        employment_id=accepted_case.employment_a_id,
        assignment_kind="FAMILY",
        family_relationship_text="자녀",
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
    )
    general_id = _insert_assignment(
        database_connection,
        accepted_case,
        staff_id=accepted_case.staff_b_id,
        employment_id=accepted_case.employment_b_id,
        assignment_kind="GENERAL",
        family_relationship_text=None,
        start_date=date(2030, 2, 1),
        end_date=date(2030, 2, 28),
    )
    assert family_id > 0
    assert general_id > 0
    _flush_constraints(database_connection)
    for assignment_id in (family_id, general_id):
        persisted = database_connection.execute(
            text("SELECT id FROM erp.care_assignment WHERE id = :id"),
            {"id": assignment_id},
        ).scalar_one_or_none()
        if persisted != assignment_id:
            _fail("W1E_0026_FORWARD_ACCEPTED_ROW_LOST")

    contract_case = _seed_case(
        database_connection,
        contract_end=date(2030, 1, 10),
    )
    _expect_violation(
        database_connection,
        contract_case,
        staff_id=contract_case.staff_a_id,
        employment_id=contract_case.employment_a_id,
        assignment_kind="FAMILY",
        family_relationship_text="자녀",
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
        expected_sqlstate="23514",
        expected_message="CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD",
    )

    employment_case = _seed_case(
        database_connection,
        employment_end=date(2030, 1, 10),
        position_a_end=date(2030, 1, 10),
        qualification_a_end=date(2030, 1, 10),
    )
    _expect_violation(
        database_connection,
        employment_case,
        staff_id=employment_case.staff_a_id,
        employment_id=employment_case.employment_a_id,
        assignment_kind="FAMILY",
        family_relationship_text="자녀",
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
        expected_sqlstate="23514",
        expected_message="CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD",
    )

    position_case = _seed_case(
        database_connection,
        position_a_end=date(2030, 1, 10),
    )
    _expect_violation(
        database_connection,
        position_case,
        staff_id=position_case.staff_a_id,
        employment_id=position_case.employment_a_id,
        assignment_kind="GENERAL",
        family_relationship_text=None,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
        expected_sqlstate="23514",
        expected_message="CARE_ASSIGNMENT_STAFF_INELIGIBLE",
    )

    qualification_gap_case = _seed_case(
        database_connection,
        qualification_a_end=date(2030, 1, 10),
    )
    _expect_violation(
        database_connection,
        qualification_gap_case,
        staff_id=qualification_gap_case.staff_a_id,
        employment_id=qualification_gap_case.employment_a_id,
        assignment_kind="GENERAL",
        family_relationship_text=None,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
        expected_sqlstate="23514",
        expected_message="CARE_ASSIGNMENT_STAFF_INELIGIBLE",
    )

    qualification_service_case = _seed_case(
        database_connection,
        qualification_a_service_code=OTHER_SERVICE_CODE,
    )
    _expect_violation(
        database_connection,
        qualification_service_case,
        staff_id=qualification_service_case.staff_a_id,
        employment_id=qualification_service_case.employment_a_id,
        assignment_kind="GENERAL",
        family_relationship_text=None,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
        expected_sqlstate="23514",
        expected_message="CARE_ASSIGNMENT_STAFF_INELIGIBLE",
    )


def test_w1e_0026_pg_reverse_guards_reject_parent_mutations(
    database_connection: Connection,
) -> None:
    case = _seed_case(database_connection)
    assignment_id = _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        assignment_kind="GENERAL",
        family_relationship_text=None,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
    )
    assert assignment_id > 0
    _flush_constraints(database_connection)

    _expect_statement_violation(
        database_connection,
        """
        UPDATE erp.recipient_contract
           SET end_date = DATE '2030-01-15', row_version = row_version + 1
         WHERE id = :id
        """,
        {"id": case.contract_id},
        "W1E_0026_REVERSE_CONTRACT",
        expected_sqlstate="23514",
        expected_message="CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN",
    )
    _expect_statement_violation(
        database_connection,
        """
        UPDATE erp.staff_employment
           SET end_date = DATE '2030-01-15', row_version = row_version + 1
         WHERE id = :id
        """,
        {"id": case.employment_a_id},
        "W1E_0026_REVERSE_EMPLOYMENT",
        expected_sqlstate="23514",
        expected_message="STAFF_PERIOD_OUTSIDE_EMPLOYMENT",
    )
    _expect_statement_violation(
        database_connection,
        """
        UPDATE erp.staff_position_period
           SET end_date = DATE '2030-01-15', row_version = row_version + 1
         WHERE id = :id
        """,
        {"id": case.position_a_id},
        "W1E_0026_REVERSE_POSITION",
        expected_sqlstate="23514",
        expected_message="CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN",
    )
    _expect_statement_violation(
        database_connection,
        """
        UPDATE erp.staff_service_qualification_period
           SET end_date = DATE '2030-01-15', row_version = row_version + 1
         WHERE id = :id
        """,
        {"id": case.qualification_a_id},
        "W1E_0026_REVERSE_QUALIFICATION_SHORTEN",
        expected_sqlstate="23514",
        expected_message="CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN",
    )
    _expect_statement_violation(
        database_connection,
        """
        UPDATE erp.staff_service_qualification_period
           SET invalidated_at_utc = clock_timestamp(),
               replacement_qualification_id = NULL,
               row_version = row_version + 1
         WHERE id = :id
        """,
        {"id": case.qualification_a_id},
        "W1E_0026_REVERSE_QUALIFICATION_INVALIDATION",
        expected_sqlstate="23514",
        expected_message="CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN",
    )

    persisted_id = database_connection.execute(
        text("SELECT id FROM erp.care_assignment WHERE id = :id"),
        {"id": assignment_id},
    ).scalar_one_or_none()
    if persisted_id != assignment_id:
        _fail("W1E_0026_REVERSE_ACCEPTED_ROW_LOST")


def test_w1e_0026_pg_contract_concurrent_assignment_vs_parent_update(
    database_engine: Engine,
) -> None:
    """Serialize an uncommitted assignment against a contract reverse update.

    The parent reverse helper must not look only at committed assignment edges.
    When this INSERT is still uncommitted the parent SELECT sees no edge; it
    must keep the contract parent-domain lock so both sides cannot succeed.
    """
    with database_engine.connect() as seed_connection:
        seed_transaction = seed_connection.begin()
        case = _seed_case(seed_connection)
        seed_transaction.commit()

    def assignment_action(connection: Connection) -> None:
        _insert_assignment(
            connection,
            case,
            staff_id=case.staff_a_id,
            employment_id=case.employment_a_id,
            assignment_kind="GENERAL",
            family_relationship_text=None,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 31),
        )

    def parent_action(connection: Connection) -> None:
        connection.execute(
            text(
                """
                UPDATE erp.recipient_contract
                   SET end_date = DATE '2030-01-15',
                       row_version = row_version + 1
                 WHERE id = :id
                """
            ),
            {"id": case.contract_id},
        )

    results = _run_two_connection_barrier(
        database_engine,
        assignment_action=assignment_action,
        parent_action=parent_action,
    )
    _assert_one_success_one_concurrent_conflict(
        results,
        marker="W1E_0026_CONTRACT_CONCURRENT",
        allowed_messages={
            "CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD",
            "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN",
        },
    )

    with database_engine.connect() as verification_connection:
        orphan_count = int(
            verification_connection.execute(
                text(
                    """
                    SELECT count(*)
                      FROM erp.care_assignment assignment
                      JOIN erp.recipient_contract contract
                        ON contract.id = assignment.recipient_contract_id
                     WHERE assignment.invalidated_at_utc IS NULL
                       AND contract.invalidated_at_utc IS NULL
                       AND NOT (assignment.assignment_period <@ contract.contract_period)
                    """
                )
            ).scalar_one()
        )
    if orphan_count != 0:
        _fail("W1E_0026_CONTRACT_CONCURRENT_ORPHAN_PERSISTED")


def test_w1e_0026_pg_employment_concurrent_assignment_vs_parent_update(
    database_engine: Engine,
) -> None:
    """Serialize an uncommitted assignment against an employment reverse update.

    The employment parent path must keep the employment parent-domain lock when
    no committed assignment edge exists.  Taking only committed-edge locks
    would let both this INSERT and the employment shrink commit.
    """
    with database_engine.connect() as seed_connection:
        seed_transaction = seed_connection.begin()
        case = _seed_case(
            seed_connection,
            position_a_end=date(2030, 1, 15),
            qualification_a_end=date(2030, 1, 15),
        )
        seed_transaction.commit()

    def assignment_action(connection: Connection) -> None:
        _insert_assignment(
            connection,
            case,
            staff_id=case.staff_a_id,
            employment_id=case.employment_a_id,
            assignment_kind="FAMILY",
            family_relationship_text="자녀",
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 31),
        )

    def parent_action(connection: Connection) -> None:
        connection.execute(
            text(
                """
                UPDATE erp.staff_employment
                   SET end_date = DATE '2030-01-15',
                       row_version = row_version + 1
                 WHERE id = :id
                """
            ),
            {"id": case.employment_a_id},
        )

    results = _run_two_connection_barrier(
        database_engine,
        assignment_action=assignment_action,
        parent_action=parent_action,
    )
    _assert_one_success_one_concurrent_conflict(
        results,
        marker="W1E_0026_EMPLOYMENT_CONCURRENT",
        allowed_messages={
            "CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD",
            "STAFF_PERIOD_OUTSIDE_EMPLOYMENT",
        },
    )

    with database_engine.connect() as verification_connection:
        orphan_count = int(
            verification_connection.execute(
                text(
                    """
                    SELECT count(*)
                      FROM erp.care_assignment assignment
                      JOIN erp.staff_employment employment
                        ON employment.id = assignment.employment_id
                       AND employment.staff_id = assignment.staff_id
                     WHERE assignment.invalidated_at_utc IS NULL
                       AND employment.invalidated_at_utc IS NULL
                       AND NOT (assignment.assignment_period <@ employment.employment_period)
                    """
                )
            ).scalar_one()
        )
    if orphan_count != 0:
        _fail("W1E_0026_EMPLOYMENT_CONCURRENT_ORPHAN_PERSISTED")


def test_w1e_0026_pg_contract_qualification_reverse_concurrent_no_orphan(
    database_engine: Engine,
) -> None:
    """Cross-parent contract service change vs qualification invalidation.

    A committed assignment edge exists, so both parents lock that edge in
    contract-then-employment order.  Exactly one transaction must commit and
    the loser must roll back with SQLSTATE 23514; a leftover orphan is
    forbidden.  Neither parent may take a domain lock first, or the two
    parent paths deadlock.
    """
    with database_engine.connect() as seed_connection:
        seed_transaction = seed_connection.begin()
        case = _seed_case(seed_connection)
        qualification_b_id = _insert_id(
            seed_connection,
            """
            INSERT INTO erp.staff_service_qualification_period
                (staff_id, employment_id, service_type_id, start_date, end_date,
                 source_license_id, created_by_account_id, updated_by_account_id, row_version)
            VALUES
                (:staff_id, :employment_id, :service_type_id, DATE '2030-01-01',
                 DATE '2030-12-31', NULL, :account_id, :account_id, 1)
            RETURNING id
            """,
            {
                "staff_id": case.staff_a_id,
                "employment_id": case.employment_a_id,
                "service_type_id": case.other_service_type_id,
                "account_id": case.account_id,
            },
            "W1E_0026_HARNESS_QUALIFICATION_B_INSERT_FAILED",
        )
        assignment_id = _insert_assignment(
            seed_connection,
            case,
            staff_id=case.staff_a_id,
            employment_id=case.employment_a_id,
            assignment_kind="GENERAL",
            family_relationship_text=None,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 12, 31),
        )
        if assignment_id <= 0:
            _fail("W1E_0026_CONTRACT_QUALIFICATION_SEED_ASSIGNMENT_INVALID")
        seed_transaction.commit()

    def contract_action(connection: Connection) -> None:
        connection.execute(
            text(
                """
                UPDATE erp.recipient_contract
                   SET service_type_id = :service_type_id,
                       row_version = row_version + 1
                 WHERE id = :id
                """
            ),
            {
                "id": case.contract_id,
                "service_type_id": case.other_service_type_id,
            },
        )

    def qualification_action(connection: Connection) -> None:
        connection.execute(
            text(
                """
                UPDATE erp.staff_service_qualification_period
                   SET invalidated_at_utc = clock_timestamp(),
                       replacement_qualification_id = NULL,
                       row_version = row_version + 1
                 WHERE id = :id
                """
            ),
            {"id": qualification_b_id},
        )

    results = _run_two_connection_barrier(
        database_engine,
        assignment_action=contract_action,
        parent_action=qualification_action,
    )
    _assert_one_success_one_concurrent_conflict(
        results,
        marker="W1E_0026_CONTRACT_QUALIFICATION_CONCURRENT",
        allowed_messages={
            "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN",
            "CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN",
        },
    )

    with database_engine.connect() as verification_connection:
        orphan_count = int(
            verification_connection.execute(
                text(
                    """
                    SELECT count(*)
                      FROM erp.care_assignment assignment
                      JOIN erp.recipient_contract contract
                        ON contract.id = assignment.recipient_contract_id
                     WHERE assignment.invalidated_at_utc IS NULL
                       AND contract.invalidated_at_utc IS NULL
                       AND assignment.assignment_kind = 'GENERAL'
                       AND NOT (
                           assignment.assignment_period <@ COALESCE(
                               (
                                   SELECT range_agg(qualification.qualification_period)
                                     FROM erp.staff_service_qualification_period
                                          qualification
                                    WHERE qualification.staff_id = assignment.staff_id
                                      AND qualification.employment_id =
                                          assignment.employment_id
                                      AND qualification.service_type_id =
                                          contract.service_type_id
                                      AND qualification.invalidated_at_utc IS NULL
                               ), '{}'::datemultirange
                           )
                       )
                    """
                )
            ).scalar_one()
        )
    if orphan_count != 0:
        _fail("W1E_0026_CONTRACT_QUALIFICATION_CONCURRENT_ORPHAN_PERSISTED")


def test_w1e_0026_pg_multi_edge_employment_parent_no_deadlock(
    database_engine: Engine,
) -> None:
    """Regression: multi-edge employment parent vs assignment-side path.

    The old employment edge helper locked ``C1 -> E`` then ``C2 -> E`` and
    could hold ``C1,E`` while waiting for ``C2``.  A concurrent assignment-side
    ``C2 -> E`` path held ``C2`` and waited for ``E``, producing SQLSTATE
    40P01.  The current helper must acquire all contract-domain locks in
    ascending contract-id order before any employment-domain lock.  The
    overlapping transactions may serialize with the assignment succeeding and
    the invalid parent update failing, or with the assignment losing the
    non-waiting lock and the already-invalid parent update also failing.  Both
    schedules must reject 40P01 and leave no orphan behind.
    """
    with database_engine.connect() as seed_connection:
        seed_transaction = seed_connection.begin()
        case = _seed_case(seed_connection)
        second_contract_id = _insert_contract(
            seed_connection,
            case,
            end_date=date(2030, 12, 31),
            service_type_id=case.other_service_type_id,
        )
        _insert_assignment(
            seed_connection,
            case,
            contract_id=case.contract_id,
            staff_id=case.staff_a_id,
            employment_id=case.employment_a_id,
            assignment_kind="FAMILY",
            family_relationship_text="자녀",
            start_date=date(2030, 1, 1),
            end_date=date(2030, 1, 31),
        )
        _insert_assignment(
            seed_connection,
            case,
            contract_id=second_contract_id,
            staff_id=case.staff_a_id,
            employment_id=case.employment_a_id,
            assignment_kind="FAMILY",
            family_relationship_text="자녀",
            start_date=date(2030, 2, 1),
            end_date=date(2030, 2, 28),
        )
        seed_transaction.commit()

    def assignment_action(connection: Connection) -> None:
        _insert_assignment(
            connection,
            case,
            contract_id=second_contract_id,
            staff_id=case.staff_a_id,
            employment_id=case.employment_a_id,
            assignment_kind="FAMILY",
            family_relationship_text="자녀",
            start_date=date(2030, 3, 1),
            end_date=date(2030, 3, 31),
        )

    def parent_action(connection: Connection) -> None:
        connection.execute(
            text(
                """
                UPDATE erp.staff_employment
                   SET end_date = DATE '2030-01-15',
                       row_version = row_version + 1
                 WHERE id = :id
                """
            ),
            {"id": case.employment_a_id},
        )

    results = _run_two_connection_barrier(
        database_engine,
        assignment_action=assignment_action,
        parent_action=parent_action,
    )
    _assert_multi_edge_employment_parent_outcome(results)

    with database_engine.connect() as verification_connection:
        orphan_count = int(
            verification_connection.execute(
                text(
                    """
                    SELECT count(*)
                      FROM erp.care_assignment assignment
                      JOIN erp.staff_employment employment
                        ON employment.id = assignment.employment_id
                       AND employment.staff_id = assignment.staff_id
                     WHERE assignment.invalidated_at_utc IS NULL
                       AND employment.invalidated_at_utc IS NULL
                       AND NOT (assignment.assignment_period <@ employment.employment_period)
                    """
                )
            ).scalar_one()
        )
    if orphan_count != 0:
        _fail("W1E_0026_MULTI_EDGE_DEADLOCK_ORPHAN_PERSISTED")


def test_w1e_0026_pg_multi_row_assignment_transaction_fine_grained_fail_fast(
    database_engine: Engine,
) -> None:
    """Regression: fine-grained fail-fast assignment lock order across rows.

    A DEFERRABLE FOR EACH ROW trigger fires once per assignment row.  With
    non-waiting transaction-scoped advisory locks, a transaction that acquires
    ``C1 -> E`` and then ``C2 -> E`` first owns C1 and E, then fails
    immediately on C2 when another transaction owns the ``erp.w1e.contract``
    key for C2.  It must not wait while holding C1/E, so no 40P01 cycle can
    form, and the loser observes SQLSTATE 55P03 with the stable
    ``CARE_ASSIGNMENT_CONCURRENT_CONFLICT`` message.
    """

    c1 = 8_000_001
    c2 = 8_000_002
    employment_id = 8_000_003

    with database_engine.connect() as blocker_connection:
        blocker_transaction = blocker_connection.begin()
        _hold_w1e_advisory_xact_lock(blocker_connection, "erp.w1e.contract", c2)

        t1_connection = database_engine.connect()
        t1_transaction = None
        try:
            t1_pid = _connection_backend_pid(t1_connection)
            t1_transaction = t1_connection.begin()
            _call_w1e_lock_assignment_path(t1_connection, c1, employment_id)

            _assert_backend_holds_advisory(
                database_engine,
                t1_pid,
                domain="erp.w1e.contract",
                key=c1,
                marker="W1E_0026_MULTI_ROW_T1_MISSING_GRANTED_C1",
            )
            _assert_backend_holds_advisory(
                database_engine,
                t1_pid,
                domain="erp.w1e.employment",
                key=employment_id,
                marker="W1E_0026_MULTI_ROW_T1_MISSING_GRANTED_E",
            )
            _assert_backend_does_not_hold_advisory(
                database_engine,
                t1_pid,
                domain="erp.w1e.global",
                key=0,
                marker="W1E_0026_MULTI_ROW_T1_HELD_GLOBAL",
            )

            try:
                _call_w1e_lock_assignment_path(t1_connection, c2, employment_id)
                _fail("W1E_0026_MULTI_ROW_FAIL_FAST_ACCEPTED")
            except OperationalError as error:
                if _sqlstate_of_error(error) != "55P03":
                    _fail(
                        "W1E_0026_MULTI_ROW_FAIL_FAST_SQLSTATE_MISMATCH:"
                        + repr(_sqlstate_of_error(error))
                    )
                if _message_primary_of_error(error) != "CARE_ASSIGNMENT_CONCURRENT_CONFLICT":
                    _fail(
                        "W1E_0026_MULTI_ROW_FAIL_FAST_MESSAGE_MISMATCH:"
                        + repr(_message_primary_of_error(error))
                    )
        finally:
            if t1_transaction is not None and t1_transaction.is_active:
                t1_transaction.rollback()
            t1_connection.close()

        blocker_transaction.rollback()


def test_w1e_0026_pg_unrelated_writes_do_not_share_global_mutex(
    database_engine: Engine,
) -> None:
    """Two unrelated W1E writes proceed while the old global key is held.

    A blocker holds the obsolete ``erp.w1e.global`` advisory key.  A W1E
    write on an unrelated contract/employment domain must still complete: the
    current helpers acquire only the exact contract and employment conflict
    keys, never a single global mutex.
    """

    contract_id = 9_000_001
    employment_id = 9_000_002

    with database_engine.connect() as blocker_connection:
        blocker_transaction = blocker_connection.begin()
        _hold_w1e_advisory_xact_lock(blocker_connection, "erp.w1e.global", 0)

        unrelated_connection = database_engine.connect()
        try:

            def unrelated_action(connection: Connection) -> None:
                _call_w1e_lock_assignment_path(connection, contract_id, employment_id)

            unrelated_thread, unrelated_result = _run_connection_transaction_thread(
                unrelated_connection,
                unrelated_action,
                thread_name="w1e-0026-unrelated-write",
            )
            unrelated_thread.join(timeout=10)
            if unrelated_thread.is_alive():
                _fail("W1E_0026_UNRELATED_WRITE_BLOCKED_ON_GLOBAL")
            outcome, error = unrelated_result[0]
            if outcome != "success":
                _fail("W1E_0026_UNRELATED_WRITE_NOT_SUCCESS:" + repr(error))
        finally:
            unrelated_connection.close()

        blocker_transaction.rollback()


def test_w1e_0026_pg_disjoint_domain_writes_overlap_and_commit(
    database_engine: Engine,
) -> None:
    """Two real W1E writes on disjoint contract/employment domains overlap.

    The obsolete global-key non-blocking check is not enough.  This test
    inserts two live assignments on distinct contract and employment ids,
    forces both deferred triggers to acquire their exact advisory keys,
    observes both backends holding those distinct keys at the same time
    with no ungranted wait, then lets both commit.
    """

    with database_engine.connect() as seed_connection:
        seed_transaction = seed_connection.begin()
        left = _seed_case(seed_connection)
        right = _seed_case(seed_connection)
        seed_transaction.commit()

    if left.contract_id == right.contract_id or left.employment_a_id == right.employment_a_id:
        _fail("W1E_0026_DISJOINT_SEED_DOMAINS_COLLIDED")

    cases = (left, right)
    pids = [0, 0]
    assignment_ids = [0, 0]
    results: list[tuple[str, object]] = [("", None), ("", None)]
    inserted = threading.Barrier(2)
    locks_held = threading.Barrier(3)
    release_commit = threading.Barrier(3)

    def _worker(index: int) -> None:
        case = cases[index]
        with database_engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
                pids[index] = int(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
                assignment_ids[index] = _insert_assignment(
                    connection,
                    case,
                    staff_id=case.staff_a_id,
                    employment_id=case.employment_a_id,
                    assignment_kind="GENERAL",
                    family_relationship_text=None,
                    start_date=date(2030, 1, 1),
                    end_date=date(2030, 12, 31),
                )
                inserted.wait(timeout=20)
                connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                locks_held.wait(timeout=20)
                release_commit.wait(timeout=20)
                transaction.commit()
                results[index] = ("success", None)
            except Exception as exc:  # noqa: BLE001 - barrier exceptions recorded
                if transaction.is_active:
                    transaction.rollback()
                results[index] = ("error", exc)
                for barrier in (inserted, locks_held, release_commit):
                    if not barrier.broken:
                        barrier.abort()

    left_thread = threading.Thread(target=_worker, args=(0,), name="w1e-0026-disjoint-left")
    right_thread = threading.Thread(target=_worker, args=(1,), name="w1e-0026-disjoint-right")
    left_thread.start()
    right_thread.start()
    try:
        locks_held.wait(timeout=20)
    except threading.BrokenBarrierError:
        left_thread.join(timeout=5)
        right_thread.join(timeout=5)
        _fail("W1E_0026_DISJOINT_WRITES_BARRIER_BROKEN:" + repr(results))

    left_pid, right_pid = pids
    if left_pid <= 0 or right_pid <= 0 or left_pid == right_pid:
        release_commit.abort()
        _fail("W1E_0026_DISJOINT_WRITES_PID_INVALID:" + repr(pids))

    _assert_backend_holds_advisory(
        database_engine,
        left_pid,
        domain="erp.w1e.contract",
        key=left.contract_id,
        marker="W1E_0026_DISJOINT_LEFT_MISSING_CONTRACT",
    )
    _assert_backend_holds_advisory(
        database_engine,
        left_pid,
        domain="erp.w1e.employment",
        key=left.employment_a_id,
        marker="W1E_0026_DISJOINT_LEFT_MISSING_EMPLOYMENT",
    )
    _assert_backend_holds_advisory(
        database_engine,
        right_pid,
        domain="erp.w1e.contract",
        key=right.contract_id,
        marker="W1E_0026_DISJOINT_RIGHT_MISSING_CONTRACT",
    )
    _assert_backend_holds_advisory(
        database_engine,
        right_pid,
        domain="erp.w1e.employment",
        key=right.employment_a_id,
        marker="W1E_0026_DISJOINT_RIGHT_MISSING_EMPLOYMENT",
    )
    _assert_backend_does_not_hold_advisory(
        database_engine,
        left_pid,
        domain="erp.w1e.contract",
        key=right.contract_id,
        marker="W1E_0026_DISJOINT_LEFT_HELD_RIGHT_CONTRACT",
    )
    _assert_backend_does_not_hold_advisory(
        database_engine,
        left_pid,
        domain="erp.w1e.employment",
        key=right.employment_a_id,
        marker="W1E_0026_DISJOINT_LEFT_HELD_RIGHT_EMPLOYMENT",
    )
    _assert_backend_does_not_hold_advisory(
        database_engine,
        right_pid,
        domain="erp.w1e.contract",
        key=left.contract_id,
        marker="W1E_0026_DISJOINT_RIGHT_HELD_LEFT_CONTRACT",
    )
    _assert_backend_does_not_hold_advisory(
        database_engine,
        right_pid,
        domain="erp.w1e.employment",
        key=left.employment_a_id,
        marker="W1E_0026_DISJOINT_RIGHT_HELD_LEFT_EMPLOYMENT",
    )
    _assert_backend_does_not_hold_advisory(
        database_engine,
        left_pid,
        domain="erp.w1e.global",
        key=0,
        marker="W1E_0026_DISJOINT_LEFT_HELD_GLOBAL",
    )
    _assert_backend_does_not_hold_advisory(
        database_engine,
        right_pid,
        domain="erp.w1e.global",
        key=0,
        marker="W1E_0026_DISJOINT_RIGHT_HELD_GLOBAL",
    )
    if _backend_has_ungranted_advisory(database_engine, left_pid):
        release_commit.abort()
        _fail("W1E_0026_DISJOINT_LEFT_WAITING")
    if _backend_has_ungranted_advisory(database_engine, right_pid):
        release_commit.abort()
        _fail("W1E_0026_DISJOINT_RIGHT_WAITING")

    try:
        release_commit.wait(timeout=20)
    except threading.BrokenBarrierError:
        _fail("W1E_0026_DISJOINT_WRITES_RELEASE_BROKEN:" + repr(results))
    left_thread.join(timeout=20)
    right_thread.join(timeout=20)
    if left_thread.is_alive() or right_thread.is_alive():
        _fail("W1E_0026_DISJOINT_WRITES_STILL_ALIVE")
    if [outcome for outcome, _error in results] != ["success", "success"]:
        _fail("W1E_0026_DISJOINT_WRITES_DID_NOT_BOTH_COMMIT:" + repr(results))
    if assignment_ids[0] <= 0 or assignment_ids[1] <= 0:
        _fail("W1E_0026_DISJOINT_ASSIGNMENT_IDS_INVALID:" + repr(assignment_ids))

    with database_engine.connect() as verification_connection:
        persisted: set[int] = set()
        for assignment_id in assignment_ids:
            value = verification_connection.execute(
                text(
                    """
                    SELECT id
                      FROM erp.care_assignment
                     WHERE id = :id
                       AND invalidated_at_utc IS NULL
                    """
                ),
                {"id": assignment_id},
            ).scalar_one_or_none()
            if value is not None:
                persisted.add(int(value))
    if persisted != set(assignment_ids):
        _fail("W1E_0026_DISJOINT_WRITES_NOT_PERSISTED:" + repr(sorted(persisted)))


def test_w1e_0026_pg_employment_lock_helper_always_locks_employment_path(
    database_engine: Engine,
) -> None:
    """The employment edge helper must always lock p_employment_id.

    Two direct advisory-lock blocker interleavings are forced here:

    * empty edge: with no committed assignment edge the helper must still
      request the employment-domain lock; and
    * ordinary with-edge: with a committed edge present the helper acquires
      the contract key first and must still request the employment-domain lock.

    The exact transient-disappearance sequence (first contract-edge SELECT
    observes C1, execution pauses before/at the C1 contract-lock call, another
    transaction deletes that edge and commits, and the helper still requests
    the exact p_employment_id key) is proven by the dedicated live node
    ``test_w1e_0026_pg_employment_helper_transient_disappearance_still_locks_employment``.
    """

    with database_engine.connect() as seed_connection:
        seed_transaction = seed_connection.begin()
        case = _seed_case(seed_connection)
        assignment_id = _insert_assignment(
            seed_connection,
            case,
            staff_id=case.staff_a_id,
            employment_id=case.employment_a_id,
            assignment_kind="GENERAL",
            family_relationship_text=None,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 12, 31),
        )
        if assignment_id <= 0:
            _fail("W1E_0026_LOCK_HELPER_SEED_ASSIGNMENT_INVALID")
        seed_transaction.commit()

    def _expect_employment_lock_conflict(
        connection: Connection,
        employment_id: int,
        staff_id: int,
        marker: str,
    ) -> None:
        transaction = connection.begin()
        try:
            _call_w1e_lock_employment_assignment_edges(
                connection,
                employment_id,
                staff_id,
            )
        except OperationalError as error:
            if _sqlstate_of_error(error) != "55P03":
                _fail(marker + "_SQLSTATE_MISMATCH:" + repr(_sqlstate_of_error(error)))
            if _message_primary_of_error(error) != "CARE_ASSIGNMENT_CONCURRENT_CONFLICT":
                _fail(marker + "_MESSAGE_MISMATCH:" + repr(_message_primary_of_error(error)))
            transaction.rollback()
            return
        transaction.rollback()
        _fail(marker + "_ACCEPTED")

    # Phase 1: with no committed edge the helper must still attempt the
    # employment-domain lock, so an uncommitted assignment cannot race a parent.
    empty_employment_id = case.employment_b_id
    empty_staff_id = case.staff_b_id
    with database_engine.connect() as employment_blocker:
        employment_blocker_transaction = employment_blocker.begin()
        _hold_w1e_advisory_xact_lock(
            employment_blocker,
            "erp.w1e.employment",
            empty_employment_id,
        )
        parent_connection = database_engine.connect()
        try:
            _expect_employment_lock_conflict(
                parent_connection,
                empty_employment_id,
                empty_staff_id,
                "W1E_0026_EMPTY_EDGE_LOCK_CONFLICT",
            )
        finally:
            parent_connection.close()
        employment_blocker_transaction.rollback()

    # Phase 2: with a committed edge the helper acquires the contract key first
    # and then must still attempt the employment-domain lock.
    employment_id = case.employment_a_id
    staff_id = case.staff_a_id
    with database_engine.connect() as employment_blocker:
        employment_blocker_transaction = employment_blocker.begin()
        _hold_w1e_advisory_xact_lock(
            employment_blocker,
            "erp.w1e.employment",
            employment_id,
        )
        parent_connection = database_engine.connect()
        try:
            _expect_employment_lock_conflict(
                parent_connection,
                employment_id,
                staff_id,
                "W1E_0026_EDGE_LOCK_CONFLICT",
            )
        finally:
            parent_connection.close()
        employment_blocker_transaction.rollback()


def test_w1e_0026_pg_employment_helper_transient_disappearance_still_locks_employment(
    database_engine: Engine,
) -> None:
    """Force the exact transient edge-disappearance interleaving.

    The production employment helper is not modified.  Only the smaller
    contract-path helper is temporarily instrumented with an explicit advisory
    test gate so the helper can be paused deterministically after its first
    contract-edge SELECT observes committed C1 and before/at the C1
    contract-lock call.  Instrumentation lives inside a restoration-guaranteed
    scope: cleanup always releases the gate and E blocker, joins or cancels the
    helper, terminates only inside the isolated ephemeral cluster, restores the
    original ``pg_get_functiondef`` DDL, compares the whole ``pg_proc``
    identity via ``to_jsonb(pg_proc)::text``, and runs ``verify_current_0026``
    before any primary or cleanup failure is surfaced.
    """

    contract_path_function_name = "fn_w1e_lock_contract_path"
    contract_path_identity_arguments = "p_contract_id bigint"

    with database_engine.connect() as baseline_connection:
        verify_current_0026(baseline_connection)

    with database_engine.connect() as seed_connection:
        seed_transaction = seed_connection.begin()
        case = _seed_case(seed_connection)
        assignment_id = _insert_assignment(
            seed_connection,
            case,
            staff_id=case.staff_a_id,
            employment_id=case.employment_a_id,
            assignment_kind="GENERAL",
            family_relationship_text=None,
            start_date=date(2030, 1, 1),
            end_date=date(2030, 12, 31),
        )
        if assignment_id <= 0:
            _fail("W1E_0026_TRANSIENT_SEED_ASSIGNMENT_INVALID")
        seed_transaction.commit()

    before_catalog = _capture_lock_function_catalog(
        database_engine,
        contract_path_function_name,
        contract_path_identity_arguments,
    )

    gate_connection: Connection | None = None
    gate_transaction = None
    employment_blocker_connection: Connection | None = None
    employment_blocker_transaction = None
    helper_connection: Connection | None = None
    helper_thread: threading.Thread | None = None
    helper_result: list[tuple[str, object]] | None = None
    helper_pid = [-1]
    blocker_pid = -1
    pid_ready = threading.Event()
    primary_error: BaseException | None = None
    cleanup_errors: list[str] = []
    cleanup_interrupt: KeyboardInterrupt | None = None

    try:
        with database_engine.begin() as instrument_connection:
            instrument_connection.execute(text(_TRANSIENT_CONTRACT_PATH_GATE_SQL))

        _assert_distinct_advisory_hashes(
            database_engine,
            [
                ("erp.w1e.contract", case.contract_id),
                ("erp.w1e.employment", case.employment_a_id),
                (_TRANSIENT_CONTRACT_GATE_DOMAIN, case.contract_id),
            ],
            "W1E_0026_TRANSIENT_DOMAIN_HASH_COLLISION",
        )

        gate_connection = database_engine.connect()
        gate_transaction = gate_connection.begin()
        _hold_w1e_advisory_xact_lock(
            gate_connection,
            _TRANSIENT_CONTRACT_GATE_DOMAIN,
            case.contract_id,
        )
        gate_pid = int(gate_connection.execute(text("SELECT pg_backend_pid()")).scalar_one())

        employment_blocker_connection = database_engine.connect()
        employment_blocker_transaction = employment_blocker_connection.begin()
        _hold_w1e_advisory_xact_lock(
            employment_blocker_connection,
            "erp.w1e.employment",
            case.employment_a_id,
        )
        blocker_pid = int(
            employment_blocker_connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
        )

        helper_connection = database_engine.connect()

        def helper_action(connection: Connection) -> None:
            helper_pid[0] = int(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
            pid_ready.set()
            _call_w1e_lock_employment_assignment_edges(
                connection,
                case.employment_a_id,
                case.staff_a_id,
            )

        helper_thread, helper_result = _run_connection_transaction_thread(
            helper_connection,
            helper_action,
            thread_name="w1e-0026-transient-helper",
        )

        if not pid_ready.wait(timeout=10):
            _proof_fail("W1E_0026_TRANSIENT_HELPER_PID_NOT_READY")

        if not _wait_for_exact_advisory_lock(
            database_engine,
            helper_pid[0],
            domain=_TRANSIENT_CONTRACT_GATE_DOMAIN,
            key=case.contract_id,
            granted=False,
            timeout_seconds=10,
        ):
            _proof_fail("W1E_0026_TRANSIENT_GATE_NOT_OBSERVED")

        if _committed_assignment_count(database_engine, assignment_id) != 1:
            _proof_fail("W1E_0026_TRANSIENT_EDGE_MISSING_AT_GATE")
        if _advisory_lock_held(
            database_engine,
            helper_pid[0],
            domain="erp.w1e.contract",
            key=case.contract_id,
            granted=True,
        ):
            _proof_fail("W1E_0026_TRANSIENT_HELPER_HELD_PRODUCTION_C_AT_GATE")
        if _advisory_lock_held(
            database_engine,
            helper_pid[0],
            domain="erp.w1e.employment",
            key=case.employment_a_id,
            granted=True,
        ):
            _proof_fail("W1E_0026_TRANSIENT_HELPER_HELD_PRODUCTION_E_AT_GATE")
        contract_holders = _advisory_holder_pids(
            database_engine,
            domain="erp.w1e.contract",
            key=case.contract_id,
            granted=True,
        )
        if contract_holders:
            _proof_fail("W1E_0026_TRANSIENT_UNRELATED_C_BLOCKER_AT_GATE:" + repr(contract_holders))
        employment_holders = _advisory_holder_pids(
            database_engine,
            domain="erp.w1e.employment",
            key=case.employment_a_id,
            granted=True,
        )
        if employment_holders != {blocker_pid}:
            _proof_fail("W1E_0026_TRANSIENT_E_BLOCKER_NOT_HELD_AT_GATE:" + repr(employment_holders))
        gate_holders = _advisory_holder_pids(
            database_engine,
            domain=_TRANSIENT_CONTRACT_GATE_DOMAIN,
            key=case.contract_id,
            granted=True,
        )
        if gate_holders != {gate_pid}:
            _proof_fail("W1E_0026_TRANSIENT_GATE_HOLDER_MISMATCH:" + repr(gate_holders))

        with database_engine.begin() as delete_connection:
            deleted_id = delete_connection.execute(
                text(
                    """
                    DELETE FROM erp.care_assignment
                     WHERE id = :assignment_id
                    RETURNING id
                    """
                ),
                {"assignment_id": assignment_id},
            ).scalar_one_or_none()
        if deleted_id is None or int(deleted_id) != assignment_id:
            _proof_fail("W1E_0026_TRANSIENT_EDGE_DELETE_MISMATCH")
        if _committed_assignment_count(database_engine, assignment_id) != 0:
            _proof_fail("W1E_0026_TRANSIENT_EDGE_STILL_PRESENT")
        if not _advisory_lock_held(
            database_engine,
            helper_pid[0],
            domain=_TRANSIENT_CONTRACT_GATE_DOMAIN,
            key=case.contract_id,
            granted=False,
        ):
            _proof_fail("W1E_0026_TRANSIENT_HELPER_LEFT_GATE_BEFORE_RESUME")

        # The helper remains paused on the test gate after the committed DELETE,
        # so the first contract-edge SELECT already observed C1.  Release the
        # gate and let it resume through the C1 contract-lock point; the exact
        # E-key blocker must then produce the stable 55P03/message.
        gate_transaction.rollback()
        gate_transaction = None

        helper_thread.join(timeout=20)
        if helper_thread.is_alive():
            _proof_fail("W1E_0026_TRANSIENT_HELPER_STILL_ALIVE")

        if helper_result is None:
            _proof_fail("W1E_0026_TRANSIENT_HELPER_RESULT_MISSING")
        outcome, error = helper_result[0]
        if outcome != "error":
            _proof_fail("W1E_0026_TRANSIENT_HELPER_ACCEPTED")
        if not isinstance(error, BaseException):
            _proof_fail("W1E_0026_TRANSIENT_HELPER_ERROR_TYPE_MISMATCH")
        sqlstate = _sqlstate_of_error(error)
        message = _message_primary_of_error(error)
        if sqlstate == "40P01":
            _proof_fail("W1E_0026_TRANSIENT_DEADLOCK_DETECTED")
        if sqlstate != "55P03" or message != "CARE_ASSIGNMENT_CONCURRENT_CONFLICT":
            _proof_fail(
                "W1E_0026_TRANSIENT_HELPER_LOCK_CONFLICT_MISMATCH: sqlstate="
                + repr(sqlstate)
                + " message="
                + repr(message)
            )

        employment_holders = _advisory_holder_pids(
            database_engine,
            domain="erp.w1e.employment",
            key=case.employment_a_id,
            granted=True,
        )
        if employment_holders != {blocker_pid}:
            _proof_fail(
                "W1E_0026_TRANSIENT_E_BLOCKER_NOT_HELD_AT_CONFLICT:" + repr(employment_holders)
            )
        contract_holders = _advisory_holder_pids(
            database_engine,
            domain="erp.w1e.contract",
            key=case.contract_id,
            granted=True,
        )
        if contract_holders:
            _proof_fail(
                "W1E_0026_TRANSIENT_UNRELATED_C_BLOCKER_AT_CONFLICT:" + repr(contract_holders)
            )

        if _advisory_lock_held(
            database_engine,
            helper_pid[0],
            domain="erp.w1e.contract",
            key=case.contract_id,
            granted=True,
        ):
            _proof_fail("W1E_0026_TRANSIENT_HELPER_HELD_C1_AFTER_ROLLBACK")
        if _advisory_lock_held(
            database_engine,
            helper_pid[0],
            domain="erp.w1e.employment",
            key=case.employment_a_id,
            granted=True,
        ):
            _proof_fail("W1E_0026_TRANSIENT_HELPER_HELD_E_AFTER_ROLLBACK")

        with database_engine.connect() as check_connection:
            residual_count = int(
                check_connection.execute(
                    text(
                        """
                        SELECT count(*)
                          FROM erp.care_assignment
                         WHERE staff_id = :staff_id
                           AND employment_id = :employment_id
                           AND invalidated_at_utc IS NULL
                        """
                    ),
                    {
                        "staff_id": case.staff_a_id,
                        "employment_id": case.employment_a_id,
                    },
                ).scalar_one()
            )
        if residual_count != 0:
            _proof_fail("W1E_0026_TRANSIENT_ORPHAN_RESIDUE_PERSISTED")
    except _TransientProofFailure as exc:
        primary_error = exc
    except BaseException as exc:
        primary_error = exc
    finally:
        try:
            if gate_transaction is not None and gate_transaction.is_active:
                gate_transaction.rollback()
        except Exception as exc:
            cleanup_errors.append("GATE_ROLLBACK:" + type(exc).__name__)
        try:
            if (
                employment_blocker_transaction is not None
                and employment_blocker_transaction.is_active
            ):
                employment_blocker_transaction.rollback()
        except Exception as exc:
            cleanup_errors.append("E_BLOCKER_ROLLBACK:" + type(exc).__name__)

        if helper_thread is not None:
            helper_thread.join(timeout=20)
            if helper_thread.is_alive() and helper_pid[0] > 0:
                try:
                    if not _signal_backend(database_engine, helper_pid[0], terminate=False):
                        cleanup_errors.append("HELPER_CANCEL_RETURNED_FALSE")
                except Exception as exc:
                    cleanup_errors.append("HELPER_CANCEL:" + type(exc).__name__)
                helper_thread.join(timeout=5)
            if helper_thread.is_alive() and helper_pid[0] > 0:
                isolated = False
                try:
                    isolated = _is_isolated_ephemeral_w1e_postgres(database_engine)
                except Exception as exc:
                    cleanup_errors.append("ISOLATED_CHECK:" + type(exc).__name__)
                if isolated:
                    try:
                        if not _signal_backend(database_engine, helper_pid[0], terminate=True):
                            cleanup_errors.append("HELPER_TERMINATE_RETURNED_FALSE")
                    except Exception as exc:
                        cleanup_errors.append("HELPER_TERMINATE:" + type(exc).__name__)
                    helper_thread.join(timeout=5)
                else:
                    cleanup_errors.append("HELPER_STUCK_NON_ISOLATED_NO_TERMINATE")
            if helper_thread.is_alive():
                cleanup_errors.append("HELPER_STILL_ALIVE_AFTER_CLEANUP")

        for close_marker, close_connection in (
            ("GATE_CLOSE", gate_connection),
            ("E_BLOCKER_CLOSE", employment_blocker_connection),
            ("HELPER_CLOSE", helper_connection),
        ):
            try:
                if close_connection is not None:
                    close_connection.invalidate()
                    close_connection.close()
            except Exception as exc:
                cleanup_errors.append(close_marker + ":" + type(exc).__name__)

        if helper_pid[0] > 0:
            try:
                leftover_locks = _backend_advisory_lock_count(database_engine, helper_pid[0])
                if leftover_locks != 0:
                    cleanup_errors.append("HELPER_ADVISORY_RESIDUE:" + str(leftover_locks))
            except Exception as exc:
                cleanup_errors.append("HELPER_LOCK_PROBE:" + type(exc).__name__)
            try:
                if _backend_is_alive(database_engine, helper_pid[0]):
                    cleanup_errors.append("HELPER_PID_STILL_ALIVE")
            except Exception as exc:
                cleanup_errors.append("HELPER_PID_PROBE:" + type(exc).__name__)

        try:
            with database_engine.begin() as restore_connection:
                restore_connection.exec_driver_sql(before_catalog["definition"])
        except Exception as exc:
            cleanup_errors.append("RESTORE_DDL:" + type(exc).__name__ + ":" + str(exc))
        try:
            after_catalog = _capture_lock_function_catalog(
                database_engine,
                contract_path_function_name,
                contract_path_identity_arguments,
            )
            mismatch = _lock_function_catalog_mismatch(before_catalog, after_catalog)
            if mismatch is not None:
                cleanup_errors.append(mismatch)
        except Exception as exc:
            cleanup_errors.append("CATALOG_COMPARE:" + type(exc).__name__ + ":" + str(exc))
        try:
            with database_engine.connect() as verify_connection:
                verify_current_0026(verify_connection)
        except BaseException as exc:
            if isinstance(exc, KeyboardInterrupt):
                cleanup_interrupt = exc
            cleanup_errors.append("VERIFY_CURRENT_0026:" + type(exc).__name__ + ":" + str(exc))

        if isinstance(primary_error, KeyboardInterrupt):
            raise primary_error
        if cleanup_interrupt is not None:
            raise cleanup_interrupt
        if primary_error is not None or cleanup_errors:
            parts: list[str] = []
            if primary_error is not None:
                parts.append("PRIMARY:" + type(primary_error).__name__ + ":" + str(primary_error))
            if cleanup_errors:
                parts.append("CLEANUP:" + " | ".join(cleanup_errors))
            _fail("W1E_0026_TRANSIENT_PROOF: " + " ".join(parts))


def test_w1e_0026_pg_period_fact_correction_boundary(
    database_connection: Connection,
) -> None:
    case = _seed_case(database_connection)
    old_id = _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        assignment_kind="GENERAL",
        family_relationship_text=None,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
    )
    _flush_constraints(database_connection)

    database_connection.execute(
        text(
            """
            UPDATE erp.care_assignment
               SET invalidated_at_utc = clock_timestamp(),
                   row_version = row_version + 1
             WHERE id = :id
            """
        ),
        {"id": old_id},
    )
    replacement_id = _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        assignment_kind="GENERAL",
        family_relationship_text=None,
        start_date=date(2030, 1, 15),
        end_date=date(2030, 2, 15),
    )
    if replacement_id == old_id:
        _fail("W1E_0026_PERIOD_FACT_STABLE_ID_COLLISION")
    database_connection.execute(
        text(
            """
            UPDATE erp.care_assignment
               SET replacement_assignment_id = :replacement_id,
                   row_version = row_version + 1
             WHERE id = :old_id
            """
        ),
        {"old_id": old_id, "replacement_id": replacement_id},
    )
    _flush_constraints(database_connection)

    row = database_connection.execute(
        text(
            """
            SELECT old.id,
                   old.invalidated_at_utc IS NOT NULL,
                   old.replacement_assignment_id,
                   replacement.replacement_assignment_id,
                   replacement.id,
                   old.assignment_period && replacement.assignment_period
              FROM erp.care_assignment old
              JOIN erp.care_assignment replacement
                ON replacement.id = :replacement_id
             WHERE old.id = :old_id
            """
        ),
        {"old_id": old_id, "replacement_id": replacement_id},
    ).one()
    if row != (
        old_id,
        True,
        replacement_id,
        None,
        replacement_id,
        True,
    ):
        _fail("W1E_0026_PERIOD_FACT_CORRECTION_MISMATCH")


def _expect_app_privilege_denied(
    connection: Connection,
    statement: str,
    marker: str,
) -> None:
    savepoint = connection.begin_nested()
    try:
        connection.execute(text(statement))
    except Exception as error:
        savepoint.rollback()
        original = getattr(error, "orig", None)
        sqlstate = getattr(original, "sqlstate", None)
        if sqlstate is None:
            diagnostic = getattr(original, "diag", None)
            sqlstate = getattr(diagnostic, "sqlstate", None)
        if sqlstate != "42501":
            _fail(marker + "_SQLSTATE_MISMATCH:" + repr(sqlstate))
        return
    savepoint.rollback()
    _fail(marker)


def test_w1e_0026_pg_postcheck_assertions_pass_without_trigger_bypass(
    database_connection: Connection,
) -> None:
    replication_role = database_connection.execute(
        text("SHOW session_replication_role")
    ).scalar_one()
    if str(replication_role) != "origin":
        _fail("W1E_0026_TRIGGER_BYPASS_REPLICATION_ROLE:" + repr(replication_role))

    non_origin_triggers = (
        database_connection.execute(
            text(
                """
            SELECT t.tgname
              FROM pg_trigger AS t
              JOIN pg_class AS c ON c.oid = t.tgrelid
              JOIN pg_namespace AS n ON n.oid = c.relnamespace
             WHERE n.nspname = 'erp'
               AND c.relname = 'care_assignment'
               AND NOT t.tgisinternal
               AND t.tgenabled <> 'O'
             ORDER BY t.tgname
            """
            )
        )
        .scalars()
        .all()
    )
    if non_origin_triggers:
        _fail(
            "W1E_0026_TRIGGER_NOT_ORIGIN_ENABLED: "
            + ",".join(str(name) for name in non_origin_triggers)
        )

    app_database_url = os.environ.get("SSWCENTER_APP_DATABASE_URL")
    if not app_database_url:
        _fail("W1E_0026_HARNESS_APP_DATABASE_URL_MISSING")
    app_engine = create_engine(app_database_url, pool_pre_ping=True)
    try:
        with app_engine.connect() as app_connection:
            _expect_app_privilege_denied(
                app_connection,
                "SET LOCAL session_replication_role = 'replica'",
                "W1E_0026_APP_ROLE_CAN_SET_REPLICA",
            )
            _expect_app_privilege_denied(
                app_connection,
                "ALTER TABLE erp.care_assignment DISABLE TRIGGER USER",
                "W1E_0026_APP_ROLE_CAN_DISABLE_TRIGGER",
            )
    finally:
        app_engine.dispose()

    verify_current_0026(database_connection)

    for acl_mutation in (
        "GRANT REFERENCES ON TABLE erp.care_assignment TO erp_app",
        "GRANT TRIGGER ON TABLE erp.care_assignment TO erp_app",
        "GRANT SELECT ON TABLE erp.care_assignment TO erp_app WITH GRANT OPTION",
    ):
        acl_savepoint = database_connection.begin_nested()
        try:
            database_connection.execute(text(acl_mutation))
            with pytest.raises(
                SystemExit,
                match="CURRENT_0026_CARE_ASSIGNMENT_APP_ACL_MISMATCH",
            ):
                verify_current_0026(database_connection)
        finally:
            if acl_savepoint.is_active:
                acl_savepoint.rollback()
        verify_current_0026(database_connection)

    exclusion_savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                "ALTER TABLE erp.care_assignment DROP CONSTRAINT "
                "ex_care_assignment_same_contract_staff_period"
            )
        )
        database_connection.execute(
            text(
                "ALTER TABLE erp.care_assignment ADD CONSTRAINT "
                "ex_care_assignment_same_contract_staff_period "
                "EXCLUDE USING gist (recipient_contract_id WITH =, "
                "assignment_period WITH &&) "
                "WHERE (invalidated_at_utc IS NULL)"
            )
        )
        with pytest.raises(
            SystemExit,
            match="CURRENT_0026_CARE_ASSIGNMENT_EXCLUSION_MISMATCH",
        ):
            verify_current_0026(database_connection)
    finally:
        if exclusion_savepoint.is_active:
            exclusion_savepoint.rollback()
    verify_current_0026(database_connection)

    family_savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                "ALTER TABLE erp.care_assignment DROP CONSTRAINT "
                "ck_care_assignment_family_relationship_present"
            )
        )
        database_connection.execute(
            text(
                "ALTER TABLE erp.care_assignment ADD CONSTRAINT "
                "ck_care_assignment_family_relationship_present "
                "CHECK (assignment_kind <> 'FAMILY' OR "
                "family_relationship_text IS NOT NULL)"
            )
        )
        with pytest.raises(
            SystemExit,
            match="CURRENT_0026_CARE_ASSIGNMENT_FAMILY_CHECK_MISMATCH",
        ):
            verify_current_0026(database_connection)
    finally:
        if family_savepoint.is_active:
            family_savepoint.rollback()
    verify_current_0026(database_connection)

    family_precedence_savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                "ALTER TABLE erp.care_assignment DROP CONSTRAINT "
                "ck_care_assignment_family_relationship_present"
            )
        )
        database_connection.execute(
            text(
                "ALTER TABLE erp.care_assignment ADD CONSTRAINT "
                "ck_care_assignment_family_relationship_present "
                "CHECK ((assignment_kind <> 'FAMILY' OR "
                "family_relationship_text IS NOT NULL) AND "
                "btrim(family_relationship_text) <> '')"
            )
        )
        with pytest.raises(
            SystemExit,
            match="CURRENT_0026_CARE_ASSIGNMENT_FAMILY_CHECK_MISMATCH",
        ):
            verify_current_0026(database_connection)
    finally:
        if family_precedence_savepoint.is_active:
            family_precedence_savepoint.rollback()
    verify_current_0026(database_connection)

    family_four_char_savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                "ALTER TABLE erp.care_assignment DROP CONSTRAINT "
                "ck_care_assignment_family_relationship_present"
            )
        )
        database_connection.execute(
            text(
                "ALTER TABLE erp.care_assignment ADD CONSTRAINT "
                "ck_care_assignment_family_relationship_present "
                "CHECK (assignment_kind <> 'FAMILY' OR "
                "(family_relationship_text IS NOT NULL AND "
                "btrim(family_relationship_text, E' \\t\\n\\r') <> ''))"
            )
        )
        with pytest.raises(
            SystemExit,
            match="CURRENT_0026_CARE_ASSIGNMENT_FAMILY_CHECK_MISMATCH",
        ):
            verify_current_0026(database_connection)
    finally:
        if family_four_char_savepoint.is_active:
            family_four_char_savepoint.rollback()
    verify_current_0026(database_connection)

    family_date_cast_savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                "ALTER TABLE erp.care_assignment DROP CONSTRAINT "
                "ck_care_assignment_family_relationship_present"
            )
        )
        database_connection.execute(
            text(
                "ALTER TABLE erp.care_assignment ADD CONSTRAINT "
                "ck_care_assignment_family_relationship_present "
                "CHECK (assignment_kind <> 'FAMILY' OR "
                "(family_relationship_text::date IS NOT NULL AND "
                "btrim(family_relationship_text, E' \\\\t\\\\n\\\\r\\\\f\\\\x0b') <> '')) "
                "NOT VALID"
            )
        )
        with pytest.raises(
            SystemExit,
            match="CURRENT_0026_CARE_ASSIGNMENT_FAMILY_CHECK_MISMATCH",
        ):
            verify_current_0026(database_connection)
    finally:
        if family_date_cast_savepoint.is_active:
            family_date_cast_savepoint.rollback()
    verify_current_0026(database_connection)

    kind_savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text("ALTER TABLE erp.care_assignment DROP CONSTRAINT ck_care_assignment_kind")
        )
        database_connection.execute(
            text(
                "ALTER TABLE erp.care_assignment ADD CONSTRAINT "
                "ck_care_assignment_kind "
                "CHECK (assignment_kind IN ('GENERAL', 'FAMILY', 'OTHER'))"
            )
        )
        with pytest.raises(
            SystemExit,
            match="CURRENT_0026_CARE_ASSIGNMENT_KIND_CHECK_MISMATCH",
        ):
            verify_current_0026(database_connection)
    finally:
        if kind_savepoint.is_active:
            kind_savepoint.rollback()
    verify_current_0026(database_connection)

    extra_trigger_savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                "CREATE TRIGGER w1e_0026_extra_care_assignment_trigger "
                "AFTER INSERT OR UPDATE ON erp.care_assignment "
                "FOR EACH ROW EXECUTE FUNCTION erp.fn_care_assignment_within_contract()"
            )
        )
        with pytest.raises(
            SystemExit,
            match="CURRENT_0026_W1E_TRIGGER_CONTRACT_MISMATCH",
        ):
            verify_current_0026(database_connection)
    finally:
        if extra_trigger_savepoint.is_active:
            extra_trigger_savepoint.rollback()
    verify_current_0026(database_connection)

    function_savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                """
                CREATE OR REPLACE FUNCTION erp.fn_care_assignment_within_contract()
                RETURNS trigger
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RETURN NEW;
                END
                $$;
                """
            )
        )
        with pytest.raises(
            SystemExit,
            match="CURRENT_0026_W1E_TRIGGER_CONTRACT_MISMATCH",
        ):
            verify_current_0026(database_connection)
    finally:
        if function_savepoint.is_active:
            function_savepoint.rollback()
    verify_current_0026(database_connection)

    lock_function_savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                """
                CREATE OR REPLACE FUNCTION erp.fn_w1e_lock_contract_path(
                    p_contract_id bigint
                )
                RETURNS void
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RETURN;
                END
                $$;
                """
            )
        )
        with pytest.raises(
            SystemExit,
            match="CURRENT_0026_W1E_LOCK_CONTRACT_MISMATCH",
        ):
            verify_current_0026(database_connection)
    finally:
        if lock_function_savepoint.is_active:
            lock_function_savepoint.rollback()
    verify_current_0026(database_connection)

    expected_0026_bodies = _migration_0026_function_bodies()
    for (_table_name, _trigger_name), expectation in sorted(W1E_TRIGGER_EXPECTATIONS.items()):
        function_name = str(expectation["function"])
        expected_body = expected_0026_bodies[function_name]
        dead_code_function_sql = _dead_code_trigger_function_sql(function_name, expected_body)
        dead_code_savepoint = database_connection.begin_nested()
        try:
            database_connection.execute(text(dead_code_function_sql))
            with pytest.raises(
                SystemExit,
                match="CURRENT_0026_W1E_TRIGGER_CONTRACT_MISMATCH",
            ):
                verify_current_0026(database_connection)
        finally:
            if dead_code_savepoint.is_active:
                dead_code_savepoint.rollback()
        verify_current_0026(database_connection)

    bypass_savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                "ALTER TABLE erp.care_assignment ENABLE REPLICA TRIGGER "
                "ct_care_assignment_within_contract"
            )
        )
        with pytest.raises(
            SystemExit,
            match="CURRENT_0026_W1E_TRIGGER_STATE_MISMATCH",
        ):
            verify_current_0026(database_connection)
    finally:
        if bypass_savepoint.is_active:
            bypass_savepoint.rollback()

    verify_current_0026(database_connection)


def test_w1e_0026_pg_lock_function_integer_overload_rejected(
    database_connection: Connection,
) -> None:
    savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                """
                CREATE FUNCTION erp.fn_w1e_lock_contract_path(
                    p_contract_id integer
                )
                RETURNS void
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RETURN;
                END
                $$;
                """
            )
        )
        with pytest.raises(
            SystemExit,
            match="CURRENT_0026_W1E_LOCK_CONTRACT_MISMATCH",
        ) as raised:
            verify_current_0026(database_connection)
        message = str(raised.value)
        assert "overloads:fn_w1e_lock_contract_path:count=2" in message
        assert "missing:fn_w1e_lock_contract_path" not in message
    finally:
        if savepoint.is_active:
            savepoint.rollback()
    verify_current_0026(database_connection)

    missing_savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(text("DROP FUNCTION erp.fn_w1e_lock_contract_path(bigint)"))
        with pytest.raises(
            SystemExit,
            match="CURRENT_0026_W1E_LOCK_CONTRACT_MISMATCH",
        ) as raised:
            verify_current_0026(database_connection)
        assert "missing:fn_w1e_lock_contract_path" in str(raised.value)
    finally:
        if missing_savepoint.is_active:
            missing_savepoint.rollback()
    verify_current_0026(database_connection)

    renamed_savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(text("DROP FUNCTION erp.fn_w1e_lock_contract_path(bigint)"))
        database_connection.execute(
            text(
                """
                CREATE FUNCTION erp.fn_w1e_lock_contract_path(
                    p_wrong_id bigint
                )
                RETURNS void
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    PERFORM pg_advisory_xact_lock(
                        hashtextextended('erp.w1e.contract', p_wrong_id)
                    );
                END
                $$;
                """
            )
        )
        with pytest.raises(
            SystemExit,
            match="CURRENT_0026_W1E_LOCK_CONTRACT_MISMATCH",
        ) as raised:
            verify_current_0026(database_connection)
        assert "arguments:fn_w1e_lock_contract_path:" in str(raised.value)
    finally:
        if renamed_savepoint.is_active:
            renamed_savepoint.rollback()
    verify_current_0026(database_connection)


def test_w1e_0026_pg_lock_function_global_remnant_rejected(
    database_connection: Connection,
) -> None:
    remnant_savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                """
                CREATE FUNCTION erp.fn_w1e_lock_global()
                RETURNS void
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    PERFORM pg_advisory_xact_lock(
                        hashtextextended('erp.w1e.global', 0)
                    );
                END
                $$;
                """
            )
        )
        with pytest.raises(
            SystemExit,
            match="CURRENT_0026_W1E_FORBIDDEN_LOCK_REMNANT",
        ) as raised:
            verify_current_0026(database_connection)
        message = str(raised.value)
        assert "function:fn_w1e_lock_global()" in message
        assert "body:fn_w1e_lock_global:erp.w1e.global" in message
    finally:
        if remnant_savepoint.is_active:
            remnant_savepoint.rollback()
    verify_current_0026(database_connection)


def test_w1e_0026_pg_care_assignment_sequence_acl_fails_closed(
    database_connection: Connection,
    superuser_engine: Engine,
) -> None:
    """Exact 0012 sequence ownership/ACL and fail-closed missing erp_app."""

    verify_current_0026(database_connection)

    with superuser_engine.connect() as super_connection:
        transaction = super_connection.begin()
        try:
            super_connection.execute(text("DROP OWNED BY erp_app"))
            super_connection.execute(text("DROP ROLE erp_app"))
            with pytest.raises(
                SystemExit,
                match="CURRENT_0026_ERP_APP_ROLE_MISSING",
            ):
                verify_current_0026(super_connection)
        finally:
            transaction.rollback()
    verify_current_0026(database_connection)

    app_mutations = (
        "GRANT UPDATE ON SEQUENCE erp.care_assignment_id_seq TO erp_app",
        "GRANT SELECT ON SEQUENCE erp.care_assignment_id_seq TO erp_app WITH GRANT OPTION",
        "GRANT USAGE ON SEQUENCE erp.care_assignment_id_seq TO erp_app WITH GRANT OPTION",
        "GRANT UPDATE ON SEQUENCE erp.care_assignment_id_seq TO erp_app WITH GRANT OPTION",
        "REVOKE USAGE ON SEQUENCE erp.care_assignment_id_seq FROM erp_app",
        "REVOKE SELECT ON SEQUENCE erp.care_assignment_id_seq FROM erp_app",
    )
    for mutation in app_mutations:
        savepoint = database_connection.begin_nested()
        try:
            database_connection.execute(text(mutation))
            with pytest.raises(
                SystemExit,
                match="CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_APP_ACL_MISMATCH",
            ):
                verify_current_0026(database_connection)
        finally:
            if savepoint.is_active:
                savepoint.rollback()
        verify_current_0026(database_connection)

    backup_mutations = (
        "GRANT USAGE ON SEQUENCE erp.care_assignment_id_seq TO erp_backup",
        "GRANT UPDATE ON SEQUENCE erp.care_assignment_id_seq TO erp_backup",
        "GRANT SELECT ON SEQUENCE erp.care_assignment_id_seq TO erp_backup WITH GRANT OPTION",
        "REVOKE SELECT ON SEQUENCE erp.care_assignment_id_seq FROM erp_backup",
    )
    for mutation in backup_mutations:
        savepoint = database_connection.begin_nested()
        try:
            database_connection.execute(text(mutation))
            with pytest.raises(
                SystemExit,
                match="CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_BACKUP_ACL_MISMATCH",
            ):
                verify_current_0026(database_connection)
        finally:
            if savepoint.is_active:
                savepoint.rollback()
        verify_current_0026(database_connection)

    public_mutations = (
        (
            "GRANT SELECT ON SEQUENCE erp.care_assignment_id_seq TO PUBLIC",
            "REVOKE SELECT ON SEQUENCE erp.care_assignment_id_seq FROM PUBLIC",
        ),
        (
            "GRANT USAGE ON SEQUENCE erp.care_assignment_id_seq TO PUBLIC",
            "REVOKE USAGE ON SEQUENCE erp.care_assignment_id_seq FROM PUBLIC",
        ),
        (
            "GRANT UPDATE ON SEQUENCE erp.care_assignment_id_seq TO PUBLIC",
            "REVOKE UPDATE ON SEQUENCE erp.care_assignment_id_seq FROM PUBLIC",
        ),
    )
    with superuser_engine.connect() as super_connection:
        transaction = super_connection.begin()
        try:
            for grant_sql, revoke_sql in public_mutations:
                savepoint = super_connection.begin_nested()
                try:
                    super_connection.execute(text(grant_sql))
                    with pytest.raises(
                        SystemExit,
                        match="CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_(ACL|APP_ACL|BACKUP_ACL)_MISMATCH",
                    ):
                        verify_current_0026(super_connection)
                    super_connection.execute(text(revoke_sql))
                    verify_current_0026(super_connection)
                finally:
                    if savepoint.is_active:
                        savepoint.rollback()
        finally:
            transaction.rollback()
    verify_current_0026(database_connection)

    third_role_mutations = (
        (
            "GRANT SELECT ON SEQUENCE erp.care_assignment_id_seq TO w1e_0026_sequence_third",
            "REVOKE SELECT ON SEQUENCE erp.care_assignment_id_seq FROM w1e_0026_sequence_third",
        ),
        (
            "GRANT USAGE ON SEQUENCE erp.care_assignment_id_seq TO w1e_0026_sequence_third",
            "REVOKE USAGE ON SEQUENCE erp.care_assignment_id_seq FROM w1e_0026_sequence_third",
        ),
        (
            "GRANT UPDATE ON SEQUENCE erp.care_assignment_id_seq TO w1e_0026_sequence_third",
            "REVOKE UPDATE ON SEQUENCE erp.care_assignment_id_seq FROM w1e_0026_sequence_third",
        ),
    )
    with superuser_engine.connect() as super_connection:
        transaction = super_connection.begin()
        try:
            super_connection.execute(text("CREATE ROLE w1e_0026_sequence_third LOGIN"))
            for grant_sql, revoke_sql in third_role_mutations:
                savepoint = super_connection.begin_nested()
                try:
                    super_connection.execute(text(grant_sql))
                    with pytest.raises(
                        SystemExit,
                        match="CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_(ACL|APP_ACL|BACKUP_ACL)_MISMATCH",
                    ):
                        verify_current_0026(super_connection)
                    super_connection.execute(text(revoke_sql))
                    verify_current_0026(super_connection)
                finally:
                    if savepoint.is_active:
                        savepoint.rollback()
        finally:
            transaction.rollback()
    verify_current_0026(database_connection)

    # An owner-grantee ACL row must still be checked, not skipped blindly:
    # a third role that holds grant option can grant the sequence back to its
    # owner, producing an owner row whose grantor is not the sequence owner.
    with superuser_engine.connect() as super_connection:
        transaction = super_connection.begin()
        try:
            super_connection.execute(text("CREATE ROLE w1e_0026_sequence_granter LOGIN"))
            owner_grantor_savepoint = super_connection.begin_nested()
            try:
                super_connection.execute(
                    text("GRANT USAGE ON SCHEMA erp TO w1e_0026_sequence_granter")
                )
                super_connection.execute(
                    text(
                        "GRANT SELECT, USAGE ON SEQUENCE "
                        "erp.care_assignment_id_seq "
                        "TO w1e_0026_sequence_granter WITH GRANT OPTION"
                    )
                )
                super_connection.execute(text("SET ROLE w1e_0026_sequence_granter"))
                try:
                    super_connection.execute(
                        text("GRANT SELECT ON SEQUENCE erp.care_assignment_id_seq TO erp_owner")
                    )
                finally:
                    super_connection.execute(text("RESET ROLE"))
                with pytest.raises(
                    SystemExit,
                    match="CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_ACL_MISMATCH",
                ):
                    verify_current_0026(super_connection)
            finally:
                if owner_grantor_savepoint.is_active:
                    owner_grantor_savepoint.rollback()
            verify_current_0026(super_connection)
        finally:
            transaction.rollback()
    verify_current_0026(database_connection)

    # An owner row carrying WITH GRANT OPTION is also ACL drift, not an
    # implicit owner privilege.
    owner_grantable_savepoint = database_connection.begin_nested()
    try:
        database_connection.execute(
            text(
                "GRANT SELECT ON SEQUENCE erp.care_assignment_id_seq TO erp_owner WITH GRANT OPTION"
            )
        )
        with pytest.raises(
            SystemExit,
            match="CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_ACL_MISMATCH",
        ):
            verify_current_0026(database_connection)
    finally:
        if owner_grantable_savepoint.is_active:
            owner_grantable_savepoint.rollback()
    verify_current_0026(database_connection)

    # Identity sequences are linked to their table, so PostgreSQL rejects
    # ``ALTER SEQUENCE ... OWNER TO`` (SQLSTATE 0A000). The current postcheck
    # still fail-closes on CURRENT_0026_CARE_ASSIGNMENT_SEQUENCE_OWNER_MISMATCH
    # if the catalog ever shows a sequence owner that is not the table owner.


def test_w1e_0026_pg_lock_function_catalog_properties_fail_closed(
    superuser_engine: Engine,
    database_connection: Connection,
) -> None:
    """Reject altered pg_proc properties and EXECUTE ACL/ownership drift."""

    verify_current_0026(database_connection)

    property_mutations = (
        "ALTER FUNCTION erp.fn_w1e_lock_contract_path(bigint) STABLE",
        "ALTER FUNCTION erp.fn_w1e_lock_contract_path(bigint) STRICT",
        "ALTER FUNCTION erp.fn_w1e_lock_contract_path(bigint) PARALLEL SAFE",
        "ALTER FUNCTION erp.fn_w1e_lock_contract_path(bigint) LEAKPROOF",
        "ALTER FUNCTION erp.fn_w1e_lock_contract_path(bigint) SECURITY DEFINER",
        "ALTER FUNCTION erp.fn_w1e_lock_contract_path(bigint) SET search_path = erp",
        "ALTER FUNCTION erp.fn_w1e_lock_contract_path(bigint) OWNER TO erp_app",
        "GRANT EXECUTE ON FUNCTION erp.fn_w1e_lock_contract_path(bigint) TO erp_app",
        "GRANT EXECUTE ON FUNCTION erp.fn_w1e_lock_contract_path(bigint) TO erp_app WITH GRANT OPTION",  # noqa: E501
    )
    with superuser_engine.connect() as super_connection:
        transaction = super_connection.begin()
        try:
            for mutation in property_mutations:
                savepoint = super_connection.begin_nested()
                try:
                    super_connection.execute(text(mutation))
                    with pytest.raises(
                        SystemExit,
                        match="CURRENT_0026_W1E_LOCK_CONTRACT_MISMATCH",
                    ):
                        verify_current_0026(super_connection)
                finally:
                    if savepoint.is_active:
                        savepoint.rollback()
                verify_current_0026(super_connection)
        finally:
            transaction.rollback()
    verify_current_0026(database_connection)


def test_w1e_0026_pg_http_create_replace_through_real_service_and_audit(
    database_engine: Engine,
) -> None:
    """Prove the real HTTP -> service -> repository -> PostgreSQL -> audit path.

    The application role is used for the HTTP write by pointing
    ``SSWCENTER_DATABASE_URL`` at ``SSWCENTER_APP_DATABASE_URL``.  Only the
    authentication identity is overridden. Because 0026 is a pinned historical
    gate while application readiness correctly requires active 0027, its test
    session dependency uses the same real ``erp_app`` runtime factory after the
    harness's direct 0026 postcheck. The FastAPI service and repository remain
    production objects and must persist the assignment lineage, row versions,
    and exact audit actions.
    """

    from fastapi.testclient import TestClient

    from app.api import dependencies as api_dependencies
    from app.core.auth import CurrentAccount
    from app.core.settings import get_settings
    from app.main import create_app

    app_database_url = os.environ.get("SSWCENTER_APP_DATABASE_URL")
    if not app_database_url:
        _fail("W1E_0026_HARNESS_APP_DATABASE_URL_MISSING")
    if make_url(app_database_url).username != "erp_app":
        _fail("W1E_0026_HARNESS_APP_DATABASE_URL_NOT_ERP_APP")

    previous_database_url = os.environ.get("SSWCENTER_DATABASE_URL")
    previous_environment = os.environ.get("SSWCENTER_ENVIRONMENT")
    os.environ["SSWCENTER_DATABASE_URL"] = app_database_url
    os.environ["SSWCENTER_ENVIRONMENT"] = "test"
    get_settings.cache_clear()
    api_dependencies._database_runtime.cache_clear()

    settings = get_settings()
    if settings.database_url is None or make_url(settings.database_url).username != "erp_app":
        _fail("W1E_0026_HTTP_SETTINGS_DATABASE_URL_NOT_ERP_APP")
    runtime_engine, _factory = api_dependencies._database_runtime(settings.database_url)
    if make_url(str(runtime_engine.url)).username != "erp_app":
        _fail("W1E_0026_HTTP_RUNTIME_ENGINE_NOT_ERP_APP")

    app = create_app()
    if api_dependencies.get_w1e_service in app.dependency_overrides:
        _fail("W1E_0026_HTTP_W1E_SERVICE_OVERRIDDEN")
    overridden: list[Callable[..., object]] = []
    try:
        with database_engine.begin() as seed_connection:
            case = _seed_case(seed_connection)

        account = CurrentAccount(
            id=case.account_id,
            display_name="W1E 0026 HTTP",
            role_code="ADMIN",
        )

        def override_account() -> CurrentAccount:
            return account

        def pinned_0026_session_override() -> Iterator[Session]:
            # Do not weaken active product readiness: this narrow historical
            # harness already ran app.db.postcheck_current_0026 directly.
            _, pinned_factory = api_dependencies._database_runtime(app_database_url)
            session = pinned_factory()
            try:
                yield session
            finally:
                session.rollback()
                session.close()

        app.dependency_overrides[api_dependencies.require_recipient_manage] = override_account
        app.dependency_overrides[api_dependencies.require_recipient_view] = override_account
        app.dependency_overrides[api_dependencies.get_db_session] = pinned_0026_session_override
        overridden.append(api_dependencies.require_recipient_manage)
        overridden.append(api_dependencies.require_recipient_view)
        overridden.append(api_dependencies.get_db_session)

        collection_path = (
            f"/api/v1/recipients/{case.recipient_id}/contracts/{case.contract_id}/assignments"
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            created = client.post(
                collection_path,
                json={
                    "staff_id": case.staff_a_id,
                    "employment_id": case.employment_a_id,
                    "assignment_kind": "GENERAL",
                    "family_relationship_text": None,
                    "start_date": "2030-02-01",
                    "end_date": "2030-02-28",
                },
            )
            if created.status_code != 201:
                _fail("W1E_0026_HTTP_CREATE_NOT_201:" + created.text)
            created_body = created.json()
            assignment_id = int(created_body["id"])
            if int(created_body["row_version"]) != 1:
                _fail("W1E_0026_HTTP_CREATE_ROW_VERSION_NOT_ONE")

            item_path = f"{collection_path}/{assignment_id}"
            replaced = client.put(
                item_path,
                json={
                    "staff_id": case.staff_a_id,
                    "employment_id": case.employment_a_id,
                    "assignment_kind": "GENERAL",
                    "family_relationship_text": None,
                    "start_date": "2030-03-01",
                    "end_date": "2030-03-31",
                    "expected_row_version": 1,
                },
            )
            if replaced.status_code != 200:
                _fail("W1E_0026_HTTP_REPLACE_NOT_200:" + replaced.text)
            replaced_body = replaced.json()
            original = replaced_body["original"]
            replacement = replaced_body["replacement"]
            replacement_id = int(replacement["id"])
            if int(original["row_version"]) != 2:
                _fail("W1E_0026_HTTP_REPLACE_ORIGINAL_ROW_VERSION_NOT_TWO")
            if int(replacement["row_version"]) != 1:
                _fail("W1E_0026_HTTP_REPLACE_REPLACEMENT_ROW_VERSION_NOT_ONE")
            if int(original["replacement_assignment_id"]) != replacement_id:
                _fail("W1E_0026_HTTP_REPLACE_LINEAGE_MISMATCH")

            replacement_item_path = f"{collection_path}/{replacement_id}"
            conflict = client.put(
                replacement_item_path,
                json={
                    "staff_id": case.staff_a_id,
                    "employment_id": case.employment_a_id,
                    "assignment_kind": "GENERAL",
                    "family_relationship_text": None,
                    "start_date": "2030-04-01",
                    "end_date": "2030-04-30",
                    "expected_row_version": 999,
                },
            )
            if conflict.status_code != 409:
                _fail("W1E_0026_HTTP_VERSION_CONFLICT_NOT_409:" + conflict.text)
            if conflict.json()["error"]["code"] != "ROW_VERSION_CONFLICT":
                _fail("W1E_0026_HTTP_VERSION_CONFLICT_CODE_MISMATCH")

        with database_engine.connect() as check_connection:
            rows = (
                check_connection.execute(
                    text(
                        "SELECT id, recipient_contract_id, staff_id, employment_id, "
                        "assignment_kind, row_version, invalidated_at_utc, "
                        "replacement_assignment_id "
                        "FROM erp.care_assignment "
                        "WHERE id IN (:assignment_id, :replacement_id) ORDER BY id"
                    ),
                    {
                        "assignment_id": assignment_id,
                        "replacement_id": replacement_id,
                    },
                )
                .mappings()
                .all()
            )
            if len(rows) != 2:
                _fail("W1E_0026_HTTP_ASSIGNMENT_ROWS_MISMATCH")
            by_id = {int(row["id"]): row for row in rows}
            original_row = by_id[assignment_id]
            replacement_row = by_id[replacement_id]
            if int(original_row["row_version"]) != 2:
                _fail("W1E_0026_HTTP_ORIGINAL_DB_ROW_VERSION_NOT_TWO")
            if original_row["invalidated_at_utc"] is None:
                _fail("W1E_0026_HTTP_ORIGINAL_NOT_INVALIDATED")
            if int(original_row["replacement_assignment_id"]) != replacement_id:
                _fail("W1E_0026_HTTP_ORIGINAL_DB_LINEAGE_MISMATCH")
            if int(replacement_row["row_version"]) != 1:
                _fail("W1E_0026_HTTP_REPLACEMENT_DB_ROW_VERSION_NOT_ONE")
            if replacement_row["invalidated_at_utc"] is not None:
                _fail("W1E_0026_HTTP_REPLACEMENT_INVALIDATED")
            if replacement_row["replacement_assignment_id"] is not None:
                _fail("W1E_0026_HTTP_REPLACEMENT_DB_LINEAGE_PRESENT")

            audit_rows = check_connection.execute(
                text(
                    "SELECT action_code, entity_type, entity_pk, actor_account_id "
                    "FROM erp.audit_event "
                    "WHERE entity_type = 'CARE_ASSIGNMENT' "
                    "AND entity_pk IN (:assignment_id, :replacement_id) ORDER BY id"
                ),
                {
                    "assignment_id": assignment_id,
                    "replacement_id": replacement_id,
                },
            ).all()
            if [str(row.action_code) for row in audit_rows] != [
                "CARE_ASSIGNMENT_CREATE",
                "CARE_ASSIGNMENT_REPLACE",
                "CARE_ASSIGNMENT_REPLACEMENT_CREATE",
            ]:
                _fail(
                    "W1E_0026_HTTP_AUDIT_ACTIONS_MISMATCH:"
                    + repr([str(row.action_code) for row in audit_rows])
                )
            if len(audit_rows) != 3:
                _fail("W1E_0026_HTTP_AUDIT_ROLLBACK_MISMATCH")
            if any(int(row.actor_account_id) != int(case.account_id) for row in audit_rows):
                _fail("W1E_0026_HTTP_AUDIT_ACTOR_MISMATCH")
            if any(row.entity_pk not in (assignment_id, replacement_id) for row in audit_rows):
                _fail("W1E_0026_HTTP_AUDIT_ENTITY_PK_MISMATCH")

        app_check_engine = create_engine(app_database_url, pool_pre_ping=True)
        try:
            with app_check_engine.connect() as app_check:
                app_user = app_check.execute(text("SELECT current_user")).scalar_one()
                if str(app_user) != "erp_app":
                    _fail("W1E_0026_HTTP_APP_CHECK_CURRENT_USER_NOT_ERP_APP")
                visible = app_check.execute(
                    text(
                        "SELECT count(*) FROM erp.care_assignment "
                        "WHERE id IN (:assignment_id, :replacement_id)"
                    ),
                    {
                        "assignment_id": assignment_id,
                        "replacement_id": replacement_id,
                    },
                ).scalar_one()
                if int(visible) != 2:
                    _fail("W1E_0026_HTTP_APP_ROLE_CANNOT_READ_WRITTEN_ROWS")
        finally:
            app_check_engine.dispose()
    finally:
        for dependency in overridden:
            app.dependency_overrides.pop(dependency, None)
        if previous_database_url is None:
            os.environ.pop("SSWCENTER_DATABASE_URL", None)
        else:
            os.environ["SSWCENTER_DATABASE_URL"] = previous_database_url
        if previous_environment is None:
            os.environ.pop("SSWCENTER_ENVIRONMENT", None)
        else:
            os.environ["SSWCENTER_ENVIRONMENT"] = previous_environment
        get_settings.cache_clear()
        api_dependencies._database_runtime.cache_clear()


def test_w1e_0026_pg_trigger_function_catalog_properties_fail_closed(
    superuser_engine: Engine,
    database_connection: Connection,
) -> None:
    """Reject altered trigger-function catalog attrs and EXECUTE ACL drift."""

    verify_current_0026(database_connection)

    property_mutations = (
        "ALTER FUNCTION erp.fn_care_assignment_within_contract() STABLE",
        "ALTER FUNCTION erp.fn_care_assignment_within_contract() STRICT",
        "ALTER FUNCTION erp.fn_care_assignment_within_contract() PARALLEL SAFE",
        "ALTER FUNCTION erp.fn_care_assignment_within_contract() LEAKPROOF",
        "ALTER FUNCTION erp.fn_care_assignment_within_contract() SECURITY DEFINER",
        "ALTER FUNCTION erp.fn_care_assignment_within_contract() SET search_path = erp",
        "ALTER FUNCTION erp.fn_care_assignment_within_contract() OWNER TO erp_app",
        "GRANT EXECUTE ON FUNCTION erp.fn_care_assignment_within_contract() TO erp_app",
        "GRANT EXECUTE ON FUNCTION erp.fn_care_assignment_within_contract() TO erp_app WITH GRANT OPTION",  # noqa: E501
        "REVOKE EXECUTE ON FUNCTION erp.fn_care_assignment_within_contract() FROM PUBLIC",
    )
    with superuser_engine.connect() as super_connection:
        transaction = super_connection.begin()
        try:
            for mutation in property_mutations:
                savepoint = super_connection.begin_nested()
                try:
                    super_connection.execute(text(mutation))
                    with pytest.raises(
                        SystemExit,
                        match="CURRENT_0026_W1E_TRIGGER_CONTRACT_MISMATCH",
                    ):
                        verify_current_0026(super_connection)
                finally:
                    if savepoint.is_active:
                        savepoint.rollback()
                verify_current_0026(super_connection)
        finally:
            transaction.rollback()
    verify_current_0026(database_connection)
