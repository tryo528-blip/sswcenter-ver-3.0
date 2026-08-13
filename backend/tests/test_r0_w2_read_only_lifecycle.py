"""R0-A W2 read-only backup/restore and forward-only lifecycle acceptance."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url

REVISION_0018 = "20260809_0018_w2_service_plan_notice"
REVISION_0019 = "20260812_0019_r0_w2_read_only"
FORWARD_ONLY_MESSAGE = (
    "20260812_0019_r0_w2_read_only is a canonical forward-only migration; "
    "operational rollback is pre-upgrade backup restore"
)
PLAN_IDS = [910001, 910002]
TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
    "MAINTAIN",
)
SEQUENCE_PRIVILEGES = ("USAGE", "SELECT", "UPDATE")
W2_FUNCTIONS = (
    "fn_recipient_certification_period_recipient_id_immutable",
    "fn_recipient_certification_period_service_plan_reverse_guard",
    "fn_recipient_contract_recipient_id_immutable",
    "fn_recipient_contract_service_plan_reverse_guard",
    "fn_service_plan_notice_before_contract_start",
    "fn_service_plan_notice_within_certification",
    "fn_service_plan_notice_within_contract",
)
GUARD_TRIGGER_PAIRS = {
    (
        "ct_recipient_certification_period_service_plan_reverse_guard",
        "recipient_certification_period",
    ),
    ("ct_recipient_contract_service_plan_reverse_guard", "recipient_contract"),
    ("ct_service_plan_notice_before_contract_start", "recipient_service_plan_notice"),
    ("ct_service_plan_notice_within_certification", "recipient_service_plan_notice"),
    ("ct_service_plan_notice_within_contract", "recipient_service_plan_notice"),
}
IMMUTABLE_TRIGGER_PAIRS = {
    ("ct_recipient_certification_period_recipient_id_immutable", "recipient_certification_period"),
    ("ct_recipient_contract_recipient_id_immutable", "recipient_contract"),
}
BASE_CONSTRAINT_NAMES = {
    "ck_service_plan_notice_date_order",
    "ck_service_plan_notice_row_version_positive",
    "fk_service_plan_notice_created_by_account",
    "fk_service_plan_notice_recipient_contract",
    "fk_service_plan_notice_replacement",
    "fk_service_plan_notice_updated_by_account",
    "pk_recipient_service_plan_notice",
}
GUARD_CONSTRAINT_NAMES = {
    "ct_service_plan_notice_before_contract_start",
    "ct_service_plan_notice_within_certification",
    "ct_service_plan_notice_within_contract",
}
# Byte-identical product seals. postcheck is 3.0-merged and presence-sealed only.
PRODUCT_HASHES = {
    "backend/alembic/versions/20260809_0018_w2_service_plan_notice.py": (
        "AB1A7FB77498CAB7EBD1163084CA98FDF9FD350F5D32A0682F81DC17EE37D716"
    ),
    "backend/alembic/versions/20260812_0019_r0_w2_read_only.py": (
        "EF7FC4917015A265D4633EFAE372314B760F193C4CFC2C98240C158CFDFB21AA"
    ),
    "scripts/restore-drill.ps1": (
        "B37B9C26C27CED5794580BA00E0CAE808C94A783B1ECA0BAA0E7A1471829C5AB"
    ),
    "scripts/verify-w1a-vs1-db.ps1": (
        "5EB67C21F12F2DAA69E791AA6AB38D64195DF7C59A52A4F85EE63D307E8EB06C"
    ),
}
PRODUCT_PRESENCE_PATHS = (
    "backend/app/db/postcheck_w1a_vs1.py",
)


def _fail(message: str) -> NoReturn:
    pytest.fail(message, pytrace=False)


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        _fail(f"R0_ROOM3_HARNESS_ENV_MISSING: {name}")
    return value


@dataclass(frozen=True)
class Harness:
    repo_root: Path
    backend_root: Path
    python_exe: Path
    powershell_exe: Path
    admin_url: str
    source_urls: dict[str, str]
    review_urls: dict[str, str]
    source_roots: dict[str, Path]
    backup_roots: dict[str, Path]
    review_roots: dict[str, Path]


def _load_harness() -> Harness:
    if os.environ.get("SSWCENTER_R0_ROOM3_LIFECYCLE") != "1":
        pytest.skip("requires the isolated R0 Room 3 lifecycle wrapper")

    repo_root = Path(__file__).resolve().parents[2]
    backend_root = repo_root / "backend"
    harness = Harness(
        repo_root=repo_root,
        backend_root=backend_root,
        python_exe=Path(_required_env("SSWCENTER_R0_ROOM3_PYTHON_EXE")).resolve(),
        powershell_exe=Path(_required_env("SSWCENTER_R0_ROOM3_POWERSHELL_EXE")).resolve(),
        admin_url=_required_env("SSWCENTER_R0_ROOM3_ADMIN_URL"),
        source_urls={
            "0018": _required_env("SSWCENTER_R0_ROOM3_0018_SOURCE_URL"),
            "0019": _required_env("SSWCENTER_R0_ROOM3_0019_SOURCE_URL"),
        },
        review_urls={
            "0018": _required_env("SSWCENTER_R0_ROOM3_0018_REVIEW_URL"),
            "0019": _required_env("SSWCENTER_R0_ROOM3_0019_REVIEW_URL"),
        },
        source_roots={
            "0018": Path(_required_env("SSWCENTER_R0_ROOM3_0018_SOURCE_ROOT")).resolve(),
            "0019": Path(_required_env("SSWCENTER_R0_ROOM3_0019_SOURCE_ROOT")).resolve(),
        },
        backup_roots={
            "0018": Path(_required_env("SSWCENTER_R0_ROOM3_0018_BACKUP_ROOT")).resolve(),
            "0019": Path(_required_env("SSWCENTER_R0_ROOM3_0019_BACKUP_ROOT")).resolve(),
        },
        review_roots={
            "0018": Path(_required_env("SSWCENTER_R0_ROOM3_0018_REVIEW_ROOT")).resolve(),
            "0019": Path(_required_env("SSWCENTER_R0_ROOM3_0019_REVIEW_ROOT")).resolve(),
        },
    )
    if not harness.python_exe.is_file() or not harness.powershell_exe.is_file():
        _fail("R0_ROOM3_HARNESS_EXECUTABLE_MISSING")
    return harness


def _validate_targets_and_roots(harness: Harness) -> None:
    expected_names = {
        harness.source_urls["0018"]: "sswcenter_r0_0018_test",
        harness.source_urls["0019"]: "sswcenter_r0_0019_test",
        harness.review_urls["0018"]: "sswcenter_r0_0018_restore_review",
        harness.review_urls["0019"]: "sswcenter_r0_0019_restore_review",
        harness.admin_url: "postgres",
    }
    for database_url, expected_name in expected_names.items():
        parsed = make_url(database_url)
        identity = ((parsed.host or "").lower(), int(parsed.port or 5432), parsed.database)
        if identity != ("127.0.0.1", 55448, expected_name):
            _fail(f"R0_ROOM3_DATABASE_TARGET_MISMATCH: {identity!r}")

    roots = [
        *harness.source_roots.values(),
        *harness.backup_roots.values(),
        *harness.review_roots.values(),
    ]
    if len({str(path).casefold() for path in roots}) != 6:
        _fail("R0_ROOM3_TEMP_ROOTS_NOT_DISTINCT")
    temp_root = Path(_required_env("SSWCENTER_R0_ROOM3_TEMP_ROOT")).resolve()
    for root in roots:
        if root.parent != temp_root:
            _fail(f"R0_ROOM3_TEMP_ROOT_ESCAPED: {root}")
        if root.exists():
            _fail(f"R0_ROOM3_TEMP_ROOT_PREEXISTED: {root}")
        if not re.search(r"[0-9a-f]{32}$", root.name):
            _fail(f"R0_ROOM3_TEMP_ROOT_GUID_MISSING: {root}")
    for root in harness.review_roots.values():
        if not root.name.startswith("sswcenter-restore-review-"):
            _fail(f"R0_ROOM3_REVIEW_ROOT_PREFIX_INVALID: {root}")


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest().upper()


def _assert_product_hashes(repo_root: Path) -> None:
    actual = {relative: _lf_sha256(repo_root / relative) for relative in PRODUCT_HASHES}
    if actual != PRODUCT_HASHES:
        _fail(f"R0_ROOM3_PRODUCT_HASH_MISMATCH: {actual!r}")
    for relative in PRODUCT_PRESENCE_PATHS:
        path = repo_root / relative
        if not path.is_file():
            _fail(f"R0_ROOM3_PRODUCT_FILE_MISSING: {relative}")
        if len(_lf_sha256(path)) != 64:
            _fail(f"R0_ROOM3_PRODUCT_HASH_SHAPE: {relative}")


def _command_env(database_url: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["SSWCENTER_ENVIRONMENT"] = "test"
    if database_url is not None:
        env["SSWCENTER_DATABASE_URL"] = database_url
    return env


def _run(
    args: list[str],
    *,
    label: str,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    print(f"R0_ROOM3_COMMAND label={label} exit={result.returncode}")
    if check and result.returncode != 0:
        _fail(
            f"R0_ROOM3_COMMAND_FAILED: label={label};exit={result.returncode};"
            f"stdout={result.stdout!r};stderr={result.stderr!r}"
        )
    return result


def _alembic(
    harness: Harness,
    database_url: str,
    operation: str,
    target: str,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            str(harness.python_exe),
            "-B",
            "-m",
            "alembic",
            "-c",
            "alembic.ini",
            operation,
            target,
        ],
        label=f"alembic-{operation}-{target}",
        cwd=harness.backend_root,
        env=_command_env(database_url),
        check=check,
    )


def _assert_empty_database(database_url: str) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            present = connection.execute(
                text("SELECT to_regclass('erp.alembic_version') IS NOT NULL")
            ).scalar()
            if present is not False:
                _fail("R0_ROOM3_SOURCE_DATABASE_NOT_EMPTY")
    finally:
        engine.dispose()


def _seed_historical_rows(database_url: str) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("SET TIME ZONE 'UTC'"))
            staff_id = connection.execute(
                text(
                    """
                    INSERT INTO erp.staff
                        (name, birth_date, sex_code, display_name, row_version)
                    VALUES
                        ('R0 ROOM3 ACCOUNT STAFF', DATE '1990-01-01', 'TEST',
                         'R0 ROOM3 ACCOUNT', 1)
                    RETURNING id
                    """
                )
            ).scalar_one()
            account_id = connection.execute(
                text(
                    """
                    INSERT INTO erp.user_account
                        (staff_id, account_code, display_name, role_code,
                         pin_hash, pin_lookup_hmac, pin_key_version, row_version)
                    VALUES
                        (:staff_id, 'R0_ROOM3', 'R0 ROOM3 ACCOUNT', 'ADMIN',
                         'r0-room3-pin-hash',
                         decode('91000391000391000391000391000391', 'hex'), 1, 1)
                    RETURNING id
                    """
                ),
                {"staff_id": staff_id},
            ).scalar_one()
            recipient_id = connection.execute(
                text(
                    """
                    INSERT INTO erp.recipient
                        (name, birth_date, sex_code,
                         created_by_account_id, updated_by_account_id)
                    VALUES
                        ('R0 ROOM3 RECIPIENT', DATE '1980-06-15', 'MALE',
                         :account_id, :account_id)
                    RETURNING id
                    """
                ),
                {"account_id": account_id},
            ).scalar_one()
            service_type_id = connection.execute(
                text("SELECT id FROM erp.service_type WHERE code = 'HOME_CARE'")
            ).scalar_one()
            contract_id = connection.execute(
                text(
                    """
                    INSERT INTO erp.recipient_contract
                        (recipient_id, service_type_id, start_date, end_date,
                         created_by_account_id, updated_by_account_id)
                    VALUES
                        (:recipient_id, :service_type_id,
                         DATE '2026-01-01', DATE '2026-12-31',
                         :account_id, :account_id)
                    RETURNING id
                    """
                ),
                {
                    "recipient_id": recipient_id,
                    "service_type_id": service_type_id,
                    "account_id": account_id,
                },
            ).scalar_one()
            connection.execute(
                text(
                    """
                    INSERT INTO erp.recipient_certification_identity
                        (recipient_id, certification_number,
                         created_by_account_id, updated_by_account_id)
                    VALUES
                        (:recipient_id, 'L9100000001', :account_id, :account_id)
                    """
                ),
                {"recipient_id": recipient_id, "account_id": account_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO erp.recipient_certification_period
                        (recipient_id, start_date, end_date,
                         created_by_account_id, updated_by_account_id)
                    VALUES
                        (:recipient_id, DATE '2026-01-01', DATE '2026-12-31',
                         :account_id, :account_id)
                    """
                ),
                {"recipient_id": recipient_id, "account_id": account_id},
            )
            connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
            connection.execute(
                text(
                    """
                    INSERT INTO erp.recipient_service_plan_notice (
                        id, recipient_contract_id, notification_date,
                        applied_start_date, applied_end_date,
                        invalidated_at_utc, replacement_service_plan_notice_id,
                        created_by_account_id, created_at_utc,
                        updated_by_account_id, updated_at_utc, row_version
                    ) VALUES (
                        910001, :contract_id, DATE '2026-03-01',
                        DATE '2026-01-01', DATE '2026-12-31',
                        TIMESTAMPTZ '2026-08-12 00:05:00+00', NULL,
                        :account_id, TIMESTAMPTZ '2026-08-12 00:00:00+00',
                        :account_id, TIMESTAMPTZ '2026-08-12 00:05:00+00', 2
                    )
                    """
                ),
                {"contract_id": contract_id, "account_id": account_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO erp.recipient_service_plan_notice (
                        id, recipient_contract_id, notification_date,
                        applied_start_date, applied_end_date,
                        invalidated_at_utc, replacement_service_plan_notice_id,
                        created_by_account_id, created_at_utc,
                        updated_by_account_id, updated_at_utc, row_version
                    ) VALUES (
                        910002, :contract_id, DATE '2026-07-01',
                        DATE '2026-01-01', DATE '2026-12-31', NULL, NULL,
                        :account_id, TIMESTAMPTZ '2026-08-12 00:05:00+00',
                        :account_id, TIMESTAMPTZ '2026-08-12 00:05:00+00', 1
                    )
                    """
                ),
                {"contract_id": contract_id, "account_id": account_id},
            )
            connection.execute(
                text(
                    """
                    UPDATE erp.recipient_service_plan_notice
                    SET replacement_service_plan_notice_id = 910002
                    WHERE id = 910001
                    """
                )
            )
            connection.execute(
                text(
                    """
                    SELECT setval(
                        'erp.recipient_service_plan_notice_id_seq'::regclass,
                        910002,
                        true
                    )
                    """
                )
            )
            connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    finally:
        engine.dispose()


def _write_sentinel(root: Path, label: str) -> tuple[Path, str]:
    sentinel = root / "blobs" / f"r0-room3-{label}-sentinel.txt"
    sentinel.parent.mkdir(parents=True)
    payload = f"R0 ROOM3 {label} SENTINEL\n".encode()
    sentinel.write_bytes(payload)
    return sentinel, hashlib.sha256(payload).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _mapping_rows(connection: Connection, sql: str) -> list[dict[str, Any]]:
    return [
        _jsonable(dict(row._mapping))
        for row in connection.execute(text(sql)).all()
    ]


def _effective_acl(connection: Connection, role: str) -> dict[str, Any]:
    table_values = connection.execute(
        text(
            """
            SELECT
                has_table_privilege(:role, 'erp.recipient_service_plan_notice', 'SELECT'),
                has_table_privilege(:role, 'erp.recipient_service_plan_notice', 'INSERT'),
                has_table_privilege(:role, 'erp.recipient_service_plan_notice', 'UPDATE'),
                has_table_privilege(:role, 'erp.recipient_service_plan_notice', 'DELETE'),
                has_table_privilege(:role, 'erp.recipient_service_plan_notice', 'TRUNCATE'),
                has_table_privilege(:role, 'erp.recipient_service_plan_notice', 'REFERENCES'),
                has_table_privilege(:role, 'erp.recipient_service_plan_notice', 'TRIGGER'),
                has_table_privilege(:role, 'erp.recipient_service_plan_notice', 'MAINTAIN')
            """
        ),
        {"role": role},
    ).one()
    sequence_values = connection.execute(
        text(
            """
            SELECT
                has_sequence_privilege(
                    :role, 'erp.recipient_service_plan_notice_id_seq', 'USAGE'
                ),
                has_sequence_privilege(
                    :role, 'erp.recipient_service_plan_notice_id_seq', 'SELECT'
                ),
                has_sequence_privilege(
                    :role, 'erp.recipient_service_plan_notice_id_seq', 'UPDATE'
                )
            """
        ),
        {"role": role},
    ).one()
    schema_values = connection.execute(
        text(
            """
            SELECT has_schema_privilege(:role, 'erp', 'USAGE'),
                   has_schema_privilege(:role, 'erp', 'CREATE')
            """
        ),
        {"role": role},
    ).one()
    return {
        "table": dict(zip(TABLE_PRIVILEGES, map(bool, table_values), strict=True)),
        "sequence": dict(zip(SEQUENCE_PRIVILEGES, map(bool, sequence_values), strict=True)),
        "schema": {"USAGE": bool(schema_values[0]), "CREATE": bool(schema_values[1])},
    }


def _snapshot(database_url: str) -> dict[str, Any]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TIME ZONE 'UTC'"))
            revision = connection.execute(
                text("SELECT version_num FROM erp.alembic_version")
            ).scalar_one()
            row_json = connection.execute(
                text(
                    """
                    SELECT COALESCE(
                        jsonb_agg(to_jsonb(plan) ORDER BY plan.id)::text,
                        '[]'
                    )
                    FROM erp.recipient_service_plan_notice AS plan
                    """
                )
            ).scalar_one()
            pks = list(
                connection.execute(
                    text("SELECT id FROM erp.recipient_service_plan_notice ORDER BY id")
                ).scalars()
            )
            sequence_state = connection.execute(
                text(
                    """
                    SELECT last_value::bigint AS last_value, is_called
                    FROM erp.recipient_service_plan_notice_id_seq
                    """
                )
            ).one()
            sequence_catalog = _mapping_rows(
                connection,
                """
                SELECT s.seqstart, s.seqincrement, s.seqmax, s.seqmin,
                       s.seqcache, s.seqcycle,
                       pg_get_userbyid(c.relowner) AS owner
                FROM pg_sequence AS s
                JOIN pg_class AS c ON c.oid = s.seqrelid
                WHERE s.seqrelid =
                    'erp.recipient_service_plan_notice_id_seq'::regclass
                """,
            )
            columns = _mapping_rows(
                connection,
                """
                SELECT a.attnum, a.attname,
                       format_type(a.atttypid, a.atttypmod) AS formatted_type,
                       a.attnotnull, a.attidentity, a.attgenerated,
                       pg_get_expr(ad.adbin, ad.adrelid) AS default_expr,
                       coll.collname AS collation,
                       COALESCE(
                           ARRAY(
                               SELECT acl::text
                               FROM unnest(a.attacl) AS acl
                               ORDER BY acl::text
                           ),
                           ARRAY[]::text[]
                       ) AS raw_acl
                FROM pg_attribute AS a
                LEFT JOIN pg_attrdef AS ad
                  ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
                LEFT JOIN pg_collation AS coll ON coll.oid = a.attcollation
                WHERE a.attrelid = 'erp.recipient_service_plan_notice'::regclass
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                ORDER BY a.attnum
                """,
            )
            constraints = _mapping_rows(
                connection,
                """
                SELECT c.conname, c.contype,
                       pg_get_constraintdef(c.oid, true) AS definition,
                       ARRAY(
                           SELECT la.attname
                           FROM unnest(c.conkey) WITH ORDINALITY AS key(attnum, ord)
                           JOIN pg_attribute AS la
                             ON la.attrelid = c.conrelid AND la.attnum = key.attnum
                           ORDER BY key.ord
                       ) AS local_columns,
                       ref_ns.nspname AS ref_schema,
                       ref.relname AS ref_table,
                       ARRAY(
                           SELECT ra.attname
                           FROM unnest(c.confkey) WITH ORDINALITY AS key(attnum, ord)
                           JOIN pg_attribute AS ra
                             ON ra.attrelid = c.confrelid AND ra.attnum = key.attnum
                           ORDER BY key.ord
                       ) AS ref_columns,
                       c.confdeltype, c.confupdtype, c.confmatchtype,
                       c.condeferrable, c.condeferred, c.convalidated
                FROM pg_constraint AS c
                LEFT JOIN pg_class AS ref ON ref.oid = c.confrelid
                LEFT JOIN pg_namespace AS ref_ns ON ref_ns.oid = ref.relnamespace
                WHERE c.conrelid = 'erp.recipient_service_plan_notice'::regclass
                ORDER BY c.conname
                """,
            )
            indexes = _mapping_rows(
                connection,
                """
                SELECT idx.relname AS index_name,
                       i.indisprimary, i.indisunique, i.indisvalid,
                       i.indisready, i.indislive, i.indcheckxmin,
                       i.indnullsnotdistinct, i.indnkeyatts, i.indnatts,
                       ARRAY(
                           SELECT a.attname
                           FROM unnest(i.indkey::smallint[])
                                WITH ORDINALITY AS key(attnum, ord)
                           LEFT JOIN pg_attribute AS a
                             ON a.attrelid = i.indrelid AND a.attnum = key.attnum
                           WHERE key.ord <= i.indnkeyatts
                           ORDER BY key.ord
                       ) AS key_columns,
                       pg_get_indexdef(i.indexrelid) AS definition
                FROM pg_index AS i
                JOIN pg_class AS idx ON idx.oid = i.indexrelid
                WHERE i.indrelid = 'erp.recipient_service_plan_notice'::regclass
                ORDER BY idx.relname
                """,
            )
            identity = _mapping_rows(
                connection,
                """
                SELECT a.attidentity,
                       pg_get_serial_sequence(
                           'erp.recipient_service_plan_notice', 'id'
                       ) AS owned_sequence,
                       d.deptype, d.refobjsubid
                FROM pg_attribute AS a
                JOIN pg_depend AS d
                  ON d.refobjid = a.attrelid
                 AND d.refobjsubid = a.attnum
                WHERE a.attrelid = 'erp.recipient_service_plan_notice'::regclass
                  AND a.attname = 'id'
                  AND d.objid =
                      'erp.recipient_service_plan_notice_id_seq'::regclass
                ORDER BY d.deptype
                """,
            )
            functions = _mapping_rows(
                connection,
                """
                SELECT p.proname,
                       pg_get_function_identity_arguments(p.oid) AS identity_args,
                       pg_get_function_result(p.oid) AS result_type,
                       lang.lanname AS language,
                       p.provolatile, p.proisstrict, p.prosecdef, p.proparallel,
                       COALESCE(p.proconfig, ARRAY[]::text[]) AS proconfig,
                       pg_get_functiondef(p.oid) AS definition
                FROM pg_proc AS p
                JOIN pg_language AS lang ON lang.oid = p.prolang
                WHERE p.pronamespace = 'erp'::regnamespace
                  AND p.proname = ANY(:names)
                ORDER BY p.proname, pg_get_function_identity_arguments(p.oid)
                """.replace(
                    ":names",
                    "ARRAY[" + ",".join(f"'{name}'" for name in W2_FUNCTIONS) + "]",
                ),
            )
            function_records = []
            for function in functions:
                definition = str(function.pop("definition"))
                function["definition_sha256"] = hashlib.sha256(definition.encode()).hexdigest()
                function_records.append(function)
            function_hash = hashlib.sha256(
                json.dumps(
                    function_records,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            trigger_names = sorted(
                {name for name, _table in GUARD_TRIGGER_PAIRS | IMMUTABLE_TRIGGER_PAIRS}
            )
            triggers = _mapping_rows(
                connection,
                """
                SELECT t.tgname, c.relname AS table_name, t.tgenabled,
                       t.tgdeferrable, t.tginitdeferred,
                       p.proname AS function_name,
                       pg_get_triggerdef(t.oid, true) AS definition
                FROM pg_trigger AS t
                JOIN pg_class AS c ON c.oid = t.tgrelid
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                JOIN pg_proc AS p ON p.oid = t.tgfoid
                WHERE n.nspname = 'erp'
                  AND NOT t.tgisinternal
                  AND t.tgname = ANY(:names)
                ORDER BY c.relname, t.tgname
                """.replace(
                    ":names", "ARRAY[" + ",".join(f"'{name}'" for name in trigger_names) + "]"
                ),
            )
            raw_relation_acl = _mapping_rows(
                connection,
                """
                SELECT c.relname, c.relkind, pg_get_userbyid(c.relowner) AS owner,
                       COALESCE(
                           ARRAY(
                               SELECT acl::text
                               FROM unnest(c.relacl) AS acl
                               ORDER BY acl::text
                           ),
                           ARRAY[]::text[]
                       ) AS raw_acl
                FROM pg_class AS c
                WHERE c.oid IN (
                    'erp.recipient_service_plan_notice'::regclass,
                    'erp.recipient_service_plan_notice_id_seq'::regclass
                )
                ORDER BY c.relkind, c.relname
                """,
            )
            raw_schema_acl = _mapping_rows(
                connection,
                """
                SELECT n.nspname, pg_get_userbyid(n.nspowner) AS owner,
                       COALESCE(
                           ARRAY(
                               SELECT acl::text
                               FROM unnest(n.nspacl) AS acl
                               ORDER BY acl::text
                           ),
                           ARRAY[]::text[]
                       ) AS raw_acl
                FROM pg_namespace AS n
                WHERE n.nspname = 'erp'
                """,
            )
            return {
                "revision": str(revision),
                "row_count": len(pks),
                "pks": pks,
                "row_json_sha256": hashlib.sha256(str(row_json).encode()).hexdigest(),
                "sequence_state": {
                    "last_value": int(sequence_state.last_value),
                    "is_called": bool(sequence_state.is_called),
                },
                "sequence_catalog": sequence_catalog,
                "columns": columns,
                "constraints": constraints,
                "indexes": indexes,
                "identity": identity,
                "functions": function_records,
                "functions_sha256": function_hash,
                "triggers": triggers,
                "acl": {
                    "raw_relations": raw_relation_acl,
                    "raw_schema": raw_schema_acl,
                    "effective": {
                        "erp_app": _effective_acl(connection, "erp_app"),
                        "erp_backup": _effective_acl(connection, "erp_backup"),
                    },
                },
            }
    finally:
        engine.dispose()


def _assert_snapshot_contract(snapshot: dict[str, Any], *, revision: str) -> None:
    if snapshot["revision"] != revision:
        _fail(f"R0_ROOM3_REVISION_MISMATCH: {snapshot['revision']!r}")
    if snapshot["row_count"] != 2 or snapshot["pks"] != PLAN_IDS:
        _fail(
            "R0_ROOM3_HISTORY_ROWS_MISMATCH: "
            f"count={snapshot['row_count']};pks={snapshot['pks']!r}"
        )
    if snapshot["sequence_state"] != {"last_value": 910002, "is_called": True}:
        _fail(f"R0_ROOM3_SEQUENCE_STATE_MISMATCH: {snapshot['sequence_state']!r}")
    if len(snapshot["columns"]) != 12:
        _fail(f"R0_ROOM3_COLUMN_COUNT_MISMATCH: {len(snapshot['columns'])}")
    constraint_names = {row["conname"] for row in snapshot["constraints"]}
    expected_constraint_names = set(BASE_CONSTRAINT_NAMES)
    if revision == REVISION_0018:
        expected_constraint_names |= GUARD_CONSTRAINT_NAMES
    if constraint_names != expected_constraint_names:
        _fail(f"R0_ROOM3_CONSTRAINT_SET_MISMATCH: {sorted(constraint_names)!r}")
    guard_constraints = {
        row["conname"]: row
        for row in snapshot["constraints"]
        if row["conname"] in GUARD_CONSTRAINT_NAMES
    }
    for name, row in guard_constraints.items():
        if (
            row["contype"] != "t"
            or not row["condeferrable"]
            or not row["condeferred"]
            or not row["convalidated"]
        ):
            _fail(f"R0_ROOM3_GUARD_CONSTRAINT_MISMATCH: {name}={row!r}")
    if [row["proname"] for row in snapshot["functions"]] != list(W2_FUNCTIONS):
        _fail("R0_ROOM3_FUNCTION_SET_MISMATCH")
    trigger_pairs = {(row["tgname"], row["table_name"]) for row in snapshot["triggers"]}
    expected_triggers = set(IMMUTABLE_TRIGGER_PAIRS)
    if revision == REVISION_0018:
        expected_triggers |= GUARD_TRIGGER_PAIRS
    if trigger_pairs != expected_triggers:
        _fail(f"R0_ROOM3_TRIGGER_PAIR_MISMATCH: {sorted(trigger_pairs)!r}")

    effective = snapshot["acl"]["effective"]
    app_expected_table = {privilege: False for privilege in TABLE_PRIVILEGES}
    app_expected_table["SELECT"] = True
    if revision == REVISION_0018:
        app_expected_table["INSERT"] = True
        app_expected_table["UPDATE"] = True
    backup_expected_table = {privilege: False for privilege in TABLE_PRIVILEGES}
    backup_expected_table["SELECT"] = True
    app_expected_sequence = {privilege: False for privilege in SEQUENCE_PRIVILEGES}
    app_expected_sequence["SELECT"] = True
    if revision == REVISION_0018:
        app_expected_sequence["USAGE"] = True
    backup_expected_sequence = {privilege: False for privilege in SEQUENCE_PRIVILEGES}
    backup_expected_sequence["SELECT"] = True
    if effective["erp_app"]["table"] != app_expected_table:
        _fail(f"R0_ROOM3_APP_TABLE_ACL_MISMATCH: {effective['erp_app']['table']!r}")
    if effective["erp_app"]["sequence"] != app_expected_sequence:
        _fail(f"R0_ROOM3_APP_SEQUENCE_ACL_MISMATCH: {effective['erp_app']['sequence']!r}")
    if effective["erp_backup"]["table"] != backup_expected_table:
        _fail("R0_ROOM3_BACKUP_TABLE_ACL_MISMATCH")
    if effective["erp_backup"]["sequence"] != backup_expected_sequence:
        _fail("R0_ROOM3_BACKUP_SEQUENCE_ACL_MISMATCH")


def _run_postcheck(
    harness: Harness,
    *,
    database_url: str,
    expected_marker: str,
    label: str,
) -> None:
    result = _run(
        [
            str(harness.powershell_exe),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness.repo_root / "scripts" / "verify-w1a-vs1-db.ps1"),
            "-DatabaseUrl",
            database_url,
            "-PythonExe",
            str(harness.python_exe),
        ],
        label=label,
        cwd=harness.repo_root,
        env=_command_env(),
    )
    output_lines = {line.strip() for line in result.stdout.splitlines()}
    if expected_marker not in output_lines:
        _fail(
            f"R0_ROOM3_POSTCHECK_MARKER_MISSING: expected={expected_marker};"
            f"stdout={result.stdout!r}"
        )
    print(expected_marker)


def _validate_backup(
    harness: Harness,
    *,
    label: str,
    revision: str,
    database_url: str,
    source_root: Path,
    backup_root: Path,
    sentinel: Path,
    sentinel_sha256: str,
) -> Path:
    result = _run(
        [
            str(harness.powershell_exe),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness.repo_root / "scripts" / "backup-postgres.ps1"),
            "-DatabaseUrl",
            database_url,
            "-DestinationRoot",
            str(backup_root),
            "-DataRoot",
            str(source_root),
            "-AppVersion",
            "r0-room3-lifecycle",
        ],
        label=f"backup-{label}",
        cwd=harness.repo_root,
        env=_command_env(),
    )
    matches = re.findall(r"(?m)^BACKUP_OK (.+)$", result.stdout)
    if len(matches) != 1:
        _fail(f"R0_ROOM3_BACKUP_MARKER_INVALID: {result.stdout!r}")
    backup_directory = Path(matches[0].strip()).resolve()
    if backup_directory.parent != backup_root or not backup_directory.is_dir():
        _fail(f"R0_ROOM3_BACKUP_DIRECTORY_INVALID: {backup_directory}")
    if [path.resolve() for path in backup_root.iterdir()] != [backup_directory]:
        _fail("R0_ROOM3_BACKUP_DIRECTORY_COUNT_MISMATCH")

    manifest_path = backup_directory / "manifest.json"
    dump_path = backup_directory / "database.dump"
    bundle_path = backup_directory / "bundle.sha256"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    expected_database = make_url(database_url).database
    if manifest.get("alembic_revision") != revision:
        _fail(f"R0_ROOM3_MANIFEST_REVISION_MISMATCH: {manifest!r}")
    if manifest.get("database_name") != expected_database:
        _fail(f"R0_ROOM3_MANIFEST_DATABASE_MISMATCH: {manifest!r}")
    if manifest.get("dump_file") != "database.dump" or manifest.get("format_version") != 1:
        _fail(f"R0_ROOM3_MANIFEST_SHAPE_MISMATCH: {manifest!r}")
    dump_hash = hashlib.sha256(dump_path.read_bytes()).hexdigest()
    if manifest.get("dump_sha256") != dump_hash:
        _fail("R0_ROOM3_MANIFEST_DUMP_SHA_MISMATCH")
    if manifest.get("dump_size_bytes") != dump_path.stat().st_size:
        _fail("R0_ROOM3_MANIFEST_DUMP_SIZE_MISMATCH")

    relative_sentinel = sentinel.relative_to(source_root).as_posix()
    expected_file_entry = {
        "relative_path": relative_sentinel,
        "sha256": sentinel_sha256,
        "size_bytes": sentinel.stat().st_size,
    }
    if manifest.get("files") != [expected_file_entry]:
        _fail(f"R0_ROOM3_MANIFEST_SENTINEL_MISMATCH: {manifest.get('files')!r}")

    bundle_entries: dict[str, str] = {}
    for line in bundle_path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) \*(.+)", line)
        if match is None or match.group(2) in bundle_entries:
            _fail(f"R0_ROOM3_BUNDLE_LINE_INVALID: {line!r}")
        bundle_entries[match.group(2)] = match.group(1)
    expected_bundle_paths = {
        "database.dump",
        "manifest.json",
        f"data/{relative_sentinel}",
    }
    if set(bundle_entries) != expected_bundle_paths:
        _fail(f"R0_ROOM3_BUNDLE_PATH_SET_MISMATCH: {sorted(bundle_entries)!r}")
    for relative_path, expected_hash in bundle_entries.items():
        actual_hash = hashlib.sha256((backup_directory / relative_path).read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            _fail(f"R0_ROOM3_BUNDLE_SHA_MISMATCH: {relative_path}")
    bundle_hash = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    print(
        f"R0_ROOM3_BACKUP_{label} revision={revision} dump_sha256={dump_hash} "
        f"bundle_sha256={bundle_hash}"
    )
    return backup_directory


def _restore(
    harness: Harness,
    *,
    label: str,
    backup_directory: Path,
    review_database_name: str,
    review_root: Path,
    expected_marker: str,
) -> None:
    result = _run(
        [
            str(harness.powershell_exe),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness.repo_root / "scripts" / "restore-drill.ps1"),
            "-BackupDirectory",
            str(backup_directory),
            "-AdminDatabaseUrl",
            harness.admin_url,
            "-ReviewDatabaseName",
            review_database_name,
            "-ReviewDataRoot",
            str(review_root),
            "-KeepReviewArtifacts",
            "-PythonExe",
            str(harness.python_exe),
        ],
        label=f"restore-{label}",
        cwd=harness.repo_root,
        env=_command_env(),
    )
    output_lines = {line.strip() for line in result.stdout.splitlines()}
    expected_restore = f"RESTORE_DRILL_OK {review_database_name}"
    if expected_marker not in output_lines or expected_restore not in output_lines:
        _fail(
            f"R0_ROOM3_RESTORE_MARKER_MISSING: marker={expected_marker};"
            f"restore={expected_restore};stdout={result.stdout!r}"
        )
    print(f"R0_ROOM3_RESTORE_{label} marker={expected_marker}")


def _assert_equal(label: str, expected: Any, actual: Any) -> None:
    if actual != expected:
        _fail(
            f"R0_ROOM3_{label}_MISMATCH: expected="
            f"{json.dumps(expected, sort_keys=True, default=str)};actual="
            f"{json.dumps(actual, sort_keys=True, default=str)}"
        )


def test_r0_w2_read_only_backup_restore_lifecycle() -> None:
    harness = _load_harness()
    _validate_targets_and_roots(harness)
    _assert_product_hashes(harness.repo_root)

    revisions = {"0018": REVISION_0018, "0019": REVISION_0019}
    markers = {
        "0018": "W2_SERVICE_PLAN_NOTICE_DB_POSTCHECK_OK",
        "0019": "R0_W2_READ_ONLY_DB_POSTCHECK_OK",
    }
    review_names = {
        "0018": "sswcenter_r0_0018_restore_review",
        "0019": "sswcenter_r0_0019_restore_review",
    }
    sentinels: dict[str, tuple[Path, str]] = {}
    source_snapshots: dict[str, dict[str, Any]] = {}

    for label in ("0018", "0019"):
        database_url = harness.source_urls[label]
        _assert_empty_database(database_url)
        _alembic(harness, database_url, "upgrade", revisions[label])
        _seed_historical_rows(database_url)
        sentinels[label] = _write_sentinel(harness.source_roots[label], label)
        source_snapshots[label] = _snapshot(database_url)
        _assert_snapshot_contract(source_snapshots[label], revision=revisions[label])
        trigger_pairs = [
            [row["tgname"], row["table_name"]]
            for row in source_snapshots[label]["triggers"]
        ]
        print(
            f"R0_ROOM3_SOURCE_{label} rows=2 pks=910001,910002 "
            f"row_sha256={source_snapshots[label]['row_json_sha256']} "
            f"function_sha256={source_snapshots[label]['functions_sha256']} "
            f"triggers={json.dumps(trigger_pairs, separators=(',', ':'))}"
        )
        _run_postcheck(
            harness,
            database_url=database_url,
            expected_marker=markers[label],
            label=f"source-postcheck-{label}",
        )

    invariant_keys = (
        "row_count",
        "pks",
        "row_json_sha256",
        "sequence_state",
        "sequence_catalog",
        "columns",
        "indexes",
        "identity",
        "functions",
        "functions_sha256",
    )
    for key in invariant_keys:
        _assert_equal(
            f"0018_0019_{key.upper()}",
            source_snapshots["0018"][key],
            source_snapshots["0019"][key],
        )
    base_constraints = {
        label: [
            row
            for row in source_snapshots[label]["constraints"]
            if row["conname"] in BASE_CONSTRAINT_NAMES
        ]
        for label in ("0018", "0019")
    }
    _assert_equal(
        "0018_0019_BASE_CONSTRAINTS",
        base_constraints["0018"],
        base_constraints["0019"],
    )

    before_downgrade = source_snapshots["0019"]
    downgrade = _alembic(
        harness,
        harness.source_urls["0019"],
        "downgrade",
        REVISION_0018,
        check=False,
    )
    if downgrade.returncode == 0:
        _fail("R0_ROOM3_FORWARD_ONLY_DOWNGRADE_UNEXPECTED_SUCCESS")
    combined_output = downgrade.stdout + "\n" + downgrade.stderr
    if FORWARD_ONLY_MESSAGE not in combined_output:
        _fail(
            "R0_ROOM3_FORWARD_ONLY_MESSAGE_MISSING: "
            f"exit={downgrade.returncode};output={combined_output!r}"
        )
    after_downgrade = _snapshot(harness.source_urls["0019"])
    _assert_equal("FORWARD_ONLY_SNAPSHOT", before_downgrade, after_downgrade)
    print(
        f"R0_ROOM3_FORWARD_ONLY exit={downgrade.returncode} "
        f"message_sha256={hashlib.sha256(FORWARD_ONLY_MESSAGE.encode()).hexdigest()}"
    )

    backup_directories: dict[str, Path] = {}
    for label in ("0018", "0019"):
        sentinel, sentinel_sha256 = sentinels[label]
        backup_directories[label] = _validate_backup(
            harness,
            label=label,
            revision=revisions[label],
            database_url=harness.source_urls[label],
            source_root=harness.source_roots[label],
            backup_root=harness.backup_roots[label],
            sentinel=sentinel,
            sentinel_sha256=sentinel_sha256,
        )

    for label in ("0018", "0019"):
        _restore(
            harness,
            label=label,
            backup_directory=backup_directories[label],
            review_database_name=review_names[label],
            review_root=harness.review_roots[label],
            expected_marker=markers[label],
        )
        restored_snapshot = _snapshot(harness.review_urls[label])
        _assert_snapshot_contract(restored_snapshot, revision=revisions[label])
        _assert_equal(
            f"SOURCE_RESTORE_{label}_SNAPSHOT",
            source_snapshots[label],
            restored_snapshot,
        )

        sentinel, sentinel_sha256 = sentinels[label]
        relative_sentinel = sentinel.relative_to(harness.source_roots[label])
        restored_sentinel = harness.review_roots[label] / relative_sentinel
        if not restored_sentinel.is_file():
            _fail(f"R0_ROOM3_RESTORED_SENTINEL_MISSING: {restored_sentinel}")
        restored_sha256 = hashlib.sha256(restored_sentinel.read_bytes()).hexdigest()
        if restored_sha256 != sentinel_sha256:
            _fail(
                f"R0_ROOM3_RESTORED_SENTINEL_SHA_MISMATCH: "
                f"expected={sentinel_sha256};actual={restored_sha256}"
            )
        print(
            f"R0_ROOM3_SOURCE_RESTORE_{label}_EXACT "
            f"sentinel_sha256={restored_sha256}"
        )

    _assert_product_hashes(harness.repo_root)
    print("R0_ROOM3_LIFECYCLE_ASSERTIONS_OK")
