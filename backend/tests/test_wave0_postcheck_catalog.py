from __future__ import annotations

import os
from collections.abc import Iterator
from copy import deepcopy

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, make_url

from app.db.postcheck import (
    WAVE0_PERMISSION_COUNT,
    WAVE0_REVISION,
    _canonical_sql,
    _verify_constraint_shapes,
    _verify_index_shapes,
    verify_wave0_invariants,
)


def _constraint_rows() -> list[dict[str, object]]:
    common: dict[str, object] = {
        "table_schema": "erp",
        "referenced_schema": "",
        "referenced_table": "",
        "referenced_columns": [],
        "match_type": " ",
        "update_action": " ",
        "delete_action": " ",
        "access_method": "",
        "index_keys": [],
        "index_collations": [],
        "index_operator_classes": [],
        "index_options": [],
        "included_columns": [],
        "index_is_unique": False,
        "index_is_valid": False,
        "index_is_ready": False,
        "index_is_primary": False,
        "index_is_exclusion": False,
        "index_nulls_not_distinct": False,
        "exclusion_operators": [],
        "expression": None,
        "predicate": None,
        "is_deferrable": False,
        "is_initially_deferred": False,
        "is_validated": True,
        "is_no_inherit": False,
    }
    return [
        {
            **common,
            "constraint_name": ("ck_installation_state_ck_installation_state_singleton_key_true"),
            "table_name": "installation_state",
            "constraint_type": "c",
            "columns": ["singleton_key"],
            "expression": "((singleton_key))",
        },
        {
            **common,
            "constraint_name": "ex_staff_employment_period",
            "table_name": "staff_employment",
            "constraint_type": "x",
            "columns": ["staff_id", "employment_period"],
            "access_method": "gist",
            "index_keys": ["staff_id", "employment_period"],
            "index_collations": ["", ""],
            "index_operator_classes": [
                "public.gist_int8_ops",
                "pg_catalog.range_ops",
            ],
            "index_options": ["0", "0"],
            "index_is_valid": True,
            "index_is_ready": True,
            "index_is_exclusion": True,
            "exclusion_operators": [
                "pg_catalog.=(bigint,bigint)",
                "pg_catalog.&&(anyrange,anyrange)",
            ],
            "predicate": "((invalidated_at_utc IS NULL))",
            "is_no_inherit": True,
        },
        {
            **common,
            "constraint_name": "ex_staff_operational_role_period",
            "table_name": "staff_operational_role_period",
            "constraint_type": "x",
            "columns": ["staff_id", "role_code", "role_period"],
            "access_method": "gist",
            "index_keys": ["staff_id", "role_code", "role_period"],
            "index_collations": ["", "pg_catalog.default", ""],
            "index_operator_classes": [
                "public.gist_int8_ops",
                "public.gist_text_ops",
                "pg_catalog.range_ops",
            ],
            "index_options": ["0", "0", "0"],
            "index_is_valid": True,
            "index_is_ready": True,
            "index_is_exclusion": True,
            "exclusion_operators": [
                "pg_catalog.=(bigint,bigint)",
                "pg_catalog.=(text,text)",
                "pg_catalog.&&(anyrange,anyrange)",
            ],
            "predicate": "((invalidated_at_utc IS NULL))",
            "is_no_inherit": True,
        },
        {
            **common,
            "constraint_name": "ex_staff_position_period",
            "table_name": "staff_position_period",
            "constraint_type": "x",
            "columns": ["staff_id", "position_period"],
            "access_method": "gist",
            "index_keys": ["staff_id", "position_period"],
            "index_collations": ["", ""],
            "index_operator_classes": [
                "public.gist_int8_ops",
                "pg_catalog.range_ops",
            ],
            "index_options": ["0", "0"],
            "index_is_valid": True,
            "index_is_ready": True,
            "index_is_exclusion": True,
            "exclusion_operators": [
                "pg_catalog.=(bigint,bigint)",
                "pg_catalog.&&(anyrange,anyrange)",
            ],
            "predicate": "((invalidated_at_utc IS NULL))",
            "is_no_inherit": True,
        },
        {
            **common,
            "constraint_name": ("fk_installation_state_first_admin_account_id_user_account"),
            "table_name": "installation_state",
            "constraint_type": "f",
            "columns": ["first_admin_account_id"],
            "referenced_schema": "erp",
            "referenced_table": "user_account",
            "referenced_columns": ["id"],
            "match_type": "s",
            "update_action": "a",
            "delete_action": "r",
            "is_no_inherit": True,
        },
    ]


def _index_rows() -> list[dict[str, object]]:
    common: dict[str, object] = {
        "table_schema": "erp",
        "included_columns": [],
        "access_method": "btree",
        "is_unique": True,
        "is_valid": True,
        "is_ready": True,
        "is_primary": False,
        "is_exclusion": False,
        "nulls_not_distinct": False,
    }
    return [
        {
            **common,
            "index_name": "uq_account_permission_active",
            "table_name": "account_permission",
            "keys": ["account_id", "permission_code"],
            "predicate": "((revoked_at_utc IS NULL))",
        },
        {
            **common,
            "index_name": "uq_center_single_active",
            "table_name": "center",
            "keys": ["true"],
            "predicate": "((active))",
        },
        {
            **common,
            "index_name": "uq_system_run_idempotency",
            "table_name": "system_run",
            "keys": ["run_type", "idempotency_key"],
            "predicate": "((idempotency_key IS NOT NULL))",
        },
    ]


def test_wave0_catalog_shapes_accept_the_sealed_contract() -> None:
    _verify_constraint_shapes(_constraint_rows())
    _verify_index_shapes(_index_rows())


@pytest.mark.parametrize(
    ("constraint_name", "field", "replacement"),
    [
        (
            "ck_installation_state_ck_installation_state_singleton_key_true",
            "table_schema",
            "public",
        ),
        (
            "ck_installation_state_ck_installation_state_singleton_key_true",
            "table_name",
            "later_installation_state",
        ),
        (
            "ck_installation_state_ck_installation_state_singleton_key_true",
            "constraint_type",
            "u",
        ),
        (
            "ck_installation_state_ck_installation_state_singleton_key_true",
            "expression",
            "singleton_key()",
        ),
        (
            "ck_installation_state_ck_installation_state_singleton_key_true",
            "is_validated",
            False,
        ),
        ("ex_staff_employment_period", "columns", ["employment_period", "staff_id"]),
        ("ex_staff_employment_period", "access_method", "btree"),
        ("ex_staff_employment_period", "index_keys", ["employment_period", "staff_id"]),
        ("ex_staff_employment_period", "index_collations", ["pg_catalog.C", ""]),
        (
            "ex_staff_employment_period",
            "index_operator_classes",
            ["public.gist_int4_ops", "pg_catalog.range_ops"],
        ),
        ("ex_staff_employment_period", "index_options", ["1", "0"]),
        ("ex_staff_employment_period", "included_columns", ["invalidated_at_utc"]),
        ("ex_staff_employment_period", "index_is_unique", True),
        ("ex_staff_employment_period", "index_is_valid", False),
        ("ex_staff_employment_period", "index_is_ready", False),
        ("ex_staff_employment_period", "index_is_primary", True),
        ("ex_staff_employment_period", "index_is_exclusion", False),
        ("ex_staff_employment_period", "index_nulls_not_distinct", True),
        (
            "ex_staff_employment_period",
            "exclusion_operators",
            [
                "public.=(bigint,bigint)",
                "pg_catalog.&&(anyrange,anyrange)",
            ],
        ),
        ("ex_staff_position_period", "predicate", "invalidated_at_utc IS NOT NULL"),
        ("ex_staff_position_period", "is_deferrable", True),
        ("ex_staff_position_period", "is_initially_deferred", True),
        ("ex_staff_position_period", "is_no_inherit", False),
        (
            "fk_installation_state_first_admin_account_id_user_account",
            "referenced_schema",
            "public",
        ),
        (
            "fk_installation_state_first_admin_account_id_user_account",
            "referenced_table",
            "staff",
        ),
        (
            "fk_installation_state_first_admin_account_id_user_account",
            "referenced_columns",
            ["account_code"],
        ),
        (
            "fk_installation_state_first_admin_account_id_user_account",
            "match_type",
            "f",
        ),
        (
            "fk_installation_state_first_admin_account_id_user_account",
            "update_action",
            "c",
        ),
        (
            "fk_installation_state_first_admin_account_id_user_account",
            "delete_action",
            "c",
        ),
        (
            "fk_installation_state_first_admin_account_id_user_account",
            "is_no_inherit",
            False,
        ),
    ],
)
def test_wave0_catalog_rejects_mutated_constraint_definitions(
    constraint_name: str,
    field: str,
    replacement: object,
) -> None:
    rows = deepcopy(_constraint_rows())
    target = next(row for row in rows if row["constraint_name"] == constraint_name)
    target[field] = replacement

    with pytest.raises(
        SystemExit,
        match="(?:Unexpected Wave 0 constraint definition|Missing Wave 0 constraints)",
    ):
        _verify_constraint_shapes(rows)


@pytest.mark.parametrize(
    ("index_name", "field", "replacement"),
    [
        ("uq_center_single_active", "table_schema", "public"),
        ("uq_center_single_active", "table_name", "installation_state"),
        ("uq_center_single_active", "is_unique", False),
        ("uq_center_single_active", "predicate", "active()"),
        ("uq_center_single_active", "predicate", '"ACTIVE"'),
        ("uq_account_permission_active", "keys", ["permission_code", "account_id"]),
        ("uq_account_permission_active", "included_columns", ["revoked_at_utc"]),
        ("uq_account_permission_active", "predicate", "revoked_at_utc IS NOT NULL"),
        ("uq_account_permission_active", "access_method", "hash"),
        ("uq_system_run_idempotency", "is_valid", False),
        ("uq_system_run_idempotency", "is_ready", False),
        ("uq_system_run_idempotency", "is_primary", True),
        ("uq_system_run_idempotency", "is_exclusion", True),
        ("uq_system_run_idempotency", "nulls_not_distinct", True),
    ],
)
def test_wave0_catalog_rejects_mutated_index_definitions(
    index_name: str,
    field: str,
    replacement: object,
) -> None:
    rows = deepcopy(_index_rows())
    target = next(row for row in rows if row["index_name"] == index_name)
    target[field] = replacement

    with pytest.raises(
        SystemExit,
        match="(?:Unexpected Wave 0 index definition|Missing Wave 0 indexes)",
    ):
        _verify_index_shapes(rows)


def test_wave0_catalog_rejects_missing_or_duplicate_expected_objects() -> None:
    constraints = _constraint_rows()
    with pytest.raises(SystemExit, match="Missing Wave 0 constraints"):
        _verify_constraint_shapes(constraints[1:])

    duplicated_constraints = _constraint_rows()
    duplicated_constraints.append(deepcopy(duplicated_constraints[0]))
    with pytest.raises(SystemExit, match="Duplicate Wave 0 catalog objects"):
        _verify_constraint_shapes(duplicated_constraints)

    indexes = _index_rows()
    with pytest.raises(SystemExit, match="Missing Wave 0 indexes"):
        _verify_index_shapes(indexes[1:])

    indexes = _index_rows()
    indexes.append(deepcopy(indexes[0]))
    with pytest.raises(SystemExit, match="Duplicate Wave 0 catalog objects"):
        _verify_index_shapes(indexes)


def test_wave0_catalog_ignores_objects_outside_the_expected_table_scope() -> None:
    constraints = _constraint_rows()
    unrelated = deepcopy(constraints[0])
    unrelated["table_name"] = "later_slice_table"
    constraints.append(unrelated)

    _verify_constraint_shapes(constraints)


def test_wave0_sql_canonicalizer_preserves_semantic_distinctions() -> None:
    assert _canonical_sql("(( active ))") == _canonical_sql("active")
    assert _canonical_sql("active") != _canonical_sql("active()")
    assert _canonical_sql("active") != _canonical_sql('"ACTIVE"')
    assert _canonical_sql("(a AND b) OR c") != _canonical_sql("a AND (b OR c)")
    assert _canonical_sql("name = 'a  b'") != _canonical_sql("name = 'a b'")
    assert _canonical_sql("a\n  AND\tb") == _canonical_sql("a AND b")


@pytest.mark.parametrize(
    "field",
    [
        "columns",
        "referenced_columns",
        "index_keys",
        "index_collations",
        "index_operator_classes",
        "index_options",
        "included_columns",
        "exclusion_operators",
    ],
)
@pytest.mark.parametrize("replacement", [None, "not-a-sequence", ["valid", None]])
def test_wave0_catalog_rejects_invalid_constraint_array_fields(
    field: str,
    replacement: object,
) -> None:
    rows = _constraint_rows()
    rows[0][field] = replacement

    with pytest.raises(SystemExit, match="Unexpected Wave 0 catalog field type"):
        _verify_constraint_shapes(rows)


@pytest.mark.parametrize("field", ["keys", "included_columns"])
@pytest.mark.parametrize("replacement", [None, "not-a-sequence", ["valid", None]])
def test_wave0_catalog_rejects_invalid_index_array_fields(
    field: str,
    replacement: object,
) -> None:
    rows = _index_rows()
    rows[0][field] = replacement

    with pytest.raises(SystemExit, match="Unexpected Wave 0 catalog field type"):
        _verify_index_shapes(rows)


@pytest.fixture
def postgres_connection() -> Iterator[Connection]:
    if os.environ.get("SSWCENTER_POSTGRES_TEST") != "1":
        pytest.skip("isolated PostgreSQL test is not enabled")

    database_url = os.environ.get("SSWCENTER_DATABASE_URL")
    if not database_url:
        pytest.fail("SSWCENTER_DATABASE_URL is required for PostgreSQL catalog tests")
    parsed_url = make_url(database_url)
    if parsed_url.host != "127.0.0.1" or not str(parsed_url.database).startswith(
        "sswcenter_wave0_catalog_"
    ):
        pytest.fail("PostgreSQL catalog tests require the dedicated loopback database")

    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))
                yield connection
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def _verify_runtime_contract(connection: Connection) -> None:
    verify_wave0_invariants(
        connection,
        expected_revision=WAVE0_REVISION,
        expected_permission_count=WAVE0_PERMISSION_COUNT,
    )


def test_postgres_rejects_function_predicate_with_the_expected_index_name(
    postgres_connection: Connection,
) -> None:
    postgres_connection.execute(text("DROP INDEX erp.uq_center_single_active"))
    postgres_connection.execute(
        text(
            """
            CREATE FUNCTION erp.wave0_active_probe()
            RETURNS boolean
            LANGUAGE sql
            IMMUTABLE
            AS 'SELECT true'
            """
        )
    )
    postgres_connection.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_center_single_active
            ON erp.center ((true))
            WHERE erp.wave0_active_probe()
            """
        )
    )

    with pytest.raises(SystemExit, match="Unexpected Wave 0 index definition"):
        _verify_runtime_contract(postgres_connection)


@pytest.mark.parametrize(
    ("referenced_schema", "match_clause", "update_clause", "validation_clause"),
    [
        ("public", "MATCH SIMPLE", "ON UPDATE NO ACTION", ""),
        ("erp", "MATCH FULL", "ON UPDATE NO ACTION", ""),
        ("erp", "MATCH SIMPLE", "ON UPDATE CASCADE", ""),
        ("erp", "MATCH SIMPLE", "ON UPDATE NO ACTION", "NOT VALID"),
    ],
    ids=["schema", "match", "update", "validation"],
)
def test_postgres_rejects_each_mutated_foreign_key_catalog_field(
    postgres_connection: Connection,
    referenced_schema: str,
    match_clause: str,
    update_clause: str,
    validation_clause: str,
) -> None:
    postgres_connection.execute(text("CREATE TABLE public.user_account (id bigint PRIMARY KEY)"))
    postgres_connection.execute(
        text(
            """
            ALTER TABLE erp.installation_state
            DROP CONSTRAINT fk_installation_state_first_admin_account_id_user_account
            """
        )
    )
    postgres_connection.execute(
        text(
            f"""
            ALTER TABLE erp.installation_state
            ADD CONSTRAINT fk_installation_state_first_admin_account_id_user_account
            FOREIGN KEY (first_admin_account_id)
            REFERENCES {referenced_schema}.user_account(id)
            {match_clause}
            {update_clause}
            ON DELETE RESTRICT
            {validation_clause}
            """
        )
    )

    with pytest.raises(SystemExit, match="Unexpected Wave 0 constraint definition"):
        _verify_runtime_contract(postgres_connection)


def test_postgres_rejects_not_valid_mutated_singleton_check(
    postgres_connection: Connection,
) -> None:
    constraint_name = "ck_installation_state_ck_installation_state_singleton_key_true"
    postgres_connection.execute(
        text(f"ALTER TABLE erp.installation_state DROP CONSTRAINT {constraint_name}")
    )
    postgres_connection.execute(
        text(
            f"""
            ALTER TABLE erp.installation_state
            ADD CONSTRAINT {constraint_name}
            CHECK (singleton_key)
            NOT VALID
            """
        )
    )

    with pytest.raises(SystemExit, match="Unexpected Wave 0 constraint definition"):
        _verify_runtime_contract(postgres_connection)


def test_postgres_rejects_include_column_with_the_expected_index_name(
    postgres_connection: Connection,
) -> None:
    postgres_connection.execute(text("DROP INDEX erp.uq_account_permission_active"))
    postgres_connection.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_account_permission_active
            ON erp.account_permission (account_id, permission_code)
            INCLUDE (revoked_at_utc)
            WHERE revoked_at_utc IS NULL
            """
        )
    )

    with pytest.raises(SystemExit, match="Unexpected Wave 0 index definition"):
        _verify_runtime_contract(postgres_connection)


def test_postgres_rejects_include_column_on_exclusion_supporting_index(
    postgres_connection: Connection,
) -> None:
    postgres_connection.execute(
        text(
            """
            ALTER TABLE erp.staff_employment
            DROP CONSTRAINT ex_staff_employment_period
            """
        )
    )
    postgres_connection.execute(
        text(
            """
            ALTER TABLE erp.staff_employment
            ADD CONSTRAINT ex_staff_employment_period
            EXCLUDE USING gist (
                staff_id WITH =,
                employment_period WITH &&
            )
            INCLUDE (invalidated_at_utc)
            WHERE (invalidated_at_utc IS NULL)
            """
        )
    )

    with pytest.raises(SystemExit, match="Unexpected Wave 0 constraint definition"):
        _verify_runtime_contract(postgres_connection)


def test_postgres_rejects_collation_on_exclusion_supporting_index_key(
    postgres_connection: Connection,
) -> None:
    postgres_connection.execute(
        text(
            """
            ALTER TABLE erp.staff_operational_role_period
            DROP CONSTRAINT ex_staff_operational_role_period
            """
        )
    )
    postgres_connection.execute(
        text(
            """
            ALTER TABLE erp.staff_operational_role_period
            ADD CONSTRAINT ex_staff_operational_role_period
            EXCLUDE USING gist (
                staff_id WITH =,
                role_code COLLATE pg_catalog."C" WITH =,
                role_period WITH &&
            )
            WHERE (invalidated_at_utc IS NULL)
            """
        )
    )

    with pytest.raises(SystemExit, match="Unexpected Wave 0 constraint definition"):
        _verify_runtime_contract(postgres_connection)


def test_postgres_ignores_expected_constraint_name_on_an_unrelated_table(
    postgres_connection: Connection,
) -> None:
    postgres_connection.execute(text("CREATE TABLE erp.wave0_later_probe (value boolean NOT NULL)"))
    postgres_connection.execute(
        text(
            """
            ALTER TABLE erp.wave0_later_probe
            ADD CONSTRAINT ck_installation_state_ck_installation_state_singleton_key_true
            CHECK (value)
            """
        )
    )

    _verify_runtime_contract(postgres_connection)


def test_postgres_rejects_a_false_singleton_key(
    postgres_connection: Connection,
) -> None:
    constraint_name = "ck_installation_state_ck_installation_state_singleton_key_true"
    postgres_connection.execute(
        text(f"ALTER TABLE erp.installation_state DROP CONSTRAINT {constraint_name}")
    )
    postgres_connection.execute(text("UPDATE erp.installation_state SET singleton_key = false"))

    with pytest.raises(SystemExit, match="installation_state singleton postcheck failed"):
        _verify_runtime_contract(postgres_connection)


@pytest.mark.parametrize(
    "mutation_sql",
    [
        ("DELETE FROM erp.installation_state",),
        (
            "ALTER TABLE erp.installation_state DROP CONSTRAINT pk_installation_state",
            "INSERT INTO erp.installation_state "
            "(singleton_key, bootstrap_completed) VALUES (true, false)",
        ),
    ],
    ids=["zero", "multiple"],
)
def test_postgres_rejects_invalid_singleton_cardinality(
    postgres_connection: Connection,
    mutation_sql: tuple[str, ...],
) -> None:
    for statement in mutation_sql:
        postgres_connection.execute(text(statement))

    with pytest.raises(SystemExit, match="installation_state singleton postcheck failed"):
        _verify_runtime_contract(postgres_connection)
