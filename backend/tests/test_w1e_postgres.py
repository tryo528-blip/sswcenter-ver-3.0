"""W1E-A1 PostgreSQL RED cases for the GENERAL care-assignment contract.

No engine or connection is created during import/collection. Live execution is
explicitly gated by SSWCENTER_W1E_REAL_PG=1 and uses direct DB contracts only;
API, UI, service, FAMILY, monthly, visit, and care-change behavior are out of
scope.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any, NoReturn
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

W1D_HEAD = "20260730_0011_w1d_recipient_contract"
W1E_REVISION = "20260801_0012_w1e_care_assignment"
ASSIGNMENT_TABLE = "erp.care_assignment"
CONTRACT_SERVICE_CODE = "HOME_CARE"
OTHER_SERVICE_CODE = "HOME_BATH"


def _fail(marker: str) -> NoReturn:
    pytest.fail(marker, pytrace=False)


def _compact_sql(value: str) -> str:
    return re.sub(r"\s+", "", value.lower()).replace("::text", "")


def _compact_expression(value: str) -> str:
    compact = _compact_sql(value)
    while compact.startswith("(") and compact.endswith(")"):
        depth = 0
        wraps_whole_expression = True
        for index, character in enumerate(compact):
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0 and index != len(compact) - 1:
                    wraps_whole_expression = False
                    break
        if not wraps_whole_expression or depth != 0:
            break
        compact = compact[1:-1]
    compact = compact.replace("(end_date+1)", "end_date+1")
    return compact


def test_compact_expression_preserves_boolean_grouping() -> None:
    cases = {
        "((end_date IS NULL) OR (start_date <= end_date))": (
            "(end_dateisnull)or(start_date<=end_date)"
        ),
        "(((row_version > 0)))": "row_version>0",
        "daterange(start_date, (end_date + 1), '[)')": ("daterange(start_date,end_date+1,'[)')"),
        "((left_side) OR (right_side)": "((left_side)or(right_side)",
    }
    for expression, expected in cases.items():
        assert _compact_expression(expression) == expected


def _without_sql_comments(value: str) -> str:
    without_line_comments = re.sub(r"--[^\r\n]*", "", value)
    return re.sub(r"/\*.*?\*/", "", without_line_comments, flags=re.DOTALL)


@pytest.fixture(scope="session")
def database_engine() -> Iterator[Engine]:
    if os.environ.get("SSWCENTER_W1E_REAL_PG") != "1":
        pytest.skip("requires the isolated W1E PostgreSQL harness")
    database_url = os.environ.get("SSWCENTER_DATABASE_URL")
    if not database_url:
        _fail("W1E_HARNESS_DATABASE_URL_MISSING")
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


@dataclass(frozen=True)
class W1ECase:
    account_id: int
    recipient_id: int
    contract_id: int
    contract_service_type_id: int
    other_service_type_id: int
    staff_a_id: int
    employment_a_id: int
    position_a_id: int
    qualification_a_id: int
    staff_b_id: int
    employment_b_id: int
    position_b_id: int
    qualification_b_id: int


def _require_catalog(connection: Connection) -> None:
    revision = connection.execute(
        text("SELECT version_num FROM erp.alembic_version")
    ).scalar_one_or_none()
    if revision != W1E_REVISION:
        _fail(
            "W1E_MIGRATION_REVISION_NOT_APPLIED: expected "
            + W1E_REVISION
            + " got "
            + repr(revision)
        )
    present = connection.execute(
        text("SELECT to_regclass('erp.care_assignment') IS NOT NULL")
    ).scalar()
    if present is not True:
        _fail("W1E_TABLE_MISSING: erp.care_assignment")


def _require_foreign_key(
    connection: Connection,
    name: str,
    *,
    local_columns: tuple[str, ...],
    target_schema: str,
    target_table: str,
    referenced_columns: tuple[str, ...],
    deferrable: bool | None = None,
    initially_deferred: bool | None = None,
) -> None:
    row = connection.execute(
        text(
            """
            SELECT
                target_schema.nspname,
                target_table.relname,
                c.confdeltype,
                c.condeferrable,
                c.condeferred,
                c.convalidated,
                ARRAY(
                    SELECT local_att.attname
                    FROM unnest(c.conkey) WITH ORDINALITY AS local_key(attnum, ord)
                    JOIN pg_attribute local_att
                      ON local_att.attrelid = c.conrelid
                     AND local_att.attnum = local_key.attnum
                    ORDER BY local_key.ord
                ),
                ARRAY(
                    SELECT target_att.attname
                    FROM unnest(c.confkey) WITH ORDINALITY AS target_key(attnum, ord)
                    JOIN pg_attribute target_att
                      ON target_att.attrelid = c.confrelid
                     AND target_att.attnum = target_key.attnum
                    ORDER BY target_key.ord
                ),
                c.confupdtype,
                c.confmatchtype
            FROM pg_constraint c
            JOIN pg_class source_table ON source_table.oid = c.conrelid
            JOIN pg_namespace source_schema ON source_schema.oid = source_table.relnamespace
            JOIN pg_class target_table ON target_table.oid = c.confrelid
            JOIN pg_namespace target_schema ON target_schema.oid = target_table.relnamespace
            WHERE source_schema.nspname = 'erp'
              AND source_table.relname = 'care_assignment'
              AND c.conname = :name
              AND c.contype = 'f'
            """
        ),
        {"name": name},
    ).one_or_none()
    if row is None:
        _fail("W1E_FOREIGN_KEY_MISSING: " + name)
    if (row[0], row[1]) != (target_schema, target_table):
        _fail("W1E_FOREIGN_KEY_TARGET_MISMATCH: " + name)
    if row[5] is not True:
        _fail("W1E_FOREIGN_KEY_NOT_VALIDATED: " + name)
    if tuple(row[6] or ()) != local_columns:
        _fail("W1E_FOREIGN_KEY_LOCAL_COLUMNS_MISMATCH: " + name)
    if tuple(row[7] or ()) != referenced_columns:
        _fail("W1E_FOREIGN_KEY_REFERENCED_COLUMNS_MISMATCH: " + name)
    if row[8] != "a" or row[9] != "s":
        _fail("W1E_FOREIGN_KEY_UPDATE_OR_MATCH_MISMATCH: " + name)
    if row[2] != "r":
        _fail("W1E_FOREIGN_KEY_DELETE_ACTION_MISMATCH: " + name)
    if deferrable is not None and row[3] is not deferrable:
        _fail("W1E_FOREIGN_KEY_DEFERRABLE_MISMATCH: " + name)
    if initially_deferred is not None and row[4] is not initially_deferred:
        _fail("W1E_FOREIGN_KEY_INITIAL_STATE_MISMATCH: " + name)


def _require_shape(connection: Connection) -> None:
    columns = {
        row[0]
        for row in connection.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'erp' AND table_name = 'care_assignment'
                """
            )
        ).all()
    }
    required_columns = {
        "id",
        "recipient_contract_id",
        "staff_id",
        "employment_id",
        "assignment_kind",
        "family_relationship_text",
        "start_date",
        "end_date",
        "assignment_period",
        "invalidated_at_utc",
        "replacement_assignment_id",
        "created_by_account_id",
        "created_at_utc",
        "updated_by_account_id",
        "updated_at_utc",
        "row_version",
    }
    if columns != required_columns:
        missing = sorted(required_columns - columns)
        extra = sorted(columns - required_columns)
        _fail(
            "W1E_TABLE_COLUMN_SET_MISMATCH: missing="
            + ",".join(missing)
            + ";extra="
            + ",".join(extra)
        )

    material_rows = connection.execute(
        text(
            """
            SELECT
                a.attname,
                format_type(a.atttypid, a.atttypmod),
                a.attnotnull,
                a.attidentity,
                a.attgenerated,
                pg_get_expr(d.adbin, d.adrelid)
            FROM pg_attribute a
            JOIN pg_class t ON t.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            LEFT JOIN pg_attrdef d
              ON d.adrelid = a.attrelid AND d.adnum = a.attnum
            WHERE n.nspname = 'erp'
              AND t.relname = 'care_assignment'
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
            """
        )
    ).all()
    material = {row[0]: row[1:] for row in material_rows}
    expected_material = {
        "id": ("bigint", True),
        "recipient_contract_id": ("bigint", True),
        "staff_id": ("bigint", True),
        "employment_id": ("bigint", True),
        "assignment_kind": ("text", True),
        "family_relationship_text": ("text", False),
        "start_date": ("date", True),
        "end_date": ("date", False),
        "assignment_period": ("daterange", True),
        "invalidated_at_utc": ("timestamp with time zone", False),
        "replacement_assignment_id": ("bigint", False),
        "created_by_account_id": ("bigint", True),
        "created_at_utc": ("timestamp with time zone", True),
        "updated_by_account_id": ("bigint", True),
        "updated_at_utc": ("timestamp with time zone", True),
        "row_version": ("integer", True),
    }
    expected_defaults = {
        "created_at_utc": "now()",
        "updated_at_utc": "now()",
        "row_version": "1",
    }
    if tuple(material) != tuple(expected_material):
        _fail("W1E_TABLE_COLUMN_SET_OR_ORDER_MISMATCH: " + repr(tuple(material)))
    for name, (expected_type, expected_not_null) in expected_material.items():
        row = material.get(name)
        if row is None:
            _fail("W1E_TABLE_COLUMN_MISSING: " + name)
        actual_type, not_null, identity, generated, expression = row
        if actual_type != expected_type or not_null is not expected_not_null:
            _fail("W1E_TABLE_COLUMN_MATERIAL_MISMATCH: " + name)
        if name == "id":
            if identity != "d" or generated != "":
                _fail("W1E_TABLE_IDENTITY_MISMATCH")
        elif identity != "":
            _fail("W1E_TABLE_UNEXPECTED_IDENTITY: " + name)
        if name == "assignment_period":
            if generated != "s":
                _fail("W1E_TABLE_PERIOD_NOT_STORED_GENERATED")
            if _compact_expression(expression or "") not in {
                "daterange(start_date,end_date+1,'[)')",
                "daterange(start_date,(end_date+1),'[)')",
            }:
                _fail("W1E_TABLE_PERIOD_EXPRESSION_MISMATCH: " + repr(expression))
        elif generated != "":
            _fail("W1E_TABLE_UNEXPECTED_GENERATED_COLUMN: " + name)
        if name != "assignment_period":
            expected_default = expected_defaults.get(name)
            if expected_default is None:
                if expression is not None:
                    _fail("W1E_TABLE_UNEXPECTED_DEFAULT: " + name + ":" + repr(expression))
            elif _compact_expression(expression or "") != expected_default:
                _fail("W1E_TABLE_DEFAULT_MISMATCH: " + name + ":" + repr(expression))

    constraint_rows = connection.execute(
        text(
            """
            SELECT
                c.conname,
                c.contype,
                c.convalidated,
                c.condeferrable,
                c.condeferred,
                ARRAY(
                    SELECT local_att.attname
                    FROM unnest(c.conkey) WITH ORDINALITY AS local_key(attnum, ord)
                    JOIN pg_attribute local_att
                      ON local_att.attrelid = c.conrelid
                     AND local_att.attnum = local_key.attnum
                    ORDER BY local_key.ord
                ),
                pg_get_expr(c.conbin, c.conrelid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'erp' AND t.relname = 'care_assignment'
              AND c.contype <> 't'
            """
        )
    ).all()
    constraints = {row[0]: row for row in constraint_rows}
    expected_constraints = {
        "pk_care_assignment": "p",
        "fk_care_assignment_recipient_contract": "f",
        "fk_care_assignment_employment": "f",
        "fk_care_assignment_replacement": "f",
        "fk_care_assignment_created_by_account": "f",
        "fk_care_assignment_updated_by_account": "f",
        "ck_care_assignment_kind": "c",
        "ck_care_assignment_date_order": "c",
        "ck_care_assignment_row_version_positive": "c",
        "ex_care_assignment_same_contract_staff_period": "x",
    }
    if set(constraints) != set(expected_constraints):
        _fail("W1E_CONSTRAINT_SET_MISMATCH: " + repr(sorted(constraints)))
    for name, kind in expected_constraints.items():
        row = constraints[name]
        if row[1] != kind or row[2] is not True:
            _fail("W1E_CONSTRAINT_KIND_OR_VALIDATION_MISMATCH: " + name)
    primary_key = constraints["pk_care_assignment"]
    if (
        tuple(primary_key[5] or ()) != ("id",)
        or primary_key[3] is not False
        or primary_key[4] is not False
    ):
        _fail("W1E_PRIMARY_KEY_COLUMNS_MISMATCH")
    expected_checks = {
        "ck_care_assignment_kind": {
            "assignment_kind=any(array['general','family'])",
            "assignment_kindin('general','family')",
        },
        "ck_care_assignment_date_order": {
            "end_dateisnullorstart_date<=end_date",
            "(end_dateisnull)or(start_date<=end_date)",
        },
        "ck_care_assignment_row_version_positive": {"row_version>0"},
    }
    for name, expected_values in expected_checks.items():
        row = constraints[name]
        if row[3] is not False or row[4] is not False:
            _fail("W1E_CHECK_DEFERRABILITY_MISMATCH: " + name)
        if _compact_expression(row[6] or "") not in expected_values:
            _fail("W1E_CHECK_EXPRESSION_MISMATCH: " + name + ":" + repr(row[6]))

    exclusion_keys = connection.execute(
        text(
            """
            SELECT local_att.attname, exclusion_operator.oprname
            FROM pg_constraint c
            CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS local_key(attnum, ord)
            CROSS JOIN LATERAL unnest(c.conexclop) WITH ORDINALITY AS operator_key(oprid, ord)
            JOIN pg_attribute local_att
              ON local_att.attrelid = c.conrelid
             AND local_att.attnum = local_key.attnum
            JOIN pg_operator exclusion_operator
              ON exclusion_operator.oid = operator_key.oprid
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'erp'
              AND t.relname = 'care_assignment'
              AND c.conname = 'ex_care_assignment_same_contract_staff_period'
              AND local_key.ord = operator_key.ord
            ORDER BY local_key.ord
            """
        )
    ).all()
    if tuple(tuple(row) for row in exclusion_keys) != (
        ("recipient_contract_id", "="),
        ("staff_id", "="),
        ("assignment_period", "&&"),
    ):
        _fail("W1E_EXCLUSION_KEYS_MISMATCH")
    exclusion_row = connection.execute(
        text(
            """
            SELECT pg_get_expr(i.indpred, i.indrelid), access_method.amname
            FROM pg_constraint c
            JOIN pg_index i ON i.indexrelid = c.conindid
            JOIN pg_class exclusion_index ON exclusion_index.oid = i.indexrelid
            JOIN pg_am access_method ON access_method.oid = exclusion_index.relam
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = 'erp'
              AND t.relname = 'care_assignment'
              AND c.conname = 'ex_care_assignment_same_contract_staff_period'
            """
        )
    ).one_or_none()
    if exclusion_row is None:
        _fail("W1E_EXCLUSION_INDEX_MISSING")
    if exclusion_row[1] != "gist":
        _fail("W1E_EXCLUSION_ACCESS_METHOD_MISMATCH")
    if _compact_expression(exclusion_row[0] or "") != "invalidated_at_utcisnull":
        _fail("W1E_EXCLUSION_ACTIVE_PREDICATE_MISMATCH")
    exclusion_constraint = constraints["ex_care_assignment_same_contract_staff_period"]
    if exclusion_constraint[3] is not False or exclusion_constraint[4] is not False:
        _fail("W1E_EXCLUSION_DEFERRABILITY_MISMATCH")

    _require_foreign_key(
        connection,
        "fk_care_assignment_recipient_contract",
        local_columns=("recipient_contract_id",),
        target_schema="erp",
        target_table="recipient_contract",
        referenced_columns=("id",),
        deferrable=False,
        initially_deferred=False,
    )
    _require_foreign_key(
        connection,
        "fk_care_assignment_employment",
        local_columns=("staff_id", "employment_id"),
        target_schema="erp",
        target_table="staff_employment",
        referenced_columns=("staff_id", "id"),
        deferrable=False,
        initially_deferred=False,
    )
    _require_foreign_key(
        connection,
        "fk_care_assignment_replacement",
        local_columns=("replacement_assignment_id",),
        target_schema="erp",
        target_table="care_assignment",
        referenced_columns=("id",),
        deferrable=True,
        initially_deferred=True,
    )
    _require_foreign_key(
        connection,
        "fk_care_assignment_created_by_account",
        local_columns=("created_by_account_id",),
        target_schema="erp",
        target_table="user_account",
        referenced_columns=("id",),
        deferrable=False,
        initially_deferred=False,
    )
    _require_foreign_key(
        connection,
        "fk_care_assignment_updated_by_account",
        local_columns=("updated_by_account_id",),
        target_schema="erp",
        target_table="user_account",
        referenced_columns=("id",),
        deferrable=False,
        initially_deferred=False,
    )

    trigger_rows = connection.execute(
        text(
            """
            SELECT
                t.tgname,
                n.nspname || '.' || c.relname,
                t.tgdeferrable,
                t.tginitdeferred,
                t.tgtype,
                function_schema.nspname,
                function_proc.proname,
                t.tgenabled,
                t.tgconstraint <> 0,
                t.tgattr::text,
                pg_get_expr(t.tgqual, t.tgrelid),
                t.tgfoid,
                t.tgnargs,
                octet_length(t.tgargs)
            FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_proc function_proc ON function_proc.oid = t.tgfoid
            JOIN pg_namespace function_schema ON function_schema.oid = function_proc.pronamespace
            WHERE n.nspname = 'erp' AND NOT t.tgisinternal
            """
        )
    ).all()
    expected_triggers = {
        "ct_care_assignment_within_contract": (
            ASSIGNMENT_TABLE,
            "fn_care_assignment_within_contract",
            21,
        ),
        "ct_care_assignment_within_employment": (
            ASSIGNMENT_TABLE,
            "fn_care_assignment_within_employment",
            21,
        ),
        "ct_care_assignment_within_position": (
            ASSIGNMENT_TABLE,
            "fn_care_assignment_within_position",
            21,
        ),
        "ct_care_assignment_general_care_qualified": (
            ASSIGNMENT_TABLE,
            "fn_care_assignment_general_care_qualified",
            21,
        ),
        "ct_recipient_contract_assignment_reverse_guard": (
            "erp.recipient_contract",
            "fn_recipient_contract_assignment_reverse_guard",
            17,
        ),
        "ct_staff_employment_child_periods_reverse_guard": (
            "erp.staff_employment",
            "fn_staff_employment_child_periods_reverse_guard",
            17,
        ),
        "ct_staff_position_care_assignment_reverse_guard": (
            "erp.staff_position_period",
            "fn_staff_position_care_assignment_reverse_guard",
            17,
        ),
        "ct_staff_service_qualification_assignment_reverse_guard": (
            "erp.staff_service_qualification_period",
            "fn_staff_service_qualification_assignment_reverse_guard",
            17,
        ),
    }
    expected_trigger_sets = {
        ASSIGNMENT_TABLE: {
            "ct_care_assignment_within_contract",
            "ct_care_assignment_within_employment",
            "ct_care_assignment_within_position",
            "ct_care_assignment_general_care_qualified",
        },
        "erp.recipient_contract": {
            "bu_recipient_contract_no_reactivation",
            "trg_recipient_contract_group_period_overlap",
            "ct_recipient_contract_assignment_reverse_guard",
        },
        "erp.staff_employment": {
            "ct_staff_employment_child_periods_reverse_guard",
        },
        "erp.staff_position_period": {
            "ct_staff_position_within_employment",
            "ct_staff_position_care_assignment_reverse_guard",
        },
        "erp.staff_service_qualification_period": {
            "ct_staff_service_qualification_within_employment",
            "ct_staff_service_qualification_source_license_guard",
            "ct_staff_service_qualification_assignment_reverse_guard",
        },
    }
    for relation, expected_names in expected_trigger_sets.items():
        actual_names = {row[0] for row in trigger_rows if row[1] == relation}
        if actual_names != expected_names:
            _fail("W1E_TRIGGER_SET_MISMATCH: " + relation + ":" + repr(sorted(actual_names)))

    trigger_function_oids: dict[str, int] = {}
    for name, (relation, function_name, trigger_type) in expected_triggers.items():
        matches = [row for row in trigger_rows if row[0] == name]
        if len(matches) != 1:
            _fail("W1E_TRIGGER_MISSING: " + name)
        row = matches[0]
        if (
            row[1] != relation
            or row[2] is not True
            or row[3] is not True
            or row[4] != trigger_type
            or row[5] != "erp"
            or row[6] != function_name
            or row[7] != "O"
            or row[8] is not True
            or row[9] != ""
            or row[10] is not None
            or type(row[11]) is not int
            or row[12] != 0
            or row[13] != 0
        ):
            _fail("W1E_TRIGGER_SIGNATURE_MISMATCH: " + name + ":" + repr(tuple(row)))
        previous_oid = trigger_function_oids.setdefault(function_name, row[11])
        if previous_oid != row[11]:
            _fail("W1E_TRIGGER_FUNCTION_OID_MISMATCH: " + function_name)

    def function_body(name: str) -> str:
        function_oid = trigger_function_oids.get(name)
        if function_oid is None:
            _fail("W1E_TRIGGER_FUNCTION_BINDING_MISSING: " + name)
        row = connection.execute(
            text(
                """
                SELECT p.prosrc, p.pronargs, p.prorettype = 'trigger'::regtype, p.prokind
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE p.oid = :function_oid
                  AND n.nspname = 'erp'
                  AND p.proname = :name
                """
            ),
            {"function_oid": function_oid, "name": name},
        ).one_or_none()
        if row is None or type(row[0]) is not str:
            _fail("W1E_FUNCTION_MISSING: " + name)
        if tuple(row[1:]) != (0, True, "f"):
            _fail("W1E_FUNCTION_SIGNATURE_MISMATCH: " + name + ":" + repr(tuple(row[1:])))
        return _without_sql_comments(row[0]).lower()

    qualified_body = function_body("fn_care_assignment_general_care_qualified")
    for fragment in ("service_type_id", "staff_service_qualification_period", "assignment_period"):
        if fragment not in qualified_body:
            _fail("W1E_QUALIFICATION_GUARD_CONTEXT_MISSING: " + fragment)
    employment_body = re.sub(
        r"\s+", " ", function_body("fn_care_assignment_within_employment")
    ).strip()
    employment_contract = re.compile(
        r"begin\s+if\s+new\.invalidated_at_utc\s+is\s+null\s+and\s+not\s+exists\s*\(\s*"
        r"select\s+1\s+from\s+erp\.staff_employment\s+(?:as\s+)?employment\s+where\s+"
        r"employment\.id\s*=\s*new\.employment_id\s+and\s+"
        r"employment\.staff_id\s*=\s*new\.staff_id\s+and\s+"
        r"employment\.invalidated_at_utc\s+is\s+null\s+and\s+"
        r"new\.assignment_period\s*<@\s*employment\.employment_period\s*\)\s+then\s+"
        r"raise\s+exception\s+using\s+errcode\s*=\s*'23514'\s*,\s*"
        r"message\s*=\s*'care_assignment_outside_employment_period'\s*;\s*"
        r"end\s+if\s*;\s*return\s+new\s*;\s*end\s*;?",
    )
    if employment_contract.fullmatch(employment_body) is None:
        _fail("W1E_EMPLOYMENT_GUARD_EXECUTION_PATH_MISMATCH")
    position_body = function_body("fn_care_assignment_within_position")
    for fragment in ("staff_position_period", "care_worker", "assignment_period"):
        if fragment not in position_body:
            _fail("W1E_POSITION_GUARD_CONTEXT_MISSING: " + fragment)
    for name in (
        "fn_recipient_contract_assignment_reverse_guard",
        "fn_staff_employment_child_periods_reverse_guard",
        "fn_staff_position_care_assignment_reverse_guard",
        "fn_staff_service_qualification_assignment_reverse_guard",
    ):
        if ASSIGNMENT_TABLE.removeprefix("erp.") not in function_body(name):
            _fail("W1E_REVERSE_GUARD_ASSIGNMENT_MISSING: " + name)


def _require_id(value: Any, marker: str) -> int:
    if type(value) is not int or value <= 0:
        _fail(marker)
    return value


def _insert_id(
    connection: Connection,
    statement: str,
    parameters: dict[str, Any],
    marker: str,
) -> int:
    value = connection.execute(text(statement), parameters).scalar_one_or_none()
    return _require_id(value, marker)


def _service_id(connection: Connection, code: str, marker: str) -> int:
    value = connection.execute(
        text("SELECT id FROM erp.service_type WHERE code = :code AND active IS TRUE"),
        {"code": code},
    ).scalar_one_or_none()
    return _require_id(value, marker)


def _seed_case(
    connection: Connection,
    *,
    contract_end: date = date(2030, 12, 31),
    employment_end: date = date(2030, 12, 31),
    position_a_end: date | None = None,
    qualification_a_start: date = date(2030, 1, 1),
    qualification_a_end: date | None = date(2030, 12, 31),
    qualification_a_service_code: str = CONTRACT_SERVICE_CODE,
) -> W1ECase:
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
            "name": "W1E ACCOUNT STAFF " + label,
            "display_name": "W1E ACCOUNT " + label,
        },
        "W1E_HARNESS_ACCOUNT_STAFF_SEED_FAILED",
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
            "account_code": "W1E_" + label,
            "display_name": "W1E ACCOUNT " + label,
            "pin_hash": "w1e-test-pin-hash-" + label,
            "pin_lookup_hmac": uuid4().bytes,
        },
        "W1E_HARNESS_ACCOUNT_SEED_FAILED",
    )
    contract_service_type_id = _service_id(
        connection, CONTRACT_SERVICE_CODE, "W1E_HARNESS_HOME_CARE_SEED_MISSING"
    )
    other_service_type_id = _service_id(
        connection, OTHER_SERVICE_CODE, "W1E_HARNESS_HOME_BATH_SEED_MISSING"
    )

    if position_a_end is None:
        position_a_end = employment_end

    def staff_id(suffix: str) -> int:
        return _insert_id(
            connection,
            """
            INSERT INTO erp.staff (name, birth_date, sex_code, display_name, row_version)
            VALUES (:name, DATE '1990-01-01', 'TEST', :display_name, 1)
            RETURNING id
            """,
            {"name": "W1E " + label + suffix, "display_name": "W1E " + label + suffix},
            "W1E_HARNESS_STAFF_INSERT_FAILED",
        )

    def employment_id(staff: int, suffix: str, end_date: date) -> int:
        sequence = _require_id(
            connection.execute(
                text("SELECT COALESCE(MAX(staff_no_sequence), 0) + 1 FROM erp.staff_employment")
            ).scalar_one(),
            "W1E_HARNESS_EMPLOYMENT_SEQUENCE_INVALID",
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
                "staff_no": "W1E_" + label + suffix,
                "staff_no_sequence": sequence,
                "end_date": end_date,
                "account_id": account_id,
            },
            "W1E_HARNESS_EMPLOYMENT_INSERT_FAILED",
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
                (:staff_id, :employment_id, 'CARE_WORKER', DATE '2030-01-01', :end_date,
                 NULL, NULL, :account_id, :account_id, 1)
            RETURNING id
            """,
            {
                "staff_id": staff,
                "employment_id": employment,
                "end_date": end_date,
                "account_id": account_id,
            },
            "W1E_HARNESS_POSITION_INSERT_FAILED",
        )

    def qualification_id(
        staff: int,
        employment: int,
        service_code: str,
        start_date: date,
        end_date: date | None,
    ) -> int:
        service_type_id = _service_id(
            connection, service_code, "W1E_HARNESS_QUALIFICATION_SERVICE_MISSING"
        )
        return _insert_id(
            connection,
            """
            INSERT INTO erp.staff_service_qualification_period
                (staff_id, employment_id, service_type_id, start_date, end_date,
                 source_license_id, created_by_account_id, updated_by_account_id, row_version)
            VALUES
                (:staff_id, :employment_id, :service_type_id, :start_date, :end_date,
                 NULL, :account_id, :account_id, 1)
            RETURNING id
            """,
            {
                "staff_id": staff,
                "employment_id": employment,
                "service_type_id": service_type_id,
                "start_date": start_date,
                "end_date": end_date,
                "account_id": account_id,
            },
            "W1E_HARNESS_QUALIFICATION_INSERT_FAILED",
        )

    staff_a = staff_id("_A")
    employment_a = employment_id(staff_a, "_A", employment_end)
    position_a = position_id(staff_a, employment_a, position_a_end)
    qualification_a = qualification_id(
        staff_a,
        employment_a,
        qualification_a_service_code,
        qualification_a_start,
        qualification_a_end,
    )
    staff_b = staff_id("_B")
    employment_b = employment_id(staff_b, "_B", employment_end)
    position_b = position_id(staff_b, employment_b, employment_end)
    qualification_b = qualification_id(
        staff_b,
        employment_b,
        CONTRACT_SERVICE_CODE,
        date(2030, 1, 1),
        employment_end,
    )
    recipient_id = _insert_id(
        connection,
        """
        INSERT INTO erp.recipient
            (name, birth_date, sex_code, created_by_account_id,
             updated_by_account_id, row_version)
        VALUES
            (:name, DATE '1950-01-01', 'TEST', :account_id, :account_id, 1)
        RETURNING id
        """,
        {"name": "W1E RECIPIENT " + label, "account_id": account_id},
        "W1E_HARNESS_RECIPIENT_INSERT_FAILED",
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
        "W1E_HARNESS_CONTRACT_INSERT_FAILED",
    )
    _flush_constraints(connection)
    return W1ECase(
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


def _flush_constraints(connection: Connection) -> None:
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def _insert_contract(
    connection: Connection,
    case: W1ECase,
    *,
    start_date: date,
    end_date: date | None,
    marker: str,
) -> int:
    return _insert_id(
        connection,
        """
        INSERT INTO erp.recipient_contract
            (recipient_id, service_type_id, start_date, end_date,
             invalidated_at_utc, replacement_contract_id,
             created_by_account_id, updated_by_account_id, row_version)
        VALUES
            (:recipient_id, :service_type_id, :start_date, :end_date,
             NULL, NULL, :account_id, :account_id, 1)
        RETURNING id
        """,
        {
            "recipient_id": case.recipient_id,
            "service_type_id": case.contract_service_type_id,
            "start_date": start_date,
            "end_date": end_date,
            "account_id": case.account_id,
        },
        marker,
    )


def _insert_qualification(
    connection: Connection,
    case: W1ECase,
    *,
    staff_id: int,
    employment_id: int,
    service_type_id: int,
    start_date: date,
    end_date: date | None,
    marker: str,
) -> int:
    return _insert_id(
        connection,
        """
        INSERT INTO erp.staff_service_qualification_period
            (staff_id, employment_id, service_type_id, start_date, end_date,
             source_license_id, created_by_account_id, updated_by_account_id, row_version)
        VALUES
            (:staff_id, :employment_id, :service_type_id, :start_date, :end_date,
             NULL, :account_id, :account_id, 1)
        RETURNING id
        """,
        {
            "staff_id": staff_id,
            "employment_id": employment_id,
            "service_type_id": service_type_id,
            "start_date": start_date,
            "end_date": end_date,
            "account_id": case.account_id,
        },
        marker,
    )


def _insert_assignment(
    connection: Connection,
    case: W1ECase,
    *,
    recipient_contract_id: int | None = None,
    staff_id: int,
    employment_id: int,
    start_date: date,
    end_date: date | None,
) -> int:
    statement = f"""
        INSERT INTO {ASSIGNMENT_TABLE}
            (recipient_contract_id, staff_id, employment_id, assignment_kind,
             family_relationship_text, start_date, end_date, invalidated_at_utc,
             replacement_assignment_id, created_by_account_id, updated_by_account_id, row_version)
        VALUES
            (:contract_id, :staff_id, :employment_id, 'GENERAL', NULL,
             :start_date, :end_date, NULL, NULL,
             :account_id, :account_id, 1)
        RETURNING id
    """
    return _insert_id(
        connection,
        statement,
        {
            "contract_id": (
                case.contract_id if recipient_contract_id is None else recipient_contract_id
            ),
            "staff_id": staff_id,
            "employment_id": employment_id,
            "start_date": start_date,
            "end_date": end_date,
            "account_id": case.account_id,
        },
        "W1E_ASSIGNMENT_INSERT_FAILED",
    )


def _assert_db_violation(
    error: IntegrityError,
    marker: str,
    *,
    expected_message: str | tuple[str, ...] | None = None,
    expected_constraint: str | None = None,
    expected_sqlstate: str | tuple[str, ...] | None = None,
) -> None:
    original = error.orig
    diagnostic = getattr(original, "diag", None)
    sqlstate = getattr(original, "sqlstate", None)
    if sqlstate is None and diagnostic is not None:
        sqlstate = getattr(diagnostic, "sqlstate", None)
    expected_states = (
        (expected_sqlstate,)
        if type(expected_sqlstate) is str
        else expected_sqlstate
        if type(expected_sqlstate) is tuple
        else ("23P01", "23503", "23514")
    )
    if sqlstate not in expected_states:
        _fail(marker + "_SQLSTATE_UNEXPECTED: " + repr(sqlstate))
    if expected_constraint is not None:
        constraint = getattr(diagnostic, "constraint_name", None)
        if constraint != expected_constraint:
            _fail(marker + "_CONSTRAINT_MISMATCH: " + repr(constraint))
    if expected_message is not None:
        messages = (expected_message,) if type(expected_message) is str else expected_message
        if (
            type(messages) is not tuple
            or not messages
            or not all(type(candidate) is str and candidate for candidate in messages)
        ):
            _fail(marker + "_EXPECTED_MESSAGE_INVALID")
        message = getattr(diagnostic, "message_primary", None)
        if type(message) is not str or message not in messages:
            _fail(marker + "_MESSAGE_MISMATCH: " + repr(message))


def _expect_violation(
    connection: Connection,
    statement: str,
    parameters: dict[str, Any],
    marker: str,
    *,
    expected_message: str | tuple[str, ...] | None = None,
    expected_constraint: str | None = None,
    expected_sqlstate: str | tuple[str, ...] | None = None,
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
            expected_message=expected_message,
            expected_constraint=expected_constraint,
            expected_sqlstate=expected_sqlstate,
        )
        connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        return
    savepoint.rollback()
    connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    _fail(marker + "_ACCEPTED")


def _expect_replacement_orphan(
    connection: Connection,
    *,
    marker: str,
    old_update: str,
    old_parameters: dict[str, Any],
    replacement_insert: str,
    replacement_parameters: dict[str, Any],
    link_update: str,
    link_parameters: dict[str, Any],
    expected_message: str,
) -> None:
    """Reject a parent replacement whose final period leaves the assignment orphaned."""
    savepoint = connection.begin_nested()
    try:
        connection.execute(text(old_update), old_parameters)
        replacement_id = _insert_id(
            connection,
            replacement_insert,
            replacement_parameters,
            marker + "_REPLACEMENT_INSERT_FAILED",
        )
        connection.execute(
            text(link_update),
            {**link_parameters, "replacement_id": replacement_id},
        )
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    except IntegrityError as error:
        savepoint.rollback()
        _assert_db_violation(
            error,
            marker,
            expected_message=expected_message,
            expected_sqlstate="23514",
        )
        connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        return
    savepoint.rollback()
    connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    _fail(marker + "_ACCEPTED")


def test_w1e_pg_catalog_and_deferred_guard_shape(database_connection: Connection) -> None:
    """Product RED: the 0012 catalog and all included guard boundaries exist."""
    _require_catalog(database_connection)
    _require_shape(database_connection)


def test_w1e_pg_general_overlap_and_containment(database_connection: Connection) -> None:
    """GENERAL overlap, adjacency, different-staff concurrency, and contract bounds."""
    _require_catalog(database_connection)
    case = _seed_case(
        database_connection,
        contract_end=date(2030, 12, 31),
        employment_end=date(2031, 12, 31),
        qualification_a_end=date(2031, 12, 31),
    )
    first_id = _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
    )
    _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        start_date=date(2030, 2, 1),
        end_date=date(2030, 2, 28),
    )
    _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_b_id,
        employment_id=case.employment_b_id,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
    )
    _flush_constraints(database_connection)

    _expect_violation(
        database_connection,
        """
        INSERT INTO erp.care_assignment
            (recipient_contract_id, staff_id, employment_id, assignment_kind,
             start_date, end_date, created_by_account_id, updated_by_account_id, row_version)
        VALUES
            (:contract_id, :staff_id, :employment_id, 'GENERAL',
             DATE '2030-01-15', DATE '2030-02-15', :account_id, :account_id, 1)
        """,
        {
            "contract_id": case.contract_id,
            "staff_id": case.staff_a_id,
            "employment_id": case.employment_a_id,
            "account_id": case.account_id,
        },
        "W1E_ASG01_OVERLAP_SAME_CONTRACT_STAFF",
        expected_constraint="ex_care_assignment_same_contract_staff_period",
        expected_sqlstate="23P01",
    )

    # Isolate contract containment from the active same-staff exclusion: this
    # case has no active assignment before the only out-of-contract insert.
    contract_case = _seed_case(database_connection, contract_end=date(2030, 1, 10))
    _expect_violation(
        database_connection,
        """
        INSERT INTO erp.care_assignment
            (recipient_contract_id, staff_id, employment_id, assignment_kind,
             start_date, end_date, created_by_account_id, updated_by_account_id, row_version)
        VALUES
            (:contract_id, :staff_id, :employment_id, 'GENERAL',
             DATE '2030-01-01', DATE '2030-01-15', :account_id, :account_id, 1)
        """,
        {
            "contract_id": contract_case.contract_id,
            "staff_id": contract_case.staff_a_id,
            "employment_id": contract_case.employment_a_id,
            "account_id": contract_case.account_id,
        },
        "W1E_ASG01_OUTSIDE_CONTRACT",
        expected_message="CARE_ASSIGNMENT_OUTSIDE_CONTRACT_PERIOD",
        expected_sqlstate="23514",
    )
    del first_id


def test_w1e_pg_composite_employment_fk_rejects_staff_mismatch(
    database_connection: Connection,
) -> None:
    """The employment FK must bind the supplied staff and employment identity."""
    _require_catalog(database_connection)
    case = _seed_case(database_connection)
    _expect_violation(
        database_connection,
        """
        INSERT INTO erp.care_assignment
            (recipient_contract_id, staff_id, employment_id, assignment_kind,
             start_date, end_date, created_by_account_id, updated_by_account_id, row_version)
        VALUES
            (:contract_id, :staff_id, :employment_id, 'GENERAL',
             DATE '2030-01-01', DATE '2030-01-31', :account_id, :account_id, 1)
        """,
        {
            "contract_id": case.contract_id,
            "staff_id": case.staff_b_id,
            "employment_id": case.employment_a_id,
            "account_id": case.account_id,
        },
        "W1E_ASG01_EMPLOYMENT_COMPOSITE_FK",
        expected_constraint="fk_care_assignment_employment",
        expected_sqlstate="23503",
    )


def test_w1e_pg_forward_employment_and_position_containment(
    database_connection: Connection,
) -> None:
    """Forward employment and CARE_WORKER position guards reject an uncovered day."""
    _require_catalog(database_connection)
    # W1A already forbids position/qualification children from extending past
    # employment. An assignment beyond employment therefore violates all nested
    # boundaries at once, and deferred-trigger name order may surface eligibility
    # before employment. _require_shape separately proves the employment trigger
    # and range-containment body; this runtime case accepts only those two exact
    # product failure classes rather than depending on trigger ordering.
    employment_case = _seed_case(
        database_connection,
        employment_end=date(2030, 1, 10),
        position_a_end=date(2030, 1, 10),
        qualification_a_end=date(2030, 1, 10),
    )
    _expect_violation(
        database_connection,
        """
        INSERT INTO erp.care_assignment
            (recipient_contract_id, staff_id, employment_id, assignment_kind,
             start_date, end_date, created_by_account_id, updated_by_account_id, row_version)
        VALUES
            (:contract_id, :staff_id, :employment_id, 'GENERAL',
             DATE '2030-01-01', DATE '2030-01-31', :account_id, :account_id, 1)
        """,
        {
            "contract_id": employment_case.contract_id,
            "staff_id": employment_case.staff_a_id,
            "employment_id": employment_case.employment_a_id,
            "account_id": employment_case.account_id,
        },
        "W1E_ASG01_FORWARD_EMPLOYMENT",
        expected_message=(
            "CARE_ASSIGNMENT_OUTSIDE_EMPLOYMENT_PERIOD",
            "CARE_ASSIGNMENT_STAFF_INELIGIBLE",
        ),
        expected_sqlstate="23514",
    )

    position_case = _seed_case(
        database_connection,
        position_a_end=date(2030, 1, 10),
    )
    _expect_violation(
        database_connection,
        """
        INSERT INTO erp.care_assignment
            (recipient_contract_id, staff_id, employment_id, assignment_kind,
             start_date, end_date, created_by_account_id, updated_by_account_id, row_version)
        VALUES
            (:contract_id, :staff_id, :employment_id, 'GENERAL',
             DATE '2030-01-01', DATE '2030-01-31', :account_id, :account_id, 1)
        """,
        {
            "contract_id": position_case.contract_id,
            "staff_id": position_case.staff_a_id,
            "employment_id": position_case.employment_a_id,
            "account_id": position_case.account_id,
        },
        "W1E_ASG01_FORWARD_POSITION",
        expected_message="CARE_ASSIGNMENT_STAFF_INELIGIBLE",
        expected_sqlstate="23514",
    )


def test_w1e_pg_general_qualification_covers_every_day_and_service(
    database_connection: Connection,
) -> None:
    """GENERAL requires continuous qualification for the contract service."""
    _require_catalog(database_connection)
    gap_case = _seed_case(
        database_connection,
        qualification_a_end=date(2030, 1, 10),
    )
    _expect_violation(
        database_connection,
        """
        INSERT INTO erp.care_assignment
            (recipient_contract_id, staff_id, employment_id, assignment_kind,
             start_date, end_date, created_by_account_id, updated_by_account_id, row_version)
        VALUES
            (:contract_id, :staff_id, :employment_id, 'GENERAL',
             DATE '2030-01-01', DATE '2030-01-31', :account_id, :account_id, 1)
        """,
        {
            "contract_id": gap_case.contract_id,
            "staff_id": gap_case.staff_a_id,
            "employment_id": gap_case.employment_a_id,
            "account_id": gap_case.account_id,
        },
        "W1E_ASG01_QUALIFIED_GAP",
        expected_message="CARE_ASSIGNMENT_STAFF_INELIGIBLE",
        expected_sqlstate="23514",
    )

    stitched_case = _seed_case(
        database_connection,
        qualification_a_end=date(2030, 1, 15),
    )
    _insert_qualification(
        database_connection,
        stitched_case,
        staff_id=stitched_case.staff_a_id,
        employment_id=stitched_case.employment_a_id,
        service_type_id=stitched_case.contract_service_type_id,
        start_date=date(2030, 1, 16),
        end_date=date(2030, 12, 31),
        marker="W1E_HARNESS_STITCHED_QUALIFICATION_INSERT_FAILED",
    )
    stitched_assignment_id = _insert_assignment(
        database_connection,
        stitched_case,
        staff_id=stitched_case.staff_a_id,
        employment_id=stitched_case.employment_a_id,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
    )
    _flush_constraints(database_connection)
    persisted_id = database_connection.execute(
        text("SELECT id FROM erp.care_assignment WHERE id = :id"),
        {"id": stitched_assignment_id},
    ).scalar_one_or_none()
    if persisted_id != stitched_assignment_id:
        _fail("W1E_ASG01_STITCHED_QUALIFICATION_COVERAGE_NOT_ACCEPTED")

    mismatch_case = _seed_case(
        database_connection,
        qualification_a_service_code=OTHER_SERVICE_CODE,
    )
    _expect_violation(
        database_connection,
        """
        INSERT INTO erp.care_assignment
            (recipient_contract_id, staff_id, employment_id, assignment_kind,
             start_date, end_date, created_by_account_id, updated_by_account_id, row_version)
        VALUES
            (:contract_id, :staff_id, :employment_id, 'GENERAL',
             DATE '2030-01-01', DATE '2030-01-31', :account_id, :account_id, 1)
        """,
        {
            "contract_id": mismatch_case.contract_id,
            "staff_id": mismatch_case.staff_a_id,
            "employment_id": mismatch_case.employment_a_id,
            "account_id": mismatch_case.account_id,
        },
        "W1E_ASG01_QUALIFIED_SERVICE_CONTEXT",
        expected_message="CARE_ASSIGNMENT_STAFF_INELIGIBLE",
        expected_sqlstate="23514",
    )


def test_w1e_pg_reverse_guards_and_period_fact_correction(
    database_connection: Connection,
) -> None:
    """Parent truncation/invalidation/replacement guards and PERIOD_FACT correction."""
    _require_catalog(database_connection)
    case = _seed_case(database_connection)
    assignment_id = _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
    )
    _flush_constraints(database_connection)

    _expect_violation(
        database_connection,
        """
        UPDATE erp.recipient_contract
        SET end_date = DATE '2030-01-15', row_version = row_version + 1
        WHERE id = :id
        """,
        {"id": case.contract_id},
        "W1E_ASG01_REVERSE_CONTRACT",
        expected_message="CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN",
        expected_sqlstate="23514",
    )
    _expect_violation(
        database_connection,
        """
        UPDATE erp.staff_employment
        SET end_date = DATE '2030-01-15', row_version = row_version + 1
        WHERE id = :id
        """,
        {"id": case.employment_a_id},
        "W1E_ASG01_REVERSE_EMPLOYMENT_NEAREST_W1A_GUARD",
        # W1A's shared employment reverse guard sees the active position and
        # qualification children before W1E's care-assignment branch can be
        # isolated. This is the nearest enforceable runtime boundary.
        expected_message="STAFF_PERIOD_OUTSIDE_EMPLOYMENT",
        expected_sqlstate="23514",
    )
    _expect_violation(
        database_connection,
        """
        UPDATE erp.staff_position_period
        SET end_date = DATE '2030-01-15', row_version = row_version + 1
        WHERE id = :id
        """,
        {"id": case.position_a_id},
        "W1E_ASG01_REVERSE_POSITION_SHORTEN",
        expected_message="CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN",
        expected_sqlstate="23514",
    )
    _expect_violation(
        database_connection,
        """
        UPDATE erp.staff_service_qualification_period
        SET invalidated_at_utc = clock_timestamp(),
            replacement_qualification_id = NULL,
            row_version = row_version + 1
        WHERE id = :id
        """,
        {"id": case.qualification_a_id},
        "W1E_ASG01_REVERSE_QUALIFICATION_INVALIDATION",
        expected_message="CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN",
        expected_sqlstate="23514",
    )
    _expect_violation(
        database_connection,
        """
        UPDATE erp.staff_service_qualification_period
        SET end_date = DATE '2030-01-15', row_version = row_version + 1
        WHERE id = :id
        """,
        {"id": case.qualification_a_id},
        "W1E_ASG01_REVERSE_QUALIFICATION_SHORTEN",
        expected_message="CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN",
        expected_sqlstate="23514",
    )

    for statement, parameters, marker, message in (
        (
            """
            UPDATE erp.recipient_contract
            SET invalidated_at_utc = clock_timestamp(),
                replacement_contract_id = NULL,
                row_version = row_version + 1
            WHERE id = :id
            """,
            {"id": case.contract_id},
            "W1E_ASG01_REVERSE_CONTRACT_INVALIDATION",
            "CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN",
        ),
        (
            """
            UPDATE erp.staff_employment
            SET invalidated_at_utc = clock_timestamp(),
                replacement_employment_id = NULL,
                row_version = row_version + 1
            WHERE id = :id
            """,
            {"id": case.employment_a_id},
            "W1E_ASG01_REVERSE_EMPLOYMENT_INVALIDATION_NEAREST_W1A_GUARD",
            "STAFF_PERIOD_OUTSIDE_EMPLOYMENT",
        ),
        (
            """
            UPDATE erp.staff_position_period
            SET invalidated_at_utc = clock_timestamp(),
                replacement_id = NULL,
                row_version = row_version + 1
            WHERE id = :id
            """,
            {"id": case.position_a_id},
            "W1E_ASG01_REVERSE_POSITION_INVALIDATION",
            "CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN",
        ),
        (
            """
            UPDATE erp.staff_service_qualification_period
            SET invalidated_at_utc = clock_timestamp(),
                replacement_qualification_id = NULL,
                row_version = row_version + 1
            WHERE id = :id
            """,
            {"id": case.qualification_a_id},
            "W1E_ASG01_REVERSE_QUALIFICATION_INVALIDATION_2",
            "CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN",
        ),
    ):
        _expect_violation(
            database_connection,
            statement,
            parameters,
            marker,
            expected_message=message,
            expected_sqlstate="23514",
        )

    _expect_replacement_orphan(
        database_connection,
        marker="W1E_ASG01_REVERSE_CONTRACT_REPLACEMENT",
        old_update="""
            UPDATE erp.recipient_contract
            SET invalidated_at_utc = clock_timestamp(),
                replacement_contract_id = NULL,
                row_version = row_version + 1
            WHERE id = :id
        """,
        old_parameters={"id": case.contract_id},
        replacement_insert="""
            INSERT INTO erp.recipient_contract
                (recipient_id, service_type_id, start_date, end_date,
                 invalidated_at_utc, replacement_contract_id,
                 created_by_account_id, updated_by_account_id, row_version)
            VALUES
                (:recipient_id, :service_type_id, DATE '2030-01-01', DATE '2030-01-15',
                 NULL, NULL, :account_id, :account_id, 1)
            RETURNING id
        """,
        replacement_parameters={
            "recipient_id": case.recipient_id,
            "service_type_id": case.contract_service_type_id,
            "account_id": case.account_id,
        },
        link_update="""
            UPDATE erp.recipient_contract
            SET replacement_contract_id = :replacement_id,
                row_version = row_version + 1
            WHERE id = :id
        """,
        link_parameters={"id": case.contract_id},
        expected_message="CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN",
    )

    employment_sequence = _require_id(
        database_connection.execute(
            text("SELECT COALESCE(MAX(staff_no_sequence), 0) + 1 FROM erp.staff_employment")
        ).scalar_one(),
        "W1E_HARNESS_EMPLOYMENT_REPLACEMENT_SEQUENCE_INVALID",
    )
    _expect_replacement_orphan(
        database_connection,
        marker="W1E_ASG01_REVERSE_EMPLOYMENT_REPLACEMENT_NEAREST_W1A_GUARD",
        old_update="""
            UPDATE erp.staff_employment
            SET invalidated_at_utc = clock_timestamp(),
                replacement_employment_id = NULL,
                row_version = row_version + 1
            WHERE id = :id
        """,
        old_parameters={"id": case.employment_a_id},
        replacement_insert="""
            INSERT INTO erp.staff_employment
                (staff_id, employment_no, staff_no, staff_no_year, staff_no_sequence,
                 start_date, end_date, created_by_account_id, updated_by_account_id, row_version)
            VALUES
                (:staff_id, 2, :staff_no, 2099, :staff_no_sequence,
                 DATE '2030-01-01', DATE '2030-01-15', :account_id, :account_id, 1)
            RETURNING id
        """,
        replacement_parameters={
            "staff_id": case.staff_a_id,
            "staff_no": "W1E_REPLACEMENT_" + uuid4().hex,
            "staff_no_sequence": employment_sequence,
            "account_id": case.account_id,
        },
        link_update="""
            UPDATE erp.staff_employment
            SET replacement_employment_id = :replacement_id,
                row_version = row_version + 1
            WHERE id = :id
        """,
        link_parameters={"id": case.employment_a_id},
        expected_message="STAFF_PERIOD_OUTSIDE_EMPLOYMENT",
    )

    _expect_replacement_orphan(
        database_connection,
        marker="W1E_ASG01_REVERSE_POSITION_REPLACEMENT",
        old_update="""
            UPDATE erp.staff_position_period
            SET invalidated_at_utc = clock_timestamp(),
                replacement_id = NULL,
                row_version = row_version + 1
            WHERE id = :id
        """,
        old_parameters={"id": case.position_a_id},
        replacement_insert="""
            INSERT INTO erp.staff_position_period
                (staff_id, employment_id, position_code, start_date, end_date,
                 invalidated_at_utc, replacement_id, created_by_account_id,
                 updated_by_account_id, row_version)
            VALUES
                (:staff_id, :employment_id, 'CARE_WORKER', DATE '2030-01-01',
                 DATE '2030-01-15', NULL, NULL, :account_id, :account_id, 1)
            RETURNING id
        """,
        replacement_parameters={
            "staff_id": case.staff_a_id,
            "employment_id": case.employment_a_id,
            "account_id": case.account_id,
        },
        link_update="""
            UPDATE erp.staff_position_period
            SET replacement_id = :replacement_id,
                row_version = row_version + 1
            WHERE id = :id
        """,
        link_parameters={"id": case.position_a_id},
        expected_message="CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN",
    )

    _expect_replacement_orphan(
        database_connection,
        marker="W1E_ASG01_REVERSE_QUALIFICATION_REPLACEMENT",
        old_update="""
            UPDATE erp.staff_service_qualification_period
            SET invalidated_at_utc = clock_timestamp(),
                replacement_qualification_id = NULL,
                row_version = row_version + 1
            WHERE id = :id
        """,
        old_parameters={"id": case.qualification_a_id},
        replacement_insert="""
            INSERT INTO erp.staff_service_qualification_period
                (staff_id, employment_id, service_type_id, start_date, end_date,
                 source_license_id, created_by_account_id, updated_by_account_id, row_version)
            VALUES
                (:staff_id, :employment_id, :service_type_id, DATE '2030-01-01',
                 DATE '2030-01-15', NULL, :account_id, :account_id, 1)
            RETURNING id
        """,
        replacement_parameters={
            "staff_id": case.staff_a_id,
            "employment_id": case.employment_a_id,
            "service_type_id": case.contract_service_type_id,
            "account_id": case.account_id,
        },
        link_update="""
            UPDATE erp.staff_service_qualification_period
            SET replacement_qualification_id = :replacement_id,
                row_version = row_version + 1
            WHERE id = :id
        """,
        link_parameters={"id": case.qualification_a_id},
        expected_message="CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN",
    )

    # A parent and its child may be corrected together when the final state is
    # covered: old contract/assignment become historical, new linked rows cover.
    correction_case = _seed_case(database_connection)
    old_contract_id = correction_case.contract_id
    old_assignment_id = _insert_assignment(
        database_connection,
        correction_case,
        staff_id=correction_case.staff_a_id,
        employment_id=correction_case.employment_a_id,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
    )
    _flush_constraints(database_connection)
    database_connection.execute(
        text(
            """
            UPDATE erp.care_assignment
            SET invalidated_at_utc = clock_timestamp(), row_version = row_version + 1
            WHERE id = :id
            """
        ),
        {"id": old_assignment_id},
    )
    database_connection.execute(
        text(
            """
            UPDATE erp.recipient_contract
            SET invalidated_at_utc = clock_timestamp(), row_version = row_version + 1
            WHERE id = :id
            """
        ),
        {"id": old_contract_id},
    )
    new_contract_id = _insert_contract(
        database_connection,
        correction_case,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 12, 31),
        marker="W1E_ASG01_VALID_PARENT_CORRECTION_CONTRACT_INSERT",
    )
    new_assignment_id = _insert_assignment(
        database_connection,
        correction_case,
        recipient_contract_id=new_contract_id,
        staff_id=correction_case.staff_a_id,
        employment_id=correction_case.employment_a_id,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
    )
    database_connection.execute(
        text(
            """
            UPDATE erp.recipient_contract
            SET replacement_contract_id = :replacement_id,
                row_version = row_version + 1
            WHERE id = :id
            """
        ),
        {"id": old_contract_id, "replacement_id": new_contract_id},
    )
    database_connection.execute(
        text(
            """
            UPDATE erp.care_assignment
            SET replacement_assignment_id = :replacement_id,
                row_version = row_version + 1
            WHERE id = :id
            """
        ),
        {"id": old_assignment_id, "replacement_id": new_assignment_id},
    )
    _flush_constraints(database_connection)
    correction_row = database_connection.execute(
        text(
            """
            SELECT
                old_contract.invalidated_at_utc IS NOT NULL,
                old_contract.replacement_contract_id,
                old_assignment.invalidated_at_utc IS NOT NULL,
                old_assignment.replacement_assignment_id,
                new_assignment.recipient_contract_id
            FROM erp.recipient_contract old_contract
            JOIN erp.care_assignment old_assignment
              ON old_assignment.id = :old_assignment_id
            JOIN erp.care_assignment new_assignment
              ON new_assignment.id = :new_assignment_id
            WHERE old_contract.id = :old_contract_id
            """
        ),
        {
            "old_contract_id": old_contract_id,
            "old_assignment_id": old_assignment_id,
            "new_assignment_id": new_assignment_id,
        },
    ).one()
    if correction_row != (
        True,
        new_contract_id,
        True,
        new_assignment_id,
        new_contract_id,
    ):
        _fail("W1E_ASG01_VALID_PARENT_CORRECTION_NOT_PRESERVED")

    database_connection.execute(
        text(
            """
            UPDATE erp.care_assignment
            SET invalidated_at_utc = clock_timestamp(), row_version = row_version + 1
            WHERE id = :id
            """
        ),
        {"id": assignment_id},
    )
    replacement_id = _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        start_date=date(2030, 1, 15),
        end_date=date(2030, 2, 15),
    )
    if replacement_id == assignment_id:
        _fail("W1E_ASG01_PERIOD_FACT_STABLE_ID_COLLISION")
    database_connection.execute(
        text(
            """
            UPDATE erp.care_assignment
            SET replacement_assignment_id = :replacement_id,
                row_version = row_version + 1
            WHERE id = :old_id
            """
        ),
        {"old_id": assignment_id, "replacement_id": replacement_id},
    )
    _flush_constraints(database_connection)
    row = database_connection.execute(
        text(
            """
            SELECT
                old.id,
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
        {"old_id": assignment_id, "replacement_id": replacement_id},
    ).one()
    if row[0] != assignment_id or row[4] != replacement_id or row[0] == row[4]:
        _fail("W1E_ASG01_PERIOD_FACT_STABLE_ID_NOT_PRESERVED")
    if row[1] is not True:
        _fail("W1E_ASG01_PERIOD_FACT_OLD_ROW_NOT_PRESERVED")
    if row[2] != replacement_id or row[3] is not None:
        _fail("W1E_ASG01_PERIOD_FACT_REPLACEMENT_LINK_MISMATCH")
    if row[5] is not True:
        _fail("W1E_ASG01_PERIOD_FACT_CORRECTION_DOES_NOT_OVERLAP")


def _seed_spare_care_worker_target(
    connection: Connection,
    case: W1ECase,
    *,
    end_date: date = date(2030, 12, 31),
) -> tuple[int, int]:
    """Create a fresh staff/employment key that can validly host a reparented
    CARE_WORKER position: the employment covers the position period and carries
    no position/qualification children, so no unrelated exclusion or W1A guard
    fires ahead of the W1E reverse-guard boundary under test."""
    label = uuid4().hex
    staff_id = _insert_id(
        connection,
        """
        INSERT INTO erp.staff (name, birth_date, sex_code, display_name, row_version)
        VALUES (:name, DATE '1990-01-01', 'TEST', :display_name, 1)
        RETURNING id
        """,
        {
            "name": "W1E SPARE " + label,
            "display_name": "W1E SPARE " + label,
        },
        "W1E_HARNESS_SPARE_STAFF_INSERT_FAILED",
    )
    sequence = _require_id(
        connection.execute(
            text("SELECT COALESCE(MAX(staff_no_sequence), 0) + 1 FROM erp.staff_employment")
        ).scalar_one(),
        "W1E_HARNESS_SPARE_EMPLOYMENT_SEQUENCE_INVALID",
    )
    employment_id = _insert_id(
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
            "staff_id": staff_id,
            "staff_no": "W1E_SPARE_" + label,
            "staff_no_sequence": sequence,
            "end_date": end_date,
            "account_id": case.account_id,
        },
        "W1E_HARNESS_SPARE_EMPLOYMENT_INSERT_FAILED",
    )
    return staff_id, employment_id


def test_w1e_pg_position_reparent_rejects_old_key_orphan(
    database_connection: Connection,
) -> None:
    """Reparenting a CARE_WORKER position off its OLD (staff, employment) key
    must be rejected when it orphans an active GENERAL assignment still bound to
    that OLD key. The NEW key is a valid, child-free employment, so only the
    reverse-guard's OLD-key re-check can reject this."""
    _require_catalog(database_connection)
    case = _seed_case(database_connection)
    _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
    )
    spare_staff_id, spare_employment_id = _seed_spare_care_worker_target(database_connection, case)
    _flush_constraints(database_connection)
    _expect_violation(
        database_connection,
        """
        UPDATE erp.staff_position_period
        SET staff_id = :spare_staff_id,
            employment_id = :spare_employment_id,
            row_version = row_version + 1
        WHERE id = :position_id
        """,
        {
            "spare_staff_id": spare_staff_id,
            "spare_employment_id": spare_employment_id,
            "position_id": case.position_a_id,
        },
        "W1E_REVERSE_POSITION_REPARENT_OLD_KEY_ORPHAN",
        expected_message="CARE_ASSIGNMENT_POSITION_ORPHAN_FORBIDDEN",
        expected_sqlstate="23514",
    )


def test_w1e_pg_qualification_rekey_rejects_old_key_orphan(
    database_connection: Connection,
) -> None:
    """Re-keying a qualification's service_type off the OLD key must be rejected
    when it orphans an active GENERAL assignment whose contract service depended
    on the OLD (staff, employment, service_type) qualification coverage."""
    _require_catalog(database_connection)
    case = _seed_case(database_connection)
    _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
    )
    _flush_constraints(database_connection)
    _expect_violation(
        database_connection,
        """
        UPDATE erp.staff_service_qualification_period
        SET service_type_id = :other_service_type_id,
            row_version = row_version + 1
        WHERE id = :qualification_id
        """,
        {
            "other_service_type_id": case.other_service_type_id,
            "qualification_id": case.qualification_a_id,
        },
        "W1E_REVERSE_QUALIFICATION_REKEY_OLD_KEY_ORPHAN",
        expected_message="CARE_ASSIGNMENT_QUALIFICATION_ORPHAN_FORBIDDEN",
        expected_sqlstate="23514",
    )


def test_w1e_pg_contract_service_transition_rechecks_qualification(
    database_connection: Connection,
) -> None:
    """Switching a contract's service_type must be rejected when the staff lacks
    continuous qualification coverage for the NEW service. Period containment is
    unchanged, so only a service-aware coverage re-check can reject this."""
    _require_catalog(database_connection)
    case = _seed_case(database_connection)
    _insert_assignment(
        database_connection,
        case,
        staff_id=case.staff_a_id,
        employment_id=case.employment_a_id,
        start_date=date(2030, 1, 1),
        end_date=date(2030, 1, 31),
    )
    _flush_constraints(database_connection)
    _expect_violation(
        database_connection,
        """
        UPDATE erp.recipient_contract
        SET service_type_id = :other_service_type_id,
            row_version = row_version + 1
        WHERE id = :contract_id
        """,
        {
            "other_service_type_id": case.other_service_type_id,
            "contract_id": case.contract_id,
        },
        "W1E_REVERSE_CONTRACT_SERVICE_TRANSITION_ORPHAN",
        expected_message="CARE_ASSIGNMENT_CONTRACT_ORPHAN_FORBIDDEN",
        expected_sqlstate="23514",
    )
